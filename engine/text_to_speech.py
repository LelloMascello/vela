import asyncio
import io
import os
import wave

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI()

# Path to the Piper executable and voice model.
# Override via environment variables if your layout differs.
PIPER_BIN   = os.getenv("PIPER_BIN",   "/usr/local/bin/piper")
PIPER_MODEL = os.getenv("PIPER_MODEL", "/piper/models/en_US-lessac-medium.onnx")

# Sample rate produced by the model (lessac-medium → 22 050 Hz).
# If you switch models, update this or set PIPER_SAMPLE_RATE accordingly.
PIPER_SAMPLE_RATE = int(os.getenv("PIPER_SAMPLE_RATE", "22050"))


class TTSRequest(BaseModel):
    text: str


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit signed mono PCM bytes in a WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)          # 16-bit → 2 bytes per sample
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


@app.post("/")
async def text_to_speech(request: TTSRequest) -> Response:
    """Synthesize *text* with Piper and return a proper WAV file."""

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    try:
        # --output-raw  → raw signed-16 PCM on stdout (no WAV header).
        # We build the WAV container ourselves in _pcm_to_wav().
        proc = await asyncio.create_subprocess_exec(
            PIPER_BIN,
            "--model", PIPER_MODEL,
            "--output-raw",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pcm_bytes, stderr_bytes = await proc.communicate(
            input=request.text.encode("utf-8")
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Piper binary not found at '{PIPER_BIN}'. "
                "Set the PIPER_BIN env variable to the correct path."
            ),
        )

    if proc.returncode != 0:
        error_msg = stderr_bytes.decode(errors="replace").strip()
        raise HTTPException(
            status_code=500,
            detail=f"Piper exited with code {proc.returncode}: {error_msg}",
        )

    wav_bytes = _pcm_to_wav(pcm_bytes, PIPER_SAMPLE_RATE)
    return Response(content=wav_bytes, media_type="audio/wav")