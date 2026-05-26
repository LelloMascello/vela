import json
import logging
import time

import httpx
from fastapi import WebSocket

from audio import MIC_SAMPLE_RATE, synthesize_and_forward_audio, transcribe_audio

log = logging.getLogger("inference")

# ── Constants ─────────────────────────────────────────────────────────────────

INFERENCE_URL = "http://localhost:8080/v1/chat/completions"

SYSTEM_PROMPT = (
    "Sei un assistente vocale utile. "
    "Riceverai messaggi in inglese o italiano; rispondi sempre nella stessa lingua parlata dall'utente. "
    "la tua risposta verrà pronunciata ad alta voce, "
    "non mostrata come testo, quindi evita markdown, elenchi puntati e liste lunghe."
)

SENTENCE_BOUNDARY_CHARS = (".", "!", "?", "…", "\n")

# ── LLM streaming ─────────────────────────────────────────────────────────────

async def stream_llm_response(
    websocket:            WebSocket,
    http_client:          httpx.AsyncClient,
    wav_bytes:            bytes,
    turn_number:          int,
    conversation_history: list[dict] | None = None,
) -> tuple[str, str]:
    """
    Transcribe *wav_bytes* via Whisper, then stream a response from llama.cpp
    and forward audio phrases to the client via TTS as each sentence boundary
    is reached.

    Returns ``(full_llm_response, transcript)`` so the caller can store both
    in conversation history correctly.
    """
    history = conversation_history or []

    # ── 1. Speech → Text ──────────────────────────────────────────────────────
    try:
        transcript = await transcribe_audio(http_client, wav_bytes)
    except Exception as exc:
        log.error("Transcription failed on turn #%d: %s", turn_number, exc)
        transcript = ""

    if not transcript:
        log.warning("Empty transcript on turn #%d — skipping LLM call", turn_number)
        return "", ""

    # ── 2. Build message list (plain text, no audio blobs) ────────────────────
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": transcript},
    ]

    payload = {
        "model":      "gemma-4-e2b",
        "messages":   messages,
        "stream":     True,
        "max_tokens": 512,
    }

    log.info(
        "→ LLM request | turn=#%d | history_turns=%d | transcript=%r",
        turn_number, len(history) // 2, transcript[:120],
    )
    t0 = time.perf_counter()

    pending_phrase     = ""
    full_response      = ""
    token_count        = 0
    phrase_count       = 0
    tts_started        = False
    first_token_logged = False

    # ── 3. Stream LLM → TTS ───────────────────────────────────────────────────
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

    # Flush any trailing text that didn't end with a sentence boundary.
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
    return full_response, transcript