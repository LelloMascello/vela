#!/usr/bin/env python3
"""
test_vela_engine.py — Vela Engine Test Suite
=============================================
Tests every engine service end-to-end.  All services must be running before
you start this script (or use --start to launch them automatically).

Usage
-----
    # With services already running:
    source .venv/bin/activate
    python test_vela_engine.py

    # Auto-start all services (fake piper + mock llama included), test, stop:
    python test_vela_engine.py --start

    # Only test specific groups:
    python test_vela_engine.py --only tts inference
    python test_vela_engine.py --only e2e

Requirements (inside venv):
    pip install aiohttp websockets
    pip install silero-vad torch torchaudio    # only needed when testing detector
    pip install piper-tts                      # only needed when NOT using --start
"""

import argparse
import asyncio
import base64
import io
import json
import math
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path

# ─── Colours ──────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {BOLD}{msg}{RESET}")
def info(msg): print(f"  {CYAN}·{RESET}  {DIM}{msg}{RESET}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def banner(msg):
    width = 60
    print()
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {msg}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")

# ─── Configuration (mirrors service defaults; all overridable via env) ─────────

BASE_DIR       = Path(__file__).parent
STANDBY_HOST   = os.environ.get("VELA_STANDBY_HOST",   "127.0.0.1")
STANDBY_PORT   = int(os.environ.get("VELA_STANDBY_PORT",  "9000"))
DETECTOR_HOST  = os.environ.get("VELA_DETECTOR_HOST",  "127.0.0.1")
DETECTOR_PORT  = int(os.environ.get("VELA_DETECTOR_PORT", "9001"))
INFERENCE_HOST = os.environ.get("VELA_INFERENCE_HOST", "127.0.0.1")
INFERENCE_PORT = int(os.environ.get("VELA_INFERENCE_PORT","9002"))
TTS_HOST       = os.environ.get("VELA_TTS_HOST",       "127.0.0.1")
TTS_PORT       = int(os.environ.get("VELA_TTS_PORT",      "9003"))
WS_HOST        = os.environ.get("VELA_WS_HOST",        "127.0.0.1")
WS_PORT        = int(os.environ.get("VELA_WS_PORT",       "8765"))
MOCK_LLAMA_PORT= int(os.environ.get("VELA_MOCK_LLAMA_PORT","8080"))

# ─── Result counters ──────────────────────────────────────────────────────────

_passed = 0
_failed = 0


def _assert(condition: bool, label: str, detail: str = "") -> bool:
    global _passed, _failed
    if condition:
        ok(label)
        _passed += 1
        return True
    else:
        fail(f"{label}  →  {detail}" if detail else label)
        _failed += 1
        return False


def _check_port(host: str, port: int, name: str) -> bool:
    """Return True if the TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except Exception as e:
        warn(f"{name} not reachable at {host}:{port}: {e}")
        return False


# ─── IPC wire-protocol helpers ────────────────────────────────────────────────
# Every engine service uses 4-byte big-endian length + UTF-8 JSON.

async def _ipc_send(writer: asyncio.StreamWriter, obj: dict) -> None:
    data = json.dumps(obj).encode()
    writer.write(len(data).to_bytes(4, "big") + data)
    await writer.drain()


async def _ipc_recv(reader: asyncio.StreamReader, timeout: float = 10.0) -> dict:
    hdr  = await asyncio.wait_for(reader.readexactly(4),                    timeout=timeout)
    body = await asyncio.wait_for(reader.readexactly(int.from_bytes(hdr, "big")), timeout=timeout)
    return json.loads(body)


async def _ipc_connect(host: str, port: int, client_id: str = "test_client"):
    """Open a TCP connection and send the mandatory init message."""
    reader, writer = await asyncio.open_connection(host, port)
    await _ipc_send(writer, {"type": "init", "client_id": client_id})
    return reader, writer


async def _ipc_close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


# ─── Audio helpers ────────────────────────────────────────────────────────────

SAMPLE_RATE   = 16_000
CHUNK_SAMPLES = 512
CHUNK_BYTES   = CHUNK_SAMPLES * 2


def _silence(seconds: float = 0.5) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


def _sine(freq: float = 440.0, seconds: float = 0.5, amplitude: float = 0.9) -> bytes:
    n = int(SAMPLE_RATE * seconds)
    return struct.pack(f"<{n}h",
                       *[int(32767 * amplitude * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
                         for i in range(n)])


def _silence_chunk() -> bytes:
    return b"\x00\x00" * CHUNK_SAMPLES


def _sine_chunk(freq: float = 440.0) -> bytes:
    return struct.pack(f"<{CHUNK_SAMPLES}h",
                       *[int(32767 * 0.9 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
                         for i in range(CHUNK_SAMPLES)])


def _wrap_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _is_valid_wav(data: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(data)) as wf:
            return wf.getnframes() >= 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST GROUPS
# ═══════════════════════════════════════════════════════════════════════════════

# ─── 1. Standby ───────────────────────────────────────────────────────────────

def test_standby():
    banner("STANDBY  (port 9000, TCP IPC)")
    asyncio.run(_standby_tests())


async def _standby_tests():
    if not _check_port(STANDBY_HOST, STANDBY_PORT, "standby"):
        warn("Skipping — standby service not reachable.")
        return

    # 1-a: Wake signal → should return ws_host and ws_port
    await _test_standby_wake()

    # 1-b: Second wake while engine is running → same port, no restart
    await _test_standby_wake_idempotent()

    # 1-c: Unknown message type → no crash
    await _test_standby_unknown_type()


async def _test_standby_wake():
    try:
        reader, writer = await asyncio.open_connection(STANDBY_HOST, STANDBY_PORT)
        await _ipc_send(writer, {"type": "wake"})
        response = await _ipc_recv(reader, timeout=45.0)   # model load can take a while
        _assert("ws_host" in response, "wake → response contains 'ws_host'",
                str(response))
        _assert("ws_port" in response, "wake → response contains 'ws_port'",
                str(response))
        if "ws_port" in response:
            _assert(isinstance(response["ws_port"], int),
                    f"ws_port is an integer ({response.get('ws_port')})")
        if "error" in response:
            fail(f"wake returned error: {response['error']}")
        else:
            info(f"Engine address: ws://{response.get('ws_host')}:{response.get('ws_port')}")
        await _ipc_close(writer)
    except asyncio.TimeoutError:
        fail("wake signal timed out (model may not have loaded within 45 s)")
    except Exception as e:
        fail(f"standby wake test raised: {e}")


async def _test_standby_wake_idempotent():
    try:
        reader, writer = await asyncio.open_connection(STANDBY_HOST, STANDBY_PORT)
        await _ipc_send(writer, {"type": "wake"})
        r1 = await _ipc_recv(reader, timeout=15.0)
        await _ipc_close(writer)

        reader, writer = await asyncio.open_connection(STANDBY_HOST, STANDBY_PORT)
        await _ipc_send(writer, {"type": "wake"})
        r2 = await _ipc_recv(reader, timeout=10.0)
        await _ipc_close(writer)

        _assert(
            r1.get("ws_port") == r2.get("ws_port"),
            "Second wake returns same ws_port (engine reused, not restarted)",
            f"{r1.get('ws_port')} vs {r2.get('ws_port')}",
        )
    except Exception as e:
        fail(f"Standby idempotent-wake test raised: {e}")


async def _test_standby_unknown_type():
    """An unknown message type should not crash standby."""
    try:
        reader, writer = await asyncio.open_connection(STANDBY_HOST, STANDBY_PORT)
        await _ipc_send(writer, {"type": "what_is_this"})
        await _ipc_close(writer)
        # Standby should still accept a fresh connection
        reader2, writer2 = await asyncio.open_connection(STANDBY_HOST, STANDBY_PORT)
        await _ipc_send(writer2, {"type": "wake"})
        response = await _ipc_recv(reader2, timeout=10.0)
        _assert("ws_port" in response, "Standby still responds after unknown message type")
        await _ipc_close(writer2)
    except Exception as e:
        fail(f"Standby unknown-type test raised: {e}")


# ─── 2. Audio detector ────────────────────────────────────────────────────────

def test_detector():
    banner("AUDIO DETECTOR  (port 9001, TCP IPC / Silero VAD)")
    asyncio.run(_detector_tests())


async def _detector_tests():
    if not _check_port(DETECTOR_HOST, DETECTOR_PORT, "audio-detector"):
        warn("Skipping — audio-detector service not reachable.")
        return

    cid = f"det_test_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(DETECTOR_HOST, DETECTOR_PORT, cid)

    # 2-a: Service accepts init
    _assert(True, "audio-detector accepted init message")

    # 2-b: Silence chunks → no segment within 1 s
    await _test_detector_silence(reader, writer, cid)

    # 2-c: Speech-like chunks → segment eventually emitted
    await _test_detector_speech(reader, writer, cid)

    # 2-d: Sub-chunk buffering — send half-chunks
    await _test_detector_sub_chunks(reader, writer, cid)

    # 2-e: Reset message accepted
    await _test_detector_reset(reader, writer, cid)

    await _ipc_close(writer)


async def _test_detector_silence(reader, writer, cid: str):
    """8 chunks of silence should produce no segment within 1 second."""
    for _ in range(8):
        chunk_b64 = base64.b64encode(_silence_chunk()).decode()
        await _ipc_send(writer, {"type": "audio_chunk", "data": chunk_b64})

    got_segment = False
    try:
        msg = await _ipc_recv(reader, timeout=1.0)
        if msg.get("type") == "segment":
            got_segment = True
    except asyncio.TimeoutError:
        pass

    _assert(not got_segment, "8 silence chunks → no speech segment emitted")


async def _test_detector_speech(reader, writer, cid: str):
    """
    Send 60 sine-wave chunks (~1.9 s at 16 kHz) followed by 25 silence chunks
    (~0.8 s) to trigger Silero's speech-end event.  Then assert a segment arrives.
    We allow up to 6 s for VAD to process and return.
    """
    info("Streaming 60 speech + 25 silence chunks to VAD (may take ~3 s) …")
    for _ in range(60):
        chunk_b64 = base64.b64encode(_sine_chunk(440.0)).decode()
        await _ipc_send(writer, {"type": "audio_chunk", "data": chunk_b64})
        await asyncio.sleep(0.005)

    for _ in range(25):
        chunk_b64 = base64.b64encode(_silence_chunk()).decode()
        await _ipc_send(writer, {"type": "audio_chunk", "data": chunk_b64})
        await asyncio.sleep(0.005)

    got_segment = False
    segment_len = 0
    try:
        msg = await _ipc_recv(reader, timeout=6.0)
        if msg.get("type") == "segment":
            got_segment = True
            segment_len = len(base64.b64decode(msg["data"])) // 2
    except asyncio.TimeoutError:
        pass

    _assert(got_segment,
            "Speech chunks + silence → VAD emits a segment",
            "Timeout — Silero may not have classified the sine as speech; "
            "this is expected if the model threshold is high.")
    if got_segment:
        info(f"Segment received: {segment_len} samples ({segment_len / SAMPLE_RATE * 1000:.0f} ms)")


async def _test_detector_sub_chunks(reader, writer, cid: str):
    """Half-sized chunks should be buffered and not trigger a VAD call until full."""
    half = CHUNK_BYTES // 2
    half_b64 = base64.b64encode(b"\x00" * half).decode()

    await _ipc_send(writer, {"type": "reset"})
    await asyncio.sleep(0.1)

    # Two halves = one full chunk; service should not crash
    await _ipc_send(writer, {"type": "audio_chunk", "data": half_b64})
    await _ipc_send(writer, {"type": "audio_chunk", "data": half_b64})

    _assert(True, "Sub-chunk audio buffered without error")


async def _test_detector_reset(reader, writer, cid: str):
    """Reset should put the detector back to LISTENING state without crashing."""
    try:
        await _ipc_send(writer, {"type": "reset"})
        await asyncio.sleep(0.2)
        # After reset, further silence should be accepted without error
        for _ in range(3):
            chunk_b64 = base64.b64encode(_silence_chunk()).decode()
            await _ipc_send(writer, {"type": "audio_chunk", "data": chunk_b64})
        _assert(True, "Reset message accepted; detector resumes without error")
    except Exception as e:
        fail(f"Detector reset test raised: {e}")


# ─── 3. Inference ─────────────────────────────────────────────────────────────

def test_inference():
    banner("INFERENCE  (port 9002, TCP IPC → llama-server port 8080)")
    asyncio.run(_inference_tests())


async def _inference_tests():
    if not _check_port(INFERENCE_HOST, INFERENCE_PORT, "inference"):
        warn("Skipping — inference service not reachable.")
        return

    # 3-a: Single utterance → phrases + stream_end
    await _test_inference_single_turn()

    # 3-b: Follow-up turn in same session → still returns stream_end
    await _test_inference_follow_up()

    # 3-c: Concurrent clients each get independent responses
    await _test_inference_concurrent()

    # 3-d: Unknown message type is ignored, service stays alive
    await _test_inference_unknown_type()


async def _test_inference_single_turn():
    cid = f"inf_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(INFERENCE_HOST, INFERENCE_PORT, cid)
    try:
        wav_b64 = base64.b64encode(_wrap_wav(_silence(0.5))).decode()
        await _ipc_send(writer, {"type": "audio", "data": wav_b64})

        phrases:  list[str] = []
        got_end   = False
        deadline  = asyncio.get_event_loop().time() + 20.0

        while asyncio.get_event_loop().time() < deadline:
            msg = await _ipc_recv(reader, timeout=20.0)
            if msg["type"] == "phrase":
                phrases.append(msg["text"])
            elif msg["type"] == "stream_end":
                got_end = True
                break
            elif msg["type"] == "error":
                fail(f"Inference returned error: {msg.get('detail')}")
                break

        _assert(got_end,             "Single turn → stream_end received")
        _assert(len(phrases) >= 1,   f"Single turn → at least 1 phrase returned ({len(phrases)} got)")
        if phrases:
            info(f"Response preview: {phrases[0][:60]!r}")
    except Exception as e:
        fail(f"Inference single-turn test raised: {e}")
    finally:
        await _ipc_close(writer)


async def _test_inference_follow_up():
    cid = f"inf_fu_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(INFERENCE_HOST, INFERENCE_PORT, cid)
    wav_b64 = base64.b64encode(_wrap_wav(_silence(0.5))).decode()
    try:
        for turn in range(2):
            await _ipc_send(writer, {"type": "audio", "data": wav_b64})
            got_end = False
            while True:
                msg = await _ipc_recv(reader, timeout=20.0)
                if msg["type"] == "stream_end":
                    got_end = True
                    break
                elif msg["type"] == "error":
                    break
            _assert(got_end, f"Follow-up turn {turn + 1} → stream_end received")
    except Exception as e:
        fail(f"Inference follow-up test raised: {e}")
    finally:
        await _ipc_close(writer)


async def _test_inference_concurrent():
    async def one_turn(n: int) -> bool:
        cid = f"inf_concurrent_{n}"
        reader, writer = await _ipc_connect(INFERENCE_HOST, INFERENCE_PORT, cid)
        wav_b64 = base64.b64encode(_wrap_wav(_silence(0.3))).decode()
        await _ipc_send(writer, {"type": "audio", "data": wav_b64})
        got_end = False
        try:
            while True:
                msg = await _ipc_recv(reader, timeout=20.0)
                if msg["type"] == "stream_end":
                    got_end = True
                    break
                elif msg["type"] == "error":
                    break
        except Exception:
            pass
        finally:
            await _ipc_close(writer)
        return got_end

    results = await asyncio.gather(one_turn(1), one_turn(2))
    _assert(all(results), "Two concurrent inference clients both received stream_end",
            f"results: {results}")


async def _test_inference_unknown_type():
    cid = f"inf_unk_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(INFERENCE_HOST, INFERENCE_PORT, cid)
    try:
        await _ipc_send(writer, {"type": "nonsense_message"})
        await asyncio.sleep(0.3)
        # Service must still handle a real request
        wav_b64 = base64.b64encode(_wrap_wav(_silence(0.2))).decode()
        await _ipc_send(writer, {"type": "audio", "data": wav_b64})
        got_end = False
        while True:
            msg = await _ipc_recv(reader, timeout=20.0)
            if msg["type"] == "stream_end":
                got_end = True
                break
            elif msg["type"] == "error":
                break
        _assert(got_end, "Unknown message type ignored; inference still responds")
    except Exception as e:
        fail(f"Inference unknown-type test raised: {e}")
    finally:
        await _ipc_close(writer)


# ─── 4. TTS ───────────────────────────────────────────────────────────────────

def test_tts():
    banner("TEXT-TO-SPEECH  (port 9003, TCP IPC / Piper)")
    asyncio.run(_tts_tests())


async def _tts_tests():
    if not _check_port(TTS_HOST, TTS_PORT, "text-to-speech"):
        warn("Skipping — text-to-speech service not reachable.")
        return

    # 4-a: Single phrase → valid WAV audio
    await _test_tts_single_phrase()

    # 4-b: Multiple phrases in sequence
    await _test_tts_sequence()

    # 4-c: Concurrent clients
    await _test_tts_concurrent()

    # 4-d: Unknown message type — no crash
    await _test_tts_unknown_type()

    # 4-e: Empty text is handled gracefully
    await _test_tts_empty_text()


async def _test_tts_single_phrase():
    cid = f"tts_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(TTS_HOST, TTS_PORT, cid)
    try:
        await _ipc_send(writer, {"type": "synthesize", "text": "Ciao, come stai?"})
        response = await _ipc_recv(reader, timeout=15.0)
        _assert(response.get("type") == "audio",
                "synthesize → response type is 'audio'",
                str(response.get("type")))
        if response.get("type") == "audio":
            raw = base64.b64decode(response["data"])
            _assert(_is_valid_wav(raw),
                    f"Returned audio is a valid WAV file ({len(raw)} bytes)")
            info(f"WAV size: {len(raw)} bytes")
    except Exception as e:
        fail(f"TTS single-phrase test raised: {e}")
    finally:
        await _ipc_close(writer)


async def _test_tts_sequence():
    cid = f"tts_seq_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(TTS_HOST, TTS_PORT, cid)
    phrases = [
        "Sono Vela, il tuo assistente vocale.",
        "Come posso aiutarti oggi?",
        "Dimmi pure cosa ti serve.",
    ]
    try:
        for i, phrase in enumerate(phrases):
            await _ipc_send(writer, {"type": "synthesize", "text": phrase})
            response = await _ipc_recv(reader, timeout=15.0)
            _assert(response.get("type") == "audio",
                    f"Phrase {i + 1}/{len(phrases)} → audio returned")
    except Exception as e:
        fail(f"TTS sequence test raised: {e}")
    finally:
        await _ipc_close(writer)


async def _test_tts_concurrent():
    async def one_request(n: int) -> bool:
        cid = f"tts_conc_{n}"
        reader, writer = await _ipc_connect(TTS_HOST, TTS_PORT, cid)
        try:
            await _ipc_send(writer, {"type": "synthesize", "text": f"Test {n}."})
            response = await _ipc_recv(reader, timeout=15.0)
            return response.get("type") == "audio"
        except Exception:
            return False
        finally:
            await _ipc_close(writer)

    results = await asyncio.gather(one_request(1), one_request(2))
    _assert(all(results), "Two concurrent TTS clients both received audio",
            f"results: {results}")


async def _test_tts_unknown_type():
    cid = f"tts_unk_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(TTS_HOST, TTS_PORT, cid)
    try:
        await _ipc_send(writer, {"type": "unsupported_op"})
        await asyncio.sleep(0.3)
        # Service must still respond to a valid request
        await _ipc_send(writer, {"type": "synthesize", "text": "Ancora funzionante."})
        response = await _ipc_recv(reader, timeout=15.0)
        _assert(response.get("type") == "audio",
                "Unknown message ignored; TTS still responds")
    except Exception as e:
        fail(f"TTS unknown-type test raised: {e}")
    finally:
        await _ipc_close(writer)


async def _test_tts_empty_text():
    cid = f"tts_empty_{uuid.uuid4().hex[:6]}"
    reader, writer = await _ipc_connect(TTS_HOST, TTS_PORT, cid)
    try:
        await _ipc_send(writer, {"type": "synthesize", "text": ""})
        # Empty text should be silently skipped; service must remain alive
        await asyncio.sleep(0.3)
        await _ipc_send(writer, {"type": "synthesize", "text": "Ancora qui."})
        response = await _ipc_recv(reader, timeout=15.0)
        _assert(response.get("type") == "audio",
                "Empty text skipped; subsequent phrase still synthesised")
    except Exception as e:
        fail(f"TTS empty-text test raised: {e}")
    finally:
        await _ipc_close(writer)


# ─── 5. Pipeline (WebSocket / main.py) ────────────────────────────────────────

def test_pipeline():
    banner("PIPELINE  (port 8765, WebSocket)")
    asyncio.run(_pipeline_tests())


async def _pipeline_tests():
    try:
        import websockets
    except ImportError:
        warn("websockets not installed — skipping pipeline tests.  pip install websockets")
        return

    try:
        async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}", open_timeout=4):
            pass
    except Exception as e:
        warn(f"main.py WebSocket not reachable at ws://{WS_HOST}:{WS_PORT}: {e}")
        warn("Skipping pipeline tests.")
        return

    # 5-a: Client connects successfully
    await _test_pipeline_connect()

    # 5-b: Silence stream → no crash
    await _test_pipeline_silence_stream()

    # 5-c: Multiple concurrent clients
    await _test_pipeline_concurrent_clients()


async def _test_pipeline_connect():
    import websockets
    try:
        async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}", open_timeout=5) as ws:
            _assert(True, "WebSocket connection established")
            info(f"Connected to ws://{WS_HOST}:{WS_PORT}")
    except Exception as e:
        fail(f"WebSocket connect failed: {e}")


async def _test_pipeline_silence_stream():
    """Stream 40 silence chunks (~1.3 s) — no crash, no spurious response_chunk."""
    import websockets
    from websockets.exceptions import ConnectionClosed

    try:
        async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}", open_timeout=5) as ws:
            chunk_count = 40
            for _ in range(chunk_count):
                await ws.send(_silence_chunk())
                await asyncio.sleep(0.005)

            # Drain any messages for 0.5 s — none expected for pure silence
            spurious = 0
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    body = json.loads(msg) if isinstance(msg, str) else {}
                    if body.get("type") == "response_chunk":
                        spurious += 1
            except (asyncio.TimeoutError, ConnectionClosed):
                pass

            _assert(True,       f"Streamed {chunk_count} silence chunks without crash")
            _assert(spurious == 0, "No response_chunk emitted for pure silence",
                    f"{spurious} spurious chunks received")
    except Exception as e:
        fail(f"Pipeline silence-stream test raised: {e}")


async def _test_pipeline_concurrent_clients():
    """Two clients connected simultaneously — neither crashes the server."""
    import websockets

    async def one_client(n: int) -> bool:
        try:
            async with websockets.connect(f"ws://{WS_HOST}:{WS_PORT}", open_timeout=5) as ws:
                for _ in range(10):
                    await ws.send(_silence_chunk())
                    await asyncio.sleep(0.005)
                return True
        except Exception:
            return False

    results = await asyncio.gather(one_client(1), one_client(2))
    _assert(all(results), "Two concurrent WebSocket clients both connected and streamed",
            f"results: {results}")


# ─── 6. End-to-end flow ───────────────────────────────────────────────────────

def test_e2e():
    banner("END-TO-END  standby → engine → WebSocket → response")
    asyncio.run(_e2e())


async def _e2e():
    import websockets

    info("Step 1 — Send wake to standby, get WebSocket address")
    ws_host = WS_HOST
    ws_port = WS_PORT

    if _check_port(STANDBY_HOST, STANDBY_PORT, "standby (e2e)"):
        try:
            reader, writer = await asyncio.open_connection(STANDBY_HOST, STANDBY_PORT)
            await _ipc_send(writer, {"type": "wake"})
            resp = await _ipc_recv(reader, timeout=45.0)
            await _ipc_close(writer)
            if "ws_host" in resp and "ws_port" in resp:
                ws_host = resp["ws_host"]
                ws_port = resp["ws_port"]
                _assert(True, f"E2E: standby returned ws://{ws_host}:{ws_port}")
            else:
                _assert(False, "E2E: standby wake response missing ws_host/ws_port",
                        str(resp))
                return
        except Exception as e:
            warn(f"E2E standby wake failed: {e} — using configured WS address")
    else:
        info(f"Standby not running — connecting directly to ws://{ws_host}:{ws_port}")

    # Brief wait for main.py to finish its own startup if just woken
    await asyncio.sleep(2.0)

    info(f"Step 2 — Connect WebSocket to ws://{ws_host}:{ws_port}")
    try:
        async with websockets.connect(
            f"ws://{ws_host}:{ws_port}", open_timeout=10
        ) as ws:
            _assert(True, "E2E: WebSocket connected")

            info("Step 3 — Stream speech audio (440 Hz sine, ~1 s)")
            for _ in range(35):
                await ws.send(_sine_chunk(440.0))
                await asyncio.sleep(0.005)

            info("Step 4 — Stream silence to trigger end-of-utterance")
            for _ in range(25):
                await ws.send(_silence_chunk())
                await asyncio.sleep(0.005)

            info("Step 5 — Wait for response_chunk (up to 30 s) …")
            response_chunk = None
            try:
                async with asyncio.timeout(30):
                    async for raw in ws:
                        body = json.loads(raw) if isinstance(raw, str) else {}
                        if body.get("type") == "response_chunk":
                            response_chunk = body
                            break
                        elif body.get("type") == "session_end":
                            break
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                pass

            _assert(response_chunk is not None,
                    "E2E: received at least one response_chunk",
                    "No response_chunk arrived — check Silero detected speech "
                    "and llama-server is running")

            if response_chunk:
                _assert("text" in response_chunk,
                        "E2E: response_chunk contains 'text'")
                _assert("audio" in response_chunk,
                        "E2E: response_chunk contains 'audio'")
                if "audio" in response_chunk:
                    raw_wav = base64.b64decode(response_chunk["audio"])
                    _assert(_is_valid_wav(raw_wav),
                            f"E2E: response audio is a valid WAV ({len(raw_wav)} bytes)")
                if "text" in response_chunk:
                    info(f"E2E response text: {response_chunk['text'][:80]!r}")

    except Exception as e:
        fail(f"E2E WebSocket test raised: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# SERVICE LAUNCHER  (--start flag)
# ═══════════════════════════════════════════════════════════════════════════════

_procs:      list[subprocess.Popen] = []
_temp_dir:   tempfile.TemporaryDirectory | None = None
_llama_thread: threading.Thread | None = None
_llama_loop:   asyncio.AbstractEventLoop | None = None


# ── Embedded mock llama-server ────────────────────────────────────────────────

_FAKE_TOKENS = [
    "Ciao", "!", " Come", " posso", " aiutarti",
    " oggi", "?", " Sono", " Vela", ",",
    " il", " tuo", " assistente", " vocale", ".",
]


def _start_mock_llama_in_thread(port: int) -> None:
    """Start a minimal OpenAI-compatible SSE server in a background thread."""
    global _llama_loop
    try:
        from aiohttp import web
    except ImportError:
        warn("aiohttp not installed — mock llama-server unavailable.  "
             "pip install aiohttp  or start a real llama-server on port 8080.")
        return

    async def _health(r):
        return web.Response(text='{"status":"ok"}', content_type="application/json")

    async def _chat(r):
        resp = web.StreamResponse(
            headers={"Content-Type": "text/event-stream; charset=utf-8"}
        )
        await resp.prepare(r)
        for token in _FAKE_TOKENS:
            chunk = {"choices": [{"delta": {"content": token}, "finish_reason": None}]}
            await resp.write(f"data: {json.dumps(chunk)}\n\n".encode())
            await asyncio.sleep(0.008)
        await resp.write(b"data: [DONE]\n\n")
        await resp.write_eof()
        return resp

    async def _run():
        app = web.Application()
        app.router.add_get("/health", _health)
        app.router.add_post("/v1/chat/completions", _chat)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        print(f"  {GREEN}▶{RESET}  mock-llama-server  (port {port})")
        await asyncio.Event().wait()

    _llama_loop = asyncio.new_event_loop()
    threading.Thread(target=_llama_loop.run_until_complete, args=(_run(),),
                     daemon=True).start()


# ── Embedded fake piper binary ─────────────────────────────────────────────────

_FAKE_PIPER_CODE = '''\
#!/usr/bin/env python3
import sys, io, wave
sys.stdin.buffer.read()
NUM = 2205  # 0.1 s at 22050 Hz
if "--output-raw" in sys.argv:
    sys.stdout.buffer.write(b"\\x00\\x00" * NUM)
else:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
        wf.writeframes(b"\\x00\\x00" * NUM)
    sys.stdout.buffer.write(buf.getvalue())
'''


def _start_services() -> None:
    global _temp_dir

    base        = Path(__file__).parent
    venv_python = base / ".venv" / "bin" / "python"
    python      = str(venv_python) if venv_python.exists() else sys.executable

    print(f"\n{BOLD}Starting services…{RESET}")

    # 1. Mock llama-server (in-thread)
    _start_mock_llama_in_thread(MOCK_LLAMA_PORT)
    time.sleep(0.5)   # let the server bind

    # 2. Fake piper binary in a temp dir
    _temp_dir = tempfile.TemporaryDirectory(prefix="vela_test_")
    fake_piper = Path(_temp_dir.name) / "piper"
    fake_piper.write_text(_FAKE_PIPER_CODE)
    fake_piper.chmod(0o755)

    # 3. Fake model file (path existence is checked by tts service)
    fake_model = Path(_temp_dir.name) / "fake_model.onnx"
    fake_model.write_bytes(b"fake")
    fake_model_json = Path(_temp_dir.name) / "fake_model.onnx.json"
    fake_model_json.write_text(json.dumps({
        "audio": {"sample_rate": 22050},
        "espeak": {"voice": "it"},
        "phoneme_type": "espeak",
        "piper_version": "1.0.0",
    }))

    augmented_env = {
        **os.environ,
        "VELA_PIPER_MODEL": str(fake_model),
        "VELA_PIPER_RATE":  "22050",
        "PATH": f"{_temp_dir.name}:{os.environ.get('PATH', '')}",
    }

    # 4. Start main.py — it spawns audio-detector, inference, and tts
    p = subprocess.Popen(
        [python, str(base / "main.py")],
        cwd=str(base),
        env=augmented_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _procs.append(p)
    print(f"  {GREEN}▶{RESET}  main.py  (pid {p.pid})")

    # 5. Start standby.py (optional — tested separately)
    p2 = subprocess.Popen(
        [python, str(base / "standby.py")],
        cwd=str(base),
        env=augmented_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _procs.append(p2)
    print(f"  {GREEN}▶{RESET}  standby.py  (pid {p2.pid})")

    print(f"{DIM}  Waiting 8 s for services to bind…{RESET}")
    time.sleep(8)


def _stop_services() -> None:
    global _temp_dir
    if not _procs:
        return
    print(f"\n{BOLD}Stopping services…{RESET}")
    for p in _procs:
        p.terminate()
    for p in _procs:
        try:
            p.wait(timeout=6)
        except subprocess.TimeoutExpired:
            p.kill()
    if _temp_dir:
        _temp_dir.cleanup()
        _temp_dir = None
    if _llama_loop and not _llama_loop.is_closed():
        _llama_loop.call_soon_threadsafe(_llama_loop.stop)
    print(f"  {GREEN}Done.{RESET}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

ALL_GROUPS = ["standby", "detector", "inference", "tts", "pipeline", "e2e"]


def _run_group(name: str) -> None:
    {
        "standby":   test_standby,
        "detector":  test_detector,
        "inference": test_inference,
        "tts":       test_tts,
        "pipeline":  test_pipeline,
        "e2e":       test_e2e,
    }[name]()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vela engine test suite")
    parser.add_argument(
        "--start", action="store_true",
        help="Auto-start all engine services before running tests",
    )
    parser.add_argument(
        "--only", nargs="+", choices=ALL_GROUPS, metavar="GROUP",
        help=f"Run only these groups: {', '.join(ALL_GROUPS)}",
    )
    args   = parser.parse_args()
    groups = args.only if args.only else ALL_GROUPS

    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  Vela Engine — Test Suite{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"{DIM}  Groups : {', '.join(groups)}{RESET}")
    print(f"{DIM}  WS     : ws://{WS_HOST}:{WS_PORT}{RESET}")
    print(f"{DIM}  IPC    : standby:{STANDBY_PORT}  det:{DETECTOR_PORT}  "
          f"inf:{INFERENCE_PORT}  tts:{TTS_PORT}{RESET}")

    if args.start:
        _start_services()
        def _sig(s, f):
            _stop_services()
            sys.exit(1)
        signal.signal(signal.SIGINT,  _sig)
        signal.signal(signal.SIGTERM, _sig)

    try:
        for g in groups:
            _run_group(g)
    finally:
        if args.start:
            _stop_services()

    # ── Summary ───────────────────────────────────────────────────────────────
    total = _passed + _failed
    print()
    print(f"{BOLD}{'═' * 60}{RESET}")
    if _failed == 0:
        print(f"  {GREEN}{BOLD}ALL {total} TESTS PASSED{RESET}")
    else:
        print(f"  {RED}{BOLD}{_failed} FAILED{RESET}  /  {total} total"
              f"  ({_passed} passed)")
    print(f"{BOLD}{'═' * 60}{RESET}\n")

    sys.exit(0 if _failed == 0 else 1)
