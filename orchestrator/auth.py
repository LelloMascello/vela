#!/usr/bin/env python3
"""
auth.py — Vela Orchestrator · Authentication Service
=====================================================
HTTP server (port 5001).  Clients hit this first:

  POST /auth/login   { "username": "...", "password": "..." }
  ← 200              { "token": "<JWT>", "ws_host": "...", "ws_port": 8766 }
  ← 401              { "error": "Invalid credentials" }

On success the client has everything it needs to open a WebSocket
connection to router.py, passing the JWT as the first message.

The SQLite database (vela.db) is shared with the registration website.
"""

import datetime
import json
import os
import socket
import sqlite3
from pathlib import Path

import bcrypt
import jwt
from flask import Flask, jsonify, request

# ─── Configuration ────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
DB_PATH     = Path(os.environ.get("VELA_DB_PATH",   str(BASE_DIR / "vela.db")))
SECRET_KEY  = os.environ.get("VELA_SECRET",         "vela-secret-CHANGE-in-production")
AUTH_PORT   = int(os.environ.get("VELA_AUTH_PORT",  5001))
ROUTER_PORT = int(os.environ.get("VELA_ROUTER_PORT", 8766))
TOKEN_TTL_H = int(os.environ.get("VELA_TOKEN_TTL",  24))   # token lifetime in hours

# ─── Flask app ────────────────────────────────────────────────────────────────

app = Flask(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _local_ip() -> str:
    """Return the LAN IP this machine uses to reach the outside world."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _init_db() -> None:
    """Create the users table if it doesn't exist yet."""
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    print(f"[auth] Database ready at {DB_PATH}")


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Expected JSON body"}), 400

    username: str = str(data.get("username", "")).strip()
    password: str = str(data.get("password", ""))

    if not username or not password:
        return jsonify({"error": "username and password are required"}), 400

    # Look up user
    with _get_db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()

    # Constant-time failure to avoid timing attacks
    if row is None:
        bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
        return jsonify({"error": "Invalid credentials"}), 401

    if not bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
        return jsonify({"error": "Invalid credentials"}), 401

    # Issue JWT
    now = datetime.datetime.utcnow()
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + datetime.timedelta(hours=TOKEN_TTL_H),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    ws_host = _local_ip()
    print(f"[auth] Login OK — user={username!r}  → ws://{ws_host}:{ROUTER_PORT}")

    return jsonify({
        "token":   token,
        "ws_host": ws_host,
        "ws_port": ROUTER_PORT,
    })


@app.route("/auth/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "auth"})


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_db()
    print(f"[auth] Listening on 0.0.0.0:{AUTH_PORT}")
    # Use threaded=True so multiple clients can log in concurrently
    app.run(host="0.0.0.0", port=AUTH_PORT, threaded=True)
