"""Alembic environment.

There are no SQLAlchemy models. `app/db/schema.sql` is the head schema and every
migration is hand-written SQL; `tests/test_service.py` asserts that
`alembic upgrade head` produces exactly the catalog that schema.sql produces.
"""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from app.db.connection import sqlalchemy_url


def run_migrations_offline() -> None:
    context.configure(url=sqlalchemy_url(), literal_binds=True, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(sqlalchemy_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None,
                          transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
