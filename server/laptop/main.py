#"""
#main.py — Vela Laptop AI Engine (FastAPI)
#
#WebSocket endpoint: ws://laptop:8001/ws/session/{client_id}?user_id={user_id}
#
#Pipeline per session (all concurrent async tasks):
#  [WebSocket in]  → audio_in  → [STT]  → text_q
#  text_q          → [Inference] → token_q  (tokens streamed as generated)
#  token_q         → [TTS]       → audio_out → [WebSocket out]
#
#After each VLM+TTS cycle, the session enters a FOLLOWUP_TIMEOUT window.
#If new speech arrives → another cycle. If timeout → session closed and
#transcript POSTed to the Pi for persistence.
#"""

import asyncio
import json
import logging
import uuid
from typing import Dict

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager

from config import (
    LAPTOP_HOST, LAPTOP_PORT,
    PI_BASE_URL,
    FIRST_UTTERANCE_TIMEOUT, FOLLOWUP_TIMEOUT,
    TTS_SAMPLE_RATE, TTS_CHANNELS, TTS_SAMPLE_WIDTH,
)
from stt_worker import STTWorker, get_model as preload_stt
from tts_worker import TTSWorker, _get_voice as preload_tts
from inference_worker import InferenceWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# Active sessions keyed by client_id
_sessions: Dict[str, "Session"] = {}


# ── Session ───────────────────────────────────────────────────────────────────

class Session:
    """
    Manages a single client's full voice interaction lifecycle.
    One session = one wake-word activation → N turns → 5 s silence → close.
    """

    def __init__(self, client_id: str, user_id: int, ws: WebSocket):
        self.client_id   = client_id
        self.user_id     = user_id
        self.ws          = ws
        self.chat_history: list[dict] = []
        self._active     = True
        self._session_id = str(uuid.uuid4())[:8]

    async def run(self) -> None:
        logger.info("[%s] Session started (user=%d)", self._session_id, self.user_id)

        # Announce audio format to client so it can configure AudioTrack
        await self.ws.send_text(json.dumps({
            "type":         "audio_config",
            "sample_rate":  TTS_SAMPLE_RATE,
            "channels":     TTS_CHANNELS,
            "bit_depth":    TTS_SAMPLE_WIDTH * 8,
        }))

        audio_in: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        text_q:   asyncio.Queue[str  | None]  = asyncio.Queue()

        # Receiving audio and STT run for the whole session lifetime
        recv_task = asyncio.create_task(self._recv_audio(audio_in))
        stt       = STTWorker(self._session_id)
        stt_task  = asyncio.create_task(stt.run(audio_in, text_q))

        in_followup = False

        try:
            while self._active:
                timeout = FOLLOWUP_TIMEOUT if in_followup else FIRST_UTTERANCE_TIMEOUT
                try:
                    text = await asyncio.wait_for(text_q.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.info("[%s] Silence timeout — closing session.", self._session_id)
                    break

                if text is None:          # WebSocket disconnected during STT
                    break

                await self._handle_turn(text)
                in_followup = True        # subsequent waits use FOLLOWUP_TIMEOUT

        finally:
            self._active = False
            recv_task.cancel()
            stt_task.cancel()
            # Drain the STT task cleanly
            await audio_in.put(None)
            await self._save_session()

    async def _handle_turn(self, user_text: str) -> None:
        """One full turn: user text → VLM inference → TTS → audio back to client."""
        logger.info("[%s] Turn: '%s'", self._session_id, user_text)

        self.chat_history.append({"role": "user", "content": user_text})

        # Notify client of transcription
        await self._send_json({"type": "transcription", "text": user_text})

        token_q:    asyncio.Queue[str   | None]  = asyncio.Queue()
        audio_out:  asyncio.Queue[bytes | None]  = asyncio.Queue(maxsize=100)

        tts  = TTSWorker(self._session_id)
        infer = InferenceWorker(self._session_id)

        # TTS and audio-sender run concurrently with inference
        tts_task  = asyncio.create_task(tts.run(token_q, audio_out))
        send_task = asyncio.create_task(self._send_audio(audio_out))

        # inference_worker fills token_q and returns full text when done
        response_text = await infer.run(self.chat_history, token_q)

        # Wait for TTS and sender to finish draining
        await tts_task
        await send_task

        if response_text:
            self.chat_history.append({"role": "assistant", "content": response_text})

        await self._send_json({"type": "turn_end"})

    async def _recv_audio(self, audio_in: asyncio.Queue) -> None:
        """Continuously receive binary audio frames from the client."""
        try:
            while self._active:
                data = await self.ws.receive_bytes()
                await audio_in.put(data)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            self._active = False
            await audio_in.put(None)   # sentinel for STT

    async def _send_audio(self, audio_out: asyncio.Queue) -> None:
        """Forward PCM audio chunks back to the client."""
        while True:
            chunk = await audio_out.get()
            if chunk is None:
                return
            try:
                await self.ws.send_bytes(chunk)
            except Exception:
                return

    async def _send_json(self, payload: dict) -> None:
        try:
            await self.ws.send_text(json.dumps(payload))
        except Exception:
            pass

    async def _save_session(self) -> None:
        """POST the conversation transcript to the Pi for MongoDB persistence."""
        if not self.chat_history:
            return
        # Build exchange pairs (user + assistant)
        exchanges = []
        i = 0
        while i < len(self.chat_history) - 1:
            if self.chat_history[i]["role"] == "user" and self.chat_history[i+1]["role"] == "assistant":
                exchanges.append({
                    "question":  self.chat_history[i]["content"],
                    "response":  self.chat_history[i+1]["content"],
                })
                i += 2
            else:
                i += 1

        if not exchanges:
            return

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{PI_BASE_URL}/api/chats/save", json={
                    "user_id":   self.user_id,
                    "exchanges": exchanges,
                })
            logger.info("[%s] Session saved (%d exchanges).", self._session_id, len(exchanges))
        except Exception as exc:
            logger.warning("[%s] Failed to save session: %s", self._session_id, exc)


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-load models at startup so the first session has no cold-start delay
    logger.info("Pre-loading STT and TTS models …")
    await asyncio.gather(preload_stt(), preload_tts())
    logger.info("Models ready. Laptop engine listening on :%d", LAPTOP_PORT)
    yield

app = FastAPI(title="Vela Laptop AI Engine", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(_sessions)}


@app.websocket("/ws/session/{client_id}")
async def session_endpoint(websocket: WebSocket, client_id: str, user_id: int = 0):
    await websocket.accept()

    if client_id in _sessions:
        # Reject duplicate connections for the same client
        await websocket.close(code=4001, reason="Session already active")
        return

    session = Session(client_id, user_id, websocket)
    _sessions[client_id] = session

    try:
        await session.run()
    except WebSocketDisconnect:
        logger.info("[client=%s] WebSocket disconnected.", client_id)
    except Exception as exc:
        logger.exception("[client=%s] Unhandled error: %s", client_id, exc)
    finally:
        _sessions.pop(client_id, None)
        try:
            await websocket.close()
        except Exception:
            pass
        logger.info("[client=%s] Session cleaned up. Active: %d", client_id, len(_sessions))


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=LAPTOP_HOST, port=LAPTOP_PORT, log_level="info")
