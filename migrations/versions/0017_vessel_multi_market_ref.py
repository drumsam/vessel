"""VESSEL multi-market reference: a listing names its reference market.

Doug, 7 October 2026, from docs/research/hk-vs-uk-market-reference.md (that
file does not exist in the repository — this migration is built from the
headline figures given directly in the request: Hong Kong retail runs a
median 22% above UK In Bond, 9 matched pairs, range -21% to +46%, and the
two named markets UK_IN_BOND and HK_RETAIL. No HK-specific single-source
sanity check exists the way app/market/vintage_band.py exists for UK In
Bond, so a HK_RETAIL reference with only one source is refused rather than
guessed at: see vessel_listing_single_source_needs_band below.

"A listing needs a named reference market, not one implicit one": every
vessel_listing row before this migration was, in fact, priced from the UK
benchmark, so the backfill names that market explicitly rather than leaving
it inferred. `vessel_reference` is append-only (mirrors vessel_mandate's own
immutability trigger) — a market's price changing is a new captured row,
never an edit to one a listing may already point to.

Revision ID: 0017_vessel_multi_market_ref
Revises: 0016_vessel_private_sale
Create Date: 2026-10-07
"""
from alembic import op

revision = "0017_vessel_multi_market_ref"
down_revision = "0016_vessel_private_sale"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE vessel_reference (
    reference_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_id         uuid NOT NULL REFERENCES seller_line(line_id),
    market          text NOT NULL CHECK (market IN ('UK_IN_BOND','HK_RETAIL')),
    reference_price numeric(14,2) NOT NULL CHECK (reference_price > 0),
    currency        char(3) NOT NULL CHECK (currency IN ('HKD','GBP')),
    source_count    int NOT NULL CHECK (source_count >= 1),
    evidence        jsonb NOT NULL DEFAULT '[]'::jsonb,
    captured_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX vessel_reference_line_market
    ON vessel_reference (line_id, market, captured_at DESC);

CREATE OR REPLACE FUNCTION vessel_forbid_reference_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'vessel_reference is append-only: a changed price is a new captured row, never an edit (reference_id %)',
        COALESCE(OLD.reference_id, NEW.reference_id);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vessel_reference_no_update
    BEFORE UPDATE OR DELETE ON vessel_reference
    FOR EACH ROW EXECUTE FUNCTION vessel_forbid_reference_mutation();

ALTER TABLE vessel_listing ADD COLUMN reference_market text;
UPDATE vessel_listing SET reference_market = 'UK_IN_BOND' WHERE reference_market IS NULL;
ALTER TABLE vessel_listing ALTER COLUMN reference_market SET NOT NULL;
ALTER TABLE vessel_listing ADD CONSTRAINT vessel_listing_reference_market_known
    CHECK (reference_market IN ('UK_IN_BOND','HK_RETAIL'));

ALTER TABLE vessel_listing ADD COLUMN reference_id uuid REFERENCES vessel_reference(reference_id);

ALTER TABLE vessel_listing DROP CONSTRAINT vessel_listing_single_source_needs_band;
ALTER TABLE vessel_listing ADD CONSTRAINT vessel_listing_single_source_needs_band CHECK (
    source_count >= 2 OR (reference_market = 'UK_IN_BOND' AND vintage_band_passed));

CREATE OR REPLACE FUNCTION vessel_forbid_price_change_once_approved() RETURNS trigger AS $$
BEGIN
    IF OLD.mandate_id IS NOT NULL AND (
        NEW.market_reference IS DISTINCT FROM OLD.market_reference OR
        NEW.band             IS DISTINCT FROM OLD.band OR
        NEW.discount_applied IS DISTINCT FROM OLD.discount_applied OR
        NEW.vessel_price     IS DISTINCT FROM OLD.vessel_price OR
        NEW.seller_net       IS DISTINCT FROM OLD.seller_net OR
        NEW.currency         IS DISTINCT FROM OLD.currency OR
        NEW.source_count     IS DISTINCT FROM OLD.source_count OR
        NEW.percentage_claim_pct IS DISTINCT FROM OLD.percentage_claim_pct OR
        NEW.display_producer IS DISTINCT FROM OLD.display_producer OR
        NEW.display_wine     IS DISTINCT FROM OLD.display_wine OR
        NEW.vintage          IS DISTINCT FROM OLD.vintage OR
        NEW.bottles          IS DISTINCT FROM OLD.bottles OR
        NEW.mandate_id       IS DISTINCT FROM OLD.mandate_id OR
        NEW.reference_market IS DISTINCT FROM OLD.reference_market OR
        NEW.reference_id     IS DISTINCT FROM OLD.reference_id
    ) THEN
        RAISE EXCEPTION
            'listing % is approved: price and identity are frozen (decision 0020)',
            OLD.listing_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

DOWNGRADE = """
CREATE OR REPLACE FUNCTION vessel_forbid_price_change_once_approved() RETURNS trigger AS $$
BEGIN
    IF OLD.mandate_id IS NOT NULL AND (
        NEW.market_reference IS DISTINCT FROM OLD.market_reference OR
        NEW.band             IS DISTINCT FROM OLD.band OR
        NEW.discount_applied IS DISTINCT FROM OLD.discount_applied OR
        NEW.vessel_price     IS DISTINCT FROM OLD.vessel_price OR
        NEW.seller_net       IS DISTINCT FROM OLD.seller_net OR
        NEW.currency         IS DISTINCT FROM OLD.currency OR
        NEW.source_count     IS DISTINCT FROM OLD.source_count OR
        NEW.percentage_claim_pct IS DISTINCT FROM OLD.percentage_claim_pct OR
        NEW.display_producer IS DISTINCT FROM OLD.display_producer OR
        NEW.display_wine     IS DISTINCT FROM OLD.display_wine OR
        NEW.vintage          IS DISTINCT FROM OLD.vintage OR
        NEW.bottles          IS DISTINCT FROM OLD.bottles OR
        NEW.mandate_id       IS DISTINCT FROM OLD.mandate_id
    ) THEN
        RAISE EXCEPTION
            'listing % is approved: price and identity are frozen (decision 0020)',
            OLD.listing_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER TABLE vessel_listing DROP CONSTRAINT vessel_listing_single_source_needs_band;
ALTER TABLE vessel_listing ADD CONSTRAINT vessel_listing_single_source_needs_band CHECK (
    source_count >= 2 OR vintage_band_passed);

ALTER TABLE vessel_listing DROP COLUMN reference_id;
ALTER TABLE vessel_listing DROP CONSTRAINT vessel_listing_reference_market_known;
ALTER TABLE vessel_listing DROP COLUMN reference_market;

DROP TRIGGER vessel_reference_no_update ON vessel_reference;
DROP FUNCTION vessel_forbid_reference_mutation;
DROP TABLE vessel_reference;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
