"""Shared FastAPI dependencies. Pulled out of app/api/main.py so a second
router module (app/api/vessel.py) can use the same connection, queue and
session dependencies without importing main.py and creating a cycle.
"""
from __future__ import annotations

from typing import Iterator, Optional

import psycopg
from fastapi import Cookie, Depends, HTTPException
from rq import Queue

from app.api import auth
from app.db import repo
from app.db.connection import transaction
from app.worker.queue import get_queue


def db() -> Iterator[psycopg.Connection]:
    """One transaction per request; rolled back if the handler raises."""
    with transaction() as conn:
        yield conn


def queue() -> Queue:
    return get_queue()


def current_operator(pricer_session: Optional[str] = Cookie(default=None),
                     conn: psycopg.Connection = Depends(db)) -> dict:
    """The signed-in operator, or 401. Every route but /health, /session and
    VESSEL's public (seller- and buyer-facing) routes depends on this."""
    operator = auth.session_operator(conn, pricer_session)
    if operator is None:
        raise HTTPException(401, "sign in required")
    return operator


def translate(e: Exception) -> HTTPException:
    if isinstance(e, repo.AmbiguousProducer):
        return HTTPException(409, {"error": str(e), "candidates": e.candidates})
    if isinstance(e, repo.Conflict):
        return HTTPException(409, str(e))
    if isinstance(e, psycopg.errors.UniqueViolation):
        return HTTPException(409, e.diag.message_detail or str(e))
    if isinstance(e, psycopg.errors.ForeignKeyViolation):
        return HTTPException(422, e.diag.message_detail or str(e))
    raise e
