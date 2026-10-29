"""Register Christie's — step 6 of "Adding a merchant adapter".

Decision 0042, second of three. Auction results, not stock: every Offer
this adapter produces is PriceKind.LAST_TRADE, never Floor/Reference/
Median (invariant 5). Reads `/en/lot/` only -- Christie's separate
"online-only" platform intermittently returned the same DataDome challenge
Heritage returns on every request and is not touched by this adapter.

Revision ID: 0031_christies
Revises: 0030_sothebys
Create Date: 2026-10-26
"""
from alembic import op

revision = "0031_christies"
down_revision = "0030_sothebys"
branch_labels = None
depends_on = None

MERCHANT_ID = "christies"
NAME = "Christie's"
NOTES = ("Auction results only, never stock -- every Offer is "
        "PriceKind.LAST_TRADE. www.christies.com/en/lot/ only, server-"
        "rendered Sitecore/Angular; the lot's own record and a second, "
        "unrelated sidebar 'lots' array both appear on the same page, "
        "disambiguated by the page's own <link rel=canonical>. duty_status "
        "is always UNKNOWN -- simplified deliberately; bringing the price "
        "in is the point. Verified live 2026-10-26.")


def _sql_literal(text: str) -> str:
    return text.replace("'", "''")


def upgrade() -> None:
    op.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) "
        f"VALUES ('{MERCHANT_ID}', '{_sql_literal(NAME)}', true, '{_sql_literal(NOTES)}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT_ID}'")
