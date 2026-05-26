import threading
from collections import deque
from contextlib import asynccontextmanager

import noisereduce as nr
import numpy as np
import openwakeword
from fastapi import FastAPI, HTTPException
from openwakeword.model import Model
from pydantic import BaseModel

SAMPLE_RATE  = 16_000
FRAME_LENGTH = 1280      # 80 ms @ 16 kHz — recommended by openwakeword

WAKE_WORD = "hey_jarvis_v0.1"

# Detection thresholds
THRESHOLD        = 0.55  # per-frame score must exceed this
SMOOTH_WINDOW    = 5     # number of recent frames to average (~400 ms)
SMOOTH_THRESHOLD = 0.45  # rolling mean must also exceed this

# Energy gate: frames with RMS below this are skipped entirely.
# Raise in louder environments (e.g. 0.015–0.025).
ENERGY_GATE_RMS = 0.008

# Noise profile: accumulate the first N frames (assumes mic opens on silence).
NOISE_PROFILE_FRAMES = 20  # ~1.6 seconds

# ── Module-level state ────────────────────────────────────────────────────────

oww_model: Model | None = None
oww_lock = threading.Lock()

_score_history: deque[float] = deque(maxlen=SMOOTH_WINDOW)
_noise_buf:     list[np.ndarray] = []
_noise_profile: np.ndarray | None = None


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global oww_model
    all_paths  = openwakeword.get_pretrained_model_paths()
    model_path = next((p for p in all_paths if WAKE_WORD in p), None)
    if model_path is None:
        raise RuntimeError(
            f"Wake-word model '{WAKE_WORD}' not found.\n"
            f"Available models: {all_paths}"
        )
    oww_model = Model(wakeword_model_paths=[model_path])
    yield
    # No explicit teardown required — GC handles it.


app = FastAPI(lifespan=lifespan)


# ── Schema ────────────────────────────────────────────────────────────────────

class AudioRequest(BaseModel):
    # Raw PCM as floats in [-1.0, 1.0]; must contain exactly FRAME_LENGTH samples.
    audio: list[float]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/config")
async def config():
    """Expose runtime parameters so clients can self-configure."""
    return {
        "frame_length":     FRAME_LENGTH,
        "sample_rate":      SAMPLE_RATE,
        "threshold":        THRESHOLD,
        "smooth_window":    SMOOTH_WINDOW,
        "smooth_threshold": SMOOTH_THRESHOLD,
    }


@app.post("/detect")
async def detect(req: AudioRequest):
    global _noise_profile, _noise_buf

    if len(req.audio) != FRAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {FRAME_LENGTH} samples, got {len(req.audio)}",
        )

    pcm_f32 = np.array(req.audio, dtype=np.float32)

    # 1. Build noise profile from the opening silence of the session
    if _noise_profile is None:
        _noise_buf.append(pcm_f32.copy())
        if len(_noise_buf) >= NOISE_PROFILE_FRAMES:
            _noise_profile = np.concatenate(_noise_buf)
            _noise_buf.clear()

    # 2. Energy gate — skip detection on near-silent frames
    rms = float(np.sqrt(np.mean(pcm_f32 ** 2)))
    if rms < ENERGY_GATE_RMS:
        _score_history.append(0.0)
        return {
            "wake_word":     False,
            "scores":        {},
            "best_model":    None,
            "best_score":    0.0,
            "smoothed_score": 0.0,
            "reason":        "energy_gate",
        }

    # 3. Noise-reduce the frame before feeding the model
    if _noise_profile is not None and len(_noise_profile) > 0:
        pcm_f32 = nr.reduce_noise(
            y=pcm_f32,
            sr=SAMPLE_RATE,
            y_noise=_noise_profile,
            stationary=True,
            prop_decrease=0.80,
            # Smaller FFT than audio.py — the frame is only 1280 samples
            n_fft=256,
            n_jobs=1,
        )

    # 4. Convert float → int16 (openwakeword expects int16)
    pcm_int16 = (pcm_f32 * 32_767).clip(-32_768, 32_767).astype(np.int16)

    # 5. Run the wake-word model (not thread-safe — serialise access)
    with oww_lock:
        prediction = oww_model.predict(pcm_int16)

    scores     = {k: float(v) for k, v in prediction.items()}
    best_model = max(scores, key=scores.get)
    best_score = scores[best_model]

    # 6. Rolling mean smoothing
    _score_history.append(best_score)
    smoothed = float(np.mean(_score_history))

    # 7. Require BOTH the raw frame AND the smoothed window to exceed thresholds
    detected = best_score >= THRESHOLD and smoothed >= SMOOTH_THRESHOLD

    return {
        "wake_word":      detected,
        "scores":         scores,
        "best_model":     best_model,
        "best_score":     best_score,
        "smoothed_score": smoothed,
    }