"""Database connections. Plain psycopg 3, standard SQL, no ORM.

psycopg returns `numeric` as `Decimal` and accepts `Decimal` for it, so money
never passes through float between Postgres and the pricing core.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


#: The Alembic revision this codebase expects the database to be at. Bump
#: this in the same commit as every new migration. `migrations/` itself is
#: not bundled into the deployed function (see .vercelignore), so this
#: constant -- not a live read of migrations/versions/ -- is the only way
#: the running API can tell "reachable" apart from "actually usable".
EXPECTED_HEAD_REVISION = "0037_parcel_trade"


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def sqlalchemy_url() -> str:
    """Alembic needs a SQLAlchemy URL naming the psycopg 3 driver."""
    url = database_url()
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    raise RuntimeError("DATABASE_URL must be a postgresql:// URL")


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or database_url(), row_factory=dict_row)


@contextmanager
def transaction(url: str | None = None) -> Iterator[psycopg.Connection]:
    """One connection, one transaction: commit on success, roll back on error."""
    with connect(url) as conn:
        with conn.transaction():
            yield conn
