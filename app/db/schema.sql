-- UK Fine Wine Deal Pricer — PostgreSQL schema.
-- Standard SQL only. No provider-specific types, no vendor extensions beyond pgcrypto.
-- No AI provider response structure appears anywhere below.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ==================================================================== people

-- Who may use the system, and who every audit row points at. Access is revoked
-- by clearing `active`, never by deleting the row: the history has to keep
-- pointing somewhere. Audit columns hold operator_id, not a copied name, so
-- renaming someone does not rewrite the past. Password hashing is argon2id, by
-- a maintained library; the hash string carries its own parameters.
CREATE TABLE operator (
    operator_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username      text NOT NULL UNIQUE,
    display_name  text NOT NULL,
    password_hash text NOT NULL,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    note          text
);

-- Server-side sessions: the cookie carries a random token and nothing else, and
-- only its hash is stored. Revoking an operator or a session takes effect on
-- the next request.
CREATE TABLE operator_session (
    session_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id uuid NOT NULL REFERENCES operator(operator_id),
    token_hash  text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz
);

CREATE INDEX operator_session_operator ON operator_session (operator_id);

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
--
-- A producer-only alias (no cuvee: the key ends in '|') catches every listing a
-- merchant prints under that producer alone. Farr prints both "Veuve Clicquot"
-- and "Veuve Clicquot Rosé", so a careless one attaches the Rosé to the Brut.
-- They are operator-only, never an AI proposal, and marked so they can be
-- audited as a set.
CREATE TABLE wine_alias (
    alias_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    wine_key     text NOT NULL UNIQUE,
    wine_id      uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    source       text NOT NULL CHECK (source IN ('operator','ai_reviewed','import')),
    approved_by  uuid NOT NULL REFERENCES operator(operator_id),
    approved_at  timestamptz NOT NULL DEFAULT now(),
    note         text,
    is_producer_only boolean NOT NULL
                 GENERATED ALWAYS AS (right(wine_key, 1) = '|') STORED,
    CONSTRAINT wine_alias_producer_only_is_operator CHECK
        (right(wine_key, 1) <> '|' OR source = 'operator')
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

-- An LWIN-7 a merchant used for more than one wine name in one capture. It may
-- be the merchant's mapping error, or our name key wrongly splitting one wine
-- that changed appellation, so an operator decides which (decision 0006).
CREATE TABLE lwin_conflict (
    conflict_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
    lwin7        text NOT NULL,
    names        jsonb NOT NULL,                  -- the merchant's own wording, verbatim
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    resolution   text CHECK (resolution IN ('same_wine','different_wines')),
    resolved_by  uuid REFERENCES operator(operator_id),
    resolved_at  timestamptz,
    note         text,
    UNIQUE (merchant_id, lwin7),
    CONSTRAINT lwin_conflict_resolved CHECK (
        (resolution IS NULL AND resolved_by IS NULL AND resolved_at IS NULL)
     OR (resolution IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL))
);

-- A merchant LWIN an operator has judged unreliable. Persisted so a resolved
-- conflict does not resurface on every collection.
CREATE TABLE merchant_lwin_untrusted (
    merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
    lwin7        text NOT NULL,
    reason       text NOT NULL,
    marked_by    uuid NOT NULL REFERENCES operator(operator_id),
    marked_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (merchant_id, lwin7)
);

-- How a merchant that can only be searched (not swept) is asked about one
-- producer: its own key for that producer, recorded rather than guessed.
-- Bordeaux Index publishes these at /fine-wine/producer/<slug>, and the slug
-- form matters: producer=domaine_armand_rousseau works, the hyphen form 404s.
CREATE TABLE merchant_search_key (
    merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
    producer_key text NOT NULL,                  -- normalised producer, as in wine_key
    params       jsonb NOT NULL,                 -- the merchant's own search terms
    source       text NOT NULL CHECK (source IN ('merchant_index','operator')),
    set_by       uuid NOT NULL REFERENCES operator(operator_id),
    set_at       timestamptz NOT NULL DEFAULT now(),
    note         text,
    PRIMARY KEY (merchant_id, producer_key)
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
    -- INDICATION is a brokerage's view of where a wine would broker, not an
    -- offer of stock. The pricing core excludes it; see decision 0013.
    price_kind       text NOT NULL CHECK (price_kind IN ('ASK','BID','LAST_TRADE','INDICATION')),

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
    target_margin numeric(6,4),                  -- the deal's global margin; see 0007
    created_by   uuid NOT NULL REFERENCES operator(operator_id),
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

    target_margin     numeric(6,4),            -- this line's margin, beats the deal's
    target_discount   numeric(6,4),            -- this line's discount off UK Reference
    manual_price      numeric(14,2),           -- beats everything

    -- Who approved the identity, how, and when. All four are set together.
    wine_id_source      text CHECK (wine_id_source IN ('lwin','alias','operator','ai_reviewed')),
    wine_id_approved_by uuid REFERENCES operator(operator_id),
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
    changed_by      uuid NOT NULL REFERENCES operator(operator_id),
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
    role           text NOT NULL CHECK (role IN ('comparable','merchant_best','cross_unit',
                                                 'indication','rejected')),
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
    priced_by         uuid NOT NULL REFERENCES operator(operator_id),

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

    -- Which rule produced sell_price, and the inputs it used (decision 0007).
    price_basis       text NOT NULL CHECK (price_basis IN
                          ('manual','line_margin','line_discount','global_margin')),
    target_margin     numeric(6,4),
    discount          numeric(6,4),
    deep_discount_threshold numeric(6,4) NOT NULL,
    sell_price        numeric(14,2),
    sell_currency     char(3) NOT NULL DEFAULT 'GBP',
    gp                numeric(14,2),
    gross_margin      numeric(6,4),            -- (sell - cost) / sell, never markup

    flags             text[] NOT NULL DEFAULT '{}',
    state             text NOT NULL CHECK (state IN ('READY','REVIEW','NO_MARKET')),

    -- Derived from the flags and the benchmark state, so it cannot drift from
    -- either: a price that is below cost, or above the UK market the client
    -- document quotes it against, or that rests on evidence an operator has to
    -- look at (REVIEW) or on no evidence at all (NO_MARKET), needs a named
    -- operator to accept it before it can be exported. See decision 0010.
    -- COST_ABOVE_UK_REFERENCE and DEEP_DISCOUNT do not gate: buying badly is a
    -- commercial fact, and selling below market is the product.
    requires_acknowledgement boolean NOT NULL
                      GENERATED ALWAYS AS (flags && ARRAY['NEGATIVE_GP',
                                           'SELL_ABOVE_UK_REFERENCE']::text[]
                                           OR state IN ('NO_MARKET','REVIEW')) STORED,

    UNIQUE (pricing_id, requires_acknowledgement),
    CONSTRAINT pricing_result_cost_currency CHECK ((cost IS NULL) = (cost_currency IS NULL)),
    CONSTRAINT pricing_result_fx_recorded CHECK (
        cost IS NULL OR cost_currency = 'GBP'
        OR (fx_rate IS NOT NULL AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL))
);

-- A named operator accepting a gating flag on one pricing result. One per
-- result: re-pricing produces a new result, which needs its own acknowledgement.
CREATE TABLE pricing_acknowledgement (
    ack_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pricing_id      uuid NOT NULL REFERENCES pricing_result(pricing_id) ON DELETE CASCADE,
    flags           text[] NOT NULL,          -- the gating flags as they stood
    state           text NOT NULL             -- and the benchmark state accepted with them
                    CHECK (state IN ('READY','REVIEW','NO_MARKET')),
    acknowledged_by uuid NOT NULL REFERENCES operator(operator_id),
    acknowledged_at timestamptz NOT NULL DEFAULT now(),
    note            text,
    UNIQUE (pricing_id),
    UNIQUE (ack_id, pricing_id)
);

-- ============================================================= buyer offers

-- A line's market claim, and the ONLY place one can come from. "£x, y% below
-- the UK market" is a statement about a market we measured, so the reference it
-- rests on is NOT NULL here: a line with no UK Reference simply has no row, and
-- a document has nothing to print for it. Not blank, not zero — absent.
-- See decision 0010.

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
    issued_by      uuid NOT NULL REFERENCES operator(operator_id),
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

    -- The export gate, enforced by keys rather than by convention. The pair
    -- (pricing_id, pricing_requires_ack) is a foreign key into pricing_result,
    -- so a line cannot claim a price needs no acknowledgement when it does; and
    -- when it does, ack_id must be an acknowledgement OF THAT price.
    pricing_requires_ack boolean NOT NULL,
    ack_id          uuid,

    PRIMARY KEY (buyer_offer_id, line_no),
    FOREIGN KEY (pricing_id, pricing_requires_ack)
        REFERENCES pricing_result (pricing_id, requires_acknowledgement),
    FOREIGN KEY (ack_id, pricing_id)
        REFERENCES pricing_acknowledgement (ack_id, pricing_id),
    CONSTRAINT buyer_offer_line_total CHECK (line_total = unit_price * quantity),
    CONSTRAINT buyer_offer_line_acknowledged CHECK
        (NOT pricing_requires_ack OR ack_id IS NOT NULL)
);

CREATE TABLE buyer_offer_market_claim (
    buyer_offer_id uuid NOT NULL,
    line_no        int NOT NULL,
    run_id         uuid NOT NULL REFERENCES benchmark_run(run_id),
    as_of          timestamptz NOT NULL,          -- when that market was measured
    uk_reference   numeric(14,2) NOT NULL,        -- never null: that is the point
    comp_count     int NOT NULL CHECK (comp_count > 0),
    -- (reference - sell) / reference, and never negative: "12% below the UK
    -- market" is a claim, and a price ABOVE the market is not a smaller one.
    -- Such a line carries no claim at all, like a line with no reference.
    below_reference numeric(6,4) NOT NULL CHECK (below_reference >= 0),
    PRIMARY KEY (buyer_offer_id, line_no),
    FOREIGN KEY (buyer_offer_id, line_no)
        REFERENCES buyer_offer_line (buyer_offer_id, line_no) ON DELETE CASCADE
);
