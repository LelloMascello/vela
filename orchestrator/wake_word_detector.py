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

# ── Detection thresholds ──────────────────────────────────────────────────────
# Two detection paths — either is sufficient to trigger:
#
#  LATCH path   : a single frame exceeds LATCH_THRESHOLD (high-confidence
#                 instant trigger; no smoothing needed).
#  SMOOTH path  : per-frame score exceeds THRESHOLD *and* the rolling mean
#                 exceeds SMOOTH_THRESHOLD (catches quieter, drawn-out
#                 pronunciations).
#
# To tune: watch the "best_score" and "smoothed_score" log lines while
# saying the wake word.  LATCH_THRESHOLD should sit just above the highest
# score you see during normal speech/noise.  THRESHOLD can be lower.
LATCH_THRESHOLD  = 0.70  # single-frame instant trigger
THRESHOLD        = 0.45  # per-frame score for smooth path
SMOOTH_WINDOW    = 5     # frames in rolling mean (~400 ms)
SMOOTH_THRESHOLD = 0.35  # rolling mean required for smooth path

# Energy gate: frames whose RMS falls below this are skipped before the model.
# Lowered from 0.008 — the onset of "hey" is often quiet and was being gated
# out, which prevented the smoothing window from building up a score.
# Set to 0.0 to disable entirely if you suspect it is causing misses.
ENERGY_GATE_RMS = 0.004

# Noise profile: accumulate the first N frames (assumes mic opens on silence).
NOISE_PROFILE_FRAMES = 20  # ~1.6 seconds

# Score logging: print best_score every N frames so you can watch live scores
# while tuning thresholds without drowning the log in noise.
# Set to 0 to disable.
LOG_SCORES_EVERY_N_FRAMES = 10

# ── Module-level state ────────────────────────────────────────────────────────

oww_model: Model | None = None
oww_lock = threading.Lock()

_score_history: deque[float] = deque(maxlen=SMOOTH_WINDOW)
_noise_buf:     list[np.ndarray] = []
_noise_profile: np.ndarray | None = None
_frame_counter: int = 0   # incremented on every non-gated frame for logging


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

@app.post("/reset")
async def reset():
    """Clear per-session score state so stale high scores from a previous
    wake-word hit cannot trigger an immediate false positive on reconnect.

    What is reset:
    - _score_history          : the rolling smoothing window (direct false-positive source)
    - oww_model.prediction_buffer : openwakeword's own score history deques

    What is intentionally NOT reset:
    - _noise_profile / _noise_buf : environment noise is constant across sessions;
      resetting forces a 1.6 s re-profiling delay and leaves frames unfiltered.
    - oww_model preprocessor ring buffer : the mel-spectrogram pipeline must stay
      primed; emptying it prevents the model from producing any predictions until
      the buffer refills, which breaks detection for the entire warm-up window.
    """
    _score_history.clear()

    with oww_lock:
        # Zero out openwakeword's per-model score histories.  We replace each
        # deque with a zeros-filled one of the same maxlen rather than calling
        # .clear(), so the deque length stays consistent with the model's
        # internal sliding-window expectations.
        if oww_model is not None:
            for key in oww_model.prediction_buffer:
                oww_model.prediction_buffer[key] = deque(
                    [0.0] * oww_model.prediction_buffer[key].maxlen,
                    maxlen=oww_model.prediction_buffer[key].maxlen,
                )

    return {"status": "ok"}


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
    global _noise_profile, _noise_buf, _frame_counter

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
    if ENERGY_GATE_RMS > 0.0 and rms < ENERGY_GATE_RMS:
        _score_history.append(0.0)
        return {
            "wake_word":      False,
            "scores":         {},
            "best_model":     None,
            "best_score":     0.0,
            "smoothed_score": 0.0,
            "reason":         "energy_gate",
        }

    # 3. Noise-reduce the frame before feeding the model.
    #    prop_decrease reduced from 0.80 → 0.60 — aggressive reduction was
    #    smearing wake-word formants and depressing model confidence.
    if _noise_profile is not None and len(_noise_profile) > 0:
        pcm_f32 = nr.reduce_noise(
            y=pcm_f32,
            sr=SAMPLE_RATE,
            y_noise=_noise_profile,
            stationary=True,
            prop_decrease=0.60,
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

    # 7. Periodic score logging for threshold tuning.
    _frame_counter += 1
    if LOG_SCORES_EVERY_N_FRAMES > 0 and (_frame_counter % LOG_SCORES_EVERY_N_FRAMES == 0):
        print(
            f"[detector] frame={_frame_counter:6d}  rms={rms:.4f}  "
            f"best_score={best_score:.3f}  smoothed={smoothed:.3f}  "
            f"model={best_model}"
        )

    # 8. Two detection paths — either triggers wake word:
    #
    #    LATCH  : single high-confidence frame (instant; no smoothing delay)
    #    SMOOTH : per-frame above THRESHOLD and rolling mean above SMOOTH_THRESHOLD
    #             (catches quieter or more drawn-out pronunciations)
    latch_hit  = best_score  >= LATCH_THRESHOLD
    smooth_hit = best_score  >= THRESHOLD and smoothed >= SMOOTH_THRESHOLD
    detected   = latch_hit or smooth_hit

    if detected:
        trigger = "latch" if latch_hit else "smooth"
        print(
            f"[detector] WAKE WORD via {trigger}  "
            f"best_score={best_score:.3f}  smoothed={smoothed:.3f}"
        )

    return {
        "wake_word":      detected,
        "scores":         scores,
        "best_model":     best_model,
        "best_score":     best_score,
        "smoothed_score": smoothed,
    }