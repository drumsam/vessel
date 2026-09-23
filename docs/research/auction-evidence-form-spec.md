# Spec — operator-entered auction evidence

For Claude Code. 21 September 2026.

## Why

The auction audit found no source we may scrape: five of seven houses prohibit
automated extraction, Bonhams blocks machines at the server, Christie's is
unverified. Bonhams' terms leave facts free (copyright covers descriptions and
photographs only). A person reading a public results page in their own browser
and writing down the facts is ordinary use.

So auction evidence enters the system the same way a phone quote does: **an
operator types it in, with a mandatory source URL.** For a Burgundy line already
in review, one to three lots is realistic by hand.

## The rule this must not break

Auction evidence is a **health check**. It never sets, moves or substitutes for
the UK Floor, Reference or Median, and it never appears as a price on a client
document. It lives in its own table, is read by its own function, and the
benchmark module never imports it.

Per-bottle normalisation is permitted **here only** (decision recorded in the
Burgundy unit problem doc): a 6-bottle lot at £3,000 hammer may be shown as
£500/btl hammer for the health check. That figure must never flow into
`benchmark.py`, `pricing`, or an export.

## Schema (standard SQL)

```sql
CREATE TABLE auction_evidence (
    auction_evidence_id  bigserial PRIMARY KEY,
    wine_id              text        NOT NULL REFERENCES wine(wine_id),
    vintage              integer     NOT NULL,
    bottle_ml            integer     NOT NULL CHECK (bottle_ml > 0),
    bottles_in_lot       integer     NOT NULL CHECK (bottles_in_lot > 0),

    auction_house        text        NOT NULL,          -- closed list, see below
    sale_date            date        NOT NULL,
    lot_ref              text        NOT NULL,
    source_url           text        NOT NULL CHECK (source_url ~ '^https://'),

    currency             char(3)     NOT NULL,
    amount               numeric(14,2) NOT NULL CHECK (amount > 0),
    amount_basis         text        NOT NULL CHECK (amount_basis IN ('HAMMER','BUYER_PREMIUM_INCLUSIVE')),
    premium_rate         numeric(6,4) NULL,             -- required when basis is inclusive
    hammer_gbp           numeric(14,2) NULL,            -- computed server-side, never typed
    fx_rate              numeric(12,6) NULL,
    fx_source            text        NULL,

    is_mixed_lot         boolean     NOT NULL DEFAULT false,
    condition_notes      text        NULL,              -- operator's own words, not catalogue prose
    condition_flagged    boolean     NOT NULL DEFAULT false,
    quarantined          boolean     NOT NULL GENERATED ALWAYS AS
                           (is_mixed_lot OR condition_flagged) STORED,

    entered_by           text        NOT NULL,
    entered_at           timestamptz NOT NULL DEFAULT now(),
    retracted_at         timestamptz NULL,
    retracted_by         text        NULL,
    retraction_reason    text        NULL,

    CONSTRAINT inclusive_needs_rate CHECK (
        amount_basis = 'HAMMER' OR premium_rate IS NOT NULL),
    CONSTRAINT sale_not_future CHECK (sale_date <= (entered_at AT TIME ZONE 'UTC')::date),
    CONSTRAINT retraction_complete CHECK (
        (retracted_at IS NULL AND retracted_by IS NULL AND retraction_reason IS NULL) OR
        (retracted_at IS NOT NULL AND retracted_by IS NOT NULL AND retraction_reason IS NOT NULL))
);
```

Rows are never updated or deleted. A mistake is **retracted** (with reason) and
re-entered. Money is `numeric`; Python uses `Decimal`.

`auction_house` is a closed list held in code: `BONHAMS`, `CHRISTIES`, plus any
house whose terms audit has been completed and recorded. Sotheby's, Heritage,
Zachys, Acker and iDealwine are **not** in the list — their terms restrict use
to personal/non-commercial, and hand-entry for a commercial pricer is still
commercial use. Adding a house requires a decision record.

## Server-side derivation (deterministic)

1. If `amount_basis = 'BUYER_PREMIUM_INCLUSIVE'`: `hammer = amount / (1 + premium_rate)`,
   rounded half-even to 2dp. This is the one documented rounding point here.
2. If `currency != 'GBP'`: convert with the FX rate of `sale_date` from the same
   FX source the pricer uses; store `fx_rate` and `fx_source`. No FX source for the
   date → store nothing converted, show "FX unavailable", never estimate.
3. `per_bottle_hammer_gbp = hammer_gbp / bottles_in_lot` — **computed at read time
   for display only**, not stored, not exported.

## The health check (read side)

`auction_health(line) -> AuctionHealth` in `app/auction/health.py` (not in
`app/core/`):

- Inputs: approved `wine_id`, vintage, bottle_ml of the seller line.
- Uses non-retracted, non-quarantined rows with `sale_date` within 24 months.
- Output: count of lots, median per-bottle hammer GBP, date range, list of URLs.
- Flag `AUCTION_BELOW_REFERENCE` (informational, **not** in `REVIEW_FLAGS`) when the
  median sits more than 10% below the UK Reference normalised to per-bottle
  *for display*. It is advice to the operator, never a gate and never a price.
- If the line has no UK Reference (NO_MARKET), show the auction lots as context
  and say plainly: "No UK market. Auction evidence is not a price."

## The form (Next.js, must work on mobile)

Opened from a line in the review queue ("Add auction evidence"), pre-filled with
the line's approved wine, vintage and bottle size (read-only; changing identity
means going through the identity queue, not this form).

Fields: house (select) · sale date · lot ref · source URL · lot size (bottles) ·
amount + currency · basis (Hammer / Including premium) · premium % (shown only for
inclusive) · mixed lot? · condition noted? + short note in the operator's words.

Validation messages, all blocking:

- "Source URL is required — evidence without a source cannot be checked."
- "Premium rate is required when the price includes buyer's premium."
- "Mixed lots are recorded but excluded from the health check."
- On paste of long catalogue prose into the condition note (> 280 chars): "Record the
  facts in your own words. Catalogue descriptions are the auction house's
  copyright."

## Tests (house style)

1. `test_auction_evidence_never_reaches_benchmark` — static check: nothing under
   `app/core/` or `app/pricing/` imports `app.auction`.
2. `test_auction_evidence_requires_source_url` — insert without URL fails at the
   database, not only in the form.
3. `test_inclusive_price_without_rate_is_refused` — a 25% premium read as hammer is
   a 25% error; the CHECK prevents it.
4. `test_mixed_lot_is_quarantined` — generated column is true; health check
   ignores it.
5. `test_per_bottle_figure_is_not_persisted_or_exported` — export payload contains
   no auction field.
6. `test_retracted_evidence_is_ignored_but_kept`.
7. `test_house_not_in_allowed_list_is_refused` — `SOTHEBYS` rejected with the
   decision-record reference in the error.
8. `test_auction_below_reference_is_not_a_review_flag` — `REVIEW_FLAGS` unchanged.

## Out of scope

Any automated retrieval from an auction site, any browser extension or bookmarklet
that reads lot pages, and any bulk import of auction results. If Bonhams grants
factual-results access (outreach draft ready), that becomes a separate licensed
adapter with its own decision record.
