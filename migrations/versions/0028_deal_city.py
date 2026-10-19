"""deal.city (decision 0036): where the cellar physically sits.

The WhatsApp message templates for a shared offer link (decision 0035)
reference "{city}" as a fact already on the deal -- it never was. Added
as a nullable free-text field, entered once by the operator; a deal that
predates this column reads null, and every caller treats that as "omit
the mention", never as something to invent.

Revision ID: 0028_deal_city
Revises: 0027_shared_offer_links
Create Date: 2026-10-21
"""
from alembic import op

revision = "0028_deal_city"
down_revision = "0027_shared_offer_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE deal ADD COLUMN city text")


def downgrade() -> None:
    op.execute("ALTER TABLE deal DROP COLUMN city")
