"""A market claim is never a negative discount.

Decision 0010. "12% below the UK market" is a claim about being below it. A
price ABOVE the market is not a smaller discount, and a document must not print
one as "-114% below": such a line carries no claim at all, exactly like a line
with no reference.

Revision ID: 0008_claim_never_negative
Revises: 0007_market_claim_state_gate
Create Date: 2026-09-20
"""
from alembic import op

revision = "0008_claim_never_negative"
down_revision = "0007_market_claim_state_gate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A claim written under the old rule said the opposite of what it meant.
    op.execute("DELETE FROM buyer_offer_market_claim WHERE below_reference < 0")
    op.execute("""ALTER TABLE buyer_offer_market_claim
                  ADD CONSTRAINT buyer_offer_market_claim_below_reference_check
                  CHECK (below_reference >= 0)""")


def downgrade() -> None:
    op.execute("ALTER TABLE buyer_offer_market_claim "
               "DROP CONSTRAINT buyer_offer_market_claim_below_reference_check")
