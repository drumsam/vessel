"""VESSEL settles as agency by default: the buyer pays the seller directly,
VESSEL invoices an 8% commission on completed sales, and nothing in the
system may assert VESSEL received funds for an AGENCY mandate.

Decision 0022 — narrows decision 0020, does not replace it. At two to three
deals a year Doug invoices a commission rather than holding buyer funds,
which removes the client-money and two-jurisdiction compliance problem.
`settlement_mode` is a term of the MANDATE (every line under one mandate
settles the same way), never per listing or per line.

`vessel_mandate` is immutable once written (decision 0020's own trigger);
adding a column is DDL, not a row UPDATE, so that trigger is unaffected.

The structural guarantee this migration exists for is on `vessel_payment`,
not a same-table CHECK: Postgres CHECK constraints are single-table, and
"a MATCHED payment exists for a reservation under an AGENCY mandate" spans
vessel_payment -> vessel_reservation -> vessel_listing -> vessel_mandate.
A BEFORE INSERT/UPDATE trigger is this schema's own established mechanism
for a cross-table invariant (vessel_forbid_mandate_mutation,
vessel_forbid_price_change_once_approved, vessel_forbid_reference_mutation
all do the same job for their own invariants) — this is a fourth, not a new
pattern. Because vessel_mandate is immutable, the looked-up settlement_mode
can never go stale after the lookup.

Revision ID: 0018_vessel_agency_settlement
Revises: 0017_vessel_multi_market_ref
Create Date: 2026-10-07
"""
from alembic import op

revision = "0018_vessel_agency_settlement"
down_revision = "0017_vessel_multi_market_ref"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE vessel_mandate ADD COLUMN settlement_mode text NOT NULL DEFAULT 'AGENCY';
ALTER TABLE vessel_mandate ADD CONSTRAINT vessel_mandate_settlement_mode_known CHECK (
    settlement_mode IN ('AGENCY','PRINCIPAL'));

-- Who confirmed receipt, and when -- never a boolean (decision 0022). Both
-- or neither: a reservation is not "half confirmed".
ALTER TABLE vessel_reservation ADD COLUMN seller_confirmed_at timestamptz;
ALTER TABLE vessel_reservation ADD COLUMN seller_confirmed_by text;
ALTER TABLE vessel_reservation ADD CONSTRAINT vessel_reservation_seller_confirmation_complete
    CHECK ((seller_confirmed_at IS NULL) = (seller_confirmed_by IS NULL));

CREATE OR REPLACE FUNCTION vessel_forbid_payment_match_for_agency() RETURNS trigger AS $$
DECLARE
    mode text;
BEGIN
    IF NEW.matched_reservation_id IS NOT NULL THEN
        SELECT m.settlement_mode INTO mode
          FROM vessel_reservation r
          JOIN vessel_listing l ON l.listing_id = r.listing_id
          JOIN vessel_mandate m ON m.mandate_id = l.mandate_id
         WHERE r.reservation_id = NEW.matched_reservation_id;
        IF mode = 'AGENCY' THEN
            RAISE EXCEPTION
                'reservation % is under an AGENCY mandate: VESSEL never holds funds for it, record the seller''s confirmation instead (confirm_seller_receipt)',
                NEW.matched_reservation_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vessel_payment_forbid_agency_match
    BEFORE INSERT OR UPDATE ON vessel_payment
    FOR EACH ROW EXECUTE FUNCTION vessel_forbid_payment_match_for_agency();
"""

DOWNGRADE = """
DROP TRIGGER vessel_payment_forbid_agency_match ON vessel_payment;
DROP FUNCTION vessel_forbid_payment_match_for_agency;

ALTER TABLE vessel_reservation DROP CONSTRAINT vessel_reservation_seller_confirmation_complete;
ALTER TABLE vessel_reservation DROP COLUMN seller_confirmed_by;
ALTER TABLE vessel_reservation DROP COLUMN seller_confirmed_at;

ALTER TABLE vessel_mandate DROP CONSTRAINT vessel_mandate_settlement_mode_known;
ALTER TABLE vessel_mandate DROP COLUMN settlement_mode;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
