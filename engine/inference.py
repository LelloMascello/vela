import asyncio
import json
import logging
import time

import httpx
from fastapi import WebSocket

from audio import MIC_SAMPLE_RATE, synthesize_and_forward_audio

log = logging.getLogger("inference")

# ── Constants ─────────────────────────────────────────────────────────────────

INFERENCE_URL = "http://localhost:8080/v1/chat/completions"

SYSTEM_PROMPT = (
    "Sei un assistente vocale utile. "
    "Riceverai audio in inglese o italiano; rispondi sempre nella stessa lingua parlata dall'utente. "
    "la tua risposta verrà pronunciata ad alta voce, "
    "non mostrata come testo, quindi evita markdown, elenchi puntati e liste lunghe."
)

SENTENCE_BOUNDARY_CHARS = (".", "!", "?", "…", "\n")

# ── Subprocess handles (module-level, mutated by launch / shutdown) ───────────

llama_server_process: asyncio.subprocess.Process | None = None
tts_server_process:   asyncio.subprocess.Process | None = None


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _pipe_output(proc: asyncio.subprocess.Process, logger: logging.Logger) -> None:
    """Relay stdout/stderr of a subprocess into *logger* in real time."""
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

    if llama_server_process is None or llama_server_process.returncode is not None:
        log.info("Starting llama.cpp …")
        llama_server_process = await asyncio.create_subprocess_shell(
            "/home/leo/llama.cpp/build/bin/llama-server "
            "-m /home/leo/llama.cpp/mymodels/gemma-4-E4B-it-UD-Q4_K_XL.gguf "
            "--mmproj /home/leo/llama.cpp/mymodels/mmproj-F16-4.gguf "
            "--host 127.0.0.1 --port 8080 -ngl 99 --reasoning off",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("llama.cpp started — pid=%d", llama_server_process.pid)
        asyncio.create_task(
            _pipe_output(llama_server_process, logging.getLogger("llama.cpp"))
        )
    else:
        log.debug("llama.cpp already running (pid=%d)", llama_server_process.pid)

    if tts_server_process is None or tts_server_process.returncode is not None:
        log.info("Starting TTS server …")
        tts_server_process = await asyncio.create_subprocess_shell(
            "fastapi run text_to_speech.py --port 8003",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("TTS server started — pid=%d", tts_server_process.pid)
        asyncio.create_task(
            _pipe_output(tts_server_process, logging.getLogger("tts"))
        )
    else:
        log.debug("TTS server already running (pid=%d)", tts_server_process.pid)


async def shutdown_backend_services() -> None:
    """Terminate llama.cpp and TTS subprocesses gracefully."""
    global llama_server_process, tts_server_process

    if llama_server_process and llama_server_process.returncode is None:
        log.info("Terminating llama.cpp (pid=%d) …", llama_server_process.pid)
        llama_server_process.terminate()
        await llama_server_process.wait()
        log.info("llama.cpp terminated (rc=%d)", llama_server_process.returncode)
        llama_server_process = None

    if tts_server_process and tts_server_process.returncode is None:
        log.info("Terminating TTS server (pid=%d) …", tts_server_process.pid)
        tts_server_process.terminate()
        await tts_server_process.wait()
        log.info("TTS server terminated (rc=%d)", tts_server_process.returncode)
        tts_server_process = None


# ── LLM streaming ─────────────────────────────────────────────────────────────

async def stream_llm_response(
    websocket:        WebSocket,
    http_client:      httpx.AsyncClient,
    speech_wav_b64:   str,
    turn_number:      int,
) -> str:
    """
    Stream a response from llama.cpp for *speech_wav_b64* and forward audio phrases
    to the client via TTS as each sentence boundary is reached.

    Returns the complete text response.

    Client messages sent during this call:
      {"type": "tts_start"}                               — once, before first phrase
      {"type": "chunk", "text": str, "audio": b64|null}   — one per sentence
      {"type": "tts_end"}                                  — once, after last phrase
    """
    payload = {
        "model": "gemma-4-e2b",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": speech_wav_b64, "format": "wav"},
                    }
                ],
            },
        ],
        "stream":     True,
        "max_tokens": 512,
    }

    log.info("→ LLM request | turn=#%d | wav_b64_chars=%d", turn_number, len(speech_wav_b64))
    t0 = time.perf_counter()

    pending_phrase    = ""
    full_response     = ""
    token_count       = 0
    phrase_count      = 0
    tts_started       = False
    first_token_logged = False

    async with http_client.stream("POST", INFERENCE_URL, json=payload) as stream:
        async for raw_line in stream.aiter_lines():
            if not raw_line.startswith("data: "):
                continue

            sse = raw_line[6:].strip()
            if sse == "[DONE]":
                break

            try:
                data = json.loads(sse)
            except json.JSONDecodeError:
                log.warning("SSE JSON parse error: %r", sse[:120])
                continue

            token: str = (
                data.get("choices", [{}])[0].get("delta", {}).get("content", "")
            )
            if not token:
                continue

            if not first_token_logged:
                log.info("← first token | turn=#%d | ttft=%.3f s", turn_number, time.perf_counter() - t0)
                first_token_logged = True

            token_count    += 1
            pending_phrase += token
            full_response  += token

            # Flush a complete sentence to TTS as soon as a boundary is detected.
            if pending_phrase.rstrip().endswith(SENTENCE_BOUNDARY_CHARS):
                phrase = pending_phrase.strip()
                pending_phrase = ""
                if phrase:
                    phrase_count += 1
                    if not tts_started:
                        await websocket.send_json({"type": "tts_start"})
                        tts_started = True
                    log.info("Flushing phrase #%d (%d chars)", phrase_count, len(phrase))
                    await synthesize_and_forward_audio(websocket, http_client, phrase)

    # Flush any trailing text that didn't end with punctuation.
    if pending_phrase.strip():
        phrase_count += 1
        phrase = pending_phrase.strip()
        if not tts_started:
            await websocket.send_json({"type": "tts_start"})
            tts_started = True
        log.info("Flushing trailing phrase #%d (%d chars)", phrase_count, len(phrase))
        await synthesize_and_forward_audio(websocket, http_client, phrase)

    if tts_started:
        await websocket.send_json({"type": "tts_end"})

    log.info(
        "← LLM complete | turn=#%d | tokens=%d | phrases=%d | chars=%d | elapsed=%.3f s",
        turn_number, token_count, phrase_count, len(full_response), time.perf_counter() - t0,
    )
    return full_response