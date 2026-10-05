"""The market chain, as two named steps: M -> buyer price -> seller receives.

Decision 0017. The pricer already took a target margin; it did not model the
buyer discount as a separate, named step. Both numbers now appear on every line
priced this way, and both settings used are recorded on the issued offer so a
reprice is auditable.

Revision ID: 0014_buyer_discount_chain
Revises: 0013_case_premium_pairs
Create Date: 2026-10-05
"""
from alembic import op

revision = "0014_buyer_discount_chain"
down_revision = "0013_case_premium_pairs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE deal ADD COLUMN buyer_discount numeric(6,4)")
    op.execute("ALTER TABLE deal ADD COLUMN margin_on_sale numeric(6,4)")

    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_price_basis_check")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_price_basis_check
                  CHECK (price_basis IN ('manual','line_margin','line_discount',
                                         'global_margin','buyer_discount'))""")
    op.execute("ALTER TABLE pricing_result ADD COLUMN buyer_discount numeric(6,4)")
    op.execute("ALTER TABLE pricing_result ADD COLUMN margin_on_sale numeric(6,4)")
    op.execute("""ALTER TABLE pricing_result ADD COLUMN buyer_price_gbp numeric(14,2)
                  GENERATED ALWAYS AS
                  (CASE WHEN price_basis = 'buyer_discount' THEN sell_price END) STORED""")
    op.execute("""ALTER TABLE pricing_result ADD COLUMN seller_price_gbp numeric(14,2)
                  GENERATED ALWAYS AS
                  (CASE WHEN price_basis = 'buyer_discount' THEN cost_gbp END) STORED""")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_chain_fields CHECK (
                      (price_basis = 'buyer_discount') =
                      (buyer_discount IS NOT NULL AND margin_on_sale IS NOT NULL))""")


def downgrade() -> None:
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_chain_fields")
    op.execute("ALTER TABLE pricing_result DROP COLUMN seller_price_gbp")
    op.execute("ALTER TABLE pricing_result DROP COLUMN buyer_price_gbp")
    op.execute("ALTER TABLE pricing_result DROP COLUMN margin_on_sale")
    op.execute("ALTER TABLE pricing_result DROP COLUMN buyer_discount")
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_price_basis_check")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_price_basis_check
                  CHECK (price_basis IN ('manual','line_margin','line_discount',
                                         'global_margin'))""")
    op.execute("ALTER TABLE deal DROP COLUMN margin_on_sale")
    op.execute("ALTER TABLE deal DROP COLUMN buyer_discount")
