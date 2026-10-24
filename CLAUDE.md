# UK Fine Wine Deal Pricer — working agreement

Read `README.md` and everything in `docs/decisions/` before changing code.

## What this is

An operator loads a seller's wine list. The system finds the lowest verified
comparable UK In Bond offer from an approved merchant universe, applies a
discount or target margin, and produces a client-facing offer.

**Accuracy beats coverage. Never invent, estimate or silently substitute a market
price. Fail closed.** A missing price is a fine outcome. A wrong price that looks
right is the failure this whole system exists to prevent.

## The rule that governs everything

> Agents propose. Deterministic code disposes.

AI interprets messy seller text, searches awkward merchant sites, extracts
candidate evidence and challenges proposed matches. AI never decides identity
approval, format comparability, duty filtering, benchmark arithmetic, margins, or
any figure on a client document.

> The adapter contract may evolve as new merchants are investigated.
> The deterministic pricing invariants must not.

## `app/core/` is locked

`app/core/benchmark.py`, `models.py`, `flags.py` and `enums.py` encode invariants
that were established by measuring live merchant data. Do not relax one to make a
merchant fit — the fix belongs in an adapter or in `app/identity/`.

If you believe an invariant is wrong, say so and cite evidence. Do not change it
quietly.

The invariants, in short:

1. Identity is compared by approved `wine_id` only. The pricing core does not
   know what a producer or a cuvée is. No name matching lives here.
2. Commercial unit equality is exact, with ONE exception the caller must ask
   for: `SellerLine.derive_units` permits a comparable to be DERIVED from
   another case size of the same 750ml wine, at `CASE_PREMIUM` (median 1.0000
   across 27 paired observations). Any wine with a region AND a colour
   recorded qualifies (decision 0018) — the premium is MEASURED for Burgundy
   and ASSUMED elsewhere, and the operator is told which. Every capture
   records the pairs it meets so every region's evidence accumulates. Derived
   comps rank behind every exact-unit comp, are used only when fewer than two
   merchants hold the seller's own unit, and always flag the line
   `DERIVED_FROM_CASE`, so a person sees them — except that the flag stops
   *gating* (never stops being shown) once 2+ merchants' comps agree WITH
   EACH OTHER, within `AGREEMENT_THRESHOLD` (10%, region-independent —
   decision 0028, correcting 0023's first attempt, which expressed
   agreement only through the vintage band and so could never fire outside
   Burgundy, where the band exists); where a vintage band also exists for
   the region it must agree too, strictly more information, not given up
   for Burgundy. One comp never qualifies either way. Magnums and half
   bottles never convert, either way. The core is told which lines
   qualify; it does not know what a region is. See `docs/decisions/0016`,
   `0018`, `0023`, `0028`.
3. Depth counts merchants, not listings.
4. Floor = lowest merchant-best · Reference = second-lowest (or the only one,
   flagged `ONE_COMP`) · Median = median of merchant-bests.
5. Hard screens: In Bond, ASK, GBP, buyable, positive price, whole pence, not a
   mixed lot. Every rejection is retained with its reason. A brokerage
   `INDICATION` is not an ASK and never prices; it is kept as corroboration
   beside cross-unit evidence, with its variance from the Reference. See 0013.
   A two-sided market's `BID` (executable demand) and `LAST_TRADE` (money
   that actually changed hands) are excluded the same way and kept the same
   way — never Floor, Reference or Median, however much better the evidence
   is than an ordinary ask. A single merchant's own bid and ask disagreeing
   by more than `WIDE_SPREAD_THRESHOLD` is flagged `TWO_SIDED_WIDE_SPREAD`,
   informational like `WIDE_SPREAD` itself for 3+ comps — but `WIDE_SPREAD`
   GATES when `comp_count == 2` (decision 0033): with exactly two comps the
   tail is the whole sample, and Reference is just the dearer of two
   numbers that contradict each other, not one outlier against a body of
   agreement. See 0026, 0033.
6. Zero comparables ⇒ `NO_MARKET`.
7. Money is `Decimal` in Python and `numeric(14,2)` in Postgres. No float ever
   touches a price. Exactly four places round, all ROUND_HALF_EVEN to pence:
   the Median and a comparable derived across case sizes (`benchmark.py`), FX
   conversion of a non-GBP cost and the sell price (`app/pricing/pricer.py`).
   A price that is not whole pence is refused as `NOT_WHOLE_PENCE`, never
   rounded. See `docs/decisions/0007`.
8. Freshness: an offer is comparable only if captured within
   `MAX_OFFER_AGE_DAYS` (14) before `as_of`, and not after it. Undated ⇒ `STALE`.
   `as_of` is an argument, never the clock. See `docs/decisions/0003`.
9. Inherited line flags (`NAME_REVIEW`, `FORMAT_REVIEW`, `DERIVED_FROM_CASE`)
   are unioned in before state is derived, and only review flags may be
   inherited: they can hold a line in review, never release one. See 0005.

10. `NO_MARKET` means every approved merchant was searched and none offers the
    wine. A line nobody has searched is `NOT_SEARCHED`: no run, no price, no
    buyer export. Never blur the two.
11. Line status is **derived on read** from the line and its latest run, never
    stored. A stored status drifts from the benchmark it describes.
12. `NEGATIVE_GP`, `SELL_ABOVE_UK_REFERENCE` and `SELL_AT_OR_ABOVE_UK_FLOOR`
    gate the buyer export until a named operator accepts them (decision 0008;
    the Floor guard is 0033 — a listed price may never equal or exceed the
    cheapest ask actually found, found live on four real two-comp Champagne
    lines where Reference, the dearer of the two, still let a 20% discount
    land above the cheaper one's own ask), and so do the benchmark states
    `NO_MARKET` and `REVIEW` (0010). `COST_ABOVE_UK_REFERENCE` and
    `DEEP_DISCOUNT` are context: selling below market is the product.
15. **A line with no UK Reference may not carry a market claim.** No "UK
    Market", no "% below" — absent, not blank. `buyer_offer_market_claim` has a
    NOT NULL reference, so a line without one has no row and a document has
    nothing to print. See 0010. Nor may a line priced at or above the UK Floor
    (`SELL_AT_OR_ABOVE_UK_FLOOR`, decision 0033): the claim would be false —
    "below market" has to mean below the cheapest ask we actually found, not
    below whichever number the benchmark called Reference — and this holds
    even once a named operator has accepted the export gate itself; accepting
    a price is not the same as the document being entitled to call it a
    bargain. Where a claim IS printed it is always `1 - sell_price/uk_floor`
    (decision 0034, `floor_saving`/`claims_a_saving` in `app/core/flags.py`),
    computed once, server-side, never from Reference and never averaged
    across a drop — and even that real figure prints as nothing at all below
    `MIN_CLAIM_THRESHOLD` (5% to start): a line a few pence under Floor is
    still sellable, it just may not be advertised as a discount. Exposed as
    `PricingOut.floor_saving_claim`; a client reads it, never recomputes it.
16. Collection has two modes: the sweep (`collect_snapshot`) and the search
    (`deep_search`, for merchants that answer per producer and vintage). Search
    keys are read from the merchant's own index, never guessed. See 0011.
17. A source that publishes a view rather than stock counts as **one merchant**,
    whatever `merchantCount` it quotes. Depth counts merchants we hold an offer
    from. See 0013.
13. A producer-only alias (no cuvée) is operator-only, refused where the
    producer has several wines unless the target is named again, and audited as
    a set. Farr prints both "Veuve Clicquot" and "Veuve Clicquot Rosé".
14. **Who** is the server's answer, never the caller's: `approved_by`,
    `priced_by` and `acknowledged_by` come from the session, and a body that
    names someone else is a 422. Audit rows hold `operator_id`, so a rename
    rewrites nothing, and access is revoked with `operator.active`. See
    `docs/decisions/0009`.

18. Neighbouring vintages are chosen by **quality, not by proximity in years**:
    same wine and unit, within ±8 years, same tier from the register, widened
    once to tier ±1 and never further. A region absent from `vintage_tier` gets
    no band and no flag. The register is keyed by region AND colour (2014
    Burgundy is tier 3 red and tier 1 white) and is maintained as
    `docs/research/vintage-tiers.csv`, loaded by `scripts/load_vintage_tiers.py`
    — a pull request, not a screen. A tier never scales a price. See 0015.
19. Pricing precedence ends with the **market chain**, not `CannotPrice`: manual
    price > line margin > line discount > deal margin > `buyer_discount`
    (`UK Reference x (1 - BUYER_DISCOUNT)`, then `x (1 - MARGIN_ON_SALE)` for
    what we pay the seller). `sell_price`/`cost_gbp` ARE the buyer price and the
    seller price for this basis — nothing downstream had to change — and
    `buyer_price_gbp`/`seller_price_gbp` are the same two figures under names
    that cannot be misread, GENERATED from them so they can never drift. Both
    settings are per-deal only, default 20%/8%, and recorded on every
    `pricing_result` that used them. This basis never produces `NEGATIVE_GP`,
    `COST_ABOVE_UK_REFERENCE` or `SELL_ABOVE_UK_REFERENCE` by construction.
    See `docs/decisions/0017`.

`REVIEW_FLAGS` in `app/core/flags.py` is the single definition of what forces
operator *review*: it is about evidence quality and commercial flags never go in
it. `COMP_EXCLUDED_VINTAGE_BAND` and `LOW_COMP_OUT_OF_BAND` are in it (0015):
they reach a run through `inherited_flags`, so the band can hold a line in
review and can never release one. `DERIVED_FROM_CASE` is the one named
exception to "membership alone decides" (decisions 0023, 0028): still a
member, still gates a single comp, but `BenchmarkResult.state` — not this set —
stops it gating a 2+-comp line once the band confirms agreement. `WIDE_SPREAD`
runs the same override in the other direction (decision 0033): never a member
here, so a 3+-comp line with a long tail is still READY, but `state` adds it
to the gating set when `comp_count == 2` — exactly two comps means the tail
is the whole sample, not an outlier against agreement. The buyer
*export* is a separate gate; see invariant 12 and decision 0008.

A benchmark run is self-contained: it records every contributing capture and
every offer exactly as used, so snapshots can be pruned without touching history.
Never add a cascade from `offer` into benchmark history. See 0004.

## Non-negotiables

- **Never destroy the original seller description.** `raw_description` and
  `raw_row` are preserved verbatim, always.
- **Never destroy original merchant wording.** Condition is normalised to flags
  *and* kept as prose in `condition_notes`.
- **No provider-specific AI response shape in the database schema.** All AI calls
  go through `app/ai/provider.py`. Nothing outside `app/ai/` imports a vendor SDK.
- **Portability.** Standard Postgres, standard SQL, Dockerised services. No
  platform-specific features that would make migration hard.

## Stack

Python + FastAPI · PostgreSQL · Next.js/React (responsive, must work on mobile) ·
Redis + RQ for background jobs. Sessions are cookie-based; passwords are argon2id
via argon2-cffi (never hand-rolled). No distributed infrastructure, no multi-agent
framework. Each "agent" is a plain job with structured input, structured output,
provenance and validation.

Pipeline:

```
INGEST → IDENTITY PROPOSAL → IDENTITY VERIFICATION → SNAPSHOT LOOKUP
→ DEEP MERCHANT SEARCH (gaps only) → AUCTION SEARCH → COMP VERIFICATION
→ DETERMINISTIC BENCHMARK → PRICING → HUMAN REVIEW → BUYER EXPORT
```

## Testing

```bash
python -m pytest -q                      # 422 pass, 163 skip; no network, no services
docker compose up -d                     # Postgres + Redis, then:
TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \
TEST_REDIS_URL=redis://localhost:6379/15 python -m pytest -q   # 585 pass
python scripts/rerun_burgundy_proof.py   # expect READY 0  REVIEW 15  NO_MARKET 5
python scripts/load_vintage_tiers.py    # the vintage register, from its CSV
python scripts/case_premium_report.py   # what the collected pairs say CASE_PREMIUM is
(cd docs/research/control-set && python run_band.py)   # the band over 70 lines
cd web && npm test                       # 5 tests: the browser-side parsing rules
cd web && npm run e2e                    # the whole operator flow in a browser;
                                         # needs the stack up, see web/e2e/README.md
```

`app/db/schema.sql` is the head schema. Change it only together with a new
Alembic revision in `migrations/versions/`; `0001_baseline` is frozen.
`test_migrations_reproduce_schema_sql_exactly` fails if the two disagree, and
`test_equivalence_check_detects_a_one_line_drift` proves that comparison can fail.
Spell out constraint names in migrations so they match what `CREATE TABLE` in
schema.sql generates.

Money crosses the API as JSON strings. A JSON number is refused, not converted.

**Every trap found against live merchant data becomes a permanent regression
test**, not a note in a doc. House style in `tests/test_traps.py`: name the
merchant, the wine, and the size of the error the test prevents.

Adapter tests run offline against committed fixtures. `normalise()` is pure — no
network, no clock, no randomness.

## Adding a merchant adapter

1. Investigate the live source. Official feed > plain HTTP > Playwright.
2. Capture a real response into `tests/fixtures/`.
3. Implement `fetch()` (network only) and `normalise()` (pure). The User-Agent
   comes from `app.adapters.http.user_agent()` (`COLLECTOR_USER_AGENT`), never a
   literal. Whole-book feeds go in `WHOLE_BOOK`, producer/vintage searches in
   `TARGETED` (`app/worker/jobs.py`).
4. Keep the merchant's condition wording whenever a condition flag is set
   (`condition_evidence()`); `Candidate` refuses a flag without its prose.
   Publish the merchant's LWIN-7 on `Candidate.lwin7` if it has one. It only
   ever cross-checks a name match — it never resolves identity by itself, and a
   LWIN used for two names opens an operator review. See `docs/decisions/0006`.
5. Write a regression test for every trap found, before calling it done.
6. Register the merchant in the `merchant` table with a migration.

## Collector politeness

Honest identifiable User-Agent with a contact URL. Never impersonate a browser.
Parse `robots.txt` per host at runtime — with `app/worker/politeness.py`, not
`urllib.robotparser`, which has no wildcard support and under-blocks
`Disallow: /*page=*`. Respect `Crawl-delay`. Cache aggressively.
Never follow blackhole trap paths. Where a merchant states an anti-automation
position, ask for a trade feed rather than scraping.

## Current state

Done: deterministic core, identity resolver, ten verified adapters — Farr,
Goedhuis Waddesdon and Lea & Sandeman (sweep), Bordeaux Index, FINE+RARE,
Lay & Wheeler Trading, Bordeaux Index LiveTrade, Justerini & Brooks, Berry
Bros. & Rudd and Jeroboams (search) — Postgres schema, AI provider
interface, FastAPI service (`app/api/`), Alembic migrations
(`migrations/`), RQ worker (`app/worker/`) for snapshot collection and
deterministic benchmark.

Justerini & Brooks (`app/adapters/justerini_brooks.py`), built for UK
breadth once the Champagne sweep showed 42 of 52 targets at one merchant
or none: server-rendered Next.js, but the real data is React Server
Component "flight" chunks scattered through the page, not the rendered
HTML. One family page returns every edition or vintage it currently
stocks; `familyName` is producer-first only sometimes (confirmed across
all eleven producers this adapter was built against), so the producer is
supplied by the caller, never parsed from the page. One listing can carry
TWO separate stock pools at once — a case (`stockCases`) and loose
bottles (`stockBottles`) — confirmed live on a Taittinger Rosé listing
showing both simultaneously; the adapter emits both as separate
candidates, since the loose one is this cellar's own commercial unit.
Yield against the live sweep: one line moved to READY (Dom Pérignon
Vintage 2008) — J&B's own currently-live vintages for these cuvées mostly
do not overlap this cellar's 2002-2016 back-vintages, which is itself the
finding (see `docs/research/uk-trade-current-releases-vs-back-vintage-
cellars.md`): the UK trade publishes current releases in cases; this
cellar is back-vintage, loose-bottle stock.

Berry Bros. & Rudd (`app/adapters/berry_bros_rudd.py`, decision 0030),
second of the three houses investigated for UK breadth: Vue/Nuxt SSR, but
the real price is in `window.__NUXT__`, a minified JS expression rather
than JSON, evaluated in a throwaway Node subprocess — the first non-Python
runtime dependency in this fleet, flagged to Doug before building further.
A hit's own top-level `purchase_mode`/`stock_origin`/`prices` are only ONE
variant Algolia promoted to that hit's headline; the real ladder is nested
in `purchase_options[]` and is read exclusively from there, deduped by
`bbx_listing_id` or, for a BBR-direct entry with none, by `(sku,
purchase_mode)` — confirmed live, one Taittinger hit alone carried a 300cl
Jeroboam never promoted to any top-level hit on the page at all. The price
field is keyed by `purchase_mode`, never `case_size`: "In Bond" always
prices the whole pack via `price_per_case_exact`, even at `case_size: 1`
(a single Jeroboam is still "a case of one"); "Delivery" (duty paid)
always prices ONE bottle via `price_per_bottle_exact` regardless of the
SKU's own case size. `stock_origin` `BBR` (direct stock) and `BBX` (Berry
Bros' own exchange) are one company publishing its book two ways, same
reading as Bordeaux Index LiveTrade (decisions 0026/0027), but with no
second adapter id to reconcile since both arrive on one fetch of one page.
A producer page server-renders only Algolia's own first page of results
with no pagination control that reaches a second one; `fetch()` raises
`ProducerPageTruncated` rather than return a silently partial page —
confirmed incomplete for Krug (24 of 58 editions), this cellar's largest
Champagne position, and five other producers. Built and tested; the live
collection run is still pending BBR's own Algolia search-only key (not
found) for the truncated producers, and its own `Visit-time: 0200-0700`
(UTC) window for everyone else.

Jeroboams (`app/adapters/jeroboams.py`, decision 0031), third and last of
the three houses investigated for UK breadth: server-rendered Next.js,
but the real data this time is plain JSON in `__NEXT_DATA__` — no Node
subprocess needed, unlike Berry Bros. & Rudd. Two page shapes publish the
same catalogue: an In Bond listing (`"ib-"` URL prefix) is a configurable
product whose `initialUniqueItems` carries a useless zero-price "-MAIN"
placeholder alongside the real priced variants; a duty-paid retail
listing has no such split. Duty status is read from the `sku` suffix
(`...IB`, optionally with a UUID for a second, independent stock lot of
the same unit) rather than the URL — confirmed live, the SAME wine (Krug
Grande Cuvée 173ème Édition) is published on both an "ib-" page and a
separate non-"ib-" retail page, and fetching the wrong one by mistake
still comes out right. `name` is unreliably producer-first or
cuvée-first, independently re-confirming the exact lesson Justerini &
Brooks already taught on a different merchant; `parse_cuvee()` checks
both comma segments against the product's own clean `producer` field
rather than assuming either order. A float-noise price
(`204.999996`) is passed through unchanged — `app.worker.jobs`'s own
`whole_pence()` check catches it centrally, the same way it already
catches Farr's float32 noise. An assortment case is caught as a mixed lot
by `lw_trading.py`'s own `mixed`/`assort(ment)` regex, reused unchanged.
No per-producer search endpoint exists; `product_paths` is resolved once
from the merchant's own complete product sitemap, outside the adapter,
same discipline as J&B's own `producer_paths`. The actual yield this
adapter was built for: a real, single-bottle, back-vintage, In Bond
listing (Henri Giraud Argonne Rosé 2012, £1,531) — the first UK source in
this fleet that reliably sells this cellar's own commercial unit rather
than only the case.

Bordeaux Index LiveTrade (`app/adapters/bordeaux_index_livetrade.py`,
decision 0027) reads the two-sided marketplace the sibling adapter's listing
pages do not: bid, offer and last trade, structured JSON already embedded in
the search page's own markup (no scraping of display text, no Playwright —
confirmed server-rendered live). Registered as its own merchant,
`bordeaux-index-livetrade`, for collection bookkeeping only — every `Offer`
it produces is published under `merchant_id` `bordeaux-index`, the sibling
adapter's own row, deliberately: LiveTrade and the regular listing pages are
one company, and two rows both saying "Bordeaux Index" must never count as
two merchants (invariant 4). Also fixed in passing: `app/worker/jobs.py`'s
`ingest()` was not passing `Candidate.release_code` through to
`resolve_candidate` at all, for any adapter — decision 0019 built the field
and the resolver support, nobody had wired the one call site. LiveTrade is
the first adapter to populate it (Krug's Grande Cuvée editions), which is
what exposed the gap.

A live Champagne sweep (9-10 October 2026, 84 cellar lines against all
seven adapters) found and fixed three more live-data gaps, none caught by
any fixture test because none had ever been run against the real adapter
through its real call path: Bordeaux Index's regular listing silently
rejected every NV Champagne card as "unparseable" (no leading vintage
token at all, not even the word "NV" — `parse_title`); `split_release_code`
was wired into the LiveTrade adapter only, so the other six never split a
Krug-style edition number out of a cuvée string at all; and FINE+RARE's
`fetch()` never declared the `producer_slugs` keyword
`app.worker.jobs._by_slug` always calls it with, so a real `collect_
targeted` call for fine-rare raised `TypeError`. `norm_producer` also read
"Dom" in "Dom Pérignon" as an abbreviation of "Domaine" rather than the
monastic title it is — harmless only because the same wrong expansion ran
on both sides of every match.

Decision 0028, from the same sweep, corrects decision 0023 itself:
`DERIVED_FROM_CASE` stopping gating now checks source agreement between
the comps directly (region-independent, `AGREEMENT_THRESHOLD`), rather
than only through a vintage band that exists for Burgundy alone —
without which a loose-bottle cellar priced from UK case sellers could
never produce a READY line outside Burgundy at all.

Decision 0029: identity resolution happens once, at capture time, against
whatever the registry was then, and never re-resolves on its own — every
alias added afterwards leaves already-rejected offers it would now
resolve sitting untouched in `offer_reject` forever, unless something
goes back for them. `app.worker.jobs.reresolve_rejects()` does, from
`offer_reject.raw` alone, no network: both places an alias is approved
(`POST /wines/{wine_id}/aliases`, the LWIN-conflict "same wine"
resolution) enqueue it automatically. Its own report says, per recovery,
whether that merchant already held the exact unit and at what price — a
recovered offer that duplicates a price already on the run changes
nothing; a genuinely new one might.

Pricing rules are in `app/pricing/pricer.py` (decision 0007): margin, discount,
precedence and the commercial flags, all pure and tested. The precedence ends
with the market chain (decision 0017) — buyer price, then seller receives —
rather than refusing to price a line that has nothing but a UK Reference.

Snapshot retention (`prune_snapshots`, per merchant) and alias suggestions over
the identity trail are built.

`app/market/` holds the checks that are *about* the comps rather than part of
the arithmetic, and nothing in it may change a figure the core produced:
`vintage_band.py` (decision 0015 — a comp far above its own wine's
quality-matched neighbouring vintages is excluded and recorded, a comp far below
is flagged and kept; both put the line in review), `units.py` (decisions 0016
and 0018 — any wine with a region and colour may derive a comparable across
case sizes, Burgundy's premium is measured and every other region's is an
assumption carried from it, and the paired observations that will eventually
measure them too) and `parcel.py` (decision 0014 — two merchants at one price
to the penny is an operator note, never a gate).

Operator accounts and sessions are built (`app/api/auth.py`,
`scripts/manage_operators.py`). The Next.js operator console is in `web/`:
deals and upload, one deal (Cellar Desk by default; its pipeline detail —
identity, evidence, price, sign-off — one click away), the exception queue,
and an issued offer.

Cellar Desk (`web/app/deals/[dealId]/page.jsx`) is the DEFAULT view of a
deal — what a deal link from `/` lands on — for "what can I sell right
now" rather than the pipeline console's own line-by-line, Collect/
Benchmark/Price view, which moved to `web/app/deals/[dealId]/lines/` and is
reached by an explicit "Pipeline details →" link: an operator has to go
looking for it, never land on it by accident. Cellar Desk itself is: every
priced line in one sortable, filterable table, a sticky footer with
running totals, a buyer-preview dialog and a CSV export. The pipeline
console's own Collect/Benchmark/Price buttons are disabled, with a
one-line reason shown, whenever `GET /health`'s `redis` field is not
`"ok"` — queuing a job nothing picks up is worse than refusing to; a
button that cannot succeed should not be pressable. `/health` itself
never 500s on a missing or unreachable queue (found live:
`scripts/desk.sh` runs no worker on purpose) — it reads a plain
`"unavailable"` instead of raising `Depends(queue)`'s own `RuntimeError`
before the handler body runs, which gave the frontend nothing to read.
Built from a real spec (`docs/research/cellar-desk-ui-spec.html`,
commits e762402/ad3c0dd) a prior session built with Doug as an interactive
HTML prototype, caught and fixed before being carried into real code: the
prototype let every line reach the preview/export regardless of comp count,
which would have bypassed invariant 12 for any one-merchant (`ONE_COMP`,
a `REVIEW_FLAGS` member) line, and its buyer-facing dialog used
decision 0017's direct-purchase language ("My fee") for what is actually an
agency sale under decision 0022 — the buyer pays the seller directly, Doug
invoices 8% commission, and the money never passes through this app. Both
are fixed in the real page: a thin line's evidence row carries an Accept
button wired to the SAME `/lines/{id}/pricing/acknowledge` endpoint the
existing deal page already uses (no new mechanism), and the preview/CSV
actions stay disabled while any selected line is unaccepted; every screen
says "seller nets" and "your commission, invoiced", never anything that
implies this app holds the money. Every money figure shown is read verbatim
from `pricing_result` (`buyer_price_gbp`/`seller_price_gbp`/`gp`, set only
when a line's own basis is `buyer_discount`) — nothing here recomputes a
price from `uk_reference`. `scripts/seed_cellar_desk_demo.py` seeds a small,
real-shaped deal (one thin line, one agreeing pair, one disagreeing pair)
for exercising the screen by hand; not a fixture, not part of any suite,
and idempotent (reuses the deal by name rather than seeding a second copy).
`scripts/seed_cellar_desk_real.py` seeds the real thing instead: the 30
lines the 9 October 2026 Champagne sweep actually priced, reconstructed
from `docs/research/cellar-desk-ui-spec.html`'s own real `ROWS` data (each
`sources[].p` there is already FX-converted for display; confirmed by
dividing by the spec's own 10.37 and finding it lands on that line's `ref`
to the penny, so this script undoes that conversion rather than seeding
HK$ amounts as if they were GBP) — real producers, real cuvées, real
per-merchant GBP asks, fed through the real benchmark and pricer so the
engine derives its own floor/reference/state exactly as it did live,
nothing hardcoded. Three demo rows cannot tell Doug whether the screen
actually works for him; thirty real ones can. `scripts/desk.sh` seeds
both, every run, and prints both URLs.

Found seeding that real data and fixed: this file's own badge/filter logic
had invented a third tier ("two merchants, agreeing" vs not) from the
gap between two merchant-bests, which is not how the real engine gates at
all — `WIDE_SPREAD` is deliberately not a review flag (CLAUDE.md itself:
"with two or more independent merchants the Reference is sound even when
the tail is long"), so a two-merchant line 57% apart is READY, same as
one 1.5% apart; only `ONE_COMP` gates. Confirmed against the real sweep:
11 lines READY, several of them wide-spread, not only the ones that
happen to agree closely. The badge and the two real filters ("Everything",
"Ready to send", "Needs you" — Doug's own plain-language correction of an
earlier "two merchants, agreeing") now read that same boolean the gate
itself uses, nothing invented; the filter bar hides itself under ten
priced lines, where it is clutter rather than a tool. The spread itself
is still shown, as evidence, one click down in the row's own expansion —
informational, same as the engine's own `WIDE_SPREAD` flag, never a gate.
The buyer preview shows every selected line, scrollable, not a top six
and a count of the rest: with thirty real lines, the preview **is** the
offer, not a sample of it.

That "only `ONE_COMP` gates" reading did not survive its own next look.
Doug checked the 11 READY lines by hand and found four of them pricing
ABOVE the cheapest ask actually found — decision 0033,
`SELL_AT_OR_ABOVE_UK_FLOOR`, and the comp-count==2 exception to
`WIDE_SPREAD`'s own non-gating rule. READY on this same real sweep is 7,
not 11, as of that decision.

`scripts/desk.sh` is the one command that gets Doug from nothing to that
screen: no Docker, no psql, no Postgres.app on his machine, so it drives
embedded Postgres (`scripts/desk.mjs`, the same package the Postgres test
runs already use) rather than `docker compose`. It creates `.venv` and
installs if either is missing, starts Postgres from a data directory under
the repo at `.localdb/` (gitignored; deliberately not `/private/tmp`, where
this feature's own embedded Postgres was once silently wiped mid-session,
taking a day's work with it), runs migrations, runs the seed script, starts
`uvicorn` and `next dev`, and prints the deal URL, username and password as
the last thing on screen — nothing after it. No Redis, no worker: Cellar
Desk reads prices that already exist, so the job queue is never needed, and
the script does not start one or fail when Redis is absent. Idempotent:
running it again while it's already running just reprints the URL; running
it after a clean shutdown skips straight back to a running stack in a few
seconds. Ctrl-C stops everything it started, Postgres included.

Decision 0033's own gate caught a line priced AT or ABOVE Floor. It said
nothing about a line priced a few pence below it while still claiming a
round 20% — decision 0034: Dom Pérignon Vintage 2010 at 0.9% below Floor
and Louis Roederer Cristal 2007 at 4.0%, both real, both found the moment
Floor replaced Reference as the basis for the number itself, not just the
gate. Every percentage claim is now `1 - sell_price/uk_floor`
(`app/core/flags.py::floor_saving`), computed once, server-side, never
derived from Reference and never averaged across a drop; a real saving
below `MIN_CLAIM_THRESHOLD` (5%, a starting value, Doug's own) prints as no
claim at all, exactly as invariant 15 already treats a line with no UK
Reference — still sellable, just not advertisable as a discount.
`PricingOut.floor_saving_claim` is the one place this is computed; the Desk
and the new client document both read it, neither recomputes it.

"Needs you" on the Desk used to be a bare badge. Doug had to ask why three
real lines carried it before he could act on any of them — the engine
already knew (`ONE_COMP`, `DERIVED_FROM_CASE`, `QUANTITY_SHORTFALL`,
`WIDE_SPREAD` at `comp_count == 2`, the pricing flags that gate export),
this file just never said so. `reasonFor()` in
`web/app/deals/[dealId]/page.jsx` maps every one of those flags to one
short human phrase, on the row, no click — "1 merchant", "1 merchant ·
case divided", "2 merchants, 57% apart", "stock basis unconfirmed" — and
the same mapping now drives the evidence row's own gate box, so the two
never disagree. It decides nothing: `gated()` already read
`requires_acknowledgement` straight from the server, and still does.

The client document still needed a document nobody but Doug could open —
"how might I message them?" was the next, obvious gap. Decision 0035:
`shared_offer_link` is a signed, unguessable, time-boxed public link
(`/share/{token}`, no login, 7-day expiry) for a chosen set of a deal's
lines, in one of two shapes — a buyer never sees cost or commission
(structurally: `build_public_payload` never adds the key for that kind,
not a null one), a seller may see commission but never the rest of the
cellar. A line still gated under invariant 12 cannot be put behind one —
a public link is itself a kind of export. The Desk's own offer document
gained a composer: a kind toggle, a generated link, and a pre-filled,
editable WhatsApp message naming the top three lines and their per-bottle
prices, opened on WhatsApp's own share sheet (`wa.me`, decision 0025's
exact mechanism, reused) or copied as plain text for WeChat or a group.
Testing it with a genuinely cookie-less browser context — the shape of
visit a real buyer always is — found a latent bug in `web/app/chrome.jsx`
that had nothing to do with this feature: its public-path check governed
only what rendered, not the redirect effect sitting above it, so a
first-time visitor to ANY public page (VESSEL's own, a member's own, and
now a shared offer link) got bounced to `/login` the instant their
sessionless check came back "out", which it always does. Fixed once,
centrally (`isPublicPath()`), for all four.

Decision 0035's composer shipped with a placeholder message, by its own
admission — Doug drafted three real ones separately, and decision 0036
wires them in. Three, not two: a buyer alone reads differently from a
buyer group (which gets the wine names and the link, no price, no top
lines at all). `web/lib/offerMessages.js` holds all three, and the rules
Doug gave "to enforce in code, not the copy" are properties of that code:
a buyer message cannot reach a seller/commission/cost/margin figure
because no buyer builder has a branch that touches those fields, checked
a second time by `assertBuyerSafe()` scanning the finished string; no
percentage prints where decision 0034 would have suppressed it, whether
one selected line's own claim is null or the whole drop's blended figure
falls under the same threshold; and a message past roughly 600
characters drops from three top lines to two before it is ever shown.
The templates reference `{city}` as an existing fact on the deal that
never was — `deal.city`, nullable free text entered once by the
operator, is the fix; null is never guessed at, only ever omitted from
the sentence it would have filled.

Doug, on the pipeline page's own legacy buyer-offer form: `line
b76ec9c8-672d-4fdf-a11c-cd2a9a0053e0 is priced REVIEW and has not been
acknowledged` — "that message is unacceptable and it is the third time."
Decision 0037, in two parts. First, every error string the API can
return to a screen was audited in one pass, not patched instance by
instance: `app/db/repo.py::gate_reason_phrase` builds one English clause
from the real flags behind `requires_acknowledgement` ("rests on one
merchant", "would lose money"), `wine_display_name` is the one name
every such error now uses to refer to a line — never a line_id, never a
wine_id — and `create_buyer_offer` collects every unaccepted line across
a submission into one message, singular at one line and plural at
several, rather than stopping at the first. The same pass removed raw
ids and raw state/flag names from VESSEL's mandate, listing and
reservation errors, the LWIN conflict resolution, auction evidence
retraction, a benchmark comp reinstatement, and two worker-job
`LookupError`s that stringify straight into the RQ traceback the
pipeline page already shows verbatim. `web/lib/pricingReasons.js`
extracts the Cellar Desk's own "needs you" phrase logic so
`web/app/deals/[dealId]/lines/line.jsx`'s "this price needs accepting"
notice reads from the same function instead of a second, incomplete one
(`.replaceAll("_"," ")` on two hardcoded flags, missing a third decision
0033 had already added).

Second: `issue.jsx` — the pipeline page's own Client+Terms+checkboxes
form, and how Doug found that message at all — predates the Desk, the
offer document and the share link, and has no acceptance step: its
"needs sign-off first" tag was informational only, never a disabled
button. Deleted outright. "There should be exactly ONE route from a
cellar to a buyer, and it should be the one with the gate in it" — the
pipeline page's own "Buyer offers" section is now one sentence and a
link to the Desk; its read-only history of already-issued offers stays,
since nothing asked for the records or the API to change, only the UI
that could create one without a gate.

Doug's biggest clients have a standing want list of ten Burgundy
producers — six of the ten ambiguous in a way worth 5–20×, which makes
identity rules load-bearing before any price is attached. Decision 0038
builds `docs/research/want-list-producer-rules.md` verbatim:
`app/identity/want_list.py` matches raw, unsplit supplier text against
ten require/exclude rules — a SUGGESTION only, never an auto-resolve, and
a different job from the resolver's own exact wine_key lookup, which
only ever judges text an adapter has already split into producer and
cuvée. A bare "Leroy" never auto-resolves even on a clean match, because
Maison Leroy is a legitimate different market at a fraction of the
price; "comte" alone never identifies Comtes Lafon, because Héritiers du
Comte Lafon is the family's own Mâcon estate; "morey" is never a
standalone token for Pierre-Yves Colin-Morey, because Morey-St-Denis is
an appellation and punctuation-stripped text can bring "colin" and
"morey" adjacent across a comma that was never meant to join them.
`wine.want_list` is set once, from the producer alone, at creation; a
line resolving to a want-list wine requires a named operator's
acknowledgement once — "even when identity resolves cleanly and even
when two merchants agree" — tied to the LINE itself
(`seller_line.want_list_ack_by`/`_at`), not to any one pricing run, so it
survives a reprice, and checked wherever decision 0037 already checks
the pricing gate: the legacy `create_buyer_offer` path and the
shareable-link path alike, both using the same human-message machinery
that decision built. Not a new flag in `app/core/` — "a listing-side
requirement, the same way decision 0025's invite gate sits outside the
engine." Auditing the shareable-link path for where to add this found
the exact raw-UUID leak decision 0037 was meant to close, missed there —
fixed in the same pass, using the same `wine_display_name`/
`gate_reason_phrase` helpers, now public across the module boundary.

Decision 0039, asked for alongside 0038 once its own scope settled these
wines "arrive in ones and twos" and Doug prices them manually from his
own Wine-Searcher account: a single-line, buy-side evaluation screen
(`web/app/evaluate/page.jsx`, `app/evaluate/repo.py`), built on decision
0024's own hand-entry discipline, not its code — a person types a fact
they actually saw, with a named source, never a scraper. Each comp Doug
names becomes a real `offer` row under a real `snapshot`/
`snapshot_merchant`, through `ensure_manual_merchant` (an open list,
deliberately unlike the four closed auction houses, since Wine-Searcher
aggregates far more retailers than this fleet has adapters for), so
`app.core.benchmark` runs completely unchanged and cannot tell a
hand-typed offer from a scraped one — "the band check catching a
mistyped GBP1,200 for GBP12,000 is worth more than the automation we
aren't building." `app.worker.jobs.benchmark_with_band` (made public for
this) is called directly, synchronously, no RQ job, the same
orchestration `benchmark_deal` already runs per line. No sell-side
pricing runs here at all — "is this a good price" is the asking price
against the Floor/Reference, a frontend display comparison
(`gapPercent`), never a new backend rule. Every evaluation lands as one
more line of a single, persistent "Buy-side evaluations" deal rather
than a fresh one each time, since Doug does this often and would rather
browse a history than a pile of one-line deals. `match_want_list`
(decision 0038) runs live as Doug types, suggestion only, same discipline
as everywhere else. Live verification against the real desk database
caught two bugs before they reached Doug: `LineOut.benchmark`
(`RunSummary`) carries no per-comp breakdown — that's `RunOut`, the
dedicated `GET /lines/{id}/benchmark` endpoint's own response, the same
split `line.jsx` already lives with — and the comp table needed the same
`"comparable"`-role filter `line.jsx`'s own table already applies, or a
merchant with one offer shows up twice. The same verification pass also
confirmed the actual point of this decision: a real evaluation run
combined REAL adapter-collected evidence already in the database
(Bordeaux Index, Justerini & Brooks) with manually-entered comps in one
benchmark, not two separate worlds.

The seller's spreadsheet is parsed **in the browser** (`web/lib/lines.js`,
covered by `npm test`); the original row goes to the API verbatim as `raw_row`,
which the API requires and refuses empty.

DEEP MERCHANT SEARCH is built (`deep_search`, `merchant_search_key`), and a
Playwright smoke test drives the whole operator flow.

Merchant specs and the control-set evidence are in `docs/research/`.

`app/vessel/` is VESSEL Private Sale (decision 0020): a side business, not
a company being grown (decision 0022 — two to three cellars a year, the
five-year growth and referral/club model parked, not pursued) — a
consignment marketplace, not the direct-purchase business the rest of this
file describes. VESSEL lists a seller's own wine under a time-boxed
mandate, names which market it is priced against (`UK_IN_BOND` or
`HK_RETAIL`, decision 0021 — a wine may carry a reference in both, and a
listing says which one priced it), and takes a fee when it sells. It
shares no table with `buyer_offer`/the chain, reads only `benchmark_run`
and `vintage_band_check` from the engine, and does not touch `app/core/`.
`engine.py` is the pricing and evidence rules (pure); `repo.py` is the
persistence, including the partial-unique-index reservation lock and the
triggers that make a mandate, an approved listing's price, and a captured
market reference immutable. Settlement is a term of the mandate
(`settlement_mode`, decision 0022): AGENCY by default — the buyer pays the
seller directly and VESSEL invoices an 8% commission per mandate, never
holding the money, structurally enforced by a trigger that forbids a
matched payment under an AGENCY mandate — and PRINCIPAL, the original
assumption, kept legal but unused and untested until someone needs it.
`docs/research/offer-document-spec.md`'s `seller_offer`/`seller_offer_line`
is a different, direct-purchase business and is marked superseded: not to
be built unless asked for by name. Two FastAPI routers (`app/api/vessel.py`):
one public (seller approval, drop, wine page, buy, proof of payment — no
login exists for sellers or buyers, by the spec's own admission, not a
developer's call), one behind the existing operator session (recommending
lines, drops, payments, seller-receipt confirmation, the commission
invoice, analytics). Four page routes in `web/app/vessel/` cover the five
specified screens.

`app/auction/` is operator-entered auction evidence (decision 0024), never
a scraper: a person reads a public lot page and types six facts in, with a
mandatory source URL. It is a health check, never a price — it never sets,
moves or substitutes for the UK Floor, Reference or Median, and nothing
under `app/core/` or `app/pricing/` imports it, checked statically, not by
convention. The closed house list is `BONHAMS`, `CHRISTIES`, `HERITAGE`,
`ZACHYS` — the last two added over their own stated personal/non-commercial
terms, on Doug's explicit instruction; said out loud in decision 0024, not
done quietly. Nothing here scrapes any of the four houses' sites; Heritage's
terms separately and additionally prohibit automated collection outright,
which this does not touch. `auction_result` (`0001_baseline`) is an earlier,
unused design for the same idea, imported by nothing; left in place because
baseline is frozen, not because it is live.

`app/member/` is buyer referrals, the smallest version that works
(decision 0025): `member` is VESSEL's first buyer account, phone-
identified, no password — proved once by a one-time code at invite
acceptance, never a persistent session. One open invite per member at a
time (`invite_one_open_per_inviter`, a partial unique index, not
application logic); first touch permanent (a phone that already accepted
one invite cannot accept another); the reward is on a completed purchase
only, never on signup, and it is access — `early_access_until`, 48 hours —
never cash. `app/notify/provider.py` is the SMS seam, same discipline as
`app/ai/provider.py`: `ConsoleNotifier` (logs the message) is the only
provider wired up, since no real one has been chosen yet. Wired into
VESSEL at exactly one point — `confirm_first_purchase` is called from
`app/api/vessel.py`'s confirm-seller-receipt route, never from inside
`app/vessel/` itself, which stays exactly as decision 0022 left it. A
seller introduction (`seller_introduction`) captures a name and a phone
against the introducer's own mandate; linking it to the lead's eventual
mandate, and paying the 1%, is a manual step, not automated. Explicitly
NOT built, named directly so nobody adds them later "out of tidiness":
waitlist positions, status tiers, membership caps, cash credits, buyer
ranking, the Thursday drop cadence, "My Cellar", or anything else from the
parked growth/club document.

Not built yet: the LWIN import (decision 0012 — waiting on the file), Albany and
Vinum, the remaining merchant adapters, AI provider implementations. A client-
and buyer-facing exported document (HTML/PDF) is specified
(`docs/research/` build brief, 5 October 2026) but not built: it needs a
design decision this file does not make alone. The vintage register covers
Burgundy only: Bordeaux, Champagne, the Rhône, Piedmont and Tuscany are
missing, and the band stays quiet for them until they are added — unit
derivation (decision 0018) does not wait on this and already covers every
region with a wine's own region and colour recorded. Stock location/landed
cost (multi-jurisdiction bond) and deal workflow at scale (bulk identity
approval, value-ordered queues, partial offers) are specified, not built.
VESSEL's drop one is built end to end (recommend, approve, drop, buy,
reserve, pay); its own "drop two to five" work is not — automated payment
matching, a scheduler for reservation timeouts, buyer/seller KYC, re-drop
and re-price within a floor, and the transfer/settlement step that would
write `vessel_listing.settled_at`.

Known open questions are in `docs/decisions/` and in the Burgundy proof report.
