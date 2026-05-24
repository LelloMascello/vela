from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from auth import signup, login
import pymongo
from bson import json_util

mydb = pymongo.MongoClient("mongodb://localhost:27017/")["ai_assistant"]
mycol = mydb["ai_chats"]

# Index on username so selects are fast even with many sessions.
mycol.create_index("username")

app = FastAPI()
app.mount("/public", StaticFiles(directory="public"), name="public")


# ── Page routes ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("public/index.html") as f:
        return f.read()


@app.get("/home", response_class=HTMLResponse)
async def home():
    with open("public/home.html") as f:
        return f.read()


@app.get("/chats", response_class=HTMLResponse)
async def chats_page():
    with open("public/chats.html") as f:
        return f.read()


# ── Auth routes ────────────────────────────────────────────────────────────

@app.post("/signup")
async def do_signup(username: str = Form(...), password: str = Form(...)):
    result = signup(username, password)
    if result:
        return JSONResponse({"ok": True, "username": result["username"]})
    return JSONResponse({"ok": False, "error": "Username already taken"}, status_code=400)


@app.post("/login")
async def do_login(username: str = Form(...), password: str = Form(...)):
    result = login(username, password)
    if result:
        return JSONResponse({"ok": True, "username": result["username"]})
    return JSONResponse({"ok": False, "error": "Invalid username or password"}, status_code=401)


# ── Chat routes ────────────────────────────────────────────────────────────

@app.post("/chats/insert")
async def insert_chats(history: dict):
    """
    Save a completed voice session as a new chat document.

    Expected body:
      {
        "username":   str,
        "created_at": int,      <- unix ms timestamp
        "chat":       list[{role, content}]
      }

    Each call inserts a NEW document so all sessions are preserved.
    There is no duplicate-key risk because MongoDB assigns its own _id.
    """
    username = history.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="Missing 'username' field in body")
    if not history.get("chat"):
        # Nothing to save — skip silently.
        return {"status": "skipped", "reason": "empty chat"}

    try:
        result = mycol.insert_one(history)
        return {"status": "success", "inserted_id": str(result.inserted_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/chats/select")
async def select_chats(username: str):
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