import sqlite3
import hashlib
import os

DB_PATH = "data/users.db" # Using the local data folder you chose

def init_db():
    """Creates the users table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    """Hashes a plaintext password using SHA-256."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def add_user(username: str, plaintext_password: str) -> bool:
    """Adds a new user to the database with a hashed password."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # The README specifies storing the SHA-256 hash in SQLite
        hashed_pw = hash_password(plaintext_password)
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", 
                       (username, hashed_pw))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False # User already exists
    finally:
        conn.close()

def verify_user(username: str, client_password_hash: str) -> bool:
    """Verifies the hash sent by the client against the stored hash."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    if row is None:
        return False
    
    stored_hash = row[0]
    # The client sends the password already hashed via SHA-256
    return stored_hash == client_password_hash
