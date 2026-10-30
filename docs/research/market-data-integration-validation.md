# Market evidence integration validation

Branch: `integration/market-evidence`, based on `pricer` commit `aeb496b`.
No merge into `main`, deployment, production database access or live collection.

## Checks actually executed

- Full backend suite with disposable Postgres 18 and Redis: **801 passed**, no
  skipped tests in that run (231.81 seconds). Includes migration/schema equivalence,
  upgrade/downgrade, merchant adapter fixtures, identity/want-list gates, and
  existing sell-side pricing, export and market-claim safeguards.
- After final identity-review protection: **77 passed** in the focused Pocket,
  integrated evidence and auction suites (56.27 seconds). This includes the new
  regression proving an evidence read cannot overwrite a later identity review.
  These are a rerun/subset, not 77 additional unique tests on top of 801.
- Frontend unit tests: **45 passed**, none skipped.
- Next.js production build: passed, including the updated Pocket route.
- Real Chromium browser journey: **1 passed** against the existing same-origin
  frontend/API proxy. It signs in, enforces want-list acknowledgement, confirms
  canonical identity, refreshes through the existing Bordeaux Index adapter,
  uploads an auction CSV, checks import counts survive evidence refresh, and sees
  merchant and auction rails separately. It was repeated with fixture reset to
  verify another upload/refresh works rather than merely displaying old data.
- New importer/reference modules: Ruff checks passed. Git whitespace checks passed.

The browser harness replaces AI parsing and merchant HTTP transport with explicit
fixtures. Authentication, canonical identity lookup/confirmation, Postgres,
benchmark persistence, importer and UI are real. It never exercises production
credentials or asserts live market coverage. Existing offline adapter fixtures
and the source's established search-key path are used.

## Final-code cache measurement

20 authenticated HTTP requests over loopback to the local API, all asserting a
cache hit and the same persisted benchmark run ID. Disposable Postgres 18,
fixture-sized evidence, no external source requests; measured while the final
frontend build was also running.

- Minimum: 25.15 ms
- Median: 39.75 ms
- 95th percentile: 94.04 ms
- Maximum: 126.58 ms

All samples were below the 500 ms target. This is local evidence, not a hosted
production latency guarantee or a large-dataset load test. Reads still validate
inputs against local source records; cached benchmark arithmetic is reused.

## Scope and schema

Reused Postgres, canonical identity/reject recovery, adapters/search keys,
snapshot health, benchmark arithmetic/history, auction evidence, Pocket and its
existing evaluate/collect-now contract. No new table, database, collector,
scheduler, dashboard, identity taxonomy or valuation engine.

Migration `0037_market_evidence` adds:

- `auction_evidence.raw_evidence` JSONB.
- `auction_evidence.import_key` nullable text and an active-event unique index.
- `benchmark_run.evidence_key` nullable text for persistent cache validity.

Schema.sql and EXPECTED_HEAD_REVISION are updated together. The fingerprint
column is the smallest addition that records input validity without a second
cache store or modifying immutable observation payloads.

## Files changed

- `app/api/inbound.py`, `app/api/schemas.py`: evidence response, literal seller
  ask, authenticated import route, explicit refresh and identity-only blocking.
- `app/inbound/repo.py`: bound line updates only on explicit reconfirmation.
- `app/market/reference.py`: cache validity and existing-result projection.
- `app/auction/importer.py`, `app/auction/repo.py`: CSV/XLSX, raw provenance,
  duplicate/conflict handling and auction-only summary.
- `app/db/repo.py`, `app/worker/jobs.py`: import envelopes in existing rejection
  recovery; imports excluded from merchant inventory resolution and pruning.
- `app/db/schema.sql`, `app/db/connection.py`, migration 0037: schema/revision.
- `pyproject.toml`: XLSX dependency.
- `web/app/pocket/page.jsx`: existing Pocket evidence rails and file control.
- Backend/browser tests, local-only fixture harness, optional system-browser
  selection in Playwright config, decision 0046, approved brief and usage guide.

`app/core/`, `app/pricing/`, `app/offerlink/` and `app/vessel/` are unchanged.

## Limits and diagnosis

- First import source is Christie's; more auction houses/column mappings are
  intentionally outside this milestone. Adapter LAST_TRADE records are not merged
  into the auction series, avoiding cross-path duplicate transactions.
- Auction summary retains existing premium/FX/quarantine/730-day window rules.
  Unresolved and invalid original rows are retained in the existing reject store.
- No proactive Core schedule or optional liquidity summary was added.
- Live AI parsing, real merchant permissions/network access and the deployed
  database were not tested. Existing application configuration is still required.
- The original Compose Postgres 17 configuration fails an existing migration
  naming Postgres 18 NOT NULL constraints. Validation used 18, matching the
  embedded development runtime. Historical migrations were not changed.
- Playwright's browser CDN was blocked by network policy. The installed system
  Chromium was used instead; browser/TLS verification was not disabled.
- The separate legacy sell-side browser smoke journey was not run. Its backend
  safeguard suites did run in the full 801-test check.

See `market-data-integration-usage.md` for Mac startup and import instructions.
