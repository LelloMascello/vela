from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np
import pvporcupine
import struct

porcupine = None
porcupine_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global porcupine
    porcupine = pvporcupine.create(keywords=["jarvis"])
    yield
    porcupine.delete()


app = FastAPI(lifespan=lifespan)


class AudioRequest(BaseModel):
    # Raw PCM as floats in [-1.0, 1.0]; must contain exactly
    # porcupine.frame_length samples (512 by default).
    audio: list[float]


@app.get("/config")
async def config():
    """Expose Porcupine runtime parameters so clients can self-configure."""
    return {
        "frame_length": porcupine.frame_length,
        "sample_rate": porcupine.sample_rate,
    }


@app.post("/detect")
async def detect(req: AudioRequest):
    if len(req.audio) != porcupine.frame_length:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {porcupine.frame_length} samples, got {len(req.audio)}"
        )

    # Convert float [-1, 1] → int16, then unpack into a tuple for Porcupine.
    pcm_int16 = (np.array(req.audio) * 32767).astype(np.int16)
    pcm = struct.unpack_from("h" * porcupine.frame_length, pcm_int16.tobytes())

    # porcupine.process() is not thread-safe; serialise access.
    with porcupine_lock:
        result = porcupine.process(pcm)

    return {
        "wake_word": result >= 0,
        "keyword_index": result,  # -1 = not detected, ≥0 = keyword index
    }