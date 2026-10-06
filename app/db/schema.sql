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
    -- An edition within the cuvee that trades at its own level: Krug's
    -- Grande Cuvee 156e and 169e, Henri Giraud's MV13. Part of identity
    -- (decision 0019) -- wine_key below folds it in as a third segment, so a
    -- vintage=1000 line with no code can never resolve to a wine that has one.
    release_code text,
    wine_key     text NOT NULL UNIQUE,          -- normalised producer|cuvee[|release_code]
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

    -- The market chain (decision 0017): M -> buyer price -> seller receives.
    -- Both default to the settings in app/pricing/pricer.py when null, and both
    -- are recorded on every pricing_result that uses them, so a reprice is a
    -- diff against what was actually used, not a new guess.
    buyer_discount numeric(6,4),                  -- trade buyers move parcels below M
    margin_on_sale numeric(6,4),                  -- our fee, taken on the buyer price

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

-- ================================================ vintage-neighbour sanity check

-- docs/research/vintage-neighbour-check-spec.md. A band is a sanity check on
-- comps we already hold, never a price: nothing in these three tables is read
-- by pricing, and nothing in them reaches a client document.

-- Operator-maintained, not a critic feed. One tier per region and vintage,
-- 1 = great, 5 = weak. A region absent from this table has no band at all:
-- the check stays quiet rather than comparing a great vintage with a weak one.
--
-- `region` carries the colour, because they diverge: 2014 Burgundy is tier 3
-- red and tier 1 white, 2009 is tier 2 red and tier 4 white. A colour-blind
-- register would produce nonsense bands.
--
-- Maintained as docs/research/vintage-tiers.csv and loaded by
-- scripts/load_vintage_tiers.py: changing a tier is a pull request, which is
-- the right amount of friction for something that decides which prices are
-- treated as outliers. Hence set_by is text (the file and its revision), not an
-- operator_id — no person types into this table.
CREATE TABLE vintage_tier (
    region      text     NOT NULL,              -- 'BURGUNDY_RED', 'BURGUNDY_WHITE', ...
    vintage     integer  NOT NULL,
    tier        smallint NOT NULL CHECK (tier BETWEEN 1 AND 5),
    tier_label  text     NOT NULL,              -- great | excellent | solid | ordinary | weak
    sources     text     NOT NULL,              -- which charts were consulted; not their scores
    note        text,
    set_by      text     NOT NULL,
    set_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region, vintage)
);

-- The band as it stood for one run. Attached to the run, never to the
-- benchmark figures. band_low/band_high are NULL together when there were
-- fewer than two neighbouring vintages: silence, not a guess.
CREATE TABLE vintage_band_check (
    run_id          uuid PRIMARY KEY REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    unit            text NOT NULL,              -- '6x750', display only
    band_low        numeric(14,2),
    band_high       numeric(14,2),
    neighbours      jsonb NOT NULL DEFAULT '[]',   -- vintage, median, merchants, as_of, stale
    low_outliers    jsonb NOT NULL DEFAULT '[]',   -- flagged, never excluded (spec 5)
    format_incoherent jsonb NOT NULL DEFAULT '[]', -- per-bottle figures live here and nowhere else
    tiers_available boolean NOT NULL,
    note            text,
    CONSTRAINT vintage_band_edges_together CHECK ((band_low IS NULL) = (band_high IS NULL)),
    CONSTRAINT vintage_band_ordered CHECK (band_low IS NULL OR band_low <= band_high)
);

-- A comp the band excluded automatically, recorded exactly like a manual
-- correction: the offer, the edge it failed, the multiple, and who put it back.
-- Only a DEAR comp is ever excluded automatically (spec 5), so the flag is
-- constrained to one value: an automatic rule must never be able to delete a
-- cheap comp, which would push the Reference up and let us overprice a client.
CREATE TABLE benchmark_comp_exclusion (
    exclusion_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          uuid NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    offer_pk        uuid REFERENCES offer(offer_pk) ON DELETE SET NULL,
    offer_snapshot  jsonb NOT NULL,             -- the offer as the run saw it; money is a string
    flag            text NOT NULL CHECK (flag = 'COMP_EXCLUDED_VINTAGE_BAND'),
    band_edge       numeric(14,2) NOT NULL,     -- band_high x HIGH_MULTIPLE, after widening
    band_multiple   numeric(6,4) NOT NULL,      -- price / edge, for the operator to see
    excluded_at     timestamptz NOT NULL DEFAULT now(),

    -- "Put it back": a new run computed with this comp restored, and who asked.
    reinstated_at   timestamptz,
    reinstated_by   uuid REFERENCES operator(operator_id),
    reinstated_reason text,
    replacement_run_id uuid REFERENCES benchmark_run(run_id),
    UNIQUE (run_id, offer_pk),
    CONSTRAINT comp_exclusion_reinstatement_complete CHECK (
        (reinstated_at IS NULL AND reinstated_by IS NULL AND reinstated_reason IS NULL
         AND replacement_run_id IS NULL)
        OR (reinstated_at IS NOT NULL AND reinstated_by IS NOT NULL
            AND reinstated_reason IS NOT NULL AND replacement_run_id IS NOT NULL))
);

CREATE INDEX comp_exclusion_open ON benchmark_comp_exclusion (run_id)
    WHERE reinstated_at IS NULL;

-- One wine seen in two pack sizes by one merchant in one fetch: the paired
-- observation that makes CASE_PREMIUM a measurement instead of a judgement
-- call (decision 0016, docs/research/case-premium-measurement.md).
--
-- Same wine, vintage, bottle size AND duty status on both sides — a Duty Paid
-- bottle against an In Bond case measures the duty, not the case. Each pack
-- size is paired against the smallest one present, so three sizes give two
-- rows, and where a loose bottle exists it is the baseline.
--
-- `ratio` is a ratio, not money: the larger pack's price per bottle over the
-- smaller's. Above 1 means the bigger unit costs more per bottle.
CREATE TABLE case_premium_pair (
    pair_id        bigserial PRIMARY KEY,
    snapshot_id    uuid NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    merchant_id    text NOT NULL REFERENCES merchant(merchant_id),
    wine_id        uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    vintage        integer NOT NULL,
    bottle_ml      integer NOT NULL CHECK (bottle_ml > 0),
    duty_status    text NOT NULL,
    captured_at    timestamptz NOT NULL,

    smaller_pack   integer NOT NULL CHECK (smaller_pack >= 1),
    smaller_price  numeric(14,2) NOT NULL CHECK (smaller_price > 0),
    larger_pack    integer NOT NULL CHECK (larger_pack > 1),
    larger_price   numeric(14,2) NOT NULL CHECK (larger_price > 0),
    ratio          numeric(10,6) NOT NULL CHECK (ratio > 0),

    -- The pair the CASE_PREMIUM constant is about. A 3-pack against a 6-pack
    -- measures something else, and case-to-case derivation applies no premium.
    is_loose_pair  boolean NOT NULL GENERATED ALWAYS AS (smaller_pack = 1) STORED,

    CONSTRAINT case_premium_pair_order CHECK (larger_pack > smaller_pack),
    UNIQUE (snapshot_id, wine_id, vintage, bottle_ml, duty_status, smaller_pack, larger_pack)
);

CREATE INDEX case_premium_pair_measure ON case_premium_pair (bottle_ml, captured_at)
    WHERE is_loose_pair;

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
                          ('manual','line_margin','line_discount','global_margin',
                           'buyer_discount')),
    target_margin     numeric(6,4),
    discount          numeric(6,4),
    deep_discount_threshold numeric(6,4) NOT NULL,
    sell_price        numeric(14,2),
    sell_currency     char(3) NOT NULL DEFAULT 'GBP',
    gp                numeric(14,2),
    gross_margin      numeric(6,4),            -- (sell - cost) / sell, never markup

    -- The market chain (decision 0017), basis 'buyer_discount' only. The two
    -- settings actually used (never the module defaults silently): buyer
    -- price = UK Reference x (1 - buyer_discount); seller receives = buyer
    -- price x (1 - margin_on_sale). buyer_price_gbp and seller_price_gbp are
    -- GENERATED from sell_price/cost_gbp for this basis alone, so the two
    -- numbers named on a client document can never drift from the figures the
    -- rest of the system already prices and audits.
    buyer_discount    numeric(6,4),
    margin_on_sale    numeric(6,4),
    buyer_price_gbp   numeric(14,2) GENERATED ALWAYS AS
                      (CASE WHEN price_basis = 'buyer_discount' THEN sell_price END) STORED,
    seller_price_gbp  numeric(14,2) GENERATED ALWAYS AS
                      (CASE WHEN price_basis = 'buyer_discount' THEN cost_gbp END) STORED,

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
        OR (fx_rate IS NOT NULL AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL)),
    CONSTRAINT pricing_result_chain_fields CHECK (
        (price_basis = 'buyer_discount') = (buyer_discount IS NOT NULL AND margin_on_sale IS NOT NULL))
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

-- ============================================================= VESSEL private sale

-- VESSEL buys nothing: it lists a seller's own wine for sale at a price
-- VESSEL sets, under a time-boxed mandate, and takes a fee on the buyer's
-- price when it sells. This is a different business from buyer_offer/
-- seller_offer above (direct purchase and resale) and shares no table with
-- either -- a listing is neither of those documents, it is a standing offer
-- to a buyer that can be reserved and bought.
-- docs/decisions/0020-vessel-private-sale.md, docs/research/vessel-private-sale-v4.md
-- (v4 supersedes v3 where they differ).

-- One seller-approval event. "Approve 42 wines" writes exactly one of these,
-- and it never changes again: the trigger below enforces that structurally,
-- not by convention -- test_mandate_record_is_immutable_once_approved.
-- No seller login exists in this system; approved_by_name is captured on the
-- approval screen itself, same way deal.seller already is free text.
CREATE TABLE vessel_mandate (
    mandate_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id          uuid NOT NULL REFERENCES deal(deal_id),
    mandate_text     text NOT NULL,              -- the rendered paragraph, verbatim
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

-- A dated collection of listings. Can be empty -- "better nothing on a
-- Thursday than filler" (v3).
CREATE TABLE vessel_drop (
    drop_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    label        text NOT NULL,                  -- "Drop 1 -- 9 October 2026"
    drop_date    date NOT NULL,
    created_by   uuid NOT NULL REFERENCES operator(operator_id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- One sellable unit: everything in one seller_line's bottle count, as one
-- lot (no partial-case sales at launch -- v3). market_reference, vessel_price
-- and seller_net are LOT TOTALS in `currency`, not per-bottle: the mockups'
-- own figures only reconcile that way (HK$84,000 / HK$69,500 / HK$63,940 for
-- six bottles of 2010 Rousseau Clos St Jacques is a plausible lot price;
-- per-bottle it would be the most expensive Burgundy premier cru on earth).
--
-- display_producer/display_wine/vintage/bottle_ml/bottles are snapshotted at
-- creation, the same discipline offer_sheet_reference's seller_offer_line
-- already uses: what the seller and buyer were shown must stay reconstructible
-- even if the wine's canonical record changes later.
-- One row per market a line's reference has been captured in — append-only,
-- like vessel_mandate: a market's price changing is a new row, never an
-- edit to one a listing may already point to. "A listing needs a named
-- reference market, not one implicit one" (decision 0020 revision, 7
-- October 2026) — UK_IN_BOND and HK_RETAIL, from
-- docs/research/hk-vs-uk-market-reference.md (median HK retail +22% over
-- UK In Bond, 9 matched pairs, range -21% to +46%).
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

CREATE TABLE vessel_listing (
    listing_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id           uuid NOT NULL REFERENCES deal(deal_id),
    line_id           uuid NOT NULL UNIQUE REFERENCES seller_line(line_id),
    run_id            uuid REFERENCES benchmark_run(run_id),  -- provenance: which run priced this
    mandate_id        uuid REFERENCES vessel_mandate(mandate_id),
    drop_id           uuid REFERENCES vessel_drop(drop_id),

    state             text NOT NULL CHECK (state IN
                          ('RECOMMENDED','DECLINED','APPROVED','LISTED',
                           'RESERVED','PAID','TRANSFERRING','SETTLED')),

    display_producer  text NOT NULL,
    display_wine      text NOT NULL,
    vintage           int  NOT NULL,
    release_code      text,                      -- 0019: '156e' and friends
    bottle_ml         int  NOT NULL CHECK (bottle_ml > 0),
    bottles           int  NOT NULL CHECK (bottles > 0),
    stock_location    text NOT NULL CHECK (stock_location IN
                          ('HK_BOND','UK_BOND','EU_BOND','DUTY_PAID_HK','OTHER')),
    warehouse         text,
    condition_notes   text,
    provenance_notes  text,

    -- Multi-currency, both first-class. fx_hkd_per_gbp is named for its
    -- direction on purpose (decision 0020 revision, 7 October 2026) — a
    -- bare "fx_rate" is exactly how a 100x conversion error happens
    -- unnoticed. Stored at the moment of pricing, never reconverted at
    -- display or at read time.
    currency          char(3) NOT NULL CHECK (currency IN ('HKD','GBP')),
    fx_hkd_per_gbp    numeric(18,8) CHECK (fx_hkd_per_gbp > 0),
    fx_source         text,
    fx_rate_date      date,
    CONSTRAINT vessel_listing_fx_recorded CHECK (
        currency = 'GBP' OR
        (fx_hkd_per_gbp IS NOT NULL AND fx_source IS NOT NULL AND fx_rate_date IS NOT NULL)),

    -- Pricing. The internal band is invisible to everyone outside VESSEL;
    -- discount_applied is the number actually used, and it must fall inside
    -- the band it claims (STRONG 10-15 / NORMAL 15-20 / CLEARANCE 20-25+).
    market_reference  numeric(14,2) NOT NULL CHECK (market_reference > 0),
    band              text NOT NULL CHECK (band IN ('STRONG','NORMAL','CLEARANCE')),
    discount_applied  numeric(5,4) NOT NULL,
    CONSTRAINT vessel_listing_discount_in_band CHECK (
        (band = 'STRONG'     AND discount_applied >= 0.10 AND discount_applied < 0.15) OR
        (band = 'NORMAL'     AND discount_applied >= 0.15 AND discount_applied < 0.20) OR
        (band = 'CLEARANCE'  AND discount_applied >= 0.20)),
    -- Rounded to a clean figure (nearest 500 HKD / nearest 50 GBP) and never
    -- changed inside a drop -- app/vessel/engine.py is the single place that
    -- arithmetic happens; this table only stores what it produced.
    vessel_price      numeric(14,2) NOT NULL CHECK (vessel_price > 0),
    seller_net        numeric(14,2) NOT NULL CHECK (seller_net > 0),

    -- The evidence claim rule -- load-bearing, enforced here, not in a
    -- template. A listing with zero sources is never created at all.
    source_count         int NOT NULL CHECK (source_count >= 1),
    vintage_band_passed   boolean NOT NULL DEFAULT false,
    derived               boolean NOT NULL DEFAULT false,   -- 0016/0018 case derivation used
    percentage_claim_pct  numeric(5,4),
    -- No HK-specific sanity check exists the way app/market/vintage_band.py
    -- exists for UK In Bond, so the single-source exception is UK only
    -- (decision 0020 revision, 7 October 2026).
    CONSTRAINT vessel_listing_single_source_needs_band CHECK (
        source_count >= 2 OR (reference_market = 'UK_IN_BOND' AND vintage_band_passed)),
    CONSTRAINT vessel_listing_claim_needs_two_sources CHECK (
        percentage_claim_pct IS NULL OR source_count >= 2),

    held_back    boolean NOT NULL DEFAULT false,  -- operator curation: qualifies, not offered this round
    created_at   timestamptz NOT NULL DEFAULT now(),
    approved_at  timestamptz,
    listed_at    timestamptz,
    settled_at   timestamptz,

    -- Which market this listing was priced from, named rather than implicit
    -- (decision 0020 revision, 7 October 2026) — reference_id is the exact
    -- vessel_reference row consulted, for provenance.
    reference_market text NOT NULL,
    CONSTRAINT vessel_listing_reference_market_known CHECK (
        reference_market IN ('UK_IN_BOND','HK_RETAIL')),
    reference_id     uuid REFERENCES vessel_reference(reference_id),

    CONSTRAINT vessel_listing_mandate_matches_state CHECK (
        (state IN ('RECOMMENDED','DECLINED') AND mandate_id IS NULL) OR
        (state NOT IN ('RECOMMENDED','DECLINED') AND mandate_id IS NOT NULL)),
    CONSTRAINT vessel_listing_drop_matches_state CHECK (
        (state IN ('RECOMMENDED','DECLINED','APPROVED') AND drop_id IS NULL) OR
        (state NOT IN ('RECOMMENDED','DECLINED','APPROVED') AND drop_id IS NOT NULL))
);

CREATE INDEX vessel_listing_drop ON vessel_listing (drop_id) WHERE drop_id IS NOT NULL;
CREATE INDEX vessel_listing_mandate ON vessel_listing (mandate_id) WHERE mandate_id IS NOT NULL;

-- The commercial promise, frozen the moment a mandate exists. Lifecycle
-- columns (state, drop_id, *_at) stay mutable; nothing a seller or buyer was
-- shown a number for does.
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

CREATE TRIGGER vessel_listing_price_frozen
    BEFORE UPDATE ON vessel_listing
    FOR EACH ROW EXECUTE FUNCTION vessel_forbid_price_change_once_approved();

-- One hold at a time, structurally. payment_reference is the key a buyer is
-- told to quote; it is generated once, per reservation, and never reused.
CREATE TABLE vessel_reservation (
    reservation_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id         uuid NOT NULL REFERENCES vessel_listing(listing_id),
    state              text NOT NULL CHECK (state IN ('HELD','EXPIRED','FULFILLED','CANCELLED')),
    payment_reference  text NOT NULL UNIQUE,
    buyer_contact       text NOT NULL CHECK (buyer_contact <> ''),  -- email or phone; no buyer account system built
    held_at             timestamptz NOT NULL DEFAULT now(),
    expires_at          timestamptz NOT NULL,
    proof_submitted_at  timestamptz,
    fulfilled_at        timestamptz,
    cancelled_at        timestamptz
);

-- "A database constraint, not application logic" (v3). Two concurrent BUYs
-- on the same listing: one INSERT succeeds, the other hits this index and
-- fails. test_one_live_reservation_per_listing.
CREATE UNIQUE INDEX vessel_one_live_reservation_per_listing
    ON vessel_reservation (listing_id) WHERE state = 'HELD';

-- Every incoming payment, matched or not. Nothing ships on an unmatched one.
CREATE TABLE vessel_payment (
    payment_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reference               text NOT NULL,        -- as received; may not match anything
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

-- Behaviour, not a profile (v3/v4): viewed, bought, declined after viewing.
-- "Time to act" is derived at read time from pairs of these rows, never stored.
CREATE TABLE vessel_event (
    event_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id    uuid NOT NULL REFERENCES vessel_listing(listing_id),
    event_type    text NOT NULL CHECK (event_type IN ('VIEWED','BOUGHT','DECLINED_AFTER_VIEWING')),
    buyer_contact text,                            -- null: an anonymous view
    occurred_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX vessel_event_listing ON vessel_event (listing_id, occurred_at);

-- Why a line was not recommended, kept so the seller-approval screen's "why
-- not the rest" counts are readable at any later visit, not only in the
-- response of the operator action that computed them. Re-running
-- recommend_lines() upserts this: a line that newly qualifies has its row
-- deleted, one still excluded gets its reason refreshed.
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
