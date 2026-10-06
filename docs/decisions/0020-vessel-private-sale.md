# 0020 — VESSEL Private Sale, drop one

**Status:** accepted, 6-7 October 2026. Doug's product, specified in
`docs/research/vessel-private-sale-v4.md` (governs over v3 where they
differ) and `docs/research/vessel-private-sale-v3.md` (the detail: screens,
state machine, operational musts).

## What this is, and why it is a new product, not a new feature

VESSEL buys nothing. It lists a seller's own wine under a time-boxed
mandate, sets the price, and takes a fee when it sells — a consignment
marketplace. That is a different business from the chain decision 0017
built (direct purchase and resale, where VESSEL is the counterparty on both
sides of the trade), even though both currently take an 8% fee and both
sit on the same pricing engine underneath. `app/vessel/` shares no table
with `buyer_offer`/`pricing_result`'s chain, and `app/vessel/engine.py`
defines its own `VESSEL_FEE` rather than importing
`app/pricing/pricer.MARGIN_ON_SALE` — the same number today, by
coincidence, not by meaning, and the two must be free to diverge.

`app/core/` is untouched, as the brief predicted. VESSEL reads two tables
the core already produces — `benchmark_run` and `vintage_band_check` — and
makes its own decisions from what is already there. It asks the core
nothing new.

## The rule that decided every tie: v4 over v3

Where the two specs disagreed, v4 won, as instructed. Four places that
mattered:

1. **No seller floor.** v3 had an editable "minimum you'd accept" field and
   a floor-check gate. v4 removes it: "declining is the floor." Built per
   v4 — `vessel_listing` has no floor column, and the only per-line input a
   seller makes is MOVE or KEEP.
2. **Bands, not a flat 20%.** v3's formula was `VESSEL price = reference x
   0.80`. v4 replaces it with STRONG/NORMAL/CLEARANCE, invisible to
   everyone outside VESSEL, chosen by the operator per listing. Built per
   v4 and the brief, which restates the bands explicitly.
3. **One source can list.** v3: "a line with one source is not listed at
   all... non-negotiable." v4 revises this on the strength of the
   quality-matched vintage band (decision 0015): one source lists,
   indicative, no percentage claim, if and only if the band both ran and
   did not flag it. Built per v4 and the brief, which restates it as the
   load-bearing evidence rule.
4. **Payment language.** v3: "we'll confirm within minutes of the money
   landing." v4: "never 'confirmed in minutes'" — the copy is exactly "Your
   purchase is confirmed when funds are received." Built per v4, and that
   exact sentence is the only payment-confirmation copy anywhere in the
   four screens.

Rounding direction is a fifth, smaller case worth naming because it moves
money: v3 says a VESSEL price is "rounded DOWN to a clean figure"; v4 and
the brief both just say "a clean figure." Always-down would favour VESSEL
over the seller for no reason either document states, and it sits oddly
beside v4's whole direction (bands instead of a flat spread, true payment
language) — all of which make the seller's position better, never worse.
Read as v4 superseding v3 here too: `round_to_clean_figure()` rounds to the
*nearest* step, half-even, not down.

## The evidence rule, exactly as specified, structurally enforced

Three outcomes, and the database repeats the middle two rather than
trusting a template:

- **0 sources** — never listed. `vessel_listing.source_count` has `CHECK
  (source_count >= 1)`: a zero-source line never gets a row at all.
- **1 source** — listed, "Indicative reference", no percentage, only if
  the vintage-band check both ran and did not flag the comp.
  `vessel_listing_single_source_needs_band` CHECK: `source_count >= 2 OR
  vintage_band_passed`.
- **2+ sources** — "Market reference" and the percentage. `
  vessel_listing_claim_needs_two_sources` CHECK: `percentage_claim_pct IS
  NULL OR source_count >= 2`.

"The band ran and did not flag it" is read off the EXISTING pipeline's own
output, not recomputed: `_benchmark_with_band` (decision 0015) already
excludes a high outlier before a run is saved, so by the time VESSEL looks,
`comp_count == 1` with a non-null `vintage_band_check.band_low` means the
one surviving comp already passed. No extra call into
`app.market.vintage_band` was needed.

## Pricing: the lot, not the bottle

`market_reference`, `band`, `discount_applied`, `vessel_price` and
`seller_net` are **lot totals** — all bottles on the listing, not a
per-bottle figure. The published mockup only reconciles that way: HK$84,000
/ HK$69,500 / HK$63,940 for six bottles of 2010 Rousseau Clos St Jacques is
a plausible case price; per bottle it would be the most expensive Burgundy
premier cru on earth. `app/vessel/engine.price_listing()` reproduces those
three figures exactly from a 17% NORMAL-band discount
(`test_price_listing_matches_the_published_mockup`).

The band itself (`STRONG` 10–15%, `NORMAL` 15–20%, `CLEARANCE` 20%+) is
re-enforced at the database: `vessel_listing_discount_in_band` CHECK ties
`discount_applied` to the `band` it is stored against, so the two can never
read differently from each other.

## Two numbers nothing in the spec pinned down — both resolved, 7 October 2026

**FX direction.** "Both first-class... with the FX rate and source stored
on the listing at the moment of pricing" did not say which way the rate
points, and the column was named `fx_rate` — flagged above as "worth a
second pair of eyes before the first real rate is typed in." Doug's call:
a bare `fx_rate` is exactly how a 100x conversion error happens unnoticed.
Renamed structurally rather than left as a comment: the column is now
`vessel_listing.fx_hkd_per_gbp` (migration 0016, written this way from the
start since it had not shipped anywhere beyond this session), and every
parameter in `app/vessel/engine.py` and `app/vessel/repo.py` follows —
`fx_rate` does not appear anywhere in `app/vessel/`.

**How long proof of payment extends the hold.** v4: "submitting proof of
payment extends the hold automatically" — no length given. Originally built
as "the same hold window again," flagged as a reading rather than a
specification. Doug's call: **one** extension, a fixed **2 hours**, then an
operator confirms — never a second automatic extension, and never the
original `hold_duration()` again. `submit_proof_of_payment()` now refuses a
second call on the same reservation (`AlreadyExtended`), and
`expire_overdue_reservations()` skips any reservation that has already used
its extension — a timer no longer resolves it, `cancel_reservation()` or
`record_payment()` does. `reservations_needing_confirmation()` is the
operator's queue for exactly this state: HELD, past its one extension,
unresolved either way.

## What "drop one" does not include, by the specs' own build order

v3's build order puts these in "drop two to five," not "drop one," and
nothing here contradicts that:

- **Payment matching is a human action, not a webhook.** `record_payment()`
  is operator-only: someone sees a bank line land and types it in. "Payment
  matching automated" is explicitly later work.
- **No scheduler runs `expire_overdue_reservations()`.** It is exposed as
  an operator-triggered endpoint; a cron or RQ-scheduler calling it on a
  timer is infrastructure, not a decision, and is not built.
- **No buyer or seller authentication.** VESSEL's four public routes are
  reachable by anyone with the link — the listing, drop and reservation
  UUIDs are the only gate. v3 names "KYC on buyers... a door policy" as an
  operational must; it is not built, and building one silently would have
  been a bigger, uninvited decision than skipping it openly.
- **No re-drop or re-price engine, and no transfer/settlement workflow.**
  `vessel_listing.settled_at` exists in the schema for the day rule 4
  ("VESSEL finishes it") is built, but nothing writes it yet — the
  sell-through report's timing reads the fulfilling *payment*'s timestamp
  instead, since that is the furthest the state machine currently reaches.

## Contradictions found, reported rather than fixed quietly

1. **`docs/research/offer-document-spec.md`'s `seller_offer`/
   `seller_offer_line` used `bigserial`/`bigint` primary and foreign keys**
   against a schema where every other table — `deal`, `seller_line`,
   `wine`, now `vessel_listing` — is `uuid`. Confirmed 7 October: the spec
   was wrong, the schema is right. Corrected directly in the spec document
   rather than left as a flag; `seller_offer`/`seller_offer_line` are still
   not built (unaffected by VESSEL), but the DDL anyone builds them from
   now matches the rest of the schema.
2. **v3's own reservation example names the unique index
   `one_live_reservation_per_line`** while indexing `reservation(listing_id)` —
   v3 uses "line" and "listing" for the same thing inconsistently in one
   place. The task and v4 both consistently say "listing," which is what
   got built and named throughout (`vessel_one_live_reservation_per_listing`,
   `test_one_live_reservation_per_listing`).
3. **The brief's `seller_net = vessel_price x (1 - 0.08)` and v3's identical
   formula do not agree with v3's OWN worked example's rounding note** ("HK
   $69,500, not HK$69,473... rounded down") when read literally as rounding
   the FINAL seller_net down too — the published £63,940 is not a multiple
   of anything a "round down" rule on seller_net itself would produce from
   69,500 x 0.92 under any rounding direction (69,500 x 0.92 = 63,940.00
   exactly, which only confirms seller_net is never separately
   clean-rounded — a non-issue once vessel_price is already clean, noted
   here only because it took tracing through the arithmetic to confirm
   there was no second rounding step hiding in the spec).

## Consequences

- Schema: `vessel_mandate`, `vessel_drop`, `vessel_listing`,
  `vessel_reservation`, `vessel_payment`, `vessel_event` (migration 0016).
  Two triggers do real work: `vessel_mandate` accepts no UPDATE or DELETE,
  ever; `vessel_listing` freezes its commercial and identity columns the
  moment it has a `mandate_id`.
- `app/vessel/engine.py` (pure) and `app/vessel/repo.py` (persistence).
  `app/api/deps.py` is new too — `db`/`queue`/`current_operator`/
  `translate` were pulled out of `app/api/main.py` so `app/api/vessel.py`
  could use them without a circular import; `main.py`'s own routes are
  unchanged by the move.
- Two routers: `app.api.vessel.router` (public — seller approval, drop,
  wine page, buy, proof of payment) and `.operator_router` (the existing
  session gate — recommending lines, drops, payments, analytics).
  `web/app/chrome.jsx` exempts `/vessel/*` from the operator sign-in
  redirect by the same mechanism it already exempts `/login`.
- Four page routes for the five screens: `/vessel/approve/[dealId]`,
  `/vessel/drops/[dropId]`, `/vessel/listings/[listingId]` (wine page and
  BUY), `/vessel/reservations/[reservationId]` (hold, payment and
  confirmation — one adaptive page, since v4's own mockups show these as
  one continuous moment rather than two destinations).
- Tests: `tests/test_vessel.py` — 16 pure engine tests (offline) and the
  ten named tests plus eight more at the repo/Postgres level, including a
  genuine two-connection race for the reservation constraint. 323 offline,
  446 with Postgres.
- Three bugs caught only by running the named tests against real Postgres,
  not by review: `add_to_drop`/`approve_mandate` originally stamped
  `listed_at`/`approved_at` from the database's own `now()` rather than
  taking `as_of`, which the sell-through timing test caught immediately by
  comparing a fake clock against a real one — fixed to take `as_of`
  explicitly, matching `benchmark()`'s own discipline. `record_payment()`
  originally matched on reference alone; a short or wrong-currency payment
  under the right reference would have confirmed a sale — fixed to require
  the exact amount and currency too, with anything else landing in the
  UNMATCHED queue the spec asks for. And the seller-approval screen's "why
  not the rest" counts were never persisted — `recommend_lines()` returned
  them once, in memory, so a seller revisiting the link after the operator
  had moved on would always see zero. `vessel_exclusion` now stores a
  reason per excluded line, upserted on every recommendation pass and
  deleted the moment a line qualifies, so the count is readable at any
  later visit and never contradicts a line that has since gained a
  listing.
