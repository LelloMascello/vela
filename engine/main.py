import logging
import sys
import time

import httpx
import numpy as np
import torch
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from audio import (
    MIC_SAMPLE_RATE,
    MIN_SPEECH_DURATION_S,
    PCM_CHUNK_BYTES_EXPECTED,
    denoise_pcm,
    encode_pcm_as_wav,
    make_vad_iterator,
)
from inference import (
    launch_backend_services,
    shutdown_backend_services,
    stream_llm_response,
)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  %(levelname)-7s  [%(name)-10s]  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("main")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 8002

DATABASE_URL = "http://127.0.0.1:8005/chats/insert"

# How many seconds of silence (no VAD speech detected) before the connection
# is closed and the client is told to reconnect to the router WebSocket.
SILENCE_TIMEOUT_S = 10.0

active_connections: set[WebSocket] = set()


# ── /ready ────────────────────────────────────────────────────────────────────

@app.get("/ready")
async def ready():
    """Launch backend services and return WebSocket connection info."""
    log.info("GET /ready — launching backend services …")
    ready = False
    try:
        await launch_backend_services()
        import asyncio
        await asyncio.sleep(3)   # give services time to initialise
        ready = True
        log.info("Services ready")
    except Exception as exc:
        log.exception("Failed to launch backend services: %s", exc)

    return {
        "ready":     ready,
        "ip":        SERVICE_HOST,
        "port":      SERVICE_PORT,
        "websocket": f"ws://{SERVICE_HOST}:{SERVICE_PORT}/ws",
    }


# ── WebSocket voice pipeline ──────────────────────────────────────────────────

@app.websocket("/ws")
async def voice_pipeline(
    websocket: WebSocket,
    username: str = Query(...),
):
    """
    Main voice pipeline:
      client mic (PCM) → VAD → denoise → llama.cpp (Gemma 4) → TTS → client

    Input:  16-bit signed PCM, mono, 16 kHz, 512 samples/chunk (1 024 bytes).

    Server → client messages:
      {"type": "tts_start"}
      {"type": "chunk",  "text": str, "audio": b64|null}
      {"type": "tts_end"}
      {"type": "done",   "full_text": str}
      {"type": "silence_timeout"}   ← client must reconnect to router /ws
    """
    await websocket.accept()
    active_connections.add(websocket)
    log.info("Client connected user=%s — total=%d", username, len(active_connections))

    # Record when this session started (unix ms) for the DB record.
    session_started_ms = int(time.time() * 1000)

    vad            = make_vad_iterator()
    speech_buffer: list[float] = []
    chunks_received = 0
    turns_handled   = 0

    # Per-connection chat history — dropped automatically when this coroutine exits.
    conversation_history: list[dict] = []

    # ── Silence-timeout state ─────────────────────────────────────────────────
    silence_start: float | None = time.monotonic()
    in_speech = False
    # ─────────────────────────────────────────────────────────────────────────

    try:
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            while True:

                # 1. Receive raw PCM chunk ─────────────────────────────────────
                raw = await websocket.receive_bytes()
                chunks_received += 1

                if len(raw) != PCM_CHUNK_BYTES_EXPECTED:
                    log.warning(
                        "Unexpected chunk size: expected=%d B  got=%d B  (chunk #%d)",
                        PCM_CHUNK_BYTES_EXPECTED, len(raw), chunks_received,
                    )

                pcm_f32 = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32_768.0
                speech_buffer.extend(pcm_f32.tolist())

                # 2. Run VAD ───────────────────────────────────────────────────
                vad_event = vad(torch.from_numpy(pcm_f32), return_seconds=False)

                # 3. Silence-timeout check ────────────────────────────────────
                if vad_event and "start" in vad_event:
                    in_speech = True
                    silence_start = None
                    log.debug("VAD start — silence timer paused")

                if not in_speech and silence_start is not None:
                    elapsed = time.monotonic() - silence_start
                    if elapsed >= SILENCE_TIMEOUT_S:
                        log.info(
                            "Silence timeout after %.1f s — closing and redirecting to router",
                            elapsed,
                        )
                        await websocket.send_json({"type": "silence_timeout"})
                        await websocket.close(code=1000, reason="Silence timeout")
                        return
                # ─────────────────────────────────────────────────────────────

                if vad_event is None or "end" not in vad_event:
                    continue

                # 4. Speech end detected ───────────────────────────────────────
                in_speech = False

                if not speech_buffer:
                    log.warning("VAD 'end' on empty buffer — skipping (chunk #%d)", chunks_received)
                    silence_start = time.monotonic()
                    continue

                pcm_turn = np.array(speech_buffer, dtype=np.float32)
                speech_buffer.clear()
                vad.reset_states()

                duration_s = len(pcm_turn) / MIC_SAMPLE_RATE
                rms        = float(np.sqrt(np.mean(pcm_turn ** 2)))
                log.info("VAD end | duration=%.2f s | rms=%.4f", duration_s, rms)

                if duration_s < MIN_SPEECH_DURATION_S:
                    log.info(
                        "Turn discarded — too short (%.2f s < %.2f s)",
                        duration_s, MIN_SPEECH_DURATION_S,
                    )
                    silence_start = time.monotonic()
                    continue

                turns_handled += 1

                # Tell the client to stop the mic and freeze the waveform now
                # that we have captured a valid utterance.  The client will
                # re-enable both once the last TTS audio chunk has finished
                # playing (triggered by "done" + audio drain).
                await websocket.send_json({"type": "listening_stop"})

                # 5. Denoise → encode speech as WAV → base64 ──────────────────
                log.debug("Denoising PCM | samples=%d", len(pcm_turn))
                pcm_clean = denoise_pcm(pcm_turn, MIC_SAMPLE_RATE)

                wav_bytes = encode_pcm_as_wav(pcm_clean, MIC_SAMPLE_RATE)
                wav_b64   = __import__("base64").b64encode(wav_bytes).decode()
                log.debug("WAV encoded | bytes=%d | b64_chars=%d", len(wav_bytes), len(wav_b64))

                # 6. Stream LLM response → TTS → client ───────────────────────
                full_text = await stream_llm_response(
                    websocket, http_client, wav_b64, turns_handled, conversation_history
                )

                conversation_history.append({"role": "user",      "content": "(voice input)"})
                conversation_history.append({"role": "assistant", "content": full_text})
                log.debug("History length: %d messages", len(conversation_history))

                await websocket.send_json({"type": "done", "full_text": full_text})
                log.info("Turn #%d complete", turns_handled)

                # 7. Response delivered — restart the silence timer ────────────
                silence_start = time.monotonic()
                log.debug("Silence timer restarted after turn #%d", turns_handled)

    except WebSocketDisconnect:
        active_connections.discard(websocket)
        # Only persist if there was at least one exchange.
        if conversation_history:
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                try:
                    resp = await http_client.post(
                        DATABASE_URL,
                        json={
                            "username":   username,
                            "created_at": session_started_ms,
                            "chat":       conversation_history,
                        }
                    )
                    resp.raise_for_status()
                    log.info("Session saved for user=%s (%d messages)", username, len(conversation_history))
                except Exception as e:
                    log.error("Failed to save history for user=%s: %s", username, e)

        log.info(
            "Client disconnected user=%s | chunks=%d | turns=%d | remaining=%d",
            username, chunks_received, turns_handled, len(active_connections),
        )
        if not active_connections:
            log.info("No active clients — shutting down backend services")
            await shutdown_backend_services()