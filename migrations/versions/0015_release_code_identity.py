"""Release-code identity: Krug's numbered editions are different wines.

Decision 0019. 41 Krug lines across Grande Cuvee 156e to 169e in a live cellar;
LWIN's vintage=1000 NV convention collapses every edition into one product.
`wine.release_code` adds a third segment to `wine_key` when present, so an
edition is a different key from the bare cuvee and a codeless candidate can
never resolve to one that has a code.

Revision ID: 0015_release_code_identity
Revises: 0014_buyer_discount_chain
Create Date: 2026-10-05
"""
from alembic import op

revision = "0015_release_code_identity"
down_revision = "0014_buyer_discount_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wine ADD COLUMN release_code text")


def downgrade() -> None:
    op.execute("ALTER TABLE wine DROP COLUMN release_code")
