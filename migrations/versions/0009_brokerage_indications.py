"""Brokerage indications: a price kind, a comp role, and FINE+RARE.

Decision 0013. An INDICATION is a brokerage's aggregated view of where a wine
would broker, not an offer of stock. The pricing core already excludes it — the
KIND screen does that without changing benchmark.py — and it is kept as
corroboration, so it needs a role of its own beside cross_unit.

Revision ID: 0009_brokerage_indications
Revises: 0008_claim_never_negative
Create Date: 2026-09-22
"""
from alembic import op

revision = "0009_brokerage_indications"
down_revision = "0008_claim_never_negative"
branch_labels = None
depends_on = None

MERCHANT = ("fine-rare", "FINE+RARE",
            "Brokerage. Publishes an aggregated pan-European broking indication per wine, "
            "not stock: every variant reads quantity 0. Searched by producer and vintage. "
            "Verified live 2026-09-22.")


def upgrade() -> None:
    op.execute("ALTER TABLE offer DROP CONSTRAINT offer_price_kind_check")
    op.execute("""ALTER TABLE offer ADD CONSTRAINT offer_price_kind_check
                  CHECK (price_kind IN ('ASK','BID','LAST_TRADE','INDICATION'))""")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_role_check")
    op.execute("""ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_role_check
                  CHECK (role IN ('comparable','merchant_best','cross_unit',
                                  'indication','rejected'))""")
    op.execute(f"""INSERT INTO merchant (merchant_id, name, approved, notes)
                   VALUES ('{MERCHANT[0]}', '{MERCHANT[1]}', true, '{MERCHANT[2]}')""")


def downgrade() -> None:
    op.execute(f"DELETE FROM offer WHERE merchant_id = '{MERCHANT[0]}'")
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT[0]}'")
    op.execute("DELETE FROM benchmark_comp WHERE role = 'indication'")
    op.execute("DELETE FROM offer WHERE price_kind = 'INDICATION'")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_role_check")
    op.execute("""ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_role_check
                  CHECK (role IN ('comparable','merchant_best','cross_unit','rejected'))""")
    op.execute("ALTER TABLE offer DROP CONSTRAINT offer_price_kind_check")
    op.execute("""ALTER TABLE offer ADD CONSTRAINT offer_price_kind_check
                  CHECK (price_kind IN ('ASK','BID','LAST_TRADE'))""")
