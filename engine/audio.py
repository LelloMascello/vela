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

SPEECH_TO_TEXT_URL       = "http://localhost:8004/"
TEXT_TO_SPEECH_URL       = "http://localhost:8003/"
MIC_SAMPLE_RATE          = 16_000
PCM_CHUNK_SAMPLES        = 512
PCM_CHUNK_BYTES_EXPECTED = PCM_CHUNK_SAMPLES * 2   # 16-bit → 2 bytes/sample

# VAD sensitivity — raise threshold / silence duration to reduce false triggers.
VAD_THRESHOLD         = 0.55   # lowered from 0.65 — less likely to clip word starts
VAD_MIN_SILENCE_MS    = 600    # raised from 400 ms — less likely to cut trailing syllables
VAD_SPEECH_PAD_MS     = 60     # default 30 ms  — padding around speech edges
MIN_SPEECH_DURATION_S = 0.5    # discard blips shorter than this

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


def denoise_pcm(pcm_f32: np.ndarray, sample_rate: int) -> np.ndarray:
    """
    Apply spectral noise reduction to a float32 mono PCM array.

    noisereduce uses the first ~0.5 s as a noise profile when no explicit
    noise clip is provided, which works well for microphone captures where
    the user hasn't started speaking yet at the very beginning of the buffer.
    Returns a float32 array of the same length.
    """
    denoised = nr.reduce_noise(y=pcm_f32, sr=sample_rate, stationary=False)
    return denoised.astype(np.float32)


def encode_pcm_as_wav(pcm_f32: np.ndarray, sample_rate: int) -> bytes:
    """Encode a float32 mono PCM array as an in-memory WAV file (stdlib only)."""
    pcm_int16 = (pcm_f32 * 32_767.0).clip(-32_768, 32_767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm_int16.tobytes())
    return buf.getvalue()


async def transcribe_audio(
    http_client: httpx.AsyncClient,
    wav_bytes:   bytes,
) -> str:
    """
    POST *wav_bytes* to the STT service and return the transcript string.

    Raises httpx.HTTPStatusError on a non-2xx response so the caller can
    decide whether to skip the turn or surface an error to the client.
    """
    log.info("STT → bytes=%d", len(wav_bytes))
    t0 = time.perf_counter()

    resp = await http_client.post(
        SPEECH_TO_TEXT_URL,
        content=wav_bytes,
        headers={"Content-Type": "audio/wav"},
        timeout=30.0,
    )
    resp.raise_for_status()

    data       = resp.json()
    transcript = data.get("text", "").strip()
    language   = data.get("language", "?")

    log.info(
        "STT ← status=%d | language=%s | chars=%d | elapsed=%.3f s",
        resp.status_code, language, len(transcript), time.perf_counter() - t0,
    )
    log.debug("Transcript: %r", transcript)

    return transcript


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