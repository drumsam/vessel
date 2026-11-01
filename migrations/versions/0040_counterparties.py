"""Workbench, offer actions and counterparty foundations (decision 0050).

inbound_offer.discarded_at/by: Delete is a soft delete — the raw capture is
never destroyed (CLAUDE.md non-negotiable), nothing cascades. A discarded
offer is hidden everywhere and can no longer be priced or confirmed.
inbound_offer.duplicated_from: provenance for Duplicate.
supplier: the commercial defaults a supplier record eventually holds.
client / client_alias: a proper client register in place of free-text buyer
names; fulfilment.client_id links a confirmed trade to it (buyer_name stays
frozen text, so existing confirmed trades are untouched).

Revision ID: 0040_counterparties
Revises: 0039_feed_scope_wine
Create Date: 2026-11-01
"""
from alembic import op

revision = "0040_counterparties"
down_revision = "0039_feed_scope_wine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE inbound_offer ADD COLUMN discarded_at timestamptz")
    op.execute("ALTER TABLE inbound_offer ADD COLUMN discarded_by uuid REFERENCES operator(operator_id)")
    op.execute("""ALTER TABLE inbound_offer ADD CONSTRAINT inbound_offer_discard_attributed
                  CHECK ((discarded_at IS NULL) = (discarded_by IS NULL))""")
    op.execute("""ALTER TABLE inbound_offer ADD COLUMN duplicated_from uuid
                  REFERENCES inbound_offer(inbound_offer_id)""")
    op.execute("ALTER TABLE supplier ADD COLUMN default_currency char(3)")
    op.execute("ALTER TABLE supplier ADD COLUMN usual_stock_location text")
    op.execute("ALTER TABLE supplier ADD COLUMN usual_bond_status text")
    op.execute("ALTER TABLE supplier ADD COLUMN payment_terms text")
    op.execute("""
        CREATE TABLE client (
            client_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name             text NOT NULL UNIQUE,
            contact_name     text,
            email            text,
            phone            text,
            default_currency char(3),
            delivery_notes   text,
            payment_terms    text,
            notes            text,
            active           boolean NOT NULL DEFAULT true,
            created_by       uuid NOT NULL REFERENCES operator(operator_id),
            created_at       timestamptz NOT NULL DEFAULT now()
        )""")
    op.execute("""
        CREATE TABLE client_alias (
            client_id  uuid NOT NULL REFERENCES client(client_id),
            alias      text NOT NULL,
            PRIMARY KEY (client_id, alias)
        )""")
    op.execute("ALTER TABLE fulfilment ADD COLUMN client_id uuid REFERENCES client(client_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE fulfilment DROP COLUMN client_id")
    op.execute("DROP TABLE client_alias")
    op.execute("DROP TABLE client")
    for col in ("payment_terms", "usual_bond_status", "usual_stock_location", "default_currency"):
        op.execute(f"ALTER TABLE supplier DROP COLUMN {col}")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN duplicated_from")
    op.execute("ALTER TABLE inbound_offer DROP CONSTRAINT inbound_offer_discard_attributed")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN discarded_by")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN discarded_at")
