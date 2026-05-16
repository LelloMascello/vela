from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import httpx
import numpy as np

from auth import login

app = FastAPI()
security = HTTPBasic()

DETECTOR_URL = "http://localhost:8001"
OTHER_SERVER_URL = "http://other-server/ready"


async def _fetch_frame_length(client: httpx.AsyncClient) -> int:
    resp = await client.get(f"{DETECTOR_URL}/config", timeout=5.0)
    resp.raise_for_status()
    return resp.json()["frame_length"]


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
    return {
        "ws_url": f"ws://{host}/ws",
        "username": result["username"],
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    async with httpx.AsyncClient() as client:
        # Fetch the real frame length from the detector instead of hardcoding it.
        try:
            frame_length = await _fetch_frame_length(client)
        except Exception as exc:
            await websocket.close(code=1011, reason=f"Detector unreachable: {exc}")
            return

        frame_bytes = frame_length * 2  # each int16 sample = 2 bytes
        byte_buffer = bytearray()

        try:
            while True:
                chunk = await websocket.receive_bytes()
                byte_buffer.extend(chunk)

                while len(byte_buffer) >= frame_bytes:
                    frame = byte_buffer[:frame_bytes]
                    del byte_buffer[:frame_bytes]

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

                    result = resp.json()

                    if result.get("wake_word"):
                        try:
                            ready_resp = await client.get(OTHER_SERVER_URL, timeout=5.0)
                            ready_resp.raise_for_status()
                            server_info = ready_resp.json()
                        except Exception as exc:
                            await websocket.send_json({"error": f"Other server error: {exc}"})
                            continue

                        if server_info.get("ready"):
                            ip = server_info.get("ip")
                            port = server_info.get("port")
                            if ip is None or port is None:
                                await websocket.send_json(
                                    {"error": "Other server response missing ip/port"}
                                )
                                continue

                            await websocket.send_json({
                                "ip": ip,
                                "port": port,
                                "message": "server ready",
                            })

        except WebSocketDisconnect:
            print("Client disconnected")