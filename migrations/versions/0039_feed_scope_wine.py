"""Decision 0048: a market-feed capture covers exactly one wine.

A merchant search covers every wine of a producer in a vintage, so its
capture is scoped (producer, vintage). A feed reports only the wines it was
asked about; scoping its capture the same way let it mask the merchant's
other wines of that producer and vintage from a fuller capture (proved in
tests/test_feed_import.py). scope_wine_id narrows a capture to one wine;
NULL keeps every existing capture exactly as it was.

Revision ID: 0039_feed_scope_wine
Revises: 0038_parcel_not_searched
Create Date: 2026-10-31
"""
from alembic import op

revision = "0039_feed_scope_wine"
down_revision = "0038_parcel_not_searched"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE snapshot_merchant ADD COLUMN scope_wine_id uuid REFERENCES wine(wine_id)")
    op.execute("""ALTER TABLE snapshot_merchant ADD CONSTRAINT snapshot_merchant_wine_scope
                  CHECK (scope_wine_id IS NULL OR scope_producer_key IS NOT NULL)""")


def downgrade() -> None:
    op.execute("ALTER TABLE snapshot_merchant DROP CONSTRAINT snapshot_merchant_wine_scope")
    op.execute("ALTER TABLE snapshot_merchant DROP COLUMN scope_wine_id")
