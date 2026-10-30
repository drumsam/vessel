"""VESSEL Pocket Milestone 1: the parcel_trade pricing basis, the offer's
own availability text, and fulfilment -- the one new table, the record of
a confirmed trade.

parcel_trade: Doug buys from a supplier and sells on at a price HE sets;
pricing_result carries it exactly as the other bases do (sell_price is the
VESSEL sell price, cost/cost_gbp the supplier price, both per commercial
unit), so the generated requires_acknowledgement column gates it the same way.

inbound_offer.availability: lead time / hold details, typed by the operator
when he creates the offer -- the supplier's message carries them, nothing
captured them, and a tombstone may not print "Available now" unless he did.

fulfilment: the commercial facts frozen at CONFIRM, copied rather than
joined so a later re-price or a corrected inbound record cannot change what
was agreed. The trigger forbids any change except OPEN -> COMPLETE, and any
delete. The (pricing_id, pricing_requires_ack)/(ack_id, pricing_id) keys are
buyer_offer_line's own export-gate pattern: a trade cannot be confirmed on a
price that needed accepting and was not.

Revision ID: 0037_parcel_trade
Revises: 0036_confirmed_commercial
Create Date: 2026-10-30
"""
from alembic import op

revision = "0037_parcel_trade"
down_revision = "0036_confirmed_commercial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_price_basis_check")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_price_basis_check
                  CHECK (price_basis IN ('manual','line_margin','line_discount',
                                         'global_margin','buyer_discount','parcel_trade'))""")

    op.execute("ALTER TABLE inbound_offer ADD COLUMN availability text")

    op.execute("""
        CREATE TABLE fulfilment (
            fulfilment_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            inbound_offer_id  uuid NOT NULL UNIQUE REFERENCES inbound_offer(inbound_offer_id),
            line_id           uuid NOT NULL REFERENCES seller_line(line_id),
            pricing_id        uuid NOT NULL,
            pricing_requires_ack boolean NOT NULL,
            ack_id            uuid,
            supplier_id       uuid NOT NULL REFERENCES supplier(supplier_id),
            buyer_name        text NOT NULL CHECK (btrim(buyer_name) <> ''),
            wine_id           uuid NOT NULL REFERENCES wine(wine_id),
            wine_name         text NOT NULL,
            vintage           int NOT NULL,
            bottle_ml         int NOT NULL,
            pack_size         int NOT NULL,
            quantity          int NOT NULL CHECK (quantity > 0),
            packaging         text,
            bond_status       text,
            stock_location    text,
            availability      text,
            currency          char(3) NOT NULL,
            supplier_price    numeric(14,2) NOT NULL CHECK (supplier_price > 0),
            vessel_sell_price numeric(14,2) NOT NULL CHECK (vessel_sell_price > 0),
            gross_total       numeric(14,2) NOT NULL,
            state             text NOT NULL DEFAULT 'OPEN' CHECK (state IN ('OPEN', 'COMPLETE')),
            confirmed_by      uuid NOT NULL REFERENCES operator(operator_id),
            confirmed_at      timestamptz NOT NULL DEFAULT now(),
            completed_by      uuid REFERENCES operator(operator_id),
            completed_at      timestamptz,
            FOREIGN KEY (pricing_id, pricing_requires_ack)
                REFERENCES pricing_result (pricing_id, requires_acknowledgement),
            FOREIGN KEY (ack_id, pricing_id)
                REFERENCES pricing_acknowledgement (ack_id, pricing_id),
            CONSTRAINT fulfilment_acknowledged CHECK (NOT pricing_requires_ack OR ack_id IS NOT NULL),
            CONSTRAINT fulfilment_gross_total CHECK (
                gross_total = (vessel_sell_price - supplier_price) * quantity),
            CONSTRAINT fulfilment_completion_attributed CHECK (
                (state = 'COMPLETE') = (completed_by IS NOT NULL AND completed_at IS NOT NULL))
        )
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION fulfilment_freeze() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'fulfilment % is a confirmed trade and cannot be deleted',
                    OLD.fulfilment_id;
            END IF;
            IF OLD.state = 'COMPLETE' THEN
                RAISE EXCEPTION 'fulfilment % is already complete', OLD.fulfilment_id;
            END IF;
            IF (to_jsonb(NEW) - 'state' - 'completed_by' - 'completed_at')
               IS DISTINCT FROM (to_jsonb(OLD) - 'state' - 'completed_by' - 'completed_at') THEN
                RAISE EXCEPTION 'fulfilment % is a confirmed trade; its facts are frozen',
                    OLD.fulfilment_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER fulfilment_no_mutation
            BEFORE UPDATE OR DELETE ON fulfilment
            FOR EACH ROW EXECUTE FUNCTION fulfilment_freeze()
    """)


def downgrade() -> None:
    op.execute("DROP TABLE fulfilment")
    op.execute("DROP FUNCTION fulfilment_freeze()")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN availability")
    op.execute("ALTER TABLE pricing_result DROP CONSTRAINT pricing_result_price_basis_check")
    op.execute("""ALTER TABLE pricing_result ADD CONSTRAINT pricing_result_price_basis_check
                  CHECK (price_basis IN ('manual','line_margin','line_discount',
                                         'global_margin','buyer_discount'))""")
