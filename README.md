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

## Money

`Decimal` in Python, `numeric(14,2)` in Postgres. No float touches a price at any
point. `£2,353.10` stays `£2,353.10` through calculation, persistence and output.

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
| `COLLECTOR_USER_AGENT` | honest, identifiable UA with a contact URL |
| `SNAPSHOT_RETENTION` | how many snapshots to keep for run-diffing |

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
python scripts/rerun_burgundy_proof.py
```

`pytest` needs no network: every adapter test runs against committed fixtures.

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
