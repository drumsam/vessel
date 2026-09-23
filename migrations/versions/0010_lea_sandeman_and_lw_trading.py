"""Register Lea & Sandeman and Lay & Wheeler Trading.

Step 5 of "Adding a merchant adapter", for the two merchants specified in
docs/research/adapter-spec-pack.md.

Revision ID: 0010_ls_and_lw_trading
Revises: 0009_brokerage_indications
Create Date: 2026-09-23
"""
from alembic import op

revision = "0010_ls_and_lw_trading"
down_revision = "0009_brokerage_indications"
branch_labels = None
depends_on = None

MERCHANTS = [
    ("lea-sandeman", "Lea & Sandeman",
     "Swept whole: /fine-wine.html?resultsPerPage=192, one request, 174 rows. "
     "Terms are conditions of sale only. Never paginate and never collect product "
     "pages (duty-paid retail per bottle). Verified live 2026-09-23."),
    ("lw-trading", "Lay & Wheeler Trading",
     "Searched by producer term via the WooCommerce Store API. A separate estate "
     "from laywheeler.com, which blocks us and must not be touched. robots asks "
     "Crawl-delay 10. Verified live 2026-09-23."),
]


def upgrade() -> None:
    for merchant_id, name, notes in MERCHANTS:
        op.execute("INSERT INTO merchant (merchant_id, name, approved, notes) "
                   f"VALUES ('{merchant_id}', '{name.replace(chr(39), chr(39) * 2)}', true, "
                   f"'{notes}')")


def downgrade() -> None:
    ids = ", ".join(f"'{m[0]}'" for m in MERCHANTS)
    op.execute(f"DELETE FROM offer WHERE merchant_id IN ({ids})")
    op.execute(f"DELETE FROM merchant WHERE merchant_id IN ({ids})")
