#"""
#main.py — Vela Pi Orchestrator (FastAPI)
#
#Responsibilities:
#  1. Auth DB (SQLite)  — signup / login
#  2. Chat DB (MongoDB) — save / get / delete chat histories
#  3. WebSocket relay   — stream audio from N clients, run wake word per client,
#                         proxy to Laptop when activated, resume on session close
#  4. Config endpoint   — serve user profile / system settings to clients
#
#WebSocket URL (clients connect here):
#  ws://pi:8000/ws/audio/{client_id}?user_id={user_id}
#"""

import asyncio
import json
import logging
import os
from typing import Dict, Optional

import websockets
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from datetime import datetime
from typing import List

from wakeword_engine import WakeWordEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
LAPTOP_WS_BASE = os.getenv("LAPTOP_WS_BASE", "ws://archlinux.local:8001")
PI_PORT        = int(os.getenv("PI_PORT", "8000"))

# ── 1. SQLite (auth) ──────────────────────────────────────────────────────────
engine     = create_engine("sqlite:///./auth.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()


class DBUser(Base):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String,  unique=True, index=True)
    email           = Column(String,  unique=True, index=True)
    hashed_password = Column(String)


Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ── 2. MongoDB (chats) ────────────────────────────────────────────────────────
mongo_client   = AsyncIOMotorClient("mongodb://localhost:27017")
mongo_db       = mongo_client.aichat_database
chat_collection = mongo_db.get_collection("chats")

# ── 3. Pydantic models ────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    username: str
    email:    EmailStr
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class ChatExchange(BaseModel):
    question:  str
    response:  str
    timestamp: Optional[datetime] = Field(default_factory=datetime.utcnow)

class ChatSessionSave(BaseModel):
    user_id:   int
    exchanges: List[ChatExchange]

# ── 4. Active client relay state ─────────────────────────────────────────────
class ClientState:
    def __init__(self, client_id: str, user_id: int):
        self.client_id  = client_id
        self.user_id    = user_id
        # FIXED: Removed client_id argument
        self.ww         = WakeWordEngine()
        self.in_session = False


_clients: Dict[str, ClientState] = {}


# ── 5. Laptop WebSocket proxy ─────────────────────────────────────────────────

async def _proxy_to_laptop(state: ClientState, client_ws: WebSocket) -> None:
    """
    Open a WebSocket to the Laptop and bidirectionally proxy all data.
    Blocks until the session ends (Laptop closes its side or client disconnects).
    """
    laptop_url = (
        f"{LAPTOP_WS_BASE}/ws/session/{state.client_id}"
        f"?user_id={state.user_id}"
    )
    logger.info("[%s] Proxying to %s", state.client_id, laptop_url)

    try:
        async with websockets.connect(laptop_url, max_size=2**22) as laptop_ws:
            # Tell client the system is now actively listening
            await client_ws.send_text(json.dumps({"type": "wake_detected"}))

            async def c2l():
                """client → laptop"""
                try:
                    while True:
                        msg = await client_ws.receive()
                        if msg["type"] == "websocket.disconnect":
                            await laptop_ws.close()
                            return
                        if "bytes" in msg and msg["bytes"]:
                            await laptop_ws.send(msg["bytes"])
                        elif "text" in msg and msg["text"]:
                            await laptop_ws.send(msg["text"])
                except Exception:
                    await laptop_ws.close()

            async def l2c():
                """laptop → client"""
                try:
                    async for message in laptop_ws:
                        if isinstance(message, bytes):
                            await client_ws.send_bytes(message)
                        else:
                            await client_ws.send_text(message)
                except Exception:
                    pass

            await asyncio.gather(c2l(), l2c(), return_exceptions=True)

    except (websockets.exceptions.WebSocketException, OSError) as exc:
        logger.error("[%s] Laptop proxy error: %s", state.client_id, exc)
        await client_ws.send_text(json.dumps({"type": "error", "message": "Laptop unreachable"}))
    finally:
        state.in_session = False
        state.ww.reset()
        logger.info("[%s] Session ended, wake word re-armed.", state.client_id)


# ── 6. FastAPI app ────────────────────────────────────────────────────────────
app = FastAPI(title="Vela Pi Orchestrator")

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    pass   # static/ directory may not exist yet

@app.get("/")
def read_login():
    return FileResponse("templates/login.html")

@app.get("/signup")
def read_signup():
    return FileResponse("templates/signup.html")

@app.get("/home")
def read_home():
    return FileResponse("templates/home.html")


# ── Auth endpoints ────────────────────────────────────────────────────────────
@app.post("/api/signup")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(DBUser).filter(
        (DBUser.username == user.username) | (DBUser.email == user.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or Email already exists")
    new_user = DBUser(
        username=user.username,
        email=user.email,
        hashed_password=pwd_context.hash(user.password),
    )
    db.add(new_user)
    db.commit()
    return {"message": "User created"}


@app.post("/api/login")
def login_user(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(DBUser).filter(DBUser.username == user.username).first()
    if not db_user or not pwd_context.verify(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"user_id": db_user.id, "username": db_user.username}


# ── Chat endpoints ────────────────────────────────────────────────────────────
@app.post("/api/chats/save")
async def save_chat_session(chat_data: ChatSessionSave):
    doc    = chat_data.model_dump()
    result = await chat_collection.insert_one(doc)
    if result.inserted_id:
        return {"message": "Saved", "chat_id": str(result.inserted_id)}
    raise HTTPException(status_code=500, detail="Failed to save")


@app.get("/api/chats/{user_id}")
async def get_user_chats(user_id: int, skip: int = 0, limit: int = 10):
    chats  = []
    cursor = chat_collection.find({"user_id": user_id}).sort("_id", -1).skip(skip).limit(limit)
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        chats.append(doc)
    return {"chats": chats}


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    try:
        obj_id = ObjectId(chat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID chat non valido")
    result = await chat_collection.delete_one({"_id": obj_id})
    if result.deleted_count == 1:
        return {"message": "Chat eliminata"}
    raise HTTPException(status_code=404, detail="Chat non trovata")


# ── Client profile / config endpoint ─────────────────────────────────────────
@app.get("/api/profile/{user_id}")
async def get_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id":       user.id,
        "username":      user.username,
        "laptop_ws_base": LAPTOP_WS_BASE,    # clients use this to know laptop address
    }


# ── WebSocket relay ───────────────────────────────────────────────────────────
@app.websocket("/ws/audio/{client_id}")
async def audio_relay(websocket: WebSocket, client_id: str, user_id: int = 0):
    await websocket.accept()
    logger.info("[%s] Client connected (user=%d)", client_id, user_id)

    state = ClientState(client_id, user_id)
    _clients[client_id] = state

    try:
        while True:
            try:
                raw = await websocket.receive_bytes()
            except WebSocketDisconnect:
                break

            if state.in_session:
                # Already proxying — should not happen (proxy handles its own loop)
                # This path is a safety guard
                continue

            # Run wake word detection on the incoming audio
            # FIXED: Changed .process() to .process_chunk()
            if state.ww.process_chunk(raw):
                state.in_session = True
                await _proxy_to_laptop(state, websocket)

    finally:
        _clients.pop(client_id, None)
        logger.info("[%s] Client disconnected.", client_id)


# ── Status endpoint ───────────────────────────────────────────────────────────
@app.get("/api/status")
async def status_endpoint():
    return {
        "connected_clients": len(_clients),
        "active_sessions":   sum(1 for c in _clients.values() if c.in_session),
    }


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PI_PORT, log_level="info")
