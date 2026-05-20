import base64
import io
import logging
import time
import wave

import httpx
import noisereduce as nr
import numpy as np
import torch
from fastapi import WebSocket
from silero_vad import VADIterator, load_silero_vad

log = logging.getLogger("audio")

# ── Constants ─────────────────────────────────────────────────────────────────

TEXT_TO_SPEECH_URL      = "http://localhost:8003/"
MIC_SAMPLE_RATE         = 16_000
PCM_CHUNK_SAMPLES       = 512
PCM_CHUNK_BYTES_EXPECTED = PCM_CHUNK_SAMPLES * 2  # 16-bit → 2 bytes/sample

# VAD sensitivity — raise threshold / silence duration to reduce false triggers.
VAD_THRESHOLD             = 0.65   # default 0.50 — ignore faint / background noise
VAD_MIN_SILENCE_MS        = 400    # default 100 ms — wait before ending a turn
VAD_SPEECH_PAD_MS         = 60     # default 30 ms  — padding around speech edges
MIN_SPEECH_DURATION_S     = 0.5    # discard blips shorter than this

# ── VAD model (loaded once at import time, shared across connections) ─────────

log.info("Loading Silero VAD model …")
_t0 = time.perf_counter()
silero_vad_model = load_silero_vad()
log.info("Silero VAD model loaded in %.3f s", time.perf_counter() - _t0)


# ── Public helpers ────────────────────────────────────────────────────────────

def make_vad_iterator() -> VADIterator:
    """Return a fresh per-connection VADIterator with tuned sensitivity."""
    return VADIterator(
        silero_vad_model,
        sampling_rate=MIC_SAMPLE_RATE,
        threshold=VAD_THRESHOLD,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_SPEECH_PAD_MS,
    )


def encode_pcm_as_wav(pcm_f32: np.ndarray, sample_rate: int) -> bytes:
    """Encode a float32 mono PCM array as an in-memory WAV file (stdlib only)."""
    pcm_int16  = (pcm_f32 * 32_767.0).clip(-32_768, 32_767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm_int16.tobytes())
    return buf.getvalue()


async def synthesize_and_forward_audio(
    websocket:   WebSocket,
    http_client: httpx.AsyncClient,
    phrase:      str,
) -> None:
    """
    POST *phrase* to the TTS service and forward the resulting audio to the client.

    Sends:  {"type": "chunk", "text": str, "audio": <base64-wav> | null}
    """
    log.info("TTS → chars=%d  text=%r", len(phrase), phrase[:80])
    t0 = time.perf_counter()

    tts_b64: str | None = None
    try:
        resp = await http_client.post(
            TEXT_TO_SPEECH_URL,
            json={"text": phrase},
            timeout=30.0,
        )
        resp.raise_for_status()
        tts_b64 = base64.b64encode(resp.content).decode()
        log.info(
            "TTS ← status=%d  bytes=%d  elapsed=%.3f s",
            resp.status_code, len(resp.content), time.perf_counter() - t0,
        )
    except Exception as exc:
        log.error("TTS request failed after %.3f s: %s", time.perf_counter() - t0, exc)

    await websocket.send_json({"type": "chunk", "text": phrase, "audio": tts_b64})