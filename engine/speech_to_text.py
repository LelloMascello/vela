import io
import logging
import sys
import time
import wave

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from faster_whisper import WhisperModel

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  %(levelname)-7s  [%(name)-10s]  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("stt")

# ── Constants ─────────────────────────────────────────────────────────────────

WHISPER_MODEL   = "large-v3-turbo"
WHISPER_DEVICE  = "auto"            # "cuda" or "cpu" to force
WHISPER_COMPUTE = "default"         # float16 on GPU, int8 on CPU
WHISPER_LANG    = None              # None → auto-detect (best for Italian/English)

# ── Model (loaded once at startup) ────────────────────────────────────────────

log.info("Loading Whisper model '%s' on device='%s' compute='%s' …",
         WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE)
_t0 = time.perf_counter()

whisper = WhisperModel(
    WHISPER_MODEL,
    device=WHISPER_DEVICE,
    compute_type=WHISPER_COMPUTE,
)
log.info("Whisper model loaded in %.3f s", time.perf_counter() - _t0)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Speech-to-Text (Whisper)", version="1.0")


def _wav_bytes_to_f32(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """
    Decode raw WAV bytes → (float32 mono array, sample_rate).

    Whisper expects float32 mono PCM at 16 kHz; we handle the conversion here
    so the caller can pass any standard WAV file produced by encode_pcm_as_wav().
    """
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as w:
        n_channels  = w.getnchannels()
        sample_rate = w.getframerate()
        sampwidth   = w.getsampwidth()
        frames      = w.readframes(w.getnframes())

    dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
    if sampwidth not in dtype_map:
        raise ValueError(f"Unsupported sample width: {sampwidth} bytes")

    pcm = np.frombuffer(frames, dtype=dtype_map[sampwidth]).astype(np.float32)
    pcm /= float(2 ** (8 * sampwidth - 1))   # normalise to [-1, 1]

    if n_channels > 1:
        pcm = pcm.reshape(-1, n_channels).mean(axis=1)  # stereo → mono

    return pcm, sample_rate


@app.post("/")
async def transcribe(request: Request) -> dict:
    """
    Transcribe raw WAV audio.

    Accepts:  raw WAV bytes in the request body
    Returns:  {"text": str, "language": str, "duration_s": float}
    """
    wav_bytes = await request.body()
    if not wav_bytes:
        raise HTTPException(status_code=400, detail="Empty request body")

    t0 = time.perf_counter()

    try:
        pcm_f32, sample_rate = _wav_bytes_to_f32(wav_bytes)
    except Exception as exc:
        log.error("WAV decode failed: %s", exc)
        raise HTTPException(status_code=422, detail=f"WAV decode error: {exc}") from exc

    duration_s = len(pcm_f32) / sample_rate
    log.info(
        "STT ← recv | bytes=%d | duration=%.2f s | sample_rate=%d",
        len(wav_bytes), duration_s, sample_rate,
    )

    # faster-whisper accepts a float32 numpy array directly.
    # beam_size=5 gives the best accuracy/speed trade-off on large-v3-turbo.
    try:
        segments, info = whisper.transcribe(
            pcm_f32,
            language=WHISPER_LANG,
            beam_size=5,
            vad_filter=False,       # VAD is already handled upstream
            word_timestamps=False,
        )
        transcript = " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as exc:
        log.error("Whisper inference failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc

    elapsed = time.perf_counter() - t0
    log.info(
        "STT → done | language=%s (p=%.2f) | chars=%d | elapsed=%.3f s | rtf=%.2fx",
        info.language, info.language_probability,
        len(transcript), elapsed, elapsed / max(duration_s, 1e-6),
    )
    log.debug("Transcript: %r", transcript)

    return {
        "text":       transcript,
        "language":   info.language,
        "duration_s": duration_s,
    }