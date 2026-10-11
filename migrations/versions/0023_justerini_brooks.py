"""Register Justerini & Brooks — step 6 of "Adding a merchant adapter".

UK breadth, 10 October 2026: 42 of 52 Champagne-sweep targets sat at one
merchant or none, which is what the whole Floor/Reference/Median design
needs 3+ sources to mean anything. First of three houses investigated,
built one at a time so each one's real contribution to READY lines is
known before the next is started. See app/adapters/justerini_brooks.py.

Revision ID: 0023_justerini_brooks
Revises: 0022_bordeaux_index_livetrade
Create Date: 2026-10-10
"""
from alembic import op

revision = "0023_justerini_brooks"
down_revision = "0022_bordeaux_index_livetrade"
branch_labels = None
depends_on = None

MERCHANT_ID = "justerini-brooks"
NAME = "Justerini & Brooks"
NOTES = ("Server-rendered Next.js App Router pages; the real data arrives as "
        "React Server Component flight chunks, not the rendered HTML a "
        "person reads. Verified live 2026-10-10.")


def upgrade() -> None:
    op.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) "
        f"VALUES ('{MERCHANT_ID}', '{NAME}', true, '{NOTES}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT_ID}'")
