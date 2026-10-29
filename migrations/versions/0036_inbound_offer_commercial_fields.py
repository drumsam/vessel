"""inbound_offer confirmed commercial fields -- Doug's own correction to
the CANDIDATE screen, 29 October 2026.

Reverses the blanket "never prefill" reading of the earlier bottle_ml/
pack_size fix: the real rule is stated-versus-silent, not prefill-
versus-blank. A field the source stated gets confirmed as read; a field
it was silent on is the operator's own assertion. That distinction only
means something if these facts are actually persisted once confirmed --
previously only identity (wine_id/vintage/bottle_ml/pack_size) was.

`confirmed_quantity` is the commercial UNIT count (decision-consistent
with every other `quantity` column in this app: units as pack_size
defines them, never bottles) -- the fork between "one case of six" and
"six loose bottles" is resolved into a real (pack_size, quantity) pair
here, by the operator, never guessed.

`confirmed_asking_price`/`_currency`/`_basis` exist because
InboundOfferProposal carried a price with no unit: "GBP420" without
knowing per-bottle, per-case or total is ambiguous by exactly the
multiple pack_size would convert by. `confirmed_asking_basis` has no
default and is nullable only because a line with no price at all has
nothing to confirm -- `app/api/inbound.py` blocks confirmation on a
null basis whenever the line is more than one bottle AND a price exists,
never confirmed_asking_price absence by itself.

Revision ID: 0036_confirmed_commercial
Revises: 0035_supplier
Create Date: 2026-10-29
"""
from alembic import op

revision = "0036_confirmed_commercial"
down_revision = "0035_supplier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE inbound_offer ADD COLUMN confirmed_quantity integer")
    op.execute("ALTER TABLE inbound_offer ADD COLUMN confirmed_packaging text")
    op.execute("ALTER TABLE inbound_offer ADD COLUMN confirmed_bond_status text")
    op.execute("ALTER TABLE inbound_offer ADD COLUMN confirmed_stock_location text")
    op.execute("ALTER TABLE inbound_offer ADD COLUMN confirmed_asking_price numeric(14,2)")
    op.execute("ALTER TABLE inbound_offer ADD COLUMN confirmed_asking_currency char(3)")
    op.execute("""
        ALTER TABLE inbound_offer ADD COLUMN confirmed_asking_basis text
            CHECK (confirmed_asking_basis IN ('per_bottle', 'per_case', 'total'))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE inbound_offer DROP COLUMN confirmed_asking_basis")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN confirmed_asking_currency")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN confirmed_asking_price")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN confirmed_stock_location")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN confirmed_bond_status")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN confirmed_packaging")
    op.execute("ALTER TABLE inbound_offer DROP COLUMN confirmed_quantity")
