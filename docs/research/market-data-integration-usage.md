# Integrated Pocket market evidence

This is the implementation of market-data-integration-milestone.md on
`integration/market-evidence`, based on `pricer`. The standalone prototype on
`main` is not merged or used.

## Open it on your Mac

In your existing real application checkout:

```sh
cd ~/Documents/claude/projects/uk-fine-wine-pricer
git fetch origin
git switch --track origin/integration/market-evidence
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
(cd web && npm ci)
bash scripts/desk.sh
```

If the integration branch already exists locally, switch to it and pull normally
instead of using `--track` again. Git will refuse a conflicting local change;
keep your work rather than resetting it.

The existing `desk.sh` starts the local demo database, applies migrations, starts
the API and frontend, and prints login information. Open the **local** browser
at http://localhost:3000/pocket. The existing demo login is `deskdemo` /
`desk-demo-password`. These credentials are for the local demo only.

Paste an offer, confirm its canonical wine, format, quantity and supplier, and
acknowledge the want-list identity check where required. Pocket shows existing
merchant evidence and auction evidence separately. Missing evidence is a valid
outcome. It does not produce a walk-away recommendation or decide the trade.

`Refresh Market` invokes existing `collect_now`, using approved adapters and
already-established search keys. Actual external collection still requires the
repository's identified COLLECTOR_USER_AGENT, permitted sources and network
access; this milestone adds no collectors. A missing key is a skip, not a failed
wine identity and not proof there is no market. Do not invent a contact identity.

The demo database may have little useful market evidence. Development validation
uses explicitly labeled fixtures, not an asserted live market. Your deployed
application and its database are not changed by checking out this branch.

## Auction CSV/XLSX

Use the upload control inside the existing Pocket evaluation. First milestone:
Christie's only, using its existing registered source. No auction scraping is
added. CSV headers or the active XLSX sheet must include:

```
producer,wine,vintage,bottle_ml,bottles_in_lot,auction_house,sale_date,lot_ref,source_url,currency,amount,amount_basis
```

`auction_house` is `CHRISTIES`. `sale_date` is ISO YYYY-MM-DD. NV is `1000`.
`amount_basis` is `HAMMER` or `BUYER_PREMIUM_INCLUSIVE`; the latter requires
`premium_rate` as a decimal fraction, e.g. `0.25`. Additional supported fields:
`release_code`, `lwin7`, `fx_rate`, `fx_source`, `is_mixed_lot`,
`condition_notes`, `condition_flagged`. Use explicit premium/FX information;
missing FX leaves GBP normalization absent, never guessed. Limits: 2 MB,
2000 rows, 20 MB expanded workbook.

Prices are lot totals, not per-bottle quotes. `wine` is the cuvée; producer is a
separate field. Identity uses the existing canonical registry, including exact
release codes. Unknown or ambiguous names stay in `offer_reject`; existing
reject re-resolution handles imported envelopes without creating merchant offers.
This does not acknowledge an inbound want-list/photo gate on the operator's behalf.

Upload reports written, unresolved, rejected and duplicate counts plus invalid
row numbers. Raw rejected rows remain in existing storage; original accepted rows
and file hash/name/row number live on `auction_evidence.raw_evidence`.
Conflicting facts for an existing sale/lot require review and retraction, not
silent replacement. A corrected result can be entered after retracting the old
one through the existing auction route. Imported audit snapshots are excluded
from merchant inventory resolution and ordinary snapshot pruning, so they cannot
hide stock or discard the unresolved import queue.

Auction summaries use the existing 730-day health window, active non-quarantined
lots and explicit premium/FX normalization. Dates, original amount/basis,
quantity and source links are shown. GBP per-bottle hammer statistics are display
context only. Unknown-FX lots count as evidence but not in GBP statistics.
Adapter LAST_TRADE rows are not merged into this rail, avoiding cross-path double
counting. Original source currency/amounts remain visible.

## API and cache

Existing endpoints are extended, not replaced:

- `POST /inbound-offers/{id}/evaluate`: local evidence only, no external fetch.
- `POST /inbound-offers/{id}/collect-now`: existing explicit refresh followed by
  the same evaluation contract.
- `POST /auction-imports`: authenticated JSON `{filename, content_base64}`.

Evaluation returns merchant/transactions, source outcomes, capture/sale ages,
run ID and cache-hit indicator. The seller's literal ask retains its currency
and basis. Pricing-data weakness does not block the decision. Identity/format
review remains blocking. No new offer-creation workflow is included; separate
sell-side pricing, export and market-claim gates are unchanged.

The fingerprint on the existing benchmark run covers line inputs, current
resolved source records, tiers/region, reinstatements and time eligibility.
Changes invalidate the cached benchmark; ordinary repeated reads reuse its
persisted results. Display ages still advance. Merchant source resolution retains
its existing latest-covering-capture/no-resurrection semantics. Only the locked
engine supplies Floor/Reference/Median, from merchant-bests, including its
explicitly flagged existing unit-derivation policy. Raw listing medians are never
substituted. Stale asks are historical context, not a current eligible Floor.

Schema: two auction columns and one nullable benchmark cache-key column, plus an
active-event unique index. No new tables. Migration `0037_market_evidence` is
additive and reversible; schema.sql and EXPECTED_HEAD_REVISION move together.
The extra benchmark column is necessary to persist input validity across
processes rather than introduce a second cache table or misuse immutable evidence.

## Run checks

Use a **disposable local Postgres 18** database for database tests. Existing
migration 0012 names a NOT NULL constraint introduced by Postgres 18; the older
Compose Postgres 17 setting does not reproduce that migration. This pre-existing
mismatch was diagnosed rather than changing historical migrations. `desk.sh` uses
the repository's embedded Postgres 18 runtime.

```sh
.venv/bin/python -m pytest -q
TEST_DATABASE_URL=postgresql://USER:PASSWORD@localhost:PORT/pricer_test \
  .venv/bin/python -m pytest -q
(cd web && npm test && npm run build)
```

Database tests DROP the public schema of TEST_DATABASE_URL. Never point them at
real or deployed evidence. See the separate validation report for actual counts.

`web/e2e/pocket-evidence.spec.mjs` runs against a separate local `*_e2e` database
and `tests/support/market_evidence_server.py`. That harness explicitly substitutes
only AI parsing and merchant HTTP transport; login, first-party API proxy,
canonical confirmation, benchmark persistence, auction import and UI are real.
It refuses a non-local/non-e2e database. Do not deploy the harness. An installed
system Chromium can be selected using PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH.
