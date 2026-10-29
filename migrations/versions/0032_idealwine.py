"""Register iDealwine — step 6 of "Adding a merchant adapter".

Decision 0042, third of three. Shop listings only, never the auction/
estimate side (login-gated, separately and explicitly claimed as
protected database content in iDealwine's own terms -- not pursued).
Every Offer is PriceKind.ASK in EUR; duty_status is UNKNOWN on every one
(a French retail shop, no bonded-warehouse concept), so under the current
invariants these mostly land as a retained DUTY rejection rather than a
priced comparable -- see the adapter module.

Revision ID: 0032_idealwine
Revises: 0031_christies
Create Date: 2026-10-26
"""
from alembic import op

revision = "0032_idealwine"
down_revision = "0031_christies"
branch_labels = None
depends_on = None

MERCHANT_ID = "idealwine"
NAME = "iDealwine"
NOTES = ("Direct shop only, never the auction/estimate side (login-gated, "
        "separately claimed as protected database content). Every Offer "
        "is PriceKind.ASK, currency EUR (confirmed live: the rendered "
        "page shows EUR even for a GB-flagged request -- priceByCountry "
        "is a tax-zone adjustment, not an FX conversion) and duty_status "
        "UNKNOWN (no bonded-warehouse concept for a French retail shop). "
        "Verified live 2026-10-26.")


def _sql_literal(text: str) -> str:
    return text.replace("'", "''")


def upgrade() -> None:
    op.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) "
        f"VALUES ('{MERCHANT_ID}', '{_sql_literal(NAME)}', true, '{_sql_literal(NOTES)}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT_ID}'")
