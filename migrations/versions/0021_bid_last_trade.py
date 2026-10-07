"""Bid and last-trade evidence from a two-sided market (decision 0026).

benchmark_comp.role already distinguishes 'indication' from a priced
comparable; 'bid' and 'last_trade' join it the same way. Neither role is
ever counted in Floor, Reference or Median — app/core/benchmark.py's own
KIND screen still admits only ASK to pricing; this widens only the
audit trail that already records corroboration, same mechanism decision
0013 built for INDICATION.

Revision ID: 0021_bid_last_trade
Revises: 0020_member_referrals
Create Date: 2026-10-08
"""
from alembic import op

revision = "0021_bid_last_trade"
down_revision = "0020_member_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_role_check")
    op.execute(
        """ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_role_check
               CHECK (role IN ('comparable','merchant_best','cross_unit','indication',
                               'bid','last_trade','rejected'))""")


def downgrade() -> None:
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_role_check")
    op.execute(
        """ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_role_check
               CHECK (role IN ('comparable','merchant_best','cross_unit','indication','rejected'))""")
