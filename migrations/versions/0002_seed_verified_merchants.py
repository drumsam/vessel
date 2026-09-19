"""Register the three verified merchant adapters.

Step 5 of "Adding a merchant adapter". The ids must equal each adapter's `id`
attribute, because offers are written with `merchant_id = adapter.id`.

Revision ID: 0002_seed_verified_merchants
Revises: 0001_baseline
Create Date: 2026-09-19
"""
from alembic import op

revision = "0002_seed_verified_merchants"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

MERCHANTS = [
    ("farr", "Farr Vintners", "Official JSON feed. Verified live 2026-09-19."),
    ("bordeaux-index", "Bordeaux Index",
     "HTML listing, targeted fetch by producer and vintage. Verified live 2026-09-19."),
    ("goedhuis", "Goedhuis Waddesdon", "Shopify products.json. Verified live 2026-09-19."),
]


def upgrade() -> None:
    for merchant_id, name, notes in MERCHANTS:
        op.execute(
            "INSERT INTO merchant (merchant_id, name, approved, notes) "
            f"VALUES ('{merchant_id}', '{name}', true, '{notes}')"
        )


def downgrade() -> None:
    ids = ", ".join(f"'{m[0]}'" for m in MERCHANTS)
    op.execute(f"DELETE FROM merchant WHERE merchant_id IN ({ids})")
