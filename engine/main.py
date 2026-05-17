import asyncio
import base64
import io
import json
import logging
import sys
import time
import wave

import httpx
import numpy as np
import torch
from silero_vad import load_silero_vad, VADIterator
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# ── Logging setup ─────────────────────────────────────────────────────────────
# Structured output with millisecond timestamps.
# Each subsystem uses its own logger so you can grep / filter by name:
#   [main]       → startup, /ready endpoint
#   [services]   → llama.cpp / TTS process lifecycle
#   [websocket]  → raw PCM chunks sent/received, WS connect/disconnect
#   [vad]        → VAD events, speech-turn capture stats
#   [llama.cpp]  → inference requests, token stream, timing
#   [tts]        → synthesis requests, audio size, timing
#
# To raise/lower verbosity for a single subsystem at runtime, e.g.:
#   logging.getLogger("vad").setLevel(logging.WARNING)

LOG_FORMAT = "%(asctime)s.%(msecs)03d  %(levelname)-7s  [%(name)-10s]  %(message)s"
logging.basicConfig(
    level=logging.DEBUG,
    format=LOG_FORMAT,
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

log_main    = logging.getLogger("main")
log_service = logging.getLogger("services")
log_ws      = logging.getLogger("websocket")
log_vad     = logging.getLogger("vad")
log_llm     = logging.getLogger("llama.cpp")
log_tts     = logging.getLogger("tts")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEXT_TO_SPEECH_URL = "http://localhost:8003/"
INFERENCE_URL      = "http://localhost:8080/v1/chat/completions"

# Silero VAD model — loaded once at startup and shared across all connections.
# Each connection gets its own stateful VADIterator wrapping this read-only model.
log_main.info("Loading Silero VAD model …")
_vad_load_start  = time.perf_counter()
silero_vad_model = load_silero_vad()
log_main.info("Silero VAD model loaded in %.3f s", time.perf_counter() - _vad_load_start)

MIC_SAMPLE_RATE          = 16000
PCM_CHUNK_SAMPLES        = 512         # samples per chunk expected from the client
PCM_CHUNK_BYTES_EXPECTED = PCM_CHUNK_SAMPLES * 2  # 16-bit → 2 bytes/sample = 1024

# Punctuation marks that signal a sentence boundary, used to flush phrases to TTS mid-stream.
SENTENCE_BOUNDARY_CHARS = (".", "!", "?", "…", "\n")

service_status = {
    "ready": False,
    "ip":    "127.0.0.1",
    "port":  8002,
}

# ── Backend process handles ───────────────────────────────────────────────────
llama_server_process: asyncio.subprocess.Process | None = None
tts_server_process:   asyncio.subprocess.Process | None = None

# ── Active WebSocket connections ──────────────────────────────────────────────
active_websocket_connections: set[WebSocket] = set()


# ── Internal helpers ──────────────────────────────────────────────────────────
def _describe_process(proc: asyncio.subprocess.Process | None, name: str) -> str:
    """Return a compact status string for a subprocess."""
    if proc is None:
        return f"{name}=not_started"
    rc = proc.returncode
    return f"{name}=running(pid={proc.pid})" if rc is None else f"{name}=exited(rc={rc})"


def _log_service_states() -> None:
    """Emit a DEBUG line with the current state of both backend services."""
    log_service.debug(
        "%s  |  %s  |  ws_connections=%d",
        _describe_process(llama_server_process, "llama.cpp"),
        _describe_process(tts_server_process,   "tts"),
        len(active_websocket_connections),
    )


def _encode_pcm_as_wav(pcm_f32: np.ndarray, sample_rate: int) -> bytes:
    """
    Encode a float32 numpy array of mono PCM samples as a WAV file in memory.
    Uses only Python's stdlib wave module — no torchaudio / torchcodec required.
    Returns raw WAV bytes.
    """
    pcm_int16 = (pcm_f32 * 32767.0).clip(-32768, 32767).astype(np.int16)
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_writer:
        wav_writer.setnchannels(1)    # mono
        wav_writer.setsampwidth(2)    # 16-bit = 2 bytes per sample
        wav_writer.setframerate(sample_rate)
        wav_writer.writeframes(pcm_int16.tobytes())
    return wav_buffer.getvalue()


async def _pipe_subprocess_output(
    proc:   asyncio.subprocess.Process,
    logger: logging.Logger,
) -> None:
    """Relay stdout/stderr lines from a subprocess into a logger in real time."""
    async def _drain(stream: asyncio.StreamReader | None, level: int) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            logger.log(level, line.decode(errors="replace").rstrip())

    await asyncio.gather(
        _drain(proc.stdout, logging.INFO),
        _drain(proc.stderr, logging.WARNING),
    )
    logger.info("Process exited (rc=%s)", proc.returncode)


# ── Service lifecycle ─────────────────────────────────────────────────────────
async def launch_backend_services() -> None:
    """Start llama.cpp and TTS subprocesses if they are not already running."""
    global llama_server_process, tts_server_process

    _log_service_states()

    # llama.cpp ---------------------------------------------------------------
    if llama_server_process is None or llama_server_process.returncode is not None:
        log_service.info(
            "Starting llama.cpp  (was: %s)",
            _describe_process(llama_server_process, "llama.cpp"),
        )
        llama_server_process = await asyncio.create_subprocess_shell(
            "/home/leo/llama.cpp/build/bin/llama-server "
            "-m /home/leo/llama.cpp/mymodels/gemma-4-E2B-it-Q4_K_M.gguf "
            "--mmproj /home/leo/llama.cpp/mymodels/mmproj-F16.gguf "
            "--host 127.0.0.1 "
            "--port 8080 "
            "-ngl 99 "
            "--reasoning off",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log_service.info("llama.cpp started — pid=%d", llama_server_process.pid)
        asyncio.create_task(_pipe_subprocess_output(llama_server_process, log_llm))
    else:
        log_service.debug(
            "llama.cpp already running (%s) — skipping launch",
            _describe_process(llama_server_process, "llama.cpp"),
        )

    # TTS ---------------------------------------------------------------------
    if tts_server_process is None or tts_server_process.returncode is not None:
        log_service.info(
            "Starting TTS server  (was: %s)",
            _describe_process(tts_server_process, "tts"),
        )
        tts_server_process = await asyncio.create_subprocess_shell(
            "fastapi run text_to_speech.py --port 8003",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log_service.info("TTS server started — pid=%d", tts_server_process.pid)
        asyncio.create_task(_pipe_subprocess_output(tts_server_process, log_tts))
    else:
        log_service.debug(
            "TTS server already running (%s) — skipping launch",
            _describe_process(tts_server_process, "tts"),
        )

    _log_service_states()


async def shutdown_backend_services() -> None:
    """Terminate llama.cpp and TTS subprocesses gracefully."""
    global llama_server_process, tts_server_process

    _log_service_states()

    if llama_server_process and llama_server_process.returncode is None:
        log_service.info("Terminating llama.cpp (pid=%d) …", llama_server_process.pid)
        llama_server_process.terminate()
        await llama_server_process.wait()
        log_service.info("llama.cpp terminated (rc=%d)", llama_server_process.returncode)
        llama_server_process = None

    if tts_server_process and tts_server_process.returncode is None:
        log_service.info("Terminating TTS server (pid=%d) …", tts_server_process.pid)
        tts_server_process.terminate()
        await tts_server_process.wait()
        log_service.info("TTS server terminated (rc=%d)", tts_server_process.returncode)
        tts_server_process = None

    _log_service_states()


# ── /ready endpoint ───────────────────────────────────────────────────────────
@app.get("/ready")
async def initialize_and_get_status():
    """Launch backend services and return connection info for the client."""
    log_main.info("GET /ready — launching backend services …")
    try:
        await launch_backend_services()
        log_main.info("Waiting 3 s for services to initialise …")
        await asyncio.sleep(3)
        _log_service_states()
        service_status["ready"] = True
        log_main.info("Services ready — reporting ready=true to client")
    except Exception as exc:
        log_main.exception("Failed to launch backend services: %s", exc)
        service_status["ready"] = False

    response_payload = {
        "ready":     service_status["ready"],
        "ip":        service_status["ip"],
        "port":      service_status["port"],
        "websocket": f"ws://{service_status['ip']}:{service_status['port']}/ws",
    }
    log_main.info("GET /ready → %s", response_payload)
    return response_payload


# ── TTS helper ────────────────────────────────────────────────────────────────
async def synthesize_and_forward_audio(
    websocket:       WebSocket,
    http_client:     httpx.AsyncClient,
    sentence_phrase: str,
) -> None:
    """Send a text phrase to the TTS service and forward the resulting WAV audio + text to the client."""
    phrase_len = len(sentence_phrase)
    log_tts.info(
        "→ request  | chars=%d | text=%r",
        phrase_len,
        sentence_phrase[:80] + ("…" if phrase_len > 80 else ""),
    )
    tts_start = time.perf_counter()

    try:
        tts_response = await http_client.post(
            TEXT_TO_SPEECH_URL,
            json={"text": sentence_phrase},
            timeout=30.0,
        )
        tts_response.raise_for_status()
        audio_bytes      = tts_response.content
        tts_audio_base64 = base64.b64encode(audio_bytes).decode()
        log_tts.info(
            "← response | status=%d | audio_bytes=%d (%.1f kB) | elapsed=%.3f s",
            tts_response.status_code,
            len(audio_bytes),
            len(audio_bytes) / 1024,
            time.perf_counter() - tts_start,
        )
    except Exception as exc:
        log_tts.error("Request failed after %.3f s: %s", time.perf_counter() - tts_start, exc)
        tts_audio_base64 = None

    ws_payload       = {"type": "chunk", "text": sentence_phrase, "audio": tts_audio_base64}
    ws_payload_bytes = len(json.dumps(ws_payload).encode())
    log_ws.debug(
        "→ send chunk | text_chars=%d | audio=%s | payload_bytes=%d",
        phrase_len,
        f"{len(tts_audio_base64)} b64 chars" if tts_audio_base64 else "None",
        ws_payload_bytes,
    )
    await websocket.send_json(ws_payload)


# ── WebSocket voice pipeline ──────────────────────────────────────────────────
@app.websocket("/ws")
async def voice_pipeline_endpoint(websocket: WebSocket):
    """
    Main voice pipeline:
      client mic (PCM) → VAD → llama.cpp (Gemma 4) → TTS → client (text + WAV).

    Expected input: 16-bit signed PCM, mono, 16 kHz, 512 samples per chunk (1 024 bytes).
    """
    await websocket.accept()
    active_websocket_connections.add(websocket)
    connection_id = id(websocket)

    log_ws.info(
        "Client connected | conn_id=%x | total_connections=%d",
        connection_id,
        len(active_websocket_connections),
    )
    _log_service_states()

    # Per-connection VAD iterator — stateful, tracks speech/silence transitions.
    speech_boundary_detector = VADIterator(silero_vad_model, sampling_rate=MIC_SAMPLE_RATE)

    # Accumulates float32 PCM samples between VAD speech-start and speech-end events.
    buffered_speech_samples: list[float] = []

    # Per-connection counters for the debug summary on disconnect.
    pcm_chunks_received  = 0
    speech_turns_handled = 0

    try:
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            while True:

                # ── 1. Receive a raw PCM chunk from the client ──────────────────
                raw_pcm_bytes = await websocket.receive_bytes()
                pcm_chunks_received += 1

                received_bytes = len(raw_pcm_bytes)
                if received_bytes != PCM_CHUNK_BYTES_EXPECTED:
                    log_ws.warning(
                        "Unexpected PCM chunk size — expected=%d B, got=%d B (chunk #%d)",
                        PCM_CHUNK_BYTES_EXPECTED,
                        received_bytes,
                        pcm_chunks_received,
                    )

                pcm_chunk_f32 = (
                    np.frombuffer(raw_pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                )
                buffered_speech_samples.extend(pcm_chunk_f32.tolist())

                peak_amplitude = float(np.abs(pcm_chunk_f32).max())
                log_ws.debug(
                    "← recv PCM | chunk=#%d | bytes=%d | samples=%d | peak=%.4f | buffer_samples=%d",
                    pcm_chunks_received,
                    received_bytes,
                    len(pcm_chunk_f32),
                    peak_amplitude,
                    len(buffered_speech_samples),
                )

                # ── 2. Run Silero VAD on the incoming chunk ─────────────────────
                # Returns {"start": N} at speech onset, {"end": N} at speech end, or None.
                vad_event = speech_boundary_detector(
                    torch.from_numpy(pcm_chunk_f32), return_seconds=False
                )

                if vad_event is not None:
                    log_vad.debug(
                        "Event=%s | buffer_samples=%d | chunk=#%d",
                        vad_event,
                        len(buffered_speech_samples),
                        pcm_chunks_received,
                    )

                if vad_event is None or "end" not in vad_event:
                    # Speech still in progress (or silence before any speech) — keep buffering.
                    continue

                if not buffered_speech_samples:
                    log_vad.warning(
                        "VAD fired 'end' on empty buffer — skipping (chunk #%d)", pcm_chunks_received
                    )
                    continue

                speech_turns_handled += 1

                # ── 3. Speech-end detected — snapshot and clear the buffer ───────
                # Clearing before the async LLM/TTS calls prevents stale samples
                # from contaminating the next utterance if an exception occurs downstream.
                complete_speech_f32 = np.array(buffered_speech_samples, dtype=np.float32)
                buffered_speech_samples.clear()
                speech_boundary_detector.reset_states()

                speech_duration_s = len(complete_speech_f32) / MIC_SAMPLE_RATE
                rms_amplitude     = float(np.sqrt(np.mean(complete_speech_f32 ** 2)))
                log_vad.info(
                    "Turn #%d captured | samples=%d | duration=%.2f s | rms=%.4f",
                    speech_turns_handled,
                    len(complete_speech_f32),
                    speech_duration_s,
                    rms_amplitude,
                )

                # ── Encode captured speech as WAV → base64 for llama.cpp ────────
                # Uses stdlib wave — no torchaudio / torchcodec dependency.
                wav_raw_bytes     = _encode_pcm_as_wav(complete_speech_f32, MIC_SAMPLE_RATE)
                speech_wav_base64 = base64.b64encode(wav_raw_bytes).decode()
                log_vad.debug(
                    "WAV encoded | raw_bytes=%d (%.1f kB) | base64_chars=%d",
                    len(wav_raw_bytes),
                    len(wav_raw_bytes) / 1024,
                    len(speech_wav_base64),
                )

                # ── 4. Send audio to llama.cpp (Gemma 4 E2B) in streaming mode ──
                inference_request_payload = {
                    "model": "gemma-4-e2b",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data":   speech_wav_base64,
                                        "format": "wav",
                                    },
                                }
                            ],
                        }
                    ],
                    "stream":     True,
                    "max_tokens": 512,
                }

                # Log the payload without the large base64 audio blob.
                log_llm.info(
                    "→ request | turn=#%d | model=%s | wav_b64_chars=%d | max_tokens=%d",
                    speech_turns_handled,
                    inference_request_payload["model"],
                    len(speech_wav_base64),
                    inference_request_payload["max_tokens"],
                )
                llm_start = time.perf_counter()

                # ── 5. Stream tokens → collect into sentences → TTS → client ────
                pending_tts_phrase    = ""
                complete_llm_response = ""
                token_count           = 0
                phrase_count          = 0
                first_token_logged    = False

                async with http_client.stream(
                    "POST", INFERENCE_URL, json=inference_request_payload
                ) as inference_stream:
                    async for raw_line in inference_stream.aiter_lines():
                        if not raw_line.startswith("data: "):
                            if raw_line.strip():
                                log_llm.debug("Non-data line: %r", raw_line)
                            continue

                        sse_payload = raw_line[6:].strip()
                        if sse_payload == "[DONE]":
                            log_llm.debug("Stream [DONE]")
                            break

                        try:
                            sse_data = json.loads(sse_payload)
                        except json.JSONDecodeError as exc:
                            log_llm.warning(
                                "SSE JSON parse error: %s | raw=%r", exc, sse_payload[:120]
                            )
                            continue

                        new_token: str = (
                            sse_data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if not new_token:
                            finish_reason = (
                                sse_data.get("choices", [{}])[0].get("finish_reason")
                            )
                            if finish_reason:
                                log_llm.debug("finish_reason=%r", finish_reason)
                            continue

                        token_count           += 1
                        pending_tts_phrase    += new_token
                        complete_llm_response += new_token

                        if not first_token_logged:
                            log_llm.info(
                                "← first token | turn=#%d | ttft=%.3f s",
                                speech_turns_handled,
                                time.perf_counter() - llm_start,
                            )
                            first_token_logged = True

                        log_llm.debug("Token #%d: %r", token_count, new_token)

                        # Flush to TTS as soon as a sentence boundary is reached.
                        if pending_tts_phrase.rstrip().endswith(SENTENCE_BOUNDARY_CHARS):
                            ready_phrase       = pending_tts_phrase.strip()
                            pending_tts_phrase = ""
                            phrase_count      += 1
                            if ready_phrase:
                                log_llm.info(
                                    "Sentence boundary — flushing phrase #%d | chars=%d | tokens_so_far=%d",
                                    phrase_count,
                                    len(ready_phrase),
                                    token_count,
                                )
                                await synthesize_and_forward_audio(
                                    websocket, http_client, ready_phrase
                                )

                # Flush any trailing text that did not end with sentence punctuation.
                if pending_tts_phrase.strip():
                    phrase_count += 1
                    log_llm.info(
                        "Flushing trailing phrase #%d | chars=%d",
                        phrase_count,
                        len(pending_tts_phrase.strip()),
                    )
                    await synthesize_and_forward_audio(
                        websocket, http_client, pending_tts_phrase.strip()
                    )

                log_llm.info(
                    "← complete | turn=#%d | tokens=%d | phrases=%d | total_chars=%d | elapsed=%.3f s",
                    speech_turns_handled,
                    token_count,
                    phrase_count,
                    len(complete_llm_response),
                    time.perf_counter() - llm_start,
                )

                # Signal to the client that this turn is fully complete.
                done_payload = {"type": "done", "full_text": complete_llm_response}
                log_ws.debug(
                    "→ send done | turn=#%d | full_text_chars=%d",
                    speech_turns_handled,
                    len(complete_llm_response),
                )
                await websocket.send_json(done_payload)

    except WebSocketDisconnect:
        active_websocket_connections.discard(websocket)
        log_ws.info(
            "Client disconnected | conn_id=%x | pcm_chunks=%d | speech_turns=%d | remaining_connections=%d",
            connection_id,
            pcm_chunks_received,
            speech_turns_handled,
            len(active_websocket_connections),
        )

        if len(active_websocket_connections) == 0:
            log_main.info("No active clients — shutting down backend services")
            await shutdown_backend_services()