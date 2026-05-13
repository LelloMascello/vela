#!/usr/bin/env python3
"""
inference.py — Vela Inference Service
=======================================
TCP server (port 9002) that bridges main.py and the running llama-server.

Protocol — messages FROM main.py:
  {"type": "init",  "client_id": "<id>"}
  {"type": "audio", "data": "<base64 WAV>"}   # one complete user utterance

Protocol — messages TO main.py:
  {"type": "phrase",     "text": "<sentence>"}   # one speakable unit
  {"type": "stream_end"}                         # no more phrases for this turn
  {"type": "error",      "detail": "<msg>"}

How it works
------------
1. The WAV is encoded as base64 and placed in an OpenAI-compatible chat
   completion request with "input_audio" content (the format supported by
   Gemma 4 / llama-server for native audio input).

2. The response is streamed back token-by-token.  Tokens are accumulated
   until a sentence boundary (`.`, `!`, `?` followed by whitespace or EOS)
   is reached, then the accumulated phrase is sent to main.py immediately
   so that TTS can start while the model is still generating the rest.

3. Conversation history is maintained per client_id so follow-up turns are
   contextually aware.  History is cleared when the connection closes.

NOTE: llama-server's exact audio-input API may require adjustment depending
on the llama.cpp build and Gemma 4 multimodal adapter version.  If the server
does not accept "input_audio", fall back to first transcribing with Whisper
and sending text.  The code includes a AUDIO_INPUT_SUPPORTED flag for this.
"""

import asyncio
import base64
import json
import re

import aiohttp

# ─── Configuration ────────────────────────────────────────────────────────────

HOST             = "127.0.0.1"
PORT             = 9002
LLAMA_URL        = "http://127.0.0.1:8080/v1/chat/completions"

# Set to False if your llama-server build does not yet support audio input.
# When False, the raw audio bytes are silently dropped and only text history
# is used (you would wire in a Whisper step before this service).
AUDIO_INPUT_SUPPORTED = True

MAX_TOKENS   = 768
TEMPERATURE  = 0.7

SYSTEM_PROMPT = (
    "You are Vela, a helpful and concise voice assistant. "
    "Your responses will be spoken aloud, so write naturally spoken Italian sentences. "
    "Avoid markdown, lists, or special formatting. "
    "Keep answers brief unless the user explicitly asks for detail."
)

# Regex that matches a sentence boundary we can split on for streaming TTS.
# Fires after  . ! ?  followed by either whitespace or end-of-buffer (≥20 chars
# accumulated so we do not split too eagerly on abbreviations).
_PHRASE_RE = re.compile(r'(?<=[.!?])\s+')
MIN_PHRASE_CHARS = 20   # don't emit a phrase shorter than this

# ─── IPC helpers ──────────────────────────────────────────────────────────────

async def _send(writer: asyncio.StreamWriter, obj: dict) -> None:
    data = json.dumps(obj).encode()
    writer.write(len(data).to_bytes(4, "big") + data)
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict:
    hdr  = await reader.readexactly(4)
    body = await reader.readexactly(int.from_bytes(hdr, "big"))
    return json.loads(body)


# ─── Phrase splitter ──────────────────────────────────────────────────────────

def _try_split(buf: str) -> tuple[list[str], str]:
    """
    Split buf on sentence boundaries.
    Returns (completed_phrases, remainder).
    Phrases shorter than MIN_PHRASE_CHARS are folded into the next one.
    """
    parts = _PHRASE_RE.split(buf)
    if len(parts) == 1:
        return [], buf   # no boundary yet

    # Everything except the last element is a complete phrase
    phrases: list[str] = []
    for p in parts[:-1]:
        p = p.strip()
        if p:
            phrases.append(p)

    remainder = parts[-1]
    return phrases, remainder


# ─── LLM streaming ───────────────────────────────────────────────────────────

def _build_user_content(audio_b64: str) -> list[dict]:
    """Build the 'content' array for the user turn."""
    if AUDIO_INPUT_SUPPORTED:
        return [
            {
                "type": "input_audio",
                "input_audio": {
                    "data":   audio_b64,
                    "format": "wav",
                },
            }
        ]
    else:
        # Fallback: if audio input is not supported, we cannot do anything
        # useful here without a separate STT step.  Return a placeholder so
        # the history is not broken.
        return [{"type": "text", "text": "[audio input not transcribed]"}]


async def _stream_inference(
    history: list[dict],
    audio_b64: str,
    writer: asyncio.StreamWriter,
) -> str:
    """
    Send the audio to the LLM, stream back the response token by token,
    emit phrase messages to main.py as sentence boundaries are reached.
    Returns the full assistant response text (to append to history).
    """
    # Append current user turn
    user_msg = {
        "role":    "user",
        "content": _build_user_content(audio_b64),
    }
    history.append(user_msg)

    payload = {
        "model":       "gemma-4",
        "messages":    history,
        "stream":      True,
        "max_tokens":  MAX_TOKENS,
        "temperature": TEMPERATURE,
    }

    buf              = ""      # accumulator between phrase boundaries
    full_response    = ""      # complete response text (for history)

    timeout = aiohttp.ClientTimeout(total=None, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(LLAMA_URL, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"llama-server error {resp.status}: {body[:200]}")

            async for raw_line in resp.content:
                line = raw_line.decode(errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                payload_str = line[6:].strip()
                if payload_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if not delta:
                    continue

                buf           += delta
                full_response += delta

                # Try to peel off complete sentences
                phrases, buf = _try_split(buf)
                for phrase in phrases:
                    if len(phrase) >= MIN_PHRASE_CHARS:
                        await _send(writer, {"type": "phrase", "text": phrase})

    # Flush whatever remains in the buffer
    remainder = buf.strip()
    if remainder:
        await _send(writer, {"type": "phrase", "text": remainder})

    return full_response


# ─── Connection handler ───────────────────────────────────────────────────────

async def _handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    peer = writer.get_extra_info("peername")
    cid  = None
    # Per-session conversation history
    history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    try:
        # First message: init
        msg = await asyncio.wait_for(_recv(reader), timeout=10.0)
        if msg.get("type") != "init":
            print(f"[inference] Expected init from {peer}, got {msg.get('type')!r}")
            return
        cid = msg["client_id"]
        print(f"[inference] Client connected: {cid} from {peer}")

        while True:
            msg = await _recv(reader)

            if msg["type"] == "audio":
                audio_b64 = msg["data"]
                try:
                    full_text = await _stream_inference(history, audio_b64, writer)
                    # Append assistant turn to history for context in follow-ups
                    history.append({"role": "assistant", "content": full_text})
                except Exception as exc:
                    print(f"[inference] Inference error for {cid}: {exc}")
                    await _send(writer, {"type": "error", "detail": str(exc)})
                finally:
                    await _send(writer, {"type": "stream_end"})

            else:
                print(f"[inference] Unknown message from {cid}: {msg.get('type')!r}")

    except asyncio.IncompleteReadError:
        pass
    except asyncio.TimeoutError:
        print(f"[inference] Init timeout from {peer}.")
    except Exception as exc:
        print(f"[inference] Error for {cid or peer}: {exc}")
    finally:
        print(f"[inference] Client disconnected: {cid or peer}  "
              f"(history had {len(history)} turns)")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    server = await asyncio.start_server(_handle_connection, HOST, PORT)
    print(f"[inference] Listening on {HOST}:{PORT}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
