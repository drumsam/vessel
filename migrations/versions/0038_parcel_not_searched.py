"""Decision 0046: a parcel trade may be priced on a line nobody has searched,
behind an explicit acknowledgement.

NOT_SEARCHED becomes a pricing_result state with no benchmark run behind it
-- run_id NULL exactly when the state is NOT_SEARCHED, and only ever on the
parcel_trade basis, where the sell price is Doug's own number rather than
one derived from the market. Every other basis keeps invariant 10 as it was:
no run, no price. NOT_SEARCHED gates export through requires_acknowledgement
the same way NO_MARKET and REVIEW do, and an acknowledgement may record it.

Revision ID: 0038_parcel_not_searched
Revises: 0037_parcel_trade
Create Date: 2026-10-30
"""
from alembic import op

revision = "0038_parcel_not_searched"
down_revision = "0037_parcel_trade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pricing_result ALTER COLUMN run_id DROP NOT NULL")
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_state_check")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_state_check
                  CHECK (state IN ('READY','REVIEW','NO_MARKET','NOT_SEARCHED'))""")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_run_iff_searched
                  CHECK ((run_id IS NULL) = (state = 'NOT_SEARCHED'))""")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_not_searched_parcel_only
                  CHECK (state <> 'NOT_SEARCHED' OR price_basis = 'parcel_trade')""")
    op.execute("""ALTER TABLE pricing_result ALTER COLUMN requires_acknowledgement
                  SET EXPRESSION AS (flags && ARRAY['NEGATIVE_GP',
                                     'SELL_ABOVE_UK_REFERENCE',
                                     'SELL_AT_OR_ABOVE_UK_FLOOR']::text[]
                                     OR state IN ('NO_MARKET','REVIEW','NOT_SEARCHED'))""")
    op.execute("ALTER TABLE pricing_acknowledgement DROP CONSTRAINT pricing_acknowledgement_state_check")
    op.execute("""ALTER TABLE pricing_acknowledgement ADD CONSTRAINT pricing_acknowledgement_state_check
                  CHECK (state IN ('READY','REVIEW','NO_MARKET','NOT_SEARCHED'))""")


def downgrade() -> None:
    op.execute("ALTER TABLE pricing_acknowledgement DROP CONSTRAINT pricing_acknowledgement_state_check")
    op.execute("""ALTER TABLE pricing_acknowledgement ADD CONSTRAINT pricing_acknowledgement_state_check
                  CHECK (state IN ('READY','REVIEW','NO_MARKET'))""")
    op.execute("""ALTER TABLE pricing_result ALTER COLUMN requires_acknowledgement
                  SET EXPRESSION AS (flags && ARRAY['NEGATIVE_GP',
                                     'SELL_ABOVE_UK_REFERENCE',
                                     'SELL_AT_OR_ABOVE_UK_FLOOR']::text[]
                                     OR state IN ('NO_MARKET','REVIEW'))""")
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_not_searched_parcel_only")
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_run_iff_searched")
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_state_check")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_state_check
                  CHECK (state IN ('READY','REVIEW','NO_MARKET'))""")
    op.execute("ALTER TABLE pricing_result ALTER COLUMN run_id SET NOT NULL")
