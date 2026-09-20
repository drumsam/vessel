"""The buyer-export gate, and producer-only alias rules.

A price carrying NEGATIVE_GP or SELL_ABOVE_UK_REFERENCE cannot reach a buyer
offer until a named operator has accepted it. Enforced by keys, not convention:
pricing_result.requires_acknowledgement is generated from the flags, and
buyer_offer_line carries a foreign key to that pair, so a line cannot claim a
price needs no acknowledgement when it does.

COST_ABOVE_UK_REFERENCE and DEEP_DISCOUNT deliberately do not gate.

Producer-only aliases (key ending in '|') are operator-only and marked, because
one attaches every listing a merchant prints under the producer alone.

Revision ID: 0005_export_gate_alias_rules
Revises: 0004_lwin_conflicts_pricing
Create Date: 2026-09-20
"""
from alembic import op

revision = "0005_export_gate_alias_rules"
down_revision = "0004_lwin_conflicts_pricing"
branch_labels = None
depends_on = None

GATING_FLAGS = "'NEGATIVE_GP','SELL_ABOVE_UK_REFERENCE'"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wine_alias ADD COLUMN is_producer_only boolean NOT NULL
            GENERATED ALWAYS AS (right(wine_key, 1) = '|') STORED""")
    # Any alias already created without a cuvee by something other than an
    # operator predates the rule; there is nothing to migrate but the rule must
    # hold from here on, so the constraint is added as-is and will fail loudly
    # if such a row exists.
    op.execute("""
        ALTER TABLE wine_alias ADD CONSTRAINT wine_alias_producer_only_is_operator
            CHECK (right(wine_key, 1) <> '|' OR source = 'operator')""")

    op.execute(f"""
        ALTER TABLE pricing_result ADD COLUMN requires_acknowledgement boolean NOT NULL
            GENERATED ALWAYS AS (flags && ARRAY[{GATING_FLAGS}]::text[]) STORED""")
    op.execute("""ALTER TABLE pricing_result
                  ADD CONSTRAINT pricing_result_pricing_id_requires_acknowledgement_key
                  UNIQUE (pricing_id, requires_acknowledgement)""")

    op.execute("""
        CREATE TABLE pricing_acknowledgement (
            ack_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            pricing_id      uuid NOT NULL REFERENCES pricing_result(pricing_id) ON DELETE CASCADE,
            flags           text[] NOT NULL,
            acknowledged_by text NOT NULL,
            acknowledged_at timestamptz NOT NULL DEFAULT now(),
            note            text,
            UNIQUE (pricing_id),
            UNIQUE (ack_id, pricing_id)
        )""")

    # Existing rows: their prices were exported under no gate at all. Rather
    # than invent an acknowledgement, they are marked as not requiring one,
    # which is what was true when they were written.
    op.execute("ALTER TABLE buyer_offer_line ADD COLUMN pricing_requires_ack boolean")
    op.execute("ALTER TABLE buyer_offer_line ADD COLUMN ack_id uuid")
    op.execute("""UPDATE buyer_offer_line l SET pricing_requires_ack = p.requires_acknowledgement
                    FROM pricing_result p WHERE p.pricing_id = l.pricing_id""")
    op.execute("ALTER TABLE buyer_offer_line ALTER COLUMN pricing_requires_ack SET NOT NULL")
    op.execute("""ALTER TABLE buyer_offer_line
                  ADD CONSTRAINT buyer_offer_line_pricing_id_pricing_requires_ack_fkey
                  FOREIGN KEY (pricing_id, pricing_requires_ack)
                  REFERENCES pricing_result (pricing_id, requires_acknowledgement)""")
    op.execute("""ALTER TABLE buyer_offer_line
                  ADD CONSTRAINT buyer_offer_line_ack_id_pricing_id_fkey
                  FOREIGN KEY (ack_id, pricing_id)
                  REFERENCES pricing_acknowledgement (ack_id, pricing_id)""")
    op.execute("""ALTER TABLE buyer_offer_line ADD CONSTRAINT buyer_offer_line_acknowledged
                  CHECK (NOT pricing_requires_ack OR ack_id IS NOT NULL)""")


def downgrade() -> None:
    op.execute("ALTER TABLE buyer_offer_line DROP CONSTRAINT buyer_offer_line_acknowledged")
    op.execute("ALTER TABLE buyer_offer_line "
               "DROP CONSTRAINT buyer_offer_line_ack_id_pricing_id_fkey")
    op.execute("ALTER TABLE buyer_offer_line "
               "DROP CONSTRAINT buyer_offer_line_pricing_id_pricing_requires_ack_fkey")
    op.execute("ALTER TABLE buyer_offer_line DROP COLUMN ack_id")
    op.execute("ALTER TABLE buyer_offer_line DROP COLUMN pricing_requires_ack")
    op.execute("DROP TABLE pricing_acknowledgement")
    op.execute("ALTER TABLE pricing_result "
               "DROP CONSTRAINT pricing_result_pricing_id_requires_acknowledgement_key")
    op.execute("ALTER TABLE pricing_result DROP COLUMN requires_acknowledgement")
    op.execute("ALTER TABLE wine_alias DROP CONSTRAINT wine_alias_producer_only_is_operator")
    op.execute("ALTER TABLE wine_alias DROP COLUMN is_producer_only")
