"""wine.appellation, classification, monopole, source, notes — decision
0043, the want-list wine register.

Doug: "STORE IT PROPERLY — not as a CSV in docs/." Migration 0029 already
added `wine.want_list` and the acknowledgement fields (decision 0038) —
this is the DATA for that structure, not a new one, but the register
needs five facts the table did not carry yet: a wine's appellation is
not its cuvée (cuvée "Vosne-Romanée Les Beaux Monts" has appellation
"Vosne-Romanée"); classification (Grand Cru / 1er Cru / Village /
Regional) is neither; whether it is a monopole (only one producer can
ever make this exact wine) is identity-relevant — the pricing core never
reads it, but an operator approving a candidate against this wine
benefits from being told; and a register row needs to say where it came
from (`source`) and carry anything else worth recording (`notes`),
exactly as `docs/research/want-list-wines.csv`'s own columns already do.

All five are nullable free text (`monopole` excepted, boolean, defaulting
false): an ordinary wine created through the API has none of this and
none of it is required there — only `scripts/load_want_list_wines.py`
populates them, for want-list wines, and a missing value stays null
rather than the empty string a form might otherwise send.

Revision ID: 0033_want_list_wine_fields
Revises: 0032_idealwine
Create Date: 2026-10-27
"""
from alembic import op

revision = "0033_want_list_wine_fields"
down_revision = "0032_idealwine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wine ADD COLUMN appellation text")
    op.execute("ALTER TABLE wine ADD COLUMN classification text")
    op.execute("ALTER TABLE wine ADD COLUMN monopole boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE wine ADD COLUMN source text")
    op.execute("ALTER TABLE wine ADD COLUMN notes text")


def downgrade() -> None:
    op.execute("ALTER TABLE wine DROP COLUMN notes")
    op.execute("ALTER TABLE wine DROP COLUMN source")
    op.execute("ALTER TABLE wine DROP COLUMN monopole")
    op.execute("ALTER TABLE wine DROP COLUMN classification")
    op.execute("ALTER TABLE wine DROP COLUMN appellation")
