"""Register Jeroboams — step 6 of "Adding a merchant adapter".

Third of the three houses Doug asked to be investigated for UK breadth, one
at a time (0023 was Justerini & Brooks, 0024 Berry Bros. & Rudd). robots.txt
and the terms-and-conditions-of-sale page were both read live before
building, per Doug's own instruction that a verbal permission never
overrides a published prohibition -- neither carries an anti-automation
clause. See app/adapters/jeroboams.py and
docs/decisions/0031-jeroboams.md.

Revision ID: 0025_jeroboams
Revises: 0024_berry_bros_rudd
Create Date: 2026-10-16
"""
from alembic import op

revision = "0025_jeroboams"
down_revision = "0024_berry_bros_rudd"
branch_labels = None
depends_on = None

MERCHANT_ID = "jeroboams"
NAME = "Jeroboams"
NOTES = ("Next.js SSR, real data as plain JSON in __NEXT_DATA__ -- no "
        "per-producer search endpoint, product_paths resolved from the "
        "merchant's own product-sitemap*.xml. The first adapter in this "
        "fleet to find a real single-bottle, back-vintage, In Bond "
        "listing rather than only case stock. Verified live 2026-10-16.")


def _sql_literal(text: str) -> str:
    return text.replace("'", "''")


def upgrade() -> None:
    op.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) "
        f"VALUES ('{MERCHANT_ID}', '{_sql_literal(NAME)}', true, '{_sql_literal(NOTES)}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT_ID}'")
