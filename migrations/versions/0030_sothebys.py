"""Register Sotheby's — step 6 of "Adding a merchant adapter".

Decision 0042: of five auction houses Doug asked for, reconnaissance found
three genuinely reachable with a plain HTTP client and two actively
defended against exactly that. This is the first of the three built.
Auction results, not stock: every Offer this adapter produces is
PriceKind.LAST_TRADE, never Floor/Reference/Median (invariant 5).

Revision ID: 0030_sothebys
Revises: 0029_want_list
Create Date: 2026-10-26
"""
from alembic import op

revision = "0030_sothebys"
down_revision = "0029_want_list"
branch_labels = None
depends_on = None

MERCHANT_ID = "sothebys"
NAME = "Sotheby's"
NOTES = ("Auction results only, never stock -- every Offer is "
        "PriceKind.LAST_TRADE. Server-rendered Next.js; the settled price "
        "is BidState.sold.premiums.finalPriceV2.amount in the page's own "
        "Apollo cache, never the JSON-LD block (which mirrors the last bid "
        "before close, not the settled price). duty_status is UNKNOWN on "
        "every lot found so far, so most results land as a retained DUTY "
        "rejection rather than visible corroboration -- see the adapter "
        "module. Verified live 2026-10-26.")


def _sql_literal(text: str) -> str:
    return text.replace("'", "''")


def upgrade() -> None:
    op.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) "
        f"VALUES ('{MERCHANT_ID}', '{_sql_literal(NAME)}', true, '{_sql_literal(NOTES)}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT_ID}'")
