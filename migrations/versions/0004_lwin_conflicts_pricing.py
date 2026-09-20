"""LWIN conflict queue, untrusted merchant LWINs, and the pricing rule columns.

Decisions 0006 (merchant LWIN policy) and 0007 (pricing rules and rounding).

* lwin_conflict: one open row per (merchant, LWIN-7) used for more than one wine
  name, with the merchant's own wording, for an operator to resolve.
* merchant_lwin_untrusted: LWINs an operator has judged unreliable, so a
  resolved conflict does not resurface on every collection.
* deal.target_margin, seller_line.target_discount: the inputs to the pricing
  precedence (manual price > line margin > line discount > deal margin).
* pricing_result.price_basis / discount / gross_margin /
  deep_discount_threshold: which rule priced the line, and with what.

Revision ID: 0004_lwin_conflicts_pricing
Revises: 0003_self_contained_benchmarks
Create Date: 2026-09-20
"""
from alembic import op

revision = "0004_lwin_conflicts_pricing"
down_revision = "0003_self_contained_benchmarks"
branch_labels = None
depends_on = None

#: Existing rows predate the rule columns. They were priced by no rule at all,
#: so the most truthful basis available is the one the operator set by hand.
DEFAULT_THRESHOLD = "0.2500"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE lwin_conflict (
            conflict_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
            lwin7        text NOT NULL,
            names        jsonb NOT NULL,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at  timestamptz NOT NULL DEFAULT now(),
            resolution   text CHECK (resolution IN ('same_wine','different_wines')),
            resolved_by  text,
            resolved_at  timestamptz,
            note         text,
            UNIQUE (merchant_id, lwin7),
            CONSTRAINT lwin_conflict_resolved CHECK (
                (resolution IS NULL AND resolved_by IS NULL AND resolved_at IS NULL)
             OR (resolution IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL))
        )""")
    op.execute("""
        CREATE TABLE merchant_lwin_untrusted (
            merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
            lwin7        text NOT NULL,
            reason       text NOT NULL,
            marked_by    text NOT NULL,
            marked_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (merchant_id, lwin7)
        )""")

    op.execute("ALTER TABLE deal ADD COLUMN target_margin numeric(6,4)")
    op.execute("ALTER TABLE seller_line ADD COLUMN target_discount numeric(6,4)")

    op.execute("ALTER TABLE pricing_result ADD COLUMN price_basis text")
    op.execute("ALTER TABLE pricing_result ADD COLUMN discount numeric(6,4)")
    op.execute("ALTER TABLE pricing_result ADD COLUMN deep_discount_threshold numeric(6,4)")
    op.execute("ALTER TABLE pricing_result ADD COLUMN gross_margin numeric(6,4)")
    op.execute("UPDATE pricing_result SET price_basis = 'manual', "
               f"deep_discount_threshold = {DEFAULT_THRESHOLD} "
               "WHERE price_basis IS NULL")
    op.execute("ALTER TABLE pricing_result ALTER COLUMN price_basis SET NOT NULL")
    op.execute("ALTER TABLE pricing_result ALTER COLUMN deep_discount_threshold SET NOT NULL")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_price_basis_check
                  CHECK (price_basis IN ('manual','line_margin','line_discount','global_margin'))""")


def downgrade() -> None:
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_price_basis_check")
    for column in ("gross_margin", "deep_discount_threshold", "discount", "price_basis"):
        op.execute(f"ALTER TABLE pricing_result DROP COLUMN {column}")
    op.execute("ALTER TABLE seller_line DROP COLUMN target_discount")
    op.execute("ALTER TABLE deal DROP COLUMN target_margin")
    op.execute("DROP TABLE merchant_lwin_untrusted")
    op.execute("DROP TABLE lwin_conflict")
