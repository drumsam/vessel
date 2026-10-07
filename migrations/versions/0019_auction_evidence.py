"""Operator-entered auction evidence: Bonhams, Christie's, Heritage, Zachys.

Decision 0024. Spec: docs/research/auction-evidence-form-spec.md, corrected
on the same two points this session already corrected elsewhere: uuid, not
bigserial (every other table in this schema is uuid — decision 0020 already
made this exact fix for seller_offer); and entered_by/retracted_by are
operator_id, from the session, never a caller-supplied name (invariant 14,
decision 0009) — the spec said `text`, written before an operator session
existed to source it from.

Auction evidence is a health check, never a price. It lives in its own
table, is read by its own module (app/auction/), and the benchmark module
never imports it — test_auction_evidence_never_reaches_benchmark proves
that statically, not by convention.

The closed house list widens the spec's original two (BONHAMS, CHRISTIES)
to four: HERITAGE and ZACHYS are added on Doug's explicit instruction,
7 October 2026, over the terms audit's own finding that both houses
restrict use to personal/non-commercial — said out loud, not done quietly
(decision 0024). This stays hand-entry only, never a scraper: nothing here
automates collection from any of the four houses' sites.

Revision ID: 0019_auction_evidence
Revises: 0018_vessel_agency_settlement
Create Date: 2026-10-07
"""
from alembic import op

revision = "0019_auction_evidence"
down_revision = "0018_vessel_agency_settlement"
branch_labels = None
depends_on = None

SCHEMA = """
CREATE TABLE auction_evidence (
    auction_evidence_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    wine_id              uuid        NOT NULL REFERENCES wine(wine_id),
    vintage              integer     NOT NULL,
    bottle_ml            integer     NOT NULL CHECK (bottle_ml > 0),
    bottles_in_lot        integer    NOT NULL CHECK (bottles_in_lot > 0),

    auction_house        text        NOT NULL,
    sale_date            date        NOT NULL,
    lot_ref              text        NOT NULL,
    source_url           text        NOT NULL CHECK (source_url ~ '^https://'),

    currency             char(3)     NOT NULL,
    amount                numeric(14,2) NOT NULL CHECK (amount > 0),
    amount_basis         text        NOT NULL CHECK (amount_basis IN ('HAMMER','BUYER_PREMIUM_INCLUSIVE')),
    premium_rate         numeric(6,4) NULL,
    hammer_gbp           numeric(14,2) NULL,            -- computed server-side, never typed
    fx_rate              numeric(12,6) NULL,
    fx_source            text        NULL,

    is_mixed_lot          boolean    NOT NULL DEFAULT false,
    condition_notes       text       NULL,              -- operator's own words, not catalogue prose
    condition_flagged     boolean    NOT NULL DEFAULT false,
    quarantined           boolean    NOT NULL GENERATED ALWAYS AS
                             (is_mixed_lot OR condition_flagged) STORED,

    entered_by            uuid       NOT NULL REFERENCES operator(operator_id),
    entered_at            timestamptz NOT NULL DEFAULT now(),
    retracted_at           timestamptz NULL,
    retracted_by           uuid       REFERENCES operator(operator_id),
    retraction_reason      text       NULL,

    CONSTRAINT auction_evidence_house_known CHECK (
        auction_house IN ('BONHAMS','CHRISTIES','HERITAGE','ZACHYS')),
    CONSTRAINT auction_evidence_inclusive_needs_rate CHECK (
        amount_basis = 'HAMMER' OR premium_rate IS NOT NULL),
    CONSTRAINT auction_evidence_sale_not_future CHECK (
        sale_date <= (entered_at AT TIME ZONE 'UTC')::date),
    CONSTRAINT auction_evidence_retraction_complete CHECK (
        (retracted_at IS NULL AND retracted_by IS NULL AND retraction_reason IS NULL) OR
        (retracted_at IS NOT NULL AND retracted_by IS NOT NULL AND retraction_reason IS NOT NULL))
);

CREATE INDEX auction_evidence_wine
    ON auction_evidence (wine_id, vintage, bottle_ml, sale_date DESC);

-- Rows are never updated except to set the three retraction columns
-- together, once. A mistake is retracted, with a reason, and re-entered —
-- never edited in place, same discipline as every other audit trail in
-- this schema.
CREATE OR REPLACE FUNCTION auction_evidence_forbid_mutation() RETURNS trigger AS $$
BEGIN
    IF OLD.retracted_at IS NOT NULL THEN
        RAISE EXCEPTION
            'auction_evidence % is already retracted; it cannot be changed again',
            OLD.auction_evidence_id;
    END IF;
    IF NEW.wine_id          IS DISTINCT FROM OLD.wine_id OR
       NEW.vintage          IS DISTINCT FROM OLD.vintage OR
       NEW.bottle_ml        IS DISTINCT FROM OLD.bottle_ml OR
       NEW.bottles_in_lot   IS DISTINCT FROM OLD.bottles_in_lot OR
       NEW.auction_house    IS DISTINCT FROM OLD.auction_house OR
       NEW.sale_date        IS DISTINCT FROM OLD.sale_date OR
       NEW.lot_ref          IS DISTINCT FROM OLD.lot_ref OR
       NEW.source_url       IS DISTINCT FROM OLD.source_url OR
       NEW.currency         IS DISTINCT FROM OLD.currency OR
       NEW.amount           IS DISTINCT FROM OLD.amount OR
       NEW.amount_basis     IS DISTINCT FROM OLD.amount_basis OR
       NEW.premium_rate     IS DISTINCT FROM OLD.premium_rate OR
       NEW.hammer_gbp       IS DISTINCT FROM OLD.hammer_gbp OR
       NEW.entered_by       IS DISTINCT FROM OLD.entered_by OR
       NEW.entered_at       IS DISTINCT FROM OLD.entered_at THEN
        RAISE EXCEPTION
            'auction_evidence % is immutable except for retraction (auction_evidence_id %)',
            OLD.auction_evidence_id, OLD.auction_evidence_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER auction_evidence_no_mutation
    BEFORE UPDATE ON auction_evidence
    FOR EACH ROW EXECUTE FUNCTION auction_evidence_forbid_mutation();
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP TRIGGER auction_evidence_no_mutation ON auction_evidence")
    op.execute("DROP FUNCTION auction_evidence_forbid_mutation")
    op.execute("DROP TABLE auction_evidence")
