"""SELL_AT_OR_ABOVE_UK_FLOOR gates the export, same family as NEGATIVE_GP
and SELL_ABOVE_UK_REFERENCE (decision 0033).

Found seeding the real 9 October 2026 Champagne sweep, not invented: with
exactly two comps, Reference is the DEARER of the two merchant-bests, so
a buyer_discount price below Reference can still sit at or above the
cheapest ask actually found. Four real lines did -- one of them only 1.7%
above Floor, and every one of them would have carried a "below market"
claim that was false. `requires_acknowledgement` is a GENERATED column
over `flags`, and Postgres has no ALTER for a generated expression: the
column (and the two constraints that reference it) must be dropped and
re-added.

Revision ID: 0026_sell_at_or_above_floor
Revises: 0025_jeroboams
Create Date: 2026-10-18
"""
from alembic import op

revision = "0026_sell_at_or_above_floor"
down_revision = "0025_jeroboams"
branch_labels = None
depends_on = None

_OLD_FLAGS = "ARRAY['NEGATIVE_GP','SELL_ABOVE_UK_REFERENCE']::text[]"
_NEW_FLAGS = "ARRAY['NEGATIVE_GP','SELL_ABOVE_UK_REFERENCE','SELL_AT_OR_ABOVE_UK_FLOOR']::text[]"


def _replace_generated_column(flags_array: str) -> None:
    op.execute("ALTER TABLE buyer_offer_line "
              "DROP CONSTRAINT buyer_offer_line_pricing_id_pricing_requires_ack_fkey")
    op.execute("ALTER TABLE pricing_result "
              "DROP CONSTRAINT pricing_result_pricing_id_requires_acknowledgement_key")
    op.execute("ALTER TABLE pricing_result DROP COLUMN requires_acknowledgement")
    op.execute(
        f"""ALTER TABLE pricing_result ADD COLUMN requires_acknowledgement boolean NOT NULL
               GENERATED ALWAYS AS (flags && {flags_array}
                                     OR state IN ('NO_MARKET','REVIEW')) STORED""")
    op.execute("ALTER TABLE pricing_result ADD CONSTRAINT "
              "pricing_result_pricing_id_requires_acknowledgement_key "
              "UNIQUE (pricing_id, requires_acknowledgement)")
    op.execute("ALTER TABLE buyer_offer_line ADD CONSTRAINT "
              "buyer_offer_line_pricing_id_pricing_requires_ack_fkey "
              "FOREIGN KEY (pricing_id, pricing_requires_ack) "
              "REFERENCES pricing_result (pricing_id, requires_acknowledgement)")


def upgrade() -> None:
    _replace_generated_column(_NEW_FLAGS)


def downgrade() -> None:
    _replace_generated_column(_OLD_FLAGS)
