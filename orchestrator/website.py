import os

import pymongo
from bson import json_util
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any

from auth import signup, login

load_dotenv(find_dotenv())

# ── Config from .env ──────────────────────────────────────────────────────────

_mongo_host = os.getenv("HOST_MONGODB", "localhost")
_mongo_port = os.getenv("PORT_MONGODB", "27017")
MONGODB_URL = f"mongodb://{_mongo_host}:{_mongo_port}/"

# ─────────────────────────────────────────────────────────────────────────────

mydb = pymongo.MongoClient(MONGODB_URL)["ai_assistant"]
mycol = mydb["ai_chats"]

# Index on username so selects are fast even with many sessions.
mycol.create_index("username")

app = FastAPI()
app.mount("/public", StaticFiles(directory="public"), name="public")


# ── Pydantic Schema for Validation ──────────────────────────────────────────

class ChatSession(BaseModel):
    username: str
    created_at: int      # unix ms timestamp
    chat: List[Dict[str, Any]]


# ── Page routes ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index():
    with open("public/index.html") as f:
        return f.read()


@app.get("/home", response_class=HTMLResponse)
def home():
    with open("public/home.html") as f:
        return f.read()


@app.get("/chats", response_class=HTMLResponse)
def chats_page():
    with open("public/chats.html") as f:
        return f.read()


# ── Auth routes ────────────────────────────────────────────────────────────

@app.post("/signup")
def do_signup(username: str = Form(...), password: str = Form(...)):
    result = signup(username, password)
    if result:
        return JSONResponse({"ok": True, "username": result["username"]})
    return JSONResponse({"ok": False, "error": "Username already taken"}, status_code=400)


@app.post("/login")
def do_login(username: str = Form(...), password: str = Form(...)):
    result = login(username, password)
    if result:
        return JSONResponse({"ok": True, "username": result["username"]})
    return JSONResponse({"ok": False, "error": "Invalid username or password"}, status_code=401)


# ── Chat routes ────────────────────────────────────────────────────────────

@app.post("/chats/insert")
def insert_chats(history: ChatSession):
    """
    Save a completed voice session as a new chat document.
    Validated automatically via Pydantic.
    """
    if not history.chat:
        return {"status": "skipped", "reason": "empty chat"}

    try:
        result = mycol.insert_one(history.model_dump())
        return {"status": "success", "inserted_id": str(result.inserted_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/chats/select")
def select_chats(username: str):
    """Return all saved sessions for *username*, newest first."""
    try:
        chats = list(
            mycol.find({"username": username}, sort=[("created_at", pymongo.DESCENDING)])
        )
        return Response(
            content=json_util.dumps(chats),
            media_type="application/json",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")