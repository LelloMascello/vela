import sqlite3
import hashlib
import os

DB_PATH = "users.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def signup(username: str, password: str) -> dict | None:
    salt = os.urandom(16).hex()
    password_hash = f"{salt}:{_hash_password(password, salt)}"

    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
        return {"username": username}
    except sqlite3.IntegrityError:
        return None  # username already exists


def login(username: str, password: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if row is None:
        return None  # user not found

    salt, stored_hash = row[0].split(":", 1)
    if _hash_password(password, salt) == stored_hash:
        return {"username": username}

    return None  # wrong password