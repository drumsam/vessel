# UK Fine Wine Deal Pricer

An operator loads a seller's wine list. The system finds the lowest verified
comparable UK In Bond offer from an approved merchant universe, applies a
discount or a target margin, and produces a client-facing offer.

**Accuracy is more important than coverage. Never invent, estimate or silently
substitute a market price. Fail closed.**

---

## The one architectural rule

> **Agents propose. Deterministic code disposes.**

AI is used for interpreting messy seller text, searching awkward merchant sites,
extracting candidate evidence and challenging proposed matches. It is never used
for identity approval, format comparability, duty filtering, benchmark
arithmetic, margins, or any figure on a client document.

A corollary that matters when you add merchants:

> **The adapter contract may evolve as new merchants are investigated.
> The deterministic pricing invariants must not.**

`app/core/benchmark.py` is the locked part. If you find yourself editing it to
make a merchant fit, the merchant belongs in an adapter or in identity
resolution instead.

---

## Pipeline

```
INGEST → IDENTITY PROPOSAL → IDENTITY VERIFICATION → SNAPSHOT LOOKUP
  → DEEP MERCHANT SEARCH (only for gaps) → AUCTION SEARCH → COMP VERIFICATION
  → DETERMINISTIC BENCHMARK → PRICING → HUMAN REVIEW → BUYER EXPORT
```

Each stage is a plain job with structured input, structured output, provenance
and validation. There is no multi-agent framework and none is needed.

## Layout

```
app/
  core/          deterministic only — no network, no LLM, no name matching
    enums.py     closed vocabularies
    models.py    Offer, SellerLine (Decimal money)
    flags.py     Flag, REVIEW_FLAGS — the single definition of "needs review"
    benchmark.py UK Floor / Reference / Median
  identity/
    resolver.py  the ONLY place producer and cuvee names are interpreted
  pricing/
    pricer.py    sell price, GP, gross margin, commercial flags (pure)
  api/           FastAPI service
  worker/        RQ jobs: collection, deep search, benchmark, pricing
  adapters/
    base.py      Adapter protocol: fetch() network, normalise() pure
    condition.py merchant condition prose -> ConditionFlag
    farr.py  bordeaux_index.py  goedhuis.py
  ai/
    provider.py  provider-independent interface + factory
  db/
    schema.sql   PostgreSQL, NUMERIC money, standard SQL
tests/
  test_traps.py  every live-data trap as a permanent regression test
  fixtures/      captured merchant responses — normalise() runs offline
docs/decisions/  numbered decision records
scripts/         proof runners
```

## Invariants enforced by `app/core/benchmark.py`

1. Identity is compared by **approved `wine_id` only**. The pricing core does not
   know what a producer or a cuvée is.
2. Commercial unit equality is **exact**. 1×75cl matches 1×75cl. No division, no
   multiplication, ever — see `docs/decisions/0001`.
3. Depth is counted in **merchants, not listings**. A merchant cannot become its
   own second-lowest reference by listing twice.
4. Floor = lowest merchant-best · Reference = second-lowest (or the only one,
   flagged `ONE_COMP`) · Median = median of merchant-bests. Reference drives
   pricing; Floor and Median are internal.
5. Duty status, price kind, currency, buyability and positive price are all hard
   screens. Every rejection is retained with a reason.
6. Zero comparables ⇒ `NO_MARKET`.
7. **Freshness.** Only offers captured within 14 days before `as_of` (and not
   after it) are comparable; the rest are rejected as `STALE` and stay visible.
   See `docs/decisions/0003`.
8. **Inherited line flags** can hold a line in review, never release one. See
   `docs/decisions/0005`.
9. **A merchant's LWIN cross-checks a name match; it never resolves identity on
   its own**, and a LWIN used for two wine names opens an operator review rather
   than being discarded. See `docs/decisions/0006`.
10. **`NO_MARKET` is not "not searched".** A line no merchant has been searched
    for has no benchmark run, so it cannot be priced or exported. Line status is
    derived on read, never stored.
11. **A price below cost, or above the UK Reference, cannot be exported** until
    a named operator accepts it. See `docs/decisions/0008`.

Benchmark runs resolve each merchant's latest covering capture independently and
keep every offer exactly as used, so snapshots are a prunable cache. See
`docs/decisions/0004`.

## Money

`Decimal` in Python, `numeric(14,2)` in Postgres. No float touches a price at any
point. `£2,353.10` stays `£2,353.10` through calculation, persistence and output.
The API carries money as JSON strings and refuses JSON numbers with a 422.
Exactly three places round, each to pence with banker's rounding and each tested
in both directions: the Median (`app/core/benchmark.py`), FX conversion of a
non-GBP cost, and the sell price (`app/pricing/pricer.py`). Any other value that
is not whole pence is refused, not rounded. See `docs/decisions/0007`.

## Pricing

```
Sell from margin     Sell = Cost / (1 - target_margin)
Sell from discount   Sell = UK Reference * (1 - discount)
Gross margin         GM   = (Sell - Cost) / Sell        -- margin, never markup
```

Precedence: manual price > line margin > line discount > deal margin. A non-GBP
cost needs the FX rate, its date and its source, which are stored with the
result. `DEEP_DISCOUNT` fires when the sell price is more than 25% below the UK
Reference; that threshold is a default, is configurable per run, and the value
used is stored. See `docs/decisions/0007`.

## Operators

Sign-in is a cookie session; passwords are argon2id. The server fills
`approved_by`, `priced_by` and `acknowledged_by` from the session, and refuses a
body that names someone else. Audit rows store `operator_id`, so renaming an
operator rewrites nothing, and access is revoked with `active` rather than by
deleting a row the history points at.

```bash
python scripts/manage_operators.py add alice "Alice Baker"   # prompts for a password
python scripts/manage_operators.py password alice            # an admin resets; no self-service
python scripts/manage_operators.py disable alice             # revoke, keeping the history
```

## Review gating

`REVIEW_FLAGS` in `app/core/flags.py` is the only definition of what forces
operator review. `ONE_COMP` is in it: a single merchant is not a market.
`WIDE_SPREAD` is deliberately not — with two independent merchants the Reference
is sound and the spread is context.

`REPACK` and `NO_ORIGINAL_CASE` do **not** force review. In the loose-bottle
Burgundy market they are the norm, and gating on them trains operators to click
through warnings.

## Adding a merchant adapter

1. Investigate the live source. Prefer an official feed, then plain HTTP, then
   Playwright. Capture a real response into `tests/fixtures/`.
2. Implement `fetch()` (network only) and `normalise()` (pure).
3. `normalise()` returns a `Candidate` (offer with `wine_id=""` plus the
   merchant's own producer/cuvée text) or a `Rejected` with a reason.
4. **Write a regression test for every trap you find** before the adapter is
   considered done. See `tests/test_traps.py` for the house style: name the
   merchant, the wine, and the size of the error the test prevents.
5. Register the merchant in the `merchant` table.

Never loosen a pricing rule to make an adapter fit.

## Adding an auction source

Auction is a health check. It never sets UK Reference. Normalise every result to
hammer first, store `premium_included` and `premium_rate` explicitly, and if a
source's premium basis cannot be established, **do not ingest it** — a 25% error
in either direction is worse than no auction column. Mixed lots, unclear lot
composition and condition-annotated lots go to quarantine, not into the series.

## Changing AI provider

```bash
AI_PROVIDER=openai
AI_MODEL=<model id>
```

`app/ai/provider.py` is the only module that resolves a provider name to an
implementation. Nothing outside `app/ai/` imports a vendor SDK, and no provider
response shape appears in `schema.sql`.

## Environment variables

| Name | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | queue backend |
| `AI_PROVIDER` | `anthropic` \| `openai` \| `gemini` |
| `AI_MODEL` | provider model id |
| `COLLECTOR_USER_AGENT` | **required** for collection: honest, identifiable UA with a contact URL |
| `SNAPSHOT_RETENTION` | captures kept **per merchant** by `prune_snapshots` (default 10) |
| `FRONTEND_ORIGINS` | comma-separated origins allowed to call the API with a session cookie |
| `INSECURE_COOKIES` | `1` only for local HTTP development; the session cookie is `Secure` by default |

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python scripts/rerun_burgundy_proof.py

docker compose up -d                  # Postgres 17 + Redis 7
export DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer
export REDIS_URL=redis://localhost:6379/0
export COLLECTOR_USER_AGENT="UKFineWinePricer/1.0 (+https://your.site/contact)"
alembic upgrade head                  # schema + the three verified merchants
uvicorn app.api.main:app --reload     # API
python -m app.worker                  # RQ worker, queue "pricer"
# on macOS: RQ_WORKER_CLASS=simple python -m app.worker
#   the forking work-horse aborts on any job that touches TLS; see app/worker/__main__.py
```

Postgres-backed tests run only when `TEST_DATABASE_URL` points at a disposable
database; they drop and recreate its `public` schema. Compose creates one,
`pricer_test`. Set `TEST_REDIS_URL` (e.g. `redis://localhost:6379/15`) to run the
queue path through real Redis instead of fakeredis.

`pytest` needs no network: every adapter test runs against committed fixtures.

## Operator console

```bash
cd web && npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
npm test                                   # the browser-side parsing rules
```

The API must list the app's origin in `FRONTEND_ORIGINS`, and for local HTTP
also needs `INSECURE_COOKIES=1`, because the session cookie is `Secure` by
default. Screens: deals and upload, one deal, the exception queue, an issued
offer. The seller's spreadsheet is parsed in the browser and the original row is
sent verbatim.

## Deployment

Frontend on Vercel · backend and jobs on Railway or Render · PostgreSQL on
Supabase. Backend services are Dockerised. Avoid platform-specific features that
would make migration difficult.

## Collector politeness

One honest, identifiable User-Agent with a contact URL. Never impersonate a
browser, never identify as a named-blocked agent. Parse and honour `robots.txt`
per host at runtime, not from a hardcoded list. Respect declared `Crawl-delay`.
Cache aggressively and refetch only on a published `lastUpdated` change. Never
follow blackhole trap paths. Where a merchant states an anti-automation position,
ask for a trade feed rather than scraping — most already produce one.
