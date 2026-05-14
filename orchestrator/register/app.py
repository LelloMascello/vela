#!/usr/bin/env python3
"""
register/app.py — Vela Orchestrator · Account Registration Website
===================================================================
Flask web application (port 5000).

Routes
------
GET  /           → registration form
POST /register   → create account, redirect to /success or back with error
GET  /success    → confirmation page
GET  /health     → JSON health check

The users table is shared with auth.py (same vela.db file).
"""

import os
import re
from pathlib import Path

import bcrypt
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash

# ─── Configuration ────────────────────────────────────────────────────────────

BASE_DIR       = Path(__file__).parent.parent          # orchestrator/
DB_PATH        = Path(os.environ.get("VELA_DB_PATH",  str(BASE_DIR / "vela.db")))
REGISTER_PORT  = int(os.environ.get("VELA_REG_PORT",  5000))
SECRET_KEY     = os.environ.get("VELA_SECRET",        "vela-secret-CHANGE-in-production")

USERNAME_RE    = re.compile(r"^[a-zA-Z0-9_\-]{3,32}$")
MIN_PASS_LEN   = 8

# ─── Flask app ────────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder="templates")
app.secret_key = SECRET_KEY


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
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
    print(f"[register] Database ready at {DB_PATH}")


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["POST"])
def register():
    username  = request.form.get("username",  "").strip()
    password  = request.form.get("password",  "")
    password2 = request.form.get("password2", "")

    # ── Validation ────────────────────────────────────────────────────────────
    if not USERNAME_RE.match(username):
        flash("Username must be 3–32 characters and contain only letters, numbers, _ or -.", "error")
        return redirect(url_for("index"))

    if len(password) < MIN_PASS_LEN:
        flash(f"Password must be at least {MIN_PASS_LEN} characters.", "error")
        return redirect(url_for("index"))

    if password != password2:
        flash("Passwords do not match.", "error")
        return redirect(url_for("index"))

    # ── Insert ────────────────────────────────────────────────────────────────
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, pw_hash),
            )
            conn.commit()
        print(f"[register] New user: {username!r}")
    except sqlite3.IntegrityError:
        flash("That username is already taken.", "error")
        return redirect(url_for("index"))

    return redirect(url_for("success", username=username))


@app.route("/success")
def success():
    username = request.args.get("username", "")
    return render_template("success.html", username=username)


@app.route("/health")
def health():
    from flask import jsonify
    return jsonify({"status": "ok", "service": "register"})


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _init_db()
    print(f"[register] Listening on 0.0.0.0:{REGISTER_PORT}")
    app.run(host="0.0.0.0", port=REGISTER_PORT, debug=False)
