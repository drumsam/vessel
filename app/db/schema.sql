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
-- Stored once, lower id first, so a pair cannot exist in both orders.
CREATE TABLE wine_exclusion (
    wine_id_a    uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    wine_id_b    uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    reason       text NOT NULL,
    PRIMARY KEY (wine_id_a, wine_id_b),
    CONSTRAINT wine_exclusion_check CHECK (wine_id_a < wine_id_b)
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

-- One row per merchant attempted in a snapshot: what was searched, when, and
-- whether it worked. A benchmark resolves, per merchant, the latest successful
-- capture whose scope covers the line (decision 0004).
-- NULL scope = the merchant's whole offer book. A targeted search (Bordeaux
-- Index: producer + vintage) covers only that producer and vintage.
CREATE TABLE snapshot_merchant (
    snapshot_id        uuid NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    merchant_id        text NOT NULL REFERENCES merchant(merchant_id),
    status             text NOT NULL CHECK (status IN ('ok','failed')),
    captured_at        timestamptz NOT NULL,
    scope_producer_key text,                     -- normalised producer, as in wine_key
    scope_vintage      int,
    scope_params       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- merchant search terms as sent
    offers_written     int NOT NULL DEFAULT 0,
    offers_rejected    int NOT NULL DEFAULT 0,
    error              text,
    PRIMARY KEY (snapshot_id, merchant_id),
    CONSTRAINT snapshot_merchant_scope CHECK ((scope_producer_key IS NULL) = (scope_vintage IS NULL)),
    CONSTRAINT snapshot_merchant_error CHECK ((status = 'failed') = (error IS NOT NULL))
);

CREATE INDEX snapshot_merchant_latest ON snapshot_merchant (merchant_id, captured_at)
    WHERE status = 'ok';

CREATE TABLE offer (
    offer_pk         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id      uuid NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    offer_id         text NOT NULL,             -- stable within a merchant
    merchant_id      text NOT NULL REFERENCES merchant(merchant_id),

    wine_id          uuid NOT NULL REFERENCES wine(wine_id),  -- unresolved => offer_reject
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

    stock_type       text NOT NULL DEFAULT 'UNKNOWN'
                     CHECK (stock_type IN ('MERCHANT_STOCK','CLIENT_STOCK','BROKERED',
                                           'MARKETPLACE','UNKNOWN')),
    stock_type_basis text NOT NULL DEFAULT 'unknown'
                     CHECK (stock_type_basis IN ('declared','inferred','unknown','unconfirmed')),

    condition_flags  text[] NOT NULL DEFAULT '{}'
                     CHECK (condition_flags <@ ARRAY['ORIGINAL_CASE','REPACK',
                            'NO_ORIGINAL_CASE','NON_PRISTINE','LABEL_DAMAGE','LEVEL_ISSUE',
                            'LEVEL_NOTED','CAPSULE_OR_CORK','SIGNS_OF_SEEPAGE']::text[]),
    condition_notes  text,                            -- verbatim merchant wording

    source_url       text,
    captured_at      timestamptz NOT NULL,
    raw              jsonb NOT NULL DEFAULT '{}'::jsonb,

    UNIQUE (snapshot_id, merchant_id, offer_id)
);

CREATE INDEX offer_lookup ON offer (wine_id, vintage, bottle_ml, pack_size)
    WHERE duty_status = 'IB' AND price_kind = 'ASK' AND is_buyable;

-- Rejected raw records. Never silently dropped. The ONE home for unresolved
-- identity (reason UNRESOLVED_IDENTITY): `raw` keeps the merchant record and the
-- names identity resolution was given, so it can be re-resolved from raw once an
-- alias is approved.
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

    -- Who approved the identity, how, and when. All four are set together.
    wine_id_source      text CHECK (wine_id_source IN ('lwin','alias','operator','ai_reviewed')),
    wine_id_approved_by text,
    wine_id_approved_at timestamptz,

    -- Line flags set upstream of the benchmark and carried into it (decision 0005).
    flags             text[] NOT NULL DEFAULT '{}'
                      CHECK (flags <@ ARRAY['NAME_REVIEW','FORMAT_REVIEW',
                                            'DERIVED_FROM_CASE']::text[]),

    UNIQUE (deal_id, row_index),
    CONSTRAINT seller_line_identity_approved CHECK (
        (wine_id IS NULL AND wine_id_source IS NULL
         AND wine_id_approved_by IS NULL AND wine_id_approved_at IS NULL)
     OR (wine_id IS NOT NULL AND wine_id_source IS NOT NULL
         AND wine_id_approved_by IS NOT NULL AND wine_id_approved_at IS NOT NULL))
);

-- Every identity or line-flag change, old and new, by whom, when, and how.
-- Repeated operator corrections of the same seller wording are alias candidates.
CREATE TABLE seller_line_identity_history (
    history_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_id         uuid NOT NULL REFERENCES seller_line(line_id) ON DELETE CASCADE,
    prev_wine_id    uuid REFERENCES wine(wine_id),
    prev_vintage    int,
    prev_bottle_ml  int,
    prev_pack_size  int,
    prev_flags      text[] NOT NULL,
    new_wine_id     uuid NOT NULL REFERENCES wine(wine_id),
    new_vintage     int NOT NULL,
    new_bottle_ml   int NOT NULL,
    new_pack_size   int NOT NULL,
    new_flags       text[] NOT NULL,
    source          text NOT NULL CHECK (source IN ('lwin','alias','operator','ai_reviewed')),
    changed_by      text NOT NULL,
    changed_at      timestamptz NOT NULL DEFAULT now()
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

-- A run is self-contained: after the snapshots it read are pruned, its figures,
-- its sources and every offer it saw are still here (decision 0004).
CREATE TABLE benchmark_run (
    run_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_id      uuid NOT NULL REFERENCES seller_line(line_id) ON DELETE CASCADE,
    as_of        timestamptz NOT NULL,           -- freshness is measured against this
    computed_at  timestamptz NOT NULL DEFAULT now(),

    uk_floor     numeric(14,2),
    uk_reference numeric(14,2),
    uk_median    numeric(14,2),
    comp_count   int NOT NULL,
    duplicate_listings int NOT NULL DEFAULT 0,
    flags        text[] NOT NULL DEFAULT '{}',
    state        text NOT NULL CHECK (state IN ('READY','REVIEW','NO_MARKET')),
    oldest_comp_age interval                     -- as_of minus the oldest merchant-best's capture
);

-- The capture each merchant contributed, one per merchant. snapshot_id goes
-- NULL when the snapshot is pruned; merchant and captured_at stay.
CREATE TABLE benchmark_run_snapshot (
    run_id       uuid NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
    snapshot_id  uuid REFERENCES snapshot(snapshot_id) ON DELETE SET NULL,
    captured_at  timestamptz NOT NULL,
    PRIMARY KEY (run_id, merchant_id)
);

-- Which offers were used, and which were not and why. Both are kept.
-- offer_snapshot is the offer exactly as the benchmark saw it; offer_pk goes
-- NULL when the snapshot it came from is pruned. Money in it is a string.
CREATE TABLE benchmark_comp (
    comp_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         uuid NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    offer_pk       uuid REFERENCES offer(offer_pk) ON DELETE SET NULL,
    role           text NOT NULL CHECK (role IN ('comparable','merchant_best','cross_unit','rejected')),
    reject_reason  text,
    offer_snapshot jsonb NOT NULL,
    UNIQUE (run_id, offer_pk, role),
    CONSTRAINT benchmark_comp_reason CHECK ((role = 'rejected') = (reject_reason IS NOT NULL))
);

-- ================================================================ pricing

-- The figures as they stood at the moment of pricing. Nothing here is
-- recomputed on read; the benchmark figures are copied, not joined.
-- fx_rate is GBP per ONE unit of cost_currency, as published by fx_source on
-- fx_rate_date. It is a rate, not money, hence not numeric(14,2).
CREATE TABLE pricing_result (
    pricing_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    line_id           uuid NOT NULL REFERENCES seller_line(line_id) ON DELETE CASCADE,
    run_id            uuid NOT NULL REFERENCES benchmark_run(run_id),
    priced_at         timestamptz NOT NULL DEFAULT now(),
    priced_by         text NOT NULL,

    uk_floor          numeric(14,2),
    uk_reference      numeric(14,2),
    uk_median         numeric(14,2),
    comp_count        int NOT NULL,
    auction_evidence  jsonb NOT NULL DEFAULT '[]'::jsonb,   -- money as strings

    cost              numeric(14,2),
    cost_currency     char(3),
    fx_rate           numeric(18,8) CHECK (fx_rate > 0),
    fx_rate_date      date,
    fx_source         text,
    cost_gbp          numeric(14,2),

    target_margin     numeric(6,4),
    sell_price        numeric(14,2),
    sell_currency     char(3) NOT NULL DEFAULT 'GBP',
    gp                numeric(14,2),

    flags             text[] NOT NULL DEFAULT '{}',
    state             text NOT NULL CHECK (state IN ('READY','REVIEW','NO_MARKET')),

    CONSTRAINT pricing_result_cost_currency CHECK ((cost IS NULL) = (cost_currency IS NULL)),
    CONSTRAINT pricing_result_fx_recorded CHECK (
        cost IS NULL OR cost_currency = 'GBP'
        OR (fx_rate IS NOT NULL AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL))
);

-- ============================================================= buyer offers

-- The offer as actually issued to a client. Its lines hold the figures as sent,
-- so a sent offer stays reproducible after the market moves. Issued lines pin
-- their seller line and pricing result: a deal with an issued offer cannot be
-- deleted out from under it.
CREATE TABLE buyer_offer (
    buyer_offer_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id        uuid NOT NULL REFERENCES deal(deal_id),
    client         text NOT NULL,
    currency       char(3) NOT NULL,
    issued_at      timestamptz NOT NULL,
    issued_by      text NOT NULL,
    terms          text
);

CREATE TABLE buyer_offer_line (
    buyer_offer_id  uuid NOT NULL REFERENCES buyer_offer(buyer_offer_id) ON DELETE CASCADE,
    line_no         int NOT NULL,
    line_id         uuid NOT NULL REFERENCES seller_line(line_id),
    pricing_id      uuid NOT NULL REFERENCES pricing_result(pricing_id),
    description     text NOT NULL,               -- exactly as printed for the client
    vintage         int NOT NULL,
    bottle_ml       int NOT NULL,
    pack_size       int NOT NULL,
    quantity        int NOT NULL CHECK (quantity > 0),
    unit_price      numeric(14,2) NOT NULL CHECK (unit_price > 0),
    line_total      numeric(14,2) NOT NULL,
    condition_notes text,
    PRIMARY KEY (buyer_offer_id, line_no),
    CONSTRAINT buyer_offer_line_total CHECK (line_total = unit_price * quantity)
);
