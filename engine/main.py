#!/usr/bin/env python3
"""
main.py — Vela Engine Orchestrator
====================================
Responsibilities
----------------
* Start audio-detector.py, inference.py, and text-to-speech.py as sub-processes.
* Serve a WebSocket endpoint for clients (ESP32-S3 / Android).
* For every connected client, run an isolated async pipeline:

    WebSocket (binary audio) ──► audio-detector
                                      │  segment (PCM)
                                      ▼
                                  inference  ──► (streams phrases)
                                      │  phrase text
                                      ▼
                                  text-to-speech
                                      │  WAV bytes
                                      ▼
                            WebSocket (JSON: text + audio)

* When the last client disconnects, notify standby.py so it can shut the
  LLM server down and terminate this process.

Wire protocol (all IPC sockets): 4-byte big-endian length + UTF-8 JSON body.
WebSocket client → engine: raw binary frames of 16 kHz / 16-bit / mono PCM.
Engine → WebSocket client: UTF-8 JSON frames.
"""

import asyncio
import base64
import io
import json
import subprocess
import sys
import wave
from pathlib import Path
from typing import Optional

import websockets
from websockets.asyncio.server import ServerConnection

# ─── Configuration ────────────────────────────────────────────────────────────

WS_HOST = "0.0.0.0"
WS_PORT = 8765

AUDIO_DETECTOR_HOST = "127.0.0.1"
AUDIO_DETECTOR_PORT = 9001

INFERENCE_HOST = "127.0.0.1"
INFERENCE_PORT = 9002

TTS_HOST = "127.0.0.1"
TTS_PORT = 9003

STANDBY_HOST = "127.0.0.1"
STANDBY_PORT = 9000

ENGINE_DIR          = Path(__file__).parent
SERVICE_READY_TIMEOUT = 20.0   # seconds to wait for each sub-service to bind

# ─── IPC helpers ──────────────────────────────────────────────────────────────

async def _send(writer: asyncio.StreamWriter, obj: dict) -> None:
    data = json.dumps(obj).encode()
    writer.write(len(data).to_bytes(4, "big") + data)
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict:
    hdr  = await reader.readexactly(4)
    body = await reader.readexactly(int.from_bytes(hdr, "big"))
    return json.loads(body)


def _pcm_to_wav(pcm: bytes, rate: int = 16_000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


# ─── Sub-process management ───────────────────────────────────────────────────

_sub_procs: list[subprocess.Popen] = []


def _start_sub_processes() -> None:
    for script in ("audio-detector.py", "inference.py", "text-to-speech.py"):
        proc = subprocess.Popen(
            [sys.executable, str(ENGINE_DIR / script)],
            cwd=str(ENGINE_DIR),
        )
        _sub_procs.append(proc)
        print(f"[main] Started {script}  (pid={proc.pid})")


def _stop_sub_processes() -> None:
    for proc in _sub_procs:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
    _sub_procs.clear()


async def _wait_service(host: str, port: int, name: str) -> None:
    deadline = asyncio.get_event_loop().time() + SERVICE_READY_TIMEOUT
    while asyncio.get_event_loop().time() < deadline:
        try:
            r, w = await asyncio.open_connection(host, port)
            w.close()
            await w.wait_closed()
            print(f"[main] {name} ready on {host}:{port}")
            return
        except (ConnectionRefusedError, OSError):
            await asyncio.sleep(0.4)
    raise TimeoutError(f"{name} did not start in {SERVICE_READY_TIMEOUT:.0f} s")


# ─── Client session ───────────────────────────────────────────────────────────

class _Session:
    """Holds the full state for one connected WebSocket client."""

    def __init__(self, ws: ServerConnection, client_id: str) -> None:
        self.ws        = ws
        self.cid       = client_id
        # IPC streams — initialised in connect()
        self.det_r: Optional[asyncio.StreamReader] = None
        self.det_w: Optional[asyncio.StreamWriter] = None
        self.inf_r: Optional[asyncio.StreamReader] = None
        self.inf_w: Optional[asyncio.StreamWriter] = None
        self.tts_r: Optional[asyncio.StreamReader] = None
        self.tts_w: Optional[asyncio.StreamWriter] = None
        # Serialises writes to det_w (two tasks write: audio forwarder + reset)
        self._det_lock = asyncio.Lock()

    # ── lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        self.det_r, self.det_w = await asyncio.open_connection(
            AUDIO_DETECTOR_HOST, AUDIO_DETECTOR_PORT
        )
        self.inf_r, self.inf_w = await asyncio.open_connection(
            INFERENCE_HOST, INFERENCE_PORT
        )
        self.tts_r, self.tts_w = await asyncio.open_connection(
            TTS_HOST, TTS_PORT
        )
        for w in (self.det_w, self.inf_w, self.tts_w):
            await _send(w, {"type": "init", "client_id": self.cid})

    async def disconnect(self) -> None:
        for w in (self.det_w, self.inf_w, self.tts_w):
            if w:
                try:
                    w.close()
                    await w.wait_closed()
                except Exception:
                    pass

    # ── audio forwarding ───────────────────────────────────────────────────────

    async def _forward_audio(self) -> None:
        """
        Read raw PCM binary frames from the WebSocket and forward them to the
        audio-detector.  Runs until the WebSocket closes or an exception occurs.
        """
        async for message in self.ws:
            if not isinstance(message, bytes):
                continue
            chunk_b64 = base64.b64encode(message).decode()
            async with self._det_lock:
                await _send(self.det_w, {"type": "audio_chunk", "data": chunk_b64})

    # ── inference + TTS pipeline ───────────────────────────────────────────────

    async def _run_pipeline(self, pcm: bytes) -> None:
        """
        Given a PCM speech segment:
          1. Wrap it in a WAV and send to inference.py.
          2. For each phrase returned, TTS it and stream result to the client.
          3. After the stream ends, send a "reset" to the audio-detector so
             it resumes listening for follow-up speech.
        """
        wav_b64 = base64.b64encode(_pcm_to_wav(pcm)).decode()
        await _send(self.inf_w, {"type": "audio", "data": wav_b64})

        while True:
            msg = await _recv(self.inf_r)

            if msg["type"] == "phrase":
                text = msg["text"]
                # TTS
                await _send(self.tts_w, {"type": "synthesize", "text": text})
                tts_msg = await _recv(self.tts_r)
                if tts_msg["type"] == "audio":
                    # Send audio + text to the WebSocket client
                    await self.ws.send(json.dumps({
                        "type":  "response_chunk",
                        "text":  text,
                        "audio": tts_msg["data"],   # base64 WAV
                    }))
                elif tts_msg["type"] == "error":
                    print(f"[main] TTS error for {self.cid}: {tts_msg.get('detail')}")

            elif msg["type"] == "stream_end":
                break

        # Signal the detector to start the follow-up window
        async with self._det_lock:
            await _send(self.det_w, {"type": "reset"})

    # ── detector event loop ────────────────────────────────────────────────────

    async def _handle_detector(self) -> None:
        """
        Read events from audio-detector.py and react:
          • "segment"        → run the inference+TTS pipeline
          • "silence_timeout" → close the WebSocket session
        Segments are processed one at a time (the pipeline must finish before
        the next one is processed); if the user speaks while inference is running
        the detector buffers the new segment and delivers it after the reset.
        """
        while True:
            msg = await _recv(self.det_r)

            if msg["type"] == "segment":
                pcm = base64.b64decode(msg["data"])
                try:
                    await self._run_pipeline(pcm)
                except Exception as exc:
                    print(f"[main] Pipeline error for {self.cid}: {exc}")

            elif msg["type"] == "silence_timeout":
                print(f"[main] Silence timeout — closing session {self.cid}.")
                await self.ws.send(json.dumps({"type": "session_end", "reason": "silence"}))
                await self.ws.close(1000, "Silence timeout")
                return

            elif msg["type"] == "error":
                print(f"[main] Detector error for {self.cid}: {msg.get('detail')}")
                return

    # ── top-level runner ───────────────────────────────────────────────────────

    async def run(self) -> None:
        await self.connect()
        try:
            # Both tasks run concurrently for the lifetime of the session.
            # _forward_audio ends when the WebSocket closes.
            # _handle_detector ends on silence_timeout or error.
            fwd_task = asyncio.create_task(self._forward_audio(),   name=f"fwd-{self.cid}")
            det_task = asyncio.create_task(self._handle_detector(), name=f"det-{self.cid}")
            done, pending = await asyncio.wait(
                {fwd_task, det_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        finally:
            await self.disconnect()


# ─── WebSocket server ─────────────────────────────────────────────────────────

_active: dict[str, _Session] = {}
_cid_counter = 0


async def _handle_ws(ws: ServerConnection) -> None:
    global _cid_counter
    _cid_counter += 1
    cid  = f"client_{_cid_counter}"
    peer = ws.remote_address
    print(f"[main] ← {cid} connected from {peer}")

    session = _Session(ws, cid)
    _active[cid] = session
    try:
        await session.run()
    except Exception as exc:
        print(f"[main] Session {cid} ended with error: {exc}")
    finally:
        _active.pop(cid, None)
        print(f"[main] ✗ {cid} disconnected  ({len(_active)} remaining)")
        if not _active:
            asyncio.create_task(_notify_idle())


async def _notify_idle() -> None:
    """Tell standby.py that no clients remain so it can shut the engine down."""
    try:
        r, w = await asyncio.open_connection(STANDBY_HOST, STANDBY_PORT)
        await _send(w, {"type": "idle"})
        w.close()
        await w.wait_closed()
        print("[main] Notified standby: engine is idle.")
    except Exception as exc:
        print(f"[main] Could not notify standby: {exc}")


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    print("[main] Starting sub-processes …")
    _start_sub_processes()

    print("[main] Waiting for sub-services …")
    await asyncio.gather(
        _wait_service(AUDIO_DETECTOR_HOST, AUDIO_DETECTOR_PORT, "audio-detector"),
        _wait_service(INFERENCE_HOST,      INFERENCE_PORT,      "inference"),
        _wait_service(TTS_HOST,            TTS_PORT,            "text-to-speech"),
    )

    print(f"[main] WebSocket server on ws://{WS_HOST}:{WS_PORT}")
    async with websockets.serve(_handle_ws, WS_HOST, WS_PORT):
        await asyncio.Future()   # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[main] Interrupted — stopping sub-processes.")
        _stop_sub_processes()
