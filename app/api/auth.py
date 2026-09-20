"""Operator identity: argon2id passwords, server-side sessions.

Who approved an identity, priced a line or accepted a flagged price is taken
from the session and never from the request body. A caller cannot name someone
else; the API refuses a body that tries (the request models forbid the field).

The cookie carries a random token and nothing else. Only its SHA-256 is stored,
so a leaked database row cannot be replayed as a session, and revoking an
operator or a session takes effect on the very next request.

Password hashing is argon2id from argon2-cffi. The hash string carries its own
parameters, so raising them later does not invalidate existing hashes; a
password that verifies against an out-of-date hash is rehashed in place.

See docs/decisions/0009-operator-identity.md.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Response

from app.db.connection import transaction

COOKIE_NAME = "pricer_session"
SESSION_HOURS = 12

_hasher = PasswordHasher()          # argon2id with the library's current defaults


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def secure_cookies() -> bool:
    """Off only for local HTTP development, and it has to be asked for."""
    return os.environ.get("INSECURE_COOKIES", "").lower() not in ("1", "true", "yes")


def start_session(conn: psycopg.Connection, operator_id: str, response: Response) -> dict:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    row = conn.execute(
        """INSERT INTO operator_session (operator_id, token_hash, expires_at)
           VALUES (%s, %s, %s) RETURNING *""",
        (operator_id, _token_hash(token), expires)).fetchone()
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=secure_cookies(),
                        samesite="lax", expires=expires, path="/")
    return row


def end_session(conn: psycopg.Connection, token: Optional[str], response: Response) -> None:
    if token:
        conn.execute(
            "UPDATE operator_session SET revoked_at = now() "
            "WHERE token_hash = %s AND revoked_at IS NULL", (_token_hash(token),))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True,
                           secure=secure_cookies(), samesite="lax")


def authenticate(conn: psycopg.Connection, username: str, password: str) -> Optional[dict]:
    """The operator, or None. An inactive operator never authenticates, and a
    wrong username still costs a verification so the two are not distinguishable
    by timing."""
    row = conn.execute("SELECT * FROM operator WHERE username = %s", (username,)).fetchone()
    stored = row["password_hash"] if row else hash_password("no such operator")
    if not verify_password(stored, password) or row is None or not row["active"]:
        return None
    if needs_rehash(stored):
        conn.execute("UPDATE operator SET password_hash = %s WHERE operator_id = %s",
                     (hash_password(password), row["operator_id"]))
    return row


def session_operator(conn: psycopg.Connection, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    return conn.execute(
        """SELECT o.* FROM operator_session s JOIN operator o USING (operator_id)
            WHERE s.token_hash = %s AND s.revoked_at IS NULL AND s.expires_at > now()
              AND o.active""",
        (_token_hash(token),)).fetchone()


# ------------------------------------------------------------- administration


def create_operator(username: str, display_name: str, password: str,
                    note: str | None = None) -> dict:
    """Used by scripts/manage_operators.py. There is no self-service password reset:
    an admin sets one (decision 0009)."""
    with transaction() as conn:
        return conn.execute(
            """INSERT INTO operator (username, display_name, password_hash, note)
               VALUES (%s, %s, %s, %s) RETURNING operator_id, username, display_name, active""",
            (username, display_name, hash_password(password), note)).fetchone()


def set_password(username: str, password: str) -> Optional[dict]:
    with transaction() as conn:
        row = conn.execute(
            """UPDATE operator SET password_hash = %s WHERE username = %s
               RETURNING operator_id, username, display_name, active""",
            (hash_password(password), username)).fetchone()
        if row:
            # Old sessions do not survive a password change.
            conn.execute("""UPDATE operator_session SET revoked_at = now()
                             WHERE operator_id = %s AND revoked_at IS NULL""",
                         (row["operator_id"],))
        return row


def set_active(username: str, active: bool) -> Optional[dict]:
    with transaction() as conn:
        row = conn.execute(
            """UPDATE operator SET active = %s WHERE username = %s
               RETURNING operator_id, username, display_name, active""",
            (active, username)).fetchone()
        if row and not active:
            conn.execute("""UPDATE operator_session SET revoked_at = now()
                             WHERE operator_id = %s AND revoked_at IS NULL""",
                         (row["operator_id"],))
        return row
