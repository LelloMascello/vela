#"""
#tts_worker.py — Streaming TTS using piper-tts
#
#Reads tokens from token_in, buffers them into sentences (split on punctuation),
#and synthesises each sentence with piper as soon as it's complete.
#Raw 16-bit PCM audio bytes are placed on audio_out for immediate streaming.
#
#piper synthesises in a ThreadPoolExecutor so inference and TTS can overlap:
#  VLM generates tokens  →  TTS synthesises sentence N
#                        ←  client receives audio of sentence N
#                        →  TTS synthesises sentence N+1  …
#"""

import asyncio
import io
import logging
import wave
from concurrent.futures import ThreadPoolExecutor

from piper.voice import PiperVoice

from config import PIPER_MODEL_PATH, TTS_SAMPLE_RATE

logger = logging.getLogger(__name__)

# Sentence boundaries — flush TTS when any of these appear
_FLUSH_CHARS = frozenset({'.', '!', '?', '\n'})
_MIN_FLUSH_LEN = 12        # avoid synthesising tiny fragments like "OK."
_MAX_BUFFER_LEN = 300      # force flush if a very long sentence arrives

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")

# Shared piper model — loaded once
_voice: PiperVoice | None = None
_voice_lock = asyncio.Lock()


async def _get_voice() -> PiperVoice:
    global _voice
    async with _voice_lock:
        if _voice is None:
            logger.info("Loading piper model …")
            loop = asyncio.get_event_loop()
            _voice = await loop.run_in_executor(
                None, PiperVoice.load, PIPER_MODEL_PATH
            )
            logger.info("Piper ready (sample_rate=%d).", TTS_SAMPLE_RATE)
    return _voice


def _synthesise_sync(voice: PiperVoice, text: str) -> bytes:
    """Blocking piper synthesis → raw PCM bytes."""
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, "wb") as wf:
        voice.synthesize(text, wf)
    wav_buf.seek(0)
    with wave.open(wav_buf, "rb") as wf:
        return wf.readframes(wf.getnframes())


class TTSWorker:
    """
    token_in  <- str (token) | None (generation done sentinel)
    audio_out -> bytes (raw PCM) | None (done sentinel)
    """

    def __init__(self, session_id: str):
        self.session_id = session_id

    async def run(self, token_in: asyncio.Queue, audio_out: asyncio.Queue) -> None:
        voice = await _get_voice()
        loop  = asyncio.get_event_loop()
        buf   = ""
        pending_tasks: list[asyncio.Task] = []

        async def synth_and_enqueue(text: str) -> None:
            pcm = await loop.run_in_executor(_executor, _synthesise_sync, voice, text)
            if pcm:
                await audio_out.put(pcm)

        while True:
            token = await token_in.get()

            if token is None:
                # Flush remaining buffer
                if buf.strip():
                    await synth_and_enqueue(buf.strip())
                # Wait for any in-flight synthesis tasks
                if pending_tasks:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
                await audio_out.put(None)
                return

            buf += token

            # Check sentence boundary
            should_flush = (
                (buf[-1] in _FLUSH_CHARS and len(buf) >= _MIN_FLUSH_LEN)
                or len(buf) >= _MAX_BUFFER_LEN
            )

            if should_flush:
                text_to_synth = buf.strip()
                buf = ""
                if text_to_synth:
                    # Create task — allows VLM to keep generating while TTS works
                    task = asyncio.create_task(synth_and_enqueue(text_to_synth))
                    pending_tasks.append(task)
                    # Prune completed tasks from list
                    pending_tasks = [t for t in pending_tasks if not t.done()]
                    logger.debug("[%s] TTS flushing: %s", self.session_id, text_to_synth[:60])
