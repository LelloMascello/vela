#"""
#inference_worker.py — Streaming VLM inference via llama-server
#
#Calls the OpenAI-compatible /v1/chat/completions endpoint with stream=True.
#Individual tokens are placed on `token_out` as they arrive, enabling the TTS
#worker to begin synthesis before generation finishes.
#
#Emits None as a terminal sentinel on token_out when generation is complete.
#Returns the full assembled response string.
#"""

import asyncio
import json
import logging
import httpx

from config import LLAMA_SERVER_URL, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Sentence-ending characters that trigger a TTS flush
SENTENCE_ENDINGS = frozenset({'.', '!', '?', '\n', ':', ';'})


class InferenceWorker:

    def __init__(self, session_id: str):
        self.session_id = session_id

    async def run(
        self,
        chat_history: list[dict],
        token_out: asyncio.Queue,
    ) -> str:
        """
        Stream tokens from the VLM into token_out.
        Returns the complete assistant response.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *chat_history,
        ]

        full_response: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    LLAMA_SERVER_URL,
                    json={
                        "model": "local",          # llama-server ignores this
                        "messages": messages,
                        "stream": True,
                        "max_tokens": 1024,
                        "temperature": 0.7,
                        "repeat_penalty": 1.1,
                    },
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break

                        try:
                            obj   = json.loads(payload)
                            token = obj["choices"][0]["delta"].get("content", "")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

                        if token:
                            full_response.append(token)
                            await token_out.put(token)

        except httpx.RequestError as exc:
            logger.error("[%s] llama-server error: %s", self.session_id, exc)
        finally:
            # Always send sentinel so TTS worker can finish cleanly
            await token_out.put(None)

        result = "".join(full_response).strip()
        logger.info("[%s] VLM response: %s", self.session_id, result[:120])
        return result
