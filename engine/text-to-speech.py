#!/usr/bin/env python3
"""
text-to-speech.py — Vela TTS Service
======================================
TCP server (port 9003) that converts text phrases into WAV audio using Piper.

Protocol — messages FROM main.py:
  {"type": "init",       "client_id": "<id>"}
  {"type": "synthesize", "text": "<phrase>"}

Protocol — messages TO main.py:
  {"type": "audio",  "data": "<base64 WAV>"}
  {"type": "error",  "detail": "<msg>"}

Piper is called as a subprocess with --output-raw so we get raw 16-bit PCM,
which we then wrap in a proper WAV container before returning.

Configuration
-------------
Set the environment variable  VELA_PIPER_MODEL  to the full path of your
.onnx voice file, or edit the PIPER_MODEL constant below.

Example (Italian Paola medium):
  VELA_PIPER_MODEL=~/piper-models/it_IT-paola-medium.onnx

The companion .onnx.json config file must be in the same directory as the
.onnx file — Piper picks it up automatically.
"""

import asyncio
import base64
import io
import json
import os
import struct
import wave
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 9003

# Override with env var VELA_PIPER_MODEL if set
_DEFAULT_MODEL = Path.home() / "piper-models/it_IT-paola-medium.onnx"
PIPER_MODEL    = Path(os.environ.get("VELA_PIPER_MODEL", str(_DEFAULT_MODEL)))

# Piper output sample rate — depends on the chosen voice model.
# Paola medium = 22 050 Hz.  Check your model's .onnx.json for "sample_rate".
PIPER_SAMPLE_RATE = int(os.environ.get("VELA_PIPER_RATE", "22050"))

# ─── IPC helpers ──────────────────────────────────────────────────────────────

async def _send(writer: asyncio.StreamWriter, obj: dict) -> None:
    data = json.dumps(obj).encode()
    writer.write(len(data).to_bytes(4, "big") + data)
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict:
    hdr  = await reader.readexactly(4)
    body = await reader.readexactly(int.from_bytes(hdr, "big"))
    return json.loads(body)


# ─── WAV helper ───────────────────────────────────────────────────────────────

def _wrap_wav(pcm_bytes: bytes, sample_rate: int = PIPER_SAMPLE_RATE) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)          # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ─── Piper synthesis ──────────────────────────────────────────────────────────

async def _synthesize(text: str) -> bytes:
    """
    Call piper via subprocess, capture raw PCM output, wrap in WAV.
    Piper reads the text from stdin and writes raw 16-bit mono PCM to stdout.
    """
    if not PIPER_MODEL.exists():
        raise FileNotFoundError(
            f"Piper model not found: {PIPER_MODEL}\n"
            "Set VELA_PIPER_MODEL to the correct path or download the model."
        )

    proc = await asyncio.create_subprocess_exec(
        "piper",
        "--model",       str(PIPER_MODEL),
        "--output-raw",
        "--quiet",                       # suppress progress output
        stdin  = asyncio.subprocess.PIPE,
        stdout = asyncio.subprocess.PIPE,
        stderr = asyncio.subprocess.DEVNULL,
    )

    # Feed the text and collect raw PCM from stdout
    raw_pcm, _ = await proc.communicate(input=text.encode("utf-8"))

    if proc.returncode != 0:
        raise RuntimeError(f"piper exited with code {proc.returncode}")

    if not raw_pcm:
        raise RuntimeError("piper produced no output — check model path and voice config")

    return _wrap_wav(raw_pcm)


# ─── Connection handler ───────────────────────────────────────────────────────

async def _handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    peer = writer.get_extra_info("peername")
    cid  = None
    try:
        # First message: init
        msg = await asyncio.wait_for(_recv(reader), timeout=10.0)
        if msg.get("type") != "init":
            print(f"[tts] Expected init from {peer}, got {msg.get('type')!r}")
            return
        cid = msg["client_id"]
        print(f"[tts] Client connected: {cid} from {peer}")

        while True:
            msg = await _recv(reader)

            if msg["type"] == "synthesize":
                text = msg.get("text", "").strip()
                if not text:
                    continue
                preview = text[:60] + ("…" if len(text) > 60 else "")
                print(f"[tts] Synthesising for {cid}: {preview!r}")
                try:
                    wav_bytes = await _synthesize(text)
                    await _send(writer, {
                        "type": "audio",
                        "data": base64.b64encode(wav_bytes).decode(),
                    })
                except Exception as exc:
                    print(f"[tts] Synthesis error for {cid}: {exc}")
                    await _send(writer, {"type": "error", "detail": str(exc)})

            else:
                print(f"[tts] Unknown message from {cid}: {msg.get('type')!r}")

    except asyncio.IncompleteReadError:
        pass   # client disconnected cleanly
    except asyncio.TimeoutError:
        print(f"[tts] Init timeout from {peer}.")
    except Exception as exc:
        print(f"[tts] Error for {cid or peer}: {exc}")
    finally:
        print(f"[tts] Client disconnected: {cid or peer}")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    # Warn early if the model is missing so the problem is obvious at startup
    if not PIPER_MODEL.exists():
        print(
            f"[tts] WARNING: Piper model not found at {PIPER_MODEL}\n"
            "  Set VELA_PIPER_MODEL env var or edit PIPER_MODEL in text-to-speech.py.\n"
            "  The service will start but synthesis calls will fail until the model is present."
        )
    else:
        print(f"[tts] Using Piper model: {PIPER_MODEL}  (rate={PIPER_SAMPLE_RATE} Hz)")

    server = await asyncio.start_server(_handle_connection, HOST, PORT)
    print(f"[tts] Listening on {HOST}:{PORT}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
