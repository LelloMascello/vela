import asyncio
import io
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

app = FastAPI()

# Path to the Piper executable and voice model.
# Override via environment variables if your layout differs.
PIPER_BIN = os.getenv("PIPER_BIN", "/usr/local/bin/piper")
PIPER_MODEL = os.getenv("PIPER_MODEL", "/piper/models/en_US-lessac-medium.onnx")


class TTSRequest(BaseModel):
    text: str


@app.post("/")
async def text_to_speech(request: TTSRequest) -> Response:
    """Synthesize `text` with Piper and return raw WAV bytes."""

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    try:
        proc = await asyncio.create_subprocess_exec(
            PIPER_BIN,
            "--model", PIPER_MODEL,
            "--output-raw",          # raw PCM on stdout → we wrap it ourselves
            "--output_file", "-",    # write WAV to stdout
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        wav_bytes, stderr_bytes = await proc.communicate(
            input=request.text.encode("utf-8")
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Piper binary not found at '{PIPER_BIN}'. "
                   "Set the PIPER_BIN env variable to the correct path.",
        )

    if proc.returncode != 0:
        error_msg = stderr_bytes.decode(errors="replace").strip()
        raise HTTPException(
            status_code=500,
            detail=f"Piper exited with code {proc.returncode}: {error_msg}",
        )

    return Response(content=wav_bytes, media_type="audio/wav")