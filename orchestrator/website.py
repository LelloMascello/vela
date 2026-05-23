from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from auth import signup, login
import pymongo
from bson import json_util
import json

mydb = pymongo.MongoClient("mongodb://localhost:27017/")["ai_assistant"]
mycol = mydb["ai_chats"]

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
    try:
        result = mycol.insert_one(history)
        return {
            "status": "success",
            "inserted_id": str(result.inserted_id)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@app.get("/chats/select")
async def select_chats(username: str):
    try:
        # Project out the internal _id to keep the response clean
        chats = list(mycol.find({"_id": username}))
        # Use bson json_util to handle any ObjectId / datetime fields safely
        return Response(
            content=json_util.dumps(chats),
            media_type="application/json"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")