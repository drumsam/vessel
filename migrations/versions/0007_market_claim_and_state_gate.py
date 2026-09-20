"""The market claim, the state gate, and merchant search keys.

Decision 0010.

* A line's market claim moves into buyer_offer_market_claim, where uk_reference
  is NOT NULL. A line with no UK Reference has no row, so a client document has
  nothing to print for it.
* pricing_result.requires_acknowledgement now also fires on a NO_MARKET or
  REVIEW benchmark state. The column is generated, so it cannot drift; changing
  the expression means rebuilding it and the two things that depend on it.
* merchant_search_key records how a search-only merchant is asked about one
  producer, so DEEP MERCHANT SEARCH never guesses a slug.

Revision ID: 0007_market_claim_state_gate
Revises: 0006_operators_and_sessions
Create Date: 2026-09-20
"""
from alembic import op
from sqlalchemy import text

revision = "0007_market_claim_state_gate"
down_revision = "0006_operators_and_sessions"
branch_labels = None
depends_on = None

#: An issued line whose recorded gate no longer matches the rebuilt column.
STALE_GATES = text("""
    SELECT count(*) FROM buyer_offer_line l JOIN pricing_result p USING (pricing_id)
     WHERE l.pricing_requires_ack IS DISTINCT FROM p.requires_acknowledgement""")

OLD_GATE = "flags && ARRAY['NEGATIVE_GP','SELL_ABOVE_UK_REFERENCE']::text[]"
NEW_GATE = (f"{OLD_GATE}\n                                           "
            "OR state IN ('NO_MARKET','REVIEW')")


def _rebuild_gate(expression: str) -> None:
    """The generated column is referenced by a unique constraint, which is
    referenced by buyer_offer_line. Drop inwards, rebuild outwards."""
    op.execute("ALTER TABLE buyer_offer_line "
               "DROP CONSTRAINT buyer_offer_line_pricing_id_pricing_requires_ack_fkey")
    op.execute("ALTER TABLE pricing_result "
               "DROP CONSTRAINT pricing_result_pricing_id_requires_acknowledgement_key")
    op.execute("ALTER TABLE pricing_result DROP COLUMN requires_acknowledgement")
    op.execute(f"""ALTER TABLE pricing_result ADD COLUMN requires_acknowledgement boolean NOT NULL
                   GENERATED ALWAYS AS ({expression}) STORED""")
    op.execute("""ALTER TABLE pricing_result
                  ADD CONSTRAINT pricing_result_pricing_id_requires_acknowledgement_key
                  UNIQUE (pricing_id, requires_acknowledgement)""")
    # Rows written before the change may now disagree with the new expression:
    # say so rather than rewrite an issued document's claim about itself.
    # (Offline `--sql` rendering has no database to ask.)
    stale = 0 if op.get_context().as_sql else op.get_bind().execute(STALE_GATES).scalar()
    if stale:
        raise RuntimeError(
            f"{stale} issued offer line(s) record a gate that the new expression disagrees "
            "with. They were exported under the old rule; decide what to do with them "
            "before migrating.")
    op.execute("""ALTER TABLE buyer_offer_line
                  ADD CONSTRAINT buyer_offer_line_pricing_id_pricing_requires_ack_fkey
                  FOREIGN KEY (pricing_id, pricing_requires_ack)
                  REFERENCES pricing_result (pricing_id, requires_acknowledgement)""")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE merchant_search_key (
            merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
            producer_key text NOT NULL,
            params       jsonb NOT NULL,
            source       text NOT NULL CHECK (source IN ('merchant_index','operator')),
            set_by       uuid NOT NULL REFERENCES operator(operator_id),
            set_at       timestamptz NOT NULL DEFAULT now(),
            note         text,
            PRIMARY KEY (merchant_id, producer_key)
        )""")

    op.execute("ALTER TABLE pricing_acknowledgement ADD COLUMN state text")
    op.execute("""UPDATE pricing_acknowledgement a SET state = p.state
                    FROM pricing_result p WHERE p.pricing_id = a.pricing_id""")
    op.execute("ALTER TABLE pricing_acknowledgement ALTER COLUMN state SET NOT NULL")
    op.execute("""ALTER TABLE pricing_acknowledgement ADD CONSTRAINT
                  pricing_acknowledgement_state_check
                  CHECK (state IN ('READY','REVIEW','NO_MARKET'))""")

    _rebuild_gate(NEW_GATE)

    op.execute("""
        CREATE TABLE buyer_offer_market_claim (
            buyer_offer_id uuid NOT NULL,
            line_no        int NOT NULL,
            run_id         uuid NOT NULL REFERENCES benchmark_run(run_id),
            as_of          timestamptz NOT NULL,
            uk_reference   numeric(14,2) NOT NULL,
            comp_count     int NOT NULL CHECK (comp_count > 0),
            below_reference numeric(6,4) NOT NULL,
            PRIMARY KEY (buyer_offer_id, line_no),
            FOREIGN KEY (buyer_offer_id, line_no)
                REFERENCES buyer_offer_line (buyer_offer_id, line_no) ON DELETE CASCADE
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE buyer_offer_market_claim")
    _rebuild_gate(OLD_GATE)
    op.execute("ALTER TABLE pricing_acknowledgement "
               "DROP CONSTRAINT pricing_acknowledgement_state_check")
    op.execute("ALTER TABLE pricing_acknowledgement DROP COLUMN state")
    op.execute("DROP TABLE merchant_search_key")
