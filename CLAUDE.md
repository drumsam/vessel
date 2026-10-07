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
   *gating* (never stops being shown) once 2+ merchants' comps agree with
   their own quality-matched neighbouring vintages (decision 0023: "trusts
   source agreement, not the constant"); one comp never qualifies, and
   neither does a line whose region has no vintage band at all. Magnums and
   half bottles never convert, either way. The core is told which lines
   qualify; it does not know what a region is. See `docs/decisions/0016`,
   `0018`, `0023`.
3. Depth counts merchants, not listings.
4. Floor = lowest merchant-best · Reference = second-lowest (or the only one,
   flagged `ONE_COMP`) · Median = median of merchant-bests.
5. Hard screens: In Bond, ASK, GBP, buyable, positive price, whole pence, not a
   mixed lot. Every rejection is retained with its reason. A brokerage
   `INDICATION` is not an ASK and never prices; it is kept as corroboration
   beside cross-unit evidence, with its variance from the Reference. See 0013.
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
12. `NEGATIVE_GP` and `SELL_ABOVE_UK_REFERENCE` gate the buyer export until a
    named operator accepts them (decision 0008), and so do the benchmark states
    `NO_MARKET` and `REVIEW` (0010). `COST_ABOVE_UK_REFERENCE` and
    `DEEP_DISCOUNT` are context: selling below market is the product.
15. **A line with no UK Reference may not carry a market claim.** No "UK
    Market", no "% below" — absent, not blank. `buyer_offer_market_claim` has a
    NOT NULL reference, so a line without one has no row and a document has
    nothing to print. See 0010.
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
exception to "membership alone decides" (decision 0023): still a member,
still gates a single comp, but `BenchmarkResult.state` — not this set —
stops it gating a 2+-comp line once the band confirms agreement. The buyer
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
python -m pytest -q                      # 347 pass, 161 skip; no network, no services
docker compose up -d                     # Postgres + Redis, then:
TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \
TEST_REDIS_URL=redis://localhost:6379/15 python -m pytest -q   # 508 pass
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

Done: deterministic core, identity resolver, six verified adapters — Farr,
Goedhuis Waddesdon and Lea & Sandeman (sweep), Bordeaux Index, FINE+RARE and
Lay & Wheeler Trading (search) — Postgres schema, AI provider interface,
FastAPI service (`app/api/`), Alembic migrations (`migrations/`), RQ worker
(`app/worker/`) for snapshot collection and deterministic benchmark.

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
deals and upload, one deal (identity, evidence, price, sign-off), the exception
queue, and an issued offer.

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
