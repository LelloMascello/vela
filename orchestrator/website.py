from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from auth import signup, login

app = FastAPI()
app.mount("/public", StaticFiles(directory="public"), name="public")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("public/index.html") as f:
        return f.read()


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