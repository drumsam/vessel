"""VESSEL Private Sale, drop one: mandate, listing, drop, reservation, payment, event.

Decision 0020. VESSEL buys nothing: it lists a seller's own wine under a
time-boxed mandate, sets the price, and takes a fee when it sells. A
different business from buyer_offer/seller_offer (direct purchase and
resale), and shares no table with either.

Revision ID: 0016_vessel_private_sale
Revises: 0015_release_code_identity
Create Date: 2026-10-07
"""
from alembic import op

revision = "0016_vessel_private_sale"
down_revision = "0015_release_code_identity"
branch_labels = None
depends_on = None

SCHEMA = """
CREATE TABLE vessel_mandate (
    mandate_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id          uuid NOT NULL REFERENCES deal(deal_id),
    mandate_text     text NOT NULL,
    window_days      int  NOT NULL DEFAULT 30 CHECK (window_days > 0),
    approved_by_name text NOT NULL CHECK (approved_by_name <> ''),
    approved_at      timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION vessel_forbid_mandate_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'vessel_mandate is immutable once written (mandate_id %)',
        COALESCE(OLD.mandate_id, NEW.mandate_id);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vessel_mandate_no_update
    BEFORE UPDATE OR DELETE ON vessel_mandate
    FOR EACH ROW EXECUTE FUNCTION vessel_forbid_mandate_mutation();

CREATE TABLE vessel_drop (
    drop_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label        text NOT NULL,
    drop_date    date NOT NULL,
    created_by   uuid NOT NULL REFERENCES operator(operator_id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE vessel_listing (
    listing_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id           uuid NOT NULL REFERENCES deal(deal_id),
    line_id           uuid NOT NULL UNIQUE REFERENCES seller_line(line_id),
    run_id            uuid REFERENCES benchmark_run(run_id),
    mandate_id        uuid REFERENCES vessel_mandate(mandate_id),
    drop_id           uuid REFERENCES vessel_drop(drop_id),

    state             text NOT NULL CHECK (state IN
                          ('RECOMMENDED','DECLINED','APPROVED','LISTED',
                           'RESERVED','PAID','TRANSFERRING','SETTLED')),

    display_producer  text NOT NULL,
    display_wine      text NOT NULL,
    vintage           int  NOT NULL,
    release_code      text,
    bottle_ml         int  NOT NULL CHECK (bottle_ml > 0),
    bottles           int  NOT NULL CHECK (bottles > 0),
    stock_location    text NOT NULL CHECK (stock_location IN
                          ('HK_BOND','UK_BOND','EU_BOND','DUTY_PAID_HK','OTHER')),
    warehouse         text,
    condition_notes   text,
    provenance_notes  text,

    -- fx_hkd_per_gbp is named for its direction on purpose: a bare
    -- "fx_rate" is exactly how a 100x conversion error happens unnoticed.
    currency          char(3) NOT NULL CHECK (currency IN ('HKD','GBP')),
    fx_hkd_per_gbp    numeric(18,8) CHECK (fx_hkd_per_gbp > 0),
    fx_source         text,
    fx_rate_date      date,
    CONSTRAINT vessel_listing_fx_recorded CHECK (
        currency = 'GBP' OR
        (fx_hkd_per_gbp IS NOT NULL AND fx_source IS NOT NULL AND fx_rate_date IS NOT NULL)),

    market_reference  numeric(14,2) NOT NULL CHECK (market_reference > 0),
    band              text NOT NULL CHECK (band IN ('STRONG','NORMAL','CLEARANCE')),
    discount_applied  numeric(5,4) NOT NULL,
    CONSTRAINT vessel_listing_discount_in_band CHECK (
        (band = 'STRONG'     AND discount_applied >= 0.10 AND discount_applied < 0.15) OR
        (band = 'NORMAL'     AND discount_applied >= 0.15 AND discount_applied < 0.20) OR
        (band = 'CLEARANCE'  AND discount_applied >= 0.20)),
    vessel_price      numeric(14,2) NOT NULL CHECK (vessel_price > 0),
    seller_net        numeric(14,2) NOT NULL CHECK (seller_net > 0),

    source_count         int NOT NULL CHECK (source_count >= 1),
    vintage_band_passed   boolean NOT NULL DEFAULT false,
    derived               boolean NOT NULL DEFAULT false,
    percentage_claim_pct  numeric(5,4),
    CONSTRAINT vessel_listing_single_source_needs_band CHECK (
        source_count >= 2 OR vintage_band_passed),
    CONSTRAINT vessel_listing_claim_needs_two_sources CHECK (
        percentage_claim_pct IS NULL OR source_count >= 2),

    held_back    boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    approved_at  timestamptz,
    listed_at    timestamptz,
    settled_at   timestamptz,

    CONSTRAINT vessel_listing_mandate_matches_state CHECK (
        (state IN ('RECOMMENDED','DECLINED') AND mandate_id IS NULL) OR
        (state NOT IN ('RECOMMENDED','DECLINED') AND mandate_id IS NOT NULL)),
    CONSTRAINT vessel_listing_drop_matches_state CHECK (
        (state IN ('RECOMMENDED','DECLINED','APPROVED') AND drop_id IS NULL) OR
        (state NOT IN ('RECOMMENDED','DECLINED','APPROVED') AND drop_id IS NOT NULL))
);

CREATE INDEX vessel_listing_drop ON vessel_listing (drop_id) WHERE drop_id IS NOT NULL;
CREATE INDEX vessel_listing_mandate ON vessel_listing (mandate_id) WHERE mandate_id IS NOT NULL;

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

CREATE TRIGGER vessel_listing_price_frozen
    BEFORE UPDATE ON vessel_listing
    FOR EACH ROW EXECUTE FUNCTION vessel_forbid_price_change_once_approved();

CREATE TABLE vessel_reservation (
    reservation_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id         uuid NOT NULL REFERENCES vessel_listing(listing_id),
    state              text NOT NULL CHECK (state IN ('HELD','EXPIRED','FULFILLED','CANCELLED')),
    payment_reference  text NOT NULL UNIQUE,
    buyer_contact       text NOT NULL CHECK (buyer_contact <> ''),
    held_at             timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    proof_submitted_at  timestamptz,
    fulfilled_at        timestamptz,
    cancelled_at        timestamptz
);

CREATE UNIQUE INDEX vessel_one_live_reservation_per_listing
    ON vessel_reservation (listing_id) WHERE state = 'HELD';

CREATE TABLE vessel_payment (
    payment_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reference               text NOT NULL,
    amount                  numeric(14,2) NOT NULL CHECK (amount > 0),
    currency                char(3) NOT NULL CHECK (currency IN ('HKD','GBP')),
    received_at             timestamptz NOT NULL,
    matched_reservation_id  uuid REFERENCES vessel_reservation(reservation_id),
    state                   text NOT NULL CHECK (state IN ('MATCHED','UNMATCHED')),
    created_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vessel_payment_match_matches_state CHECK (
        (state = 'MATCHED' AND matched_reservation_id IS NOT NULL) OR
        (state = 'UNMATCHED' AND matched_reservation_id IS NULL))
);

CREATE INDEX vessel_payment_unmatched ON vessel_payment (reference) WHERE state = 'UNMATCHED';

CREATE TABLE vessel_event (
    event_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id    uuid NOT NULL REFERENCES vessel_listing(listing_id),
    event_type    text NOT NULL CHECK (event_type IN ('VIEWED','BOUGHT','DECLINED_AFTER_VIEWING')),
    buyer_contact text,
    occurred_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX vessel_event_listing ON vessel_event (listing_id, occurred_at);

CREATE TABLE vessel_exclusion (
    deal_id    uuid NOT NULL REFERENCES deal(deal_id),
    line_id    uuid NOT NULL REFERENCES seller_line(line_id),
    reason     text NOT NULL CHECK (reason IN
                   ('NO_MARKET','THIN_EVIDENCE','BELOW_MINIMUM_VALUE',
                    'IDENTITY_PENDING','BETTER_HELD')),
    detail     text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (deal_id, line_id)
);
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP TABLE vessel_exclusion")
    op.execute("DROP TABLE vessel_event")
    op.execute("DROP TABLE vessel_payment")
    op.execute("DROP TABLE vessel_reservation")
    op.execute("DROP TRIGGER vessel_listing_price_frozen ON vessel_listing")
    op.execute("DROP FUNCTION vessel_forbid_price_change_once_approved")
    op.execute("DROP TABLE vessel_listing")
    op.execute("DROP TABLE vessel_drop")
    op.execute("DROP TRIGGER vessel_mandate_no_update ON vessel_mandate")
    op.execute("DROP FUNCTION vessel_forbid_mandate_mutation")
    op.execute("DROP TABLE vessel_mandate")
