#!/usr/bin/env python3
"""
audio-detector.py — Vela VAD Service
======================================
TCP server (port 9001) that wraps Silero VAD for streaming audio.

Protocol — messages FROM main.py:
  {"type": "init",        "client_id": "<id>"}
  {"type": "audio_chunk", "data": "<base64 raw PCM>"}   # 16 kHz / 16-bit / mono
  {"type": "reset"}       # sent after inference+TTS completes; restarts follow-up window

Protocol — messages TO main.py:
  {"type": "segment",         "data": "<base64 raw PCM>"}   # complete speech segment
  {"type": "silence_timeout"}                               # 8 s of silence with no speech
  {"type": "error",           "detail": "<msg>"}

State machine per client
------------------------
LISTENING
  • VAD runs on every 512-sample chunk (32 ms at 16 kHz)
  • Silence timer ticks; fires silence_timeout after SILENCE_TIMEOUT seconds
  • On speech-start → accumulate chunks
  • On speech-end   → send segment → go to PAUSED
PAUSED  (waiting for inference+TTS to complete)
  • VAD still runs; if the user speaks immediately, we capture that too
  • Silence timer is frozen
  • On "reset" from main.py:
      – if a new segment was captured while paused → send it, stay PAUSED
      – otherwise → go to LISTENING, restart silence timer
"""

import asyncio
import base64
import json
from enum import Enum, auto

import numpy as np
import torch
from silero_vad import load_silero_vad, VADIterator

# ─── Configuration ────────────────────────────────────────────────────────────

HOST            = "127.0.0.1"
PORT            = 9001

SAMPLE_RATE     = 16_000          # Hz
CHUNK_SAMPLES   = 512             # samples per VAD call (32 ms)  — Silero requirement
BYTES_PER_CHUNK = CHUNK_SAMPLES * 2   # int16 = 2 bytes/sample

SILENCE_TIMEOUT = 8.0             # seconds of continuous silence before closing
VAD_THRESHOLD   = 0.50            # Silero speech probability threshold
MIN_SILENCE_MS  = 600             # ms of silence needed to end a speech segment
SPEECH_PAD_MS   = 150             # ms added around each speech segment

# ─── Load Silero model once (shared across all connections) ───────────────────

print("[audio-detector] Loading Silero VAD model …")
_MODEL = load_silero_vad()
print("[audio-detector] Model loaded.")


# ─── IPC helpers ──────────────────────────────────────────────────────────────

async def _send(writer: asyncio.StreamWriter, obj: dict) -> None:
    data = json.dumps(obj).encode()
    writer.write(len(data).to_bytes(4, "big") + data)
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict:
    hdr  = await reader.readexactly(4)
    body = await reader.readexactly(int.from_bytes(hdr, "big"))
    return json.loads(body)


# ─── Session state ────────────────────────────────────────────────────────────

class _State(Enum):
    LISTENING = auto()
    PAUSED    = auto()   # segment sent, waiting for reset


class _ClientSession:
    def __init__(self, cid: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.cid    = cid
        self.reader = reader
        self.writer = writer

        self.vad_iter = VADIterator(
            _MODEL,
            threshold           = VAD_THRESHOLD,
            sampling_rate       = SAMPLE_RATE,
            min_silence_duration_ms = MIN_SILENCE_MS,
            speech_pad_ms       = SPEECH_PAD_MS,
        )

        self.state: _State   = _State.LISTENING
        self.in_speech: bool = False

        # Accumulates int16 bytes while speech is active
        self.speech_buf: bytearray = bytearray()

        # If user speaks while PAUSED, we save the segment here.
        # It's delivered when the next "reset" arrives.
        self.pending_segment: bytes | None = None

        # Silence timer: updated on every meaningful event
        self._last_event: float = asyncio.get_event_loop().time()
        self._timeout_task: asyncio.Task | None = None

        # Buffer for audio bytes arriving faster than they are consumed
        self._pcm_buf: bytearray = bytearray()

    # ── VAD chunk processing ──────────────────────────────────────────────────

    def _process_chunk(self, chunk16: bytes) -> str | None:
        """
        Feed one 512-sample chunk to the VAD iterator.
        Returns "start", "end", or None.
        """
        samples = np.frombuffer(chunk16, dtype=np.int16).astype(np.float32) / 32_768.0
        tensor  = torch.from_numpy(samples)
        event   = self.vad_iter(tensor, return_seconds=False)   # dict | None
        if event is None:
            return None
        if "start" in event:
            return "start"
        if "end" in event:
            return "end"
        return None

    def _ingest_chunk(self, chunk16: bytes) -> str | None:
        """
        Process one chunk and update speech_buf accordingly.
        Always appends to speech_buf while in_speech is True so that
        we capture audio even when PAUSED.
        Returns the VAD event string or None.
        """
        event = self._process_chunk(chunk16)

        if event == "start":
            self.in_speech = True
            self.speech_buf = bytearray(chunk16)

        elif event == "end":
            if self.in_speech:
                self.speech_buf.extend(chunk16)
            self.in_speech = False

        elif self.in_speech:
            self.speech_buf.extend(chunk16)

        return event

    # ── Silence watchdog ──────────────────────────────────────────────────────

    async def _watchdog(self) -> None:
        """Fires silence_timeout if the LISTENING state has been idle too long."""
        while True:
            await asyncio.sleep(0.5)
            if self.state != _State.LISTENING or self.in_speech:
                continue
            elapsed = asyncio.get_event_loop().time() - self._last_event
            if elapsed >= SILENCE_TIMEOUT:
                print(f"[audio-detector] Silence timeout for {self.cid}.")
                await _send(self.writer, {"type": "silence_timeout"})
                return   # watchdog exits; run() will notice and close

    # ── Message handlers ──────────────────────────────────────────────────────

    async def _on_audio_chunk(self, data_b64: str) -> None:
        chunk = base64.b64decode(data_b64)
        self._pcm_buf.extend(chunk)

        while len(self._pcm_buf) >= BYTES_PER_CHUNK:
            chunk16 = bytes(self._pcm_buf[:BYTES_PER_CHUNK])
            del self._pcm_buf[:BYTES_PER_CHUNK]

            event = self._ingest_chunk(chunk16)

            if event == "start":
                self._last_event = asyncio.get_event_loop().time()

            elif event == "end":
                segment = bytes(self.speech_buf)
                self.speech_buf.clear()
                self.vad_iter.reset_states()

                if self.state == _State.LISTENING:
                    # Normal path: send segment and pause until inference done
                    print(f"[audio-detector] Speech segment ready for {self.cid}"
                          f" ({len(segment)//2} samples).")
                    await _send(self.writer, {
                        "type": "segment",
                        "data": base64.b64encode(segment).decode(),
                    })
                    self.state = _State.PAUSED

                else:
                    # PAUSED: inference is already running.
                    # Save the new segment; deliver it after the current reset.
                    print(f"[audio-detector] Follow-up speech captured for {self.cid} (queued).")
                    self.pending_segment = segment

    async def _on_reset(self) -> None:
        if self.pending_segment is not None:
            # A new segment arrived while paused — send it now, stay PAUSED
            print(f"[audio-detector] Delivering queued segment for {self.cid}.")
            await _send(self.writer, {
                "type": "segment",
                "data": base64.b64encode(self.pending_segment).decode(),
            })
            self.pending_segment = None
            # still PAUSED; waiting for the next reset after this new inference
        else:
            # Nothing queued — go back to LISTENING
            self.state       = _State.LISTENING
            self.in_speech   = False
            self.speech_buf.clear()
            self.vad_iter.reset_states()
            self._last_event = asyncio.get_event_loop().time()
            print(f"[audio-detector] Follow-up window open for {self.cid}.")

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._timeout_task = asyncio.create_task(
            self._watchdog(), name=f"watchdog-{self.cid}"
        )
        try:
            while True:
                msg = await _recv(self.reader)
                t   = msg.get("type")

                if t == "audio_chunk":
                    await self._on_audio_chunk(msg["data"])

                elif t == "reset":
                    await self._on_reset()

                elif t == "init":
                    pass   # already handled by caller

                else:
                    print(f"[audio-detector] Unknown message type from {self.cid}: {t!r}")

        except asyncio.IncompleteReadError:
            pass   # client disconnected
        except Exception as exc:
            print(f"[audio-detector] Error for {self.cid}: {exc}")
        finally:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass


# ─── TCP server ───────────────────────────────────────────────────────────────

async def _handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    peer = writer.get_extra_info("peername")
    try:
        # First message must be "init"
        msg = await asyncio.wait_for(_recv(reader), timeout=10.0)
        if msg.get("type") != "init":
            print(f"[audio-detector] Expected init from {peer}, got {msg.get('type')!r}")
            writer.close()
            return
        cid = msg["client_id"]
        print(f"[audio-detector] Client connected: {cid} from {peer}")

        session = _ClientSession(cid, reader, writer)
        await session.run()

    except asyncio.TimeoutError:
        print(f"[audio-detector] Init timeout from {peer}.")
    except Exception as exc:
        print(f"[audio-detector] Connection error from {peer}: {exc}")
    finally:
        print(f"[audio-detector] Client disconnected from {peer}.")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    server = await asyncio.start_server(_handle_connection, HOST, PORT)
    print(f"[audio-detector] Listening on {HOST}:{PORT}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
