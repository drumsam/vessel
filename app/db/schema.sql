-- UK Fine Wine Deal Pricer — PostgreSQL schema.
-- Standard SQL only. No provider-specific types, no vendor extensions beyond pgcrypto.
-- No AI provider response structure appears anywhere below.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ========================================================= canonical wine table

CREATE TABLE wine (
    wine_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    producer     text NOT NULL,
    cuvee        text NOT NULL,
    region       text,
    colour       text,
    lwin7        text UNIQUE,
    wine_key     text NOT NULL UNIQUE,          -- normalised producer|cuvee
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Controlled aliases. Created by operator correction or by a reviewed AI
-- proposal. Every alias records who approved it — no anonymous aliases.
CREATE TABLE wine_alias (
    alias_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    wine_key     text NOT NULL UNIQUE,
    wine_id      uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    source       text NOT NULL CHECK (source IN ('operator','ai_reviewed','import')),
    approved_by  text NOT NULL,
    approved_at  timestamptz NOT NULL DEFAULT now(),
    note         text
);

-- Pairs that must never collapse. Asserted in tests and enforced at write time.
CREATE TABLE wine_exclusion (
    wine_id_a    uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    wine_id_b    uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    reason       text NOT NULL,
    PRIMARY KEY (wine_id_a, wine_id_b),
    CHECK (wine_id_a <> wine_id_b)
);

-- ================================================================ merchant data

CREATE TABLE merchant (
    merchant_id  text PRIMARY KEY,              -- 'farr', 'bordeaux-index'
    name         text NOT NULL,
    approved     boolean NOT NULL DEFAULT true,
    notes        text
);

CREATE TABLE snapshot (
    snapshot_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at      timestamptz NOT NULL,
    schema_version   text NOT NULL,
    is_demo          boolean NOT NULL DEFAULT false,
    adapters_attempted int NOT NULL DEFAULT 0,
    adapters_succeeded int NOT NULL DEFAULT 0,
    offers_written     int NOT NULL DEFAULT 0,
    offers_rejected    int NOT NULL DEFAULT 0,
    failures           jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE offer (
    offer_pk         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id      uuid NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    offer_id         text NOT NULL,             -- stable within a merchant
    merchant_id      text NOT NULL REFERENCES merchant(merchant_id),

    wine_id          uuid REFERENCES wine(wine_id),   -- NULL => unresolved, never priced
    vintage          int  NOT NULL,                   -- 1000 = NV
    bottle_ml        int  NOT NULL CHECK (bottle_ml > 0),
    pack_size        int  NOT NULL CHECK (pack_size >= 1),

    price            numeric(14,2) NOT NULL,          -- NUMERIC, never float
    currency         char(3) NOT NULL,
    duty_status      text NOT NULL CHECK (duty_status IN ('IB','DP','UNKNOWN')),
    price_kind       text NOT NULL CHECK (price_kind IN ('ASK','BID','LAST_TRADE')),

    is_buyable       boolean NOT NULL,
    offered_units    int,
    is_mixed_lot     boolean NOT NULL DEFAULT false,

    stock_type       text NOT NULL DEFAULT 'UNKNOWN',
    stock_type_basis text NOT NULL DEFAULT 'unknown'
                     CHECK (stock_type_basis IN ('declared','inferred','unknown','unconfirmed')),

    condition_flags  text[] NOT NULL DEFAULT '{}',
    condition_notes  text,                            -- verbatim merchant wording

    source_url       text,
    captured_at      timestamptz NOT NULL,
    raw              jsonb NOT NULL DEFAULT '{}'::jsonb,

    UNIQUE (snapshot_id, merchant_id, offer_id)
);

CREATE INDEX offer_lookup ON offer (wine_id, vintage, bottle_ml, pack_size)
    WHERE duty_status = 'IB' AND price_kind = 'ASK' AND is_buyable;

-- Rejected raw records. Never silently dropped.
CREATE TABLE offer_reject (
    reject_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id  uuid NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
    reason       text NOT NULL,
    detail       text,
    raw          jsonb NOT NULL
);

-- ==================================================================== auction

CREATE TABLE auction_result (
    auction_result_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auction_house     text NOT NULL,
    sale_date         date NOT NULL,
    lot_ref           text,
    wine_id           uuid REFERENCES wine(wine_id),
    vintage           int NOT NULL,
    bottle_ml         int,                        -- NULL = assumed standard, not observed
    pack_size         int,
    hammer            numeric(14,2),
    buyer_paid        numeric(14,2),
    premium_included  boolean NOT NULL,
    premium_rate      numeric(6,4),
    currency          char(3) NOT NULL,
    location          text,
    condition_notes   text,
    raw_composition   text NOT NULL,
    quarantined       boolean NOT NULL DEFAULT false,
    quarantine_reason text,
    source_url        text
);

-- ======================================================== deals and seller lines

CREATE TABLE deal (
    deal_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,
    seller       text,
    source_file  text,
    currency     char(3),                        -- confirmed by the operator on import
    created_by   text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE seller_line (
    line_id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id           uuid NOT NULL REFERENCES deal(deal_id) ON DELETE CASCADE,
    row_index         int NOT NULL,

    raw_description   text NOT NULL,             -- NEVER overwritten
    raw_row           jsonb NOT NULL,            -- the original spreadsheet row

    wine_id           uuid REFERENCES wine(wine_id),
    vintage           int,
    bottle_ml         int,
    pack_size         int,
    quantity          int NOT NULL,

    cost              numeric(14,2),
    cost_currency     char(3),

    target_margin     numeric(6,4),
    manual_price      numeric(14,2),

    UNIQUE (deal_id, row_index)
);

-- ================================================= AI decision audit (provenance)

-- One row per AI-assisted decision. Provider-neutral by construction: the
-- proposal is OUR schema, not the provider's response shape.
CREATE TABLE ai_decision (
    ai_decision_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_id          uuid REFERENCES seller_line(line_id) ON DELETE CASCADE,
    capability       text NOT NULL CHECK (capability IN (
                        'resolve_wine_identity','review_wine_identity',
                        'review_comparables','parse_condition')),
    raw_input        jsonb NOT NULL,
    proposal         jsonb NOT NULL,
    provider         text NOT NULL,              -- 'anthropic' | 'openai' | ...
    model            text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    verifier_result  jsonb,
    final_value      jsonb,
    operator_changed boolean NOT NULL DEFAULT false,
    operator         text
);

-- ============================================================ benchmark results

CREATE TABLE benchmark_run (
    run_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_id      uuid NOT NULL REFERENCES seller_line(line_id) ON DELETE CASCADE,
    snapshot_id  uuid REFERENCES snapshot(snapshot_id),
    computed_at  timestamptz NOT NULL DEFAULT now(),

    uk_floor     numeric(14,2),
    uk_reference numeric(14,2),
    uk_median    numeric(14,2),
    comp_count   int NOT NULL,
    duplicate_listings int NOT NULL DEFAULT 0,
    flags        text[] NOT NULL DEFAULT '{}',
    state        text NOT NULL CHECK (state IN ('READY','REVIEW','NO_MARKET'))
);

-- Which offers were used, and which were not and why. Both are kept.
CREATE TABLE benchmark_comp (
    run_id     uuid NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    offer_pk   uuid NOT NULL REFERENCES offer(offer_pk),
    role       text NOT NULL CHECK (role IN ('comparable','merchant_best','cross_unit','rejected')),
    reject_reason text,
    PRIMARY KEY (run_id, offer_pk, role)
);
