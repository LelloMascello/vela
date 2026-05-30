import os

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import httpx
import numpy as np

from auth import login

load_dotenv(find_dotenv())

# ── Config from .env ──────────────────────────────────────────────────────────

DETECTOR_URL = (
    f"http://{os.getenv('HOST_DETECTOR', 'localhost')}"
    f":{os.getenv('PORT_DETECTOR', '8001')}"
)
MAIN_WS_HOST = os.getenv("MAIN_WS_HOST", "localhost")
MAIN_WS_PORT = int(os.getenv("PORT_MAIN", "8002"))

# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI()
security = HTTPBasic()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# How many frames to consume from the client without forwarding to the detector
# at the start of each new session.  This flushes any audio that accumulated
# in the client buffer during the reconnection window AND gives the detector's
# own internal sliding-window time to drain stale speech from a previous
# session before we start evaluating wake-word scores.
# At 16 kHz / 512 samples per frame → ~320 ms of warm-up.
DETECTOR_WARMUP_FRAMES = 10


async def _fetch_frame_length(client: httpx.AsyncClient) -> int:
    resp = await client.get(f"{DETECTOR_URL}/config", timeout=5.0)
    resp.raise_for_status()
    return resp.json()["frame_length"]


async def _reset_detector(client: httpx.AsyncClient) -> None:
    try:
        resp = await client.post(f"{DETECTOR_URL}/reset", timeout=5.0)
        resp.raise_for_status()
    except Exception as exc:
        # Non-fatal: detector may not implement /reset.
        print(f"[router] detector /reset skipped or failed: {exc}")


@app.post("/auth")
async def authentication(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    result = login(credentials.username, credentials.password)
    if not result:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    host = request.headers.get("host", "localhost")
    # Strip any accidental path component; keep only host:port
    host = host.split("/")[0]
    return {
        "ws_url": f"ws://{host}/ws?username={result['username']}",
        "username": result["username"],
    }


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    username: str = Query(...),
):
    await websocket.accept()

    async with httpx.AsyncClient() as client:
        # Fetch the real frame length from the detector instead of hardcoding it.
        try:
            frame_length = await _fetch_frame_length(client)
        except Exception as exc:
            await websocket.close(code=1011, reason=f"Detector unreachable: {exc}")
            return

        # Reset the detector's internal sliding-window state so that audio
        # buffered from a previous session cannot trigger an immediate false
        # wake-word hit on the very first frame of this new session.
        await _reset_detector(client)

        frame_bytes = frame_length * 2  # each int16 sample = 2 bytes
        byte_buffer = bytearray()
        frames_processed = 0  # counts frames forwarded to the detector

        try:
            while True:
                chunk = await websocket.receive_bytes()
                byte_buffer.extend(chunk)

                while len(byte_buffer) >= frame_bytes:
                    frame = byte_buffer[:frame_bytes]
                    del byte_buffer[:frame_bytes]

                    frames_processed += 1

                    # Convert int16 bytes → float32 in [-1.0, 1.0]
                    pcm_int16 = np.frombuffer(frame, dtype=np.int16)
                    audio_floats = (pcm_int16 / 32767.0).tolist()

                    try:
                        resp = await client.post(
                            f"{DETECTOR_URL}/detect",
                            json={"audio": audio_floats},
                            timeout=5.0,
                        )
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        await websocket.send_json({
                            "error": f"Detector error: {exc.response.status_code}"
                        })
                        continue
                    except httpx.RequestError as exc:
                        await websocket.send_json({"error": f"Detector unreachable: {exc}"})
                        continue

                    # Warm-up: forward frames to the detector so its mel-feature
                    # and score-history buffers fill with fresh audio, but suppress
                    # the wake-word result.
                    if frames_processed <= DETECTOR_WARMUP_FRAMES:
                        continue

                    result = resp.json()

                    if result.get("wake_word"):
                        await websocket.send_json({
                            "ip":       MAIN_WS_HOST,
                            "port":     MAIN_WS_PORT,
                            "message":  "server ready",
                            "username": username,
                        })

        except WebSocketDisconnect:
            print(f"Client disconnected: {username}")