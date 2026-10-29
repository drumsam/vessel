"""supplier, supplier_alias, inbound_offer.supplier_id -- decision pending
(supplier-attribution-spec.md), a prerequisite for build brief Phase 1b
step 6, not an enhancement: CONFIRM renders "Seller: Y" and there was no
counterparty entity in the schema at all, and `deal.seller` is free text
-- fine for one cellar typed once, wrong for 8-10 recurring suppliers.

`supplier_id` is nullable on `inbound_offer` itself -- capture must never
be blocked, the raw record is sacred and written before anything else
happens -- but `POST /inbound-offers/{id}/confirm-identity` refuses
without one, exactly as it already refuses a want-list wine without
`want_list_ack`: same enforcement point, same shape, same reason, the
cheap moment to capture this is now and it can never be recovered later.

`supplier_alias.alias` is stored already normalised via `norm()`
(`identity/resolver.py`, the same normaliser the wine register uses) so
matching a pasted message is a plain substring check against the
normalised raw text, never a reimplementation.

Revision ID: 0035_supplier
Revises: 0034_inbound_offer
Create Date: 2026-10-29
"""
from alembic import op

revision = "0035_supplier"
down_revision = "0034_inbound_offer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE supplier (
            supplier_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name         text NOT NULL UNIQUE,
            contact_name text,
            phone        text,
            email        text,
            notes        text,
            active       boolean NOT NULL DEFAULT true,
            created_by   uuid NOT NULL REFERENCES operator(operator_id),
            created_at   timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE supplier_alias (
            supplier_id  uuid NOT NULL REFERENCES supplier(supplier_id),
            alias        text NOT NULL,
            PRIMARY KEY (supplier_id, alias)
        )
    """)
    op.execute("ALTER TABLE inbound_offer ADD COLUMN supplier_id uuid REFERENCES supplier(supplier_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE inbound_offer DROP COLUMN supplier_id")
    op.execute("DROP TABLE supplier_alias")
    op.execute("DROP TABLE supplier")
