import logging
import sys

import httpx
import numpy as np
import torch
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from audio import (
    MIC_SAMPLE_RATE,
    MIN_SPEECH_DURATION_S,
    PCM_CHUNK_BYTES_EXPECTED,
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
async def voice_pipeline(websocket: WebSocket):
    """
    Main voice pipeline:
      client mic (PCM) → VAD → llama.cpp (Gemma 4) → TTS → client (text + WAV)

    Input:  16-bit signed PCM, mono, 16 kHz, 512 samples/chunk (1 024 bytes).

    Server → client messages:
      {"type": "tts_start"}
      {"type": "chunk",  "text": str, "audio": b64|null}
      {"type": "tts_end"}
      {"type": "done",   "full_text": str}
    """
    await websocket.accept()
    active_connections.add(websocket)
    log.info("Client connected — total=%d", len(active_connections))

    vad             = make_vad_iterator()
    speech_buffer:  list[float] = []
    chunks_received = 0
    turns_handled   = 0

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

                if vad_event is None or "end" not in vad_event:
                    continue   # speech still in progress (or silence) — keep buffering

                # 3. Speech end detected ───────────────────────────────────────
                if not speech_buffer:
                    log.warning("VAD 'end' on empty buffer — skipping (chunk #%d)", chunks_received)
                    continue

                pcm_turn = np.array(speech_buffer, dtype=np.float32)
                speech_buffer.clear()
                vad.reset_states()

                duration_s = len(pcm_turn) / MIC_SAMPLE_RATE
                rms        = float(np.sqrt(np.mean(pcm_turn ** 2)))
                log.info("VAD end | duration=%.2f s | rms=%.4f", duration_s, rms)

                # Drop blips shorter than the minimum — almost certainly noise.
                if duration_s < MIN_SPEECH_DURATION_S:
                    log.info("Turn discarded — too short (%.2f s < %.2f s)", duration_s, MIN_SPEECH_DURATION_S)
                    continue

                turns_handled += 1

                # 4. Encode speech as WAV → base64 ────────────────────────────
                wav_bytes = encode_pcm_as_wav(pcm_turn, MIC_SAMPLE_RATE)
                wav_b64   = __import__("base64").b64encode(wav_bytes).decode()
                log.debug("WAV encoded | bytes=%d | b64_chars=%d", len(wav_bytes), len(wav_b64))

                # 5. Stream LLM response → TTS → client ───────────────────────
                full_text = await stream_llm_response(
                    websocket, http_client, wav_b64, turns_handled
                )

                await websocket.send_json({"type": "done", "full_text": full_text})
                log.info("Turn #%d complete", turns_handled)

    except WebSocketDisconnect:
        active_connections.discard(websocket)
        log.info(
            "Client disconnected | chunks=%d | turns=%d | remaining=%d",
            chunks_received, turns_handled, len(active_connections),
        )
        if not active_connections:
            log.info("No active clients — shutting down backend services")
            await shutdown_backend_services()