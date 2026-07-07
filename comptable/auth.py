"""
Authentification — password hashing + session tokens.
Stdlib only: hashlib (pbkdf2_hmac) + secrets + sqlite3.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from typing import Optional, Tuple

# ── Password hashing (PBKDF2-SHA256) ──
SALT_BYTES = 16
HASH_ITERATIONS = 200_000
KEY_LENGTH = 32


def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[str, str]:
    """Hash a password. Returns (salt_hex, hash_hex)."""
    if salt is None:
        salt = os.urandom(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ITERATIONS, KEY_LENGTH)
    return salt.hex(), dk.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """Verify a password against stored salt+hash."""
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ITERATIONS, KEY_LENGTH)
    return hmac.compare_digest(dk.hex(), hash_hex)


# ── Session tokens ──
TOKEN_BYTES = 32
SESSION_TTL = 86400 * 7  # 7 jours


def generate_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


# ── DB operations ──
def init_auth_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL UNIQUE,
            salt        TEXT NOT NULL,
            password    TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'admin',
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token       TEXT PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            username    TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            last_seen   TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
    """)


def create_user(conn: sqlite3.Connection, username: str, password: str, role: str = "admin") -> bool:
    """Create a user. Returns True on success, False if username exists."""
    salt, pw_hash = hash_password(password)
    try:
        conn.execute(
            "INSERT INTO users (username, salt, password, role) VALUES (?, ?, ?, ?)",
            (username, salt, pw_hash, role),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> Optional[str]:
    """Verify credentials. Returns session token on success, None on failure."""
    row = conn.execute(
        "SELECT id, username, salt, password, role FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if not row:
        return None
    if not verify_password(password, row["salt"], row["password"]):
        return None

    # Create session
    token = generate_token()
    conn.execute(
        "INSERT OR REPLACE INTO sessions (token, user_id, username) VALUES (?, ?, ?)",
        (token, row["id"], row["username"]),
    )
    conn.commit()
    return token


def get_session(conn: sqlite3.Connection, token: str) -> Optional[dict]:
    """Get session info for a token. Returns None if expired or invalid."""
    row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    if not row:
        return None
    # Check TTL
    created = row["created_at"]
    # Simple TTL check — if last_seen is older than TTL, delete session
    from datetime import datetime, timedelta
    try:
        last = datetime.fromisoformat(row["last_seen"].replace("Z", "+00:00"))
        age = (datetime.now() - last.replace(tzinfo=None)).total_seconds()
        if age > SESSION_TTL:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
    except (ValueError, TypeError):
        pass

    # Update last_seen
    conn.execute(
        "UPDATE sessions SET last_seen = datetime('now','localtime') WHERE token = ?",
        (token,),
    )
    conn.commit()
    return dict(row)


def logout(conn: sqlite3.Connection, token: str):
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()


def list_users(conn: sqlite3.Connection):
    return [dict(r) for r in conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()]


def change_password(conn: sqlite3.Connection, username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
    """Change password. Returns (success, message)."""
    row = conn.execute("SELECT salt, password FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return False, "Utilisateur inconnu"
    if not verify_password(old_password, row["salt"], row["password"]):
        return False, "Mot de passe actuel incorrect"
    salt, pw_hash = hash_password(new_password)
    conn.execute("UPDATE users SET salt = ?, password = ? WHERE username = ?", (salt, pw_hash, username))
    conn.commit()
    return True, "Mot de passe changé"


def setup_default_admin(conn: sqlite3.Connection):
    """Ensure at least one admin user exists. Creates admin/admin if no users."""
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        create_user(conn, "admin", "admin", "admin")
        return True
    return False
