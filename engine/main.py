from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from pydantic import BaseModel

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/ready")
async def get_ready():
    # start /llama.cpp/build/bin/llama-server   -m /llama.cpp/mymodels/gemma-4-E2B-it-Q4_K_M.gguf   --mmproj /llama.cpp/mymodels/mmproj-F16.gguf   --host 127.0.0.1   --port 8080   -ngl 99   --reasoning off
    # start fastapi text_to_speech.py --port 8003
    # if there are error during this process it return ready = false
    # if everything is fine it return the websocket connection
    return {
        "ready": _state["ready"],
        "ip": _state["ip"],
        "port": _state["port"],
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

        try:

        except WebSocketDisconnect:
            print("Client disconnected")