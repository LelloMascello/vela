#!/usr/bin/env python3
"""
standby.py — Vela Engine Standby Service
=========================================
Listens on TCP port 9000 for two kinds of messages:

  FROM the Pi orchestrator:
    {"type": "wake"}
    → Start the LLM server (llama-server) and main.py if not already running.
    → Reply with {"ws_host": "<lan-ip>", "ws_port": 8765}.

  FROM main.py (when the last client disconnects):
    {"type": "idle"}
    → Terminate both main.py and llama-server to free resources.

Wire protocol: every message is a 4-byte big-endian length header followed by
UTF-8 JSON.  Same protocol used across the whole engine.
"""

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────

STANDBY_HOST = "0.0.0.0"
STANDBY_PORT = 9000
WS_PORT       = 8765          # port main.py will bind for WebSocket clients

# llama-server binary & model paths
LLAMA_BIN    = Path.home() / "llama.cpp/.build/bin/llama-server"
LLAMA_MODEL  = Path.home() / "llama.cpp/mymodels/gemma-4-E2B-it-Q4_K_M.gguf"
LLAMA_MMPROJ = Path.home() / "llama.cpp/mymodels/mmproj-F16.gguf"
LLAMA_HOST   = "127.0.0.1"
LLAMA_PORT   = 8080

ENGINE_DIR   = Path(__file__).parent

LLAMA_CMD = [
    str(LLAMA_BIN),
    "-m",        str(LLAMA_MODEL),
    "--mmproj",  str(LLAMA_MMPROJ),
    "--host",    LLAMA_HOST,
    "--port",    str(LLAMA_PORT),
    "-ngl",      "99",
    "--reasoning", "off",
]

LLAMA_READY_TIMEOUT = 90.0   # seconds to wait for the server to load the model
MAIN_STARTUP_PAUSE  =  1.5   # seconds to let main.py bind its WebSocket port

# ─── Process handles ──────────────────────────────────────────────────────────

_llama_proc: subprocess.Popen | None = None
_main_proc:  subprocess.Popen | None = None


# ─── Utilities ────────────────────────────────────────────────────────────────

async def send_msg(writer: asyncio.StreamWriter, obj: dict) -> None:
    data = json.dumps(obj).encode()
    writer.write(len(data).to_bytes(4, "big") + data)
    await writer.drain()


async def recv_msg(reader: asyncio.StreamReader) -> dict:
    hdr  = await reader.readexactly(4)
    body = await reader.readexactly(int.from_bytes(hdr, "big"))
    return json.loads(body)


def _alive(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


def _local_ip() -> str:
    """Best-effort: return the LAN IP that can reach the internet."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


async def _wait_llama_ready(timeout: float = LLAMA_READY_TIMEOUT) -> None:
    """Poll llama-server's /health endpoint until it returns HTTP 200."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            r, w = await asyncio.open_connection(LLAMA_HOST, LLAMA_PORT)
            w.write(b"GET /health HTTP/1.0\r\nHost: localhost\r\n\r\n")
            await w.drain()
            data = await asyncio.wait_for(r.read(256), timeout=3.0)
            w.close()
            await w.wait_closed()
            if b"200" in data:
                print("[standby] llama-server is ready.")
                return
        except Exception:
            pass
        await asyncio.sleep(1.5)
    raise TimeoutError(
        f"llama-server did not become ready within {timeout:.0f} s. "
        "Check that the model files exist and the binary path is correct."
    )


# ─── Engine lifecycle ─────────────────────────────────────────────────────────

async def _start_engine() -> None:
    global _llama_proc, _main_proc

    if _alive(_main_proc):
        print("[standby] Engine already running — reusing existing instance.")
        return

    # 1. Start the LLM server
    print("[standby] Launching llama-server …")
    _llama_proc = subprocess.Popen(
        LLAMA_CMD,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 2. Wait for it to finish loading the model
    print("[standby] Waiting for llama-server to load the model …")
    await _wait_llama_ready()

    # 3. Start main.py (which will in turn start the audio sub-processes)
    print("[standby] Launching main.py …")
    _main_proc = subprocess.Popen(
        [sys.executable, str(ENGINE_DIR / "main.py")],
        cwd=str(ENGINE_DIR),
    )

    # Give main.py time to bind the WebSocket port and start its sub-services
    await asyncio.sleep(MAIN_STARTUP_PAUSE)
    print("[standby] Engine is online.")


async def _stop_engine() -> None:
    global _llama_proc, _main_proc
    print("[standby] Shutting down engine …")

    for proc, label in [(_main_proc, "main.py"), (_llama_proc, "llama-server")]:
        if _alive(proc):
            proc.terminate()
            try:
                proc.wait(timeout=8)
                print(f"[standby] {label} terminated.")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"[standby] {label} killed (did not stop in time).")

    _main_proc  = None
    _llama_proc = None
    print("[standby] Engine is offline.")


# ─── Connection handler ───────────────────────────────────────────────────────

async def _handle_connection(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    peer = writer.get_extra_info("peername")
    try:
        msg = await asyncio.wait_for(recv_msg(reader), timeout=15.0)
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
        writer.close()
        return

    msg_type = msg.get("type")

    if msg_type == "wake":
        print(f"[standby] Wake signal from {peer}.")
        try:
            await _start_engine()
            await send_msg(writer, {
                "ws_host": _local_ip(),
                "ws_port": WS_PORT,
            })
            print(f"[standby] Sent WebSocket info to {peer}.")
        except Exception as exc:
            print(f"[standby] Failed to start engine: {exc}")
            await send_msg(writer, {"error": str(exc)})

    elif msg_type == "idle":
        print(f"[standby] Idle signal from main.py ({peer}) — no clients remain.")
        await _stop_engine()

    else:
        print(f"[standby] Unknown message type from {peer}: {msg_type!r}")

    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    server = await asyncio.start_server(
        _handle_connection, STANDBY_HOST, STANDBY_PORT
    )
    addrs = [str(s.getsockname()) for s in server.sockets]
    print(f"[standby] Listening on {', '.join(addrs)}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[standby] Interrupted.")
        for proc in (_main_proc, _llama_proc):
            if _alive(proc):
                proc.terminate()
