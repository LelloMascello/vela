import asyncio
import base64
import io
import json

import httpx
import numpy as np
import torch
import torchaudio
from silero_vad import load_silero_vad, VADIterator
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEXT_TO_SPEECH_URL = "http://localhost:8003/"
INFERENCE_URL = "http://localhost:8080/v1/chat/completions"

# Silero VAD model — loaded once at startup and shared across all connections.
# Each connection gets its own stateful VADIterator wrapping this read-only model.
silero_vad_model = load_silero_vad()

MIC_SAMPLE_RATE = 16000
# Punctuation marks that signal a sentence boundary, used to flush phrases to TTS mid-stream.
SENTENCE_BOUNDARY_CHARS = (".", "!", "?", "…", "\n")

service_status = {
    "ready": False,
    "ip": "127.0.0.1",
    "port": 8002,
}

# --- BACKEND PROCESS HANDLES ---
llama_server_process: asyncio.subprocess.Process | None = None
tts_server_process: asyncio.subprocess.Process | None = None

# --- ACTIVE WEBSOCKET CONNECTIONS ---
active_websocket_connections: set[WebSocket] = set()


async def launch_backend_services() -> None:
    """Start llama.cpp and TTS subprocesses if they are not already running."""
    global llama_server_process, tts_server_process

    if llama_server_process is None or llama_server_process.returncode is not None:
        llama_server_process = await asyncio.create_subprocess_shell(
            "/llama.cpp/build/bin/llama-server "
            "-m /llama.cpp/mymodels/gemma-4-E2B-it-Q4_K_M.gguf "
            "--mmproj /llama.cpp/mymodels/mmproj-F16.gguf "
            "--host 127.0.0.1 "
            "--port 8080 "
            "-ngl 99 "
            "--reasoning off"
        )

    if tts_server_process is None or tts_server_process.returncode is not None:
        tts_server_process = await asyncio.create_subprocess_shell(
            "fastapi run text_to_speech.py --port 8003"
        )


async def shutdown_backend_services() -> None:
    """Terminate llama.cpp and TTS subprocesses gracefully."""
    global llama_server_process, tts_server_process

    if llama_server_process and llama_server_process.returncode is None:
        llama_server_process.terminate()
        await llama_server_process.wait()
        llama_server_process = None

    if tts_server_process and tts_server_process.returncode is None:
        tts_server_process.terminate()
        await tts_server_process.wait()
        tts_server_process = None


@app.get("/ready")
async def initialize_and_get_status():
    """Launch backend services and return connection info for the client."""
    try:
        await launch_backend_services()
        await asyncio.sleep(3)
        service_status["ready"] = True
    except Exception as exc:
        print(exc)
        service_status["ready"] = False

    return {
        "ready": service_status["ready"],
        "ip": service_status["ip"],
        "port": service_status["port"],
        "websocket": f"ws://{service_status['ip']}:{service_status['port']}/ws",
    }


async def synthesize_and_forward_audio(
    websocket: WebSocket,
    http_client: httpx.AsyncClient,
    sentence_phrase: str,
) -> None:
    """Send a text phrase to the TTS service and forward the resulting WAV audio + text to the client."""
    try:
        tts_response = await http_client.post(
            TEXT_TO_SPEECH_URL,
            json={"text": sentence_phrase},
            timeout=30.0,
        )
        tts_response.raise_for_status()
        tts_audio_base64 = base64.b64encode(tts_response.content).decode()
    except Exception as exc:
        print(f"[TTS error] {exc}")
        tts_audio_base64 = None

    await websocket.send_json({
        "type": "chunk",
        "text": sentence_phrase,
        "audio": tts_audio_base64,
    })


@app.websocket("/ws")
async def voice_pipeline_endpoint(websocket: WebSocket):
    """
    Main voice pipeline:
      client mic (PCM) → VAD → llama.cpp (Gemma 4) → TTS → client (text + WAV).

    Expected input: 16-bit signed PCM, mono, 16 kHz, 512 samples per chunk (1024 bytes).
    """
    await websocket.accept()
    active_websocket_connections.add(websocket)

    # Per-connection VAD iterator — stateful, tracks speech/silence transitions.
    speech_boundary_detector = VADIterator(silero_vad_model, sampling_rate=MIC_SAMPLE_RATE)

    # Accumulates float32 PCM samples between VAD speech-start and speech-end events.
    buffered_speech_samples: list[float] = []

    try:
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            while True:
                # ── 1. Receive a raw PCM chunk from the client ──────────────────────────
                raw_pcm_bytes = await websocket.receive_bytes()

                pcm_chunk_f32 = np.frombuffer(raw_pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                buffered_speech_samples.extend(pcm_chunk_f32.tolist())

                # ── 2. Run Silero VAD on the incoming chunk ─────────────────────────────
                # Returns {"start": N} at speech onset, {"end": N} at speech end, or None.
                vad_event = speech_boundary_detector(
                    torch.from_numpy(pcm_chunk_f32), return_seconds=False
                )

                if vad_event is None or "end" not in vad_event:
                    # Speech is still in progress (or silence before any speech) — keep buffering.
                    continue

                if not buffered_speech_samples:
                    continue  # Edge case: VAD fired on an empty buffer.

                # ── 3. Speech-end detected — snapshot and clear the buffer immediately ──
                # Clearing before the async LLM/TTS calls prevents stale samples
                # from contaminating the next utterance if an exception occurs downstream.
                complete_speech_f32 = np.array(buffered_speech_samples, dtype=np.float32)
                buffered_speech_samples.clear()
                speech_boundary_detector.reset_states()

                # Encode the captured speech as WAV → base64 for llama.cpp.
                wav_byte_buffer = io.BytesIO()
                torchaudio.save(
                    wav_byte_buffer,
                    torch.from_numpy(complete_speech_f32).unsqueeze(0),
                    MIC_SAMPLE_RATE,
                    format="wav",
                )
                speech_wav_base64 = base64.b64encode(wav_byte_buffer.getvalue()).decode()

                # ── 4. Send audio to llama.cpp (Gemma 4 E2B) in streaming mode ──────────
                inference_request_payload = {
                    "model": "gemma-4-e2b",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_audio",
                                    "input_audio": {
                                        "data": speech_wav_base64,
                                        "format": "wav",
                                    },
                                }
                            ],
                        }
                    ],
                    "stream": True,
                    "max_tokens": 512,
                }

                # ── 5. Stream tokens → collect into sentences → TTS → forward to client ─
                pending_tts_phrase = ""
                complete_llm_response = ""

                async with http_client.stream(
                    "POST", INFERENCE_URL, json=inference_request_payload
                ) as inference_stream:
                    async for raw_line in inference_stream.aiter_lines():
                        if not raw_line.startswith("data: "):
                            continue

                        sse_payload = raw_line[6:].strip()
                        if sse_payload == "[DONE]":
                            break

                        try:
                            sse_data = json.loads(sse_payload)
                        except json.JSONDecodeError:
                            continue

                        new_token: str = (
                            sse_data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if not new_token:
                            continue

                        pending_tts_phrase += new_token
                        complete_llm_response += new_token

                        # Flush to TTS as soon as a sentence boundary is reached.
                        if pending_tts_phrase.rstrip().endswith(SENTENCE_BOUNDARY_CHARS):
                            ready_phrase = pending_tts_phrase.strip()
                            pending_tts_phrase = ""
                            if ready_phrase:
                                await synthesize_and_forward_audio(
                                    websocket, http_client, ready_phrase
                                )

                # Flush any trailing text that did not end with sentence punctuation.
                if pending_tts_phrase.strip():
                    await synthesize_and_forward_audio(
                        websocket, http_client, pending_tts_phrase.strip()
                    )

                # Signal to the client that this turn is fully complete.
                await websocket.send_json(
                    {"type": "done", "full_text": complete_llm_response}
                )

    except WebSocketDisconnect:
        active_websocket_connections.discard(websocket)
        print("Client disconnected")

        if len(active_websocket_connections) == 0:
            print("No active clients — shutting down backend services")
            await shutdown_backend_services()