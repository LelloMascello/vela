#"""
#stt_worker.py — Speech-to-Text using faster-whisper
#
#Async task: reads raw 16-bit PCM chunks from audio_in queue, detects
#sentence boundaries via energy-based VAD, emits transcribed text to text_out.
#CPU-bound Whisper inference is offloaded to a ThreadPoolExecutor.
#"""

import asyncio
import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from faster_whisper import WhisperModel

from config import (
    STT_MODEL, STT_DEVICE, STT_COMPUTE_TYPE, STT_LANGUAGE,
    SILENCE_RMS_THRESHOLD, SILENCE_CHUNK_COUNT, MIN_SPEECH_BYTES,
)

logger = logging.getLogger(__name__)

# Shared model across all sessions — loaded once at startup
_model: WhisperModel | None = None
_model_lock = asyncio.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


async def get_model() -> WhisperModel:
    global _model
    async with _model_lock:
        if _model is None:
            logger.info("Loading Whisper '%s' …", STT_MODEL)
            loop = asyncio.get_event_loop()
            _model = await loop.run_in_executor(
                None,
                lambda: WhisperModel(STT_MODEL, device=STT_DEVICE, compute_type=STT_COMPUTE_TYPE),
            )
            logger.info("Whisper ready.")
    return _model


# ── helpers ──────────────────────────────────────────────────────────────────

def _rms(chunk: bytes) -> float:
    samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0


def _pcm_to_float32(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _transcribe_sync(model: WhisperModel, audio: np.ndarray) -> str:
    segments, _ = model.transcribe(
        audio,
        language=STT_LANGUAGE,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )
    return " ".join(s.text.strip() for s in segments).strip()


# ── worker ────────────────────────────────────────────────────────────────────

class STTWorker:
    """
    Consumes PCM audio chunks, emits complete utterances.

    audio_in  <- bytes (PCM chunk) | None (stop sentinel)
    text_out  -> str  (transcription) | None (done sentinel)
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._buf: bytes = b""
        self._sil: int = 0

    async def run(self, audio_in: asyncio.Queue, text_out: asyncio.Queue) -> None:
        model = await get_model()
        loop  = asyncio.get_event_loop()
        logger.debug("[%s] STT started", self.session_id)

        while True:
            chunk = await audio_in.get()

            if chunk is None:                              # session ending
                await self._flush(model, loop, text_out, force=True)
                await text_out.put(None)
                return

            self._buf += chunk
            rms = _rms(chunk)
            self._sil = (self._sil + 1) if rms < SILENCE_RMS_THRESHOLD else 0

            if self._sil >= SILENCE_CHUNK_COUNT and len(self._buf) >= MIN_SPEECH_BYTES:
                await self._flush(model, loop, text_out)

    async def _flush(self, model, loop, text_out, force=False):
        if not self._buf or (not force and len(self._buf) < MIN_SPEECH_BYTES):
            return
        audio = _pcm_to_float32(self._buf)
        self._buf = b""
        self._sil = 0
        text = await loop.run_in_executor(_executor, _transcribe_sync, model, audio)
        if text:
            logger.info("[%s] STT: %s", self.session_id, text)
            await text_out.put(text)
