#!/usr/bin/env python3
"""
router.py — Vela Orchestrator · Audio Stream Router
====================================================
WebSocket server (port 8766).

Connection lifecycle
--------------------
1. Client opens ws://pi:8766
2. Client sends first message (JSON):
       { "type": "auth", "token": "<JWT from auth.py>" }
3. Router validates the JWT.
   • Failure → send error JSON, close.
   • Success → send { "type": "ready" }
4. Client streams raw 16-kHz 16-bit mono PCM audio as binary WebSocket frames.
5. Each chunk is forwarded to wake_word_detector.py via HTTP POST /detect
   (client_id sent as X-Client-Id header so the detector keeps per-client state).
6. When the detector returns { "detected": true }:
   a. Router sends a TCP "wake" message to standby.py (engine) using the
      4-byte length-prefixed JSON protocol, receives ws_host / ws_port back.
   b. Router streams the audio cue bytes ("Sì, di cosa hai bisogno?")
      to the client as a binary WebSocket message.
   c. Router sends { "type": "handoff", "ws_host": ..., "ws_port": ... }
      to the client — the client must now open a *new* connection to
      main.py at that address.
   d. Router closes this connection cleanly.
"""

import asyncio
import json
import os
import socket
import uuid
from pathlib import Path

import aiohttp
import jwt
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

# ─── Configuration ────────────────────────────────────────────────────────────

BASE_DIR        = Path(__file__).parent
SECRET_KEY      = os.environ.get("VELA_SECRET",          "vela-secret-CHANGE-in-production")
ROUTER_PORT     = int(os.environ.get("VELA_ROUTER_PORT",  8766))
DETECTOR_URL    = os.environ.get("VELA_DETECTOR_URL",     "http://127.0.0.1:5002/detect")
DETECTOR_RESET  = os.environ.get("VELA_DETECTOR_RESET",  "http://127.0.0.1:5002/reset")
STANDBY_HOST    = os.environ.get("VELA_STANDBY_HOST",    "127.0.0.1")
STANDBY_PORT    = int(os.environ.get("VELA_STANDBY_PORT", 9000))
CUE_AUDIO_PATH  = Path(os.environ.get("VELA_CUE_PATH",   str(BASE_DIR / "audio" / "standby_cue.wav")))

DETECTION_THRESHOLD = float(os.environ.get("VELA_THRESHOLD", 0.5))

# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _tcp_send_recv(host: str, port: int, obj: dict) -> dict:
    """
    Send a single request to standby.py using the 4-byte length-prefixed
    JSON wire protocol and return the response.
    """
    reader, writer = await asyncio.open_connection(host, port)
    try:
        data = json.dumps(obj).encode("utf-8")
        writer.write(len(data).to_bytes(4, "big") + data)
        await writer.drain()

        hdr  = await asyncio.wait_for(reader.readexactly(4), timeout=15.0)
        body = await asyncio.wait_for(
            reader.readexactly(int.from_bytes(hdr, "big")), timeout=15.0
        )
        return json.loads(body)
    finally:
        writer.close()
        await writer.wait_closed()


def _validate_token(token: str) -> str | None:
    """
    Validate a JWT token.  Returns the username (sub) on success, None on failure.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def _local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


async def _load_cue_bytes() -> bytes | None:
    """Load the audio cue from disk; returns None if the file doesn't exist."""
    if CUE_AUDIO_PATH.exists():
        return CUE_AUDIO_PATH.read_bytes()
    print(f"[router] ⚠  Audio cue not found at {CUE_AUDIO_PATH}. "
          "Run generate_cue.py to create it.")
    return None


# ─── Wake-word detection ──────────────────────────────────────────────────────

async def _detect_chunk(
    session: aiohttp.ClientSession,
    audio_bytes: bytes,
    client_id: str,
) -> bool:
    """POST an audio chunk to wake_word_detector.py and return detected flag."""
    try:
        async with session.post(
            DETECTOR_URL,
            data=audio_bytes,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Client-Id":  client_id,
            },
            timeout=aiohttp.ClientTimeout(total=2.0),
        ) as resp:
            result = await resp.json()
            score  = result.get("score", 0.0)
            if result.get("detected"):
                print(f"[router] Wake word detected for client={client_id!r}  score={score:.3f}")
            return bool(result.get("detected", False))
    except Exception as exc:
        print(f"[router] Detector error for {client_id!r}: {exc}")
        return False


async def _reset_detector(session: aiohttp.ClientSession, client_id: str) -> None:
    """Tell the detector to discard buffered audio for this client."""
    try:
        async with session.post(
            DETECTOR_RESET,
            headers={"X-Client-Id": client_id},
            timeout=aiohttp.ClientTimeout(total=2.0),
        ) as _:
            pass
    except Exception:
        pass


# ─── Wake-word action ─────────────────────────────────────────────────────────

async def _handle_wake_word(websocket, username: str) -> None:
    """
    Called when the wake word is detected for a connected client:
      1. Ask standby.py to spin up the engine, get main.py WS address.
      2. Stream the audio cue to the client.
      3. Send a handoff message with main.py's address.
    """
    print(f"[router] → Contacting standby.py for user={username!r} …")

    # 1. Wake the engine
    try:
        resp = await _tcp_send_recv(STANDBY_HOST, STANDBY_PORT, {"type": "wake"})
    except Exception as exc:
        print(f"[router] standby.py unreachable: {exc}")
        await websocket.send(json.dumps({
            "type":  "error",
            "error": "Engine unavailable — please try again in a moment.",
        }))
        return

    if "error" in resp:
        print(f"[router] standby.py returned error: {resp['error']}")
        await websocket.send(json.dumps({"type": "error", "error": resp["error"]}))
        return

    ws_host = resp.get("ws_host", _local_ip())
    ws_port = resp.get("ws_port", 8765)
    print(f"[router] Engine ready at {ws_host}:{ws_port}")

    # 2. Send audio cue
    cue_bytes = await _load_cue_bytes()
    if cue_bytes:
        await websocket.send(cue_bytes)          # binary frame → client plays it
        print(f"[router] Audio cue sent to {username!r} ({len(cue_bytes)} bytes)")

    # 3. Handoff
    await websocket.send(json.dumps({
        "type":    "handoff",
        "ws_host": ws_host,
        "ws_port": ws_port,
    }))
    print(f"[router] Handoff sent to {username!r} → ws://{ws_host}:{ws_port}")


# ─── Connection handler ───────────────────────────────────────────────────────

async def _handle_connection(websocket) -> None:
    """Main handler for each incoming WebSocket connection."""
    peer = websocket.remote_address

    # ── Step 1: Authentication ────────────────────────────────────────────────
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
    except asyncio.TimeoutError:
        print(f"[router] Auth timeout from {peer}")
        await websocket.close(1008, "Auth timeout")
        return
    except (ConnectionClosedError, ConnectionClosedOK):
        return

    try:
        auth_msg = json.loads(raw)
        assert auth_msg.get("type") == "auth"
        token = auth_msg["token"]
    except (json.JSONDecodeError, KeyError, AssertionError):
        await websocket.send(json.dumps({"type": "error", "error": "Expected {type:auth, token:...}"}))
        await websocket.close(1008, "Bad auth message")
        return

    username = _validate_token(token)
    if username is None:
        await websocket.send(json.dumps({"type": "error", "error": "Invalid or expired token"}))
        await websocket.close(1008, "Invalid token")
        return

    client_id = f"{username}-{uuid.uuid4().hex[:8]}"
    print(f"[router] Client connected: user={username!r}  id={client_id}  peer={peer}")
    await websocket.send(json.dumps({"type": "ready", "client_id": client_id}))

    # ── Step 2: Audio stream → wake word detector ─────────────────────────────
    wake_detected = False
    async with aiohttp.ClientSession() as session:
        try:
            async for message in websocket:
                if not isinstance(message, bytes):
                    continue  # ignore any stray text frames after auth

                wake_detected = await _detect_chunk(session, message, client_id)
                if wake_detected:
                    await _handle_wake_word(websocket, username)
                    break

        except (ConnectionClosedError, ConnectionClosedOK):
            pass
        except Exception as exc:
            print(f"[router] Unexpected error for {client_id}: {exc}")
        finally:
            # Clean up per-client detector state
            await _reset_detector(session, client_id)

    print(f"[router] Client disconnected: {client_id}  (wake={wake_detected})")


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"[router] Listening on ws://0.0.0.0:{ROUTER_PORT}")
    print(f"[router] Wake word detector  → {DETECTOR_URL}")
    print(f"[router] Standby (engine)    → tcp://{STANDBY_HOST}:{STANDBY_PORT}")
    print(f"[router] Audio cue           → {CUE_AUDIO_PATH}")

    async with websockets.serve(
        _handle_connection,
        "0.0.0.0",
        ROUTER_PORT,
        ping_interval=20,
        ping_timeout=40,
        max_size=512 * 1024,    # 512 KB max message (generous for audio chunks)
    ) as server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[router] Interrupted.")
