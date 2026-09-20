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
2. Commercial unit equality is exact. No division, no multiplication, ever.
3. Depth counts merchants, not listings.
4. Floor = lowest merchant-best · Reference = second-lowest (or the only one,
   flagged `ONE_COMP`) · Median = median of merchant-bests.
5. Hard screens: In Bond, ASK, GBP, buyable, positive price, not a mixed lot.
   Every rejection is retained with its reason.
6. Zero comparables ⇒ `NO_MARKET`.
7. Money is `Decimal` in Python and `numeric(14,2)` in Postgres. No float ever
   touches a price. Exactly three places round, all ROUND_HALF_EVEN to pence:
   the Median (`benchmark.py`), FX conversion of a non-GBP cost and the sell
   price (`app/pricing/pricer.py`). A price that is not whole pence is refused
   as `NOT_WHOLE_PENCE`, never rounded. See `docs/decisions/0007`.
8. Freshness: an offer is comparable only if captured within
   `MAX_OFFER_AGE_DAYS` (14) before `as_of`, and not after it. Undated ⇒ `STALE`.
   `as_of` is an argument, never the clock. See `docs/decisions/0003`.
9. Inherited line flags (`NAME_REVIEW`, `FORMAT_REVIEW`, `DERIVED_FROM_CASE`)
   are unioned in before state is derived, and only review flags may be
   inherited: they can hold a line in review, never release one. See 0005.

10. `NO_MARKET` means every approved merchant was searched and none offers the
    wine. A line nobody has searched is `NOT_SEARCHED`: no run, no price, no
    buyer export. Never blur the two.

`REVIEW_FLAGS` in `app/core/flags.py` is the single definition of what forces
operator review. `ONE_COMP` is in it deliberately: one merchant is not a market.
Commercial flags (`NEGATIVE_GP`, `DEEP_DISCOUNT`, …) are context, not gates.

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
Redis + RQ for background jobs. No distributed infrastructure, no multi-agent
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
python -m pytest -q                      # 167 pass, 53 skip; no network, no services
docker compose up -d                     # Postgres + Redis, then:
TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \
TEST_REDIS_URL=redis://localhost:6379/15 python -m pytest -q   # 220 pass
python scripts/rerun_burgundy_proof.py   # expect READY 0  REVIEW 5  NO_MARKET 15
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
Parse `robots.txt` per host at runtime. Respect `Crawl-delay`. Cache aggressively.
Never follow blackhole trap paths. Where a merchant states an anti-automation
position, ask for a trade feed rather than scraping.

## Current state

Done: deterministic core, identity resolver, three verified adapters (Farr,
Bordeaux Index, Goedhuis Waddesdon), Postgres schema, AI provider interface,
FastAPI service (`app/api/`), Alembic migrations (`migrations/`), RQ worker
(`app/worker/`) for snapshot collection and deterministic benchmark.

Pricing rules are in `app/pricing/pricer.py` (decision 0007): margin, discount,
precedence and the commercial flags, all pure and tested.

Not built yet: Next.js frontend, the remaining ten merchant adapters, AI
provider implementations, buyer export (the tables exist), the auction layer,
and snapshot retention.

Known open questions are in `docs/decisions/` and in the Burgundy proof report.
