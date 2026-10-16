"""Register Berry Bros. & Rudd — step 6 of "Adding a merchant adapter".

Second of the three houses Doug asked to be investigated for UK breadth, one
at a time (see 0023_justerini_brooks). Doug's verbal permission to fetch
pricing is additive comfort, not an override of robots.txt's own
`Visit-time: 0200-0700` (UTC) directive, which app/worker/politeness.py
enforces unchanged. See app/adapters/berry_bros_rudd.py and
docs/decisions/0030-berry-bros-rudd.md.

Revision ID: 0024_berry_bros_rudd
Revises: 0023_justerini_brooks
Create Date: 2026-10-11
"""
from alembic import op

revision = "0024_berry_bros_rudd"
down_revision = "0023_justerini_brooks"
branch_labels = None
depends_on = None

MERCHANT_ID = "berry-bros-rudd"
NAME = "Berry Bros. & Rudd"
NOTES = ("Vue/Nuxt SSR; the real pricing is in window.__NUXT__, a JS "
        "expression evaluated in a Node subprocess, not the page's own "
        "JSON-LD (a stale placeholder). One merchant_id for both its own "
        "direct stock (stock_origin BBR) and its own BBX exchange "
        "(stock_origin BBX) -- one company, two surfaces, same reading as "
        "Bordeaux Index LiveTrade (decision 0026/0027). Verified live "
        "2026-10-11.")


def _sql_literal(text: str) -> str:
    return text.replace("'", "''")


def upgrade() -> None:
    op.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) "
        f"VALUES ('{MERCHANT_ID}', '{_sql_literal(NAME)}', true, '{_sql_literal(NOTES)}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT_ID}'")
