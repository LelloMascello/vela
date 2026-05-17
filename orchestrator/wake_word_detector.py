from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np
import openwakeword
from openwakeword.model import Model

SAMPLE_RATE = 16000   # openwakeword expects 16 kHz
FRAME_LENGTH = 1280   # 80 ms at 16 kHz — recommended by openwakeword

# Pick one of the bundled models: hey_jarvis, hey_mycroft, alexa, timer, weather
WAKE_WORD = "alexa_v0.1"

oww_model = None
oww_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global oww_model
    # Find the .onnx path for the chosen model from the bundled pretrained models.
    all_paths = openwakeword.get_pretrained_model_paths()
    model_path = next((p for p in all_paths if WAKE_WORD in p), None)
    if model_path is None:
        raise RuntimeError(f"Model '{WAKE_WORD}' not found. Available: {all_paths}")
    oww_model = Model(wakeword_model_paths=[model_path])
    yield
    # No explicit teardown needed — GC handles it.


app = FastAPI(lifespan=lifespan)


class AudioRequest(BaseModel):
    # Raw PCM as floats in [-1.0, 1.0]; must contain exactly FRAME_LENGTH samples.
    audio: list[float]


@app.get("/config")
async def config():
    """Expose runtime parameters so clients can self-configure."""
    return {
        "frame_length": FRAME_LENGTH,
        "sample_rate": SAMPLE_RATE,
    }


@app.post("/detect")
async def detect(req: AudioRequest):
    if len(req.audio) != FRAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {FRAME_LENGTH} samples, got {len(req.audio)}"
        )

    # Convert float [-1, 1] → int16, which openwakeword expects.
    pcm_int16 = (np.array(req.audio, dtype=np.float32) * 32767).astype(np.int16)

    # Model.predict() is not thread-safe; serialise access.
    with oww_lock:
        prediction = oww_model.predict(pcm_int16)

    # prediction is a dict of {model_name: score}, score in [0.0, 1.0].
    scores = {k: float(v) for k, v in prediction.items()}
    best_model = max(scores, key=scores.get)
    best_score = scores[best_model]

    # A score above 0.5 is the recommended detection threshold.
    THRESHOLD = 0.5
    detected = best_score >= THRESHOLD

    return {
        "wake_word": detected,
        "scores": scores,        # full per-model scores for debugging
        "best_model": best_model,
        "best_score": best_score,
    }