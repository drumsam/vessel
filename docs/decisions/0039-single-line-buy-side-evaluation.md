# 0039 — single-line, buy-side evaluation

**Status:** accepted, 24 October 2026. Asked for alongside decision 0038,
in the same message, once the scope question for the client want list was
settled: these wines "arrive in ones and twos" and Doug prices them
manually from his own Wine-Searcher account, so no new merchant adapter
and no job queue were ever the right shape for this. Built on decision
0024's own hand-entry pattern (auction evidence), named explicitly as the
template.

## The ask, in Doug's own words

"Doug types what he was offered and the market prices he found with each
source named, and a manually entered price goes through exactly the same
screens as a scraped one — same Offer model, same vintage-band check,
same Floor/Reference/Median, no fast path and no trusted-operator
bypass. At these prices the band check catching a mistyped GBP1,200 for
GBP12,000 is worth more than the automation we aren't building."

This is a buy-side screen: Doug is evaluating whether to BUY a wine a
supplier offered him, not pricing one he already owns to sell. The rest
of this codebase prices the sell side exclusively; nothing here asked
for that to change.

## What's reused, unchanged

Everything that makes a price trustworthy in this system is untouched:

- **The Offer model and hard screens.** Each comp Doug names becomes a
  real `offer` table row, under a real `snapshot`/`snapshot_merchant` —
  the exact tables a merchant adapter writes to. `app.core.benchmark`
  cannot tell a hand-typed offer from a scraped one, and is never asked
  to: In Bond, ASK, GBP, buyable, positive price, whole pence, not a
  mixed lot all apply exactly as they do to Farr or Bordeaux Index.
  `benchmark_comp.offer_pk` is a real foreign key into `offer.offer_pk`,
  which is *why* the comps have to become real rows rather than being
  benchmarked in memory — a run that can't point back at the row it was
  computed from can't be persisted the way every other run in this app
  is.
- **The deterministic core.** `app.worker.jobs.benchmark_with_band` (made
  public for this — it was `_benchmark_with_band`) is called directly,
  synchronously, as a plain function: the same orchestration
  `benchmark_deal` already runs per line — `derive_units` set from the
  wine's region (decision 0016), `benchmark()`, `check_vintage_band()`,
  a re-benchmark if the band excluded a high outlier, `derivation_
  confirmed`, then `repo.save_benchmark()`/`save_vintage_band()`. Nothing
  about this orchestration was duplicated or special-cased for a manual
  line.
- **`LineOut`.** The response is the same schema every other line in
  this app already returns. No new output shape for a benchmark result
  to drift against.
- **The want list (decision 0038).** `match_want_list()` runs live as
  Doug types the raw description, as a suggestion only — it never sets
  `wine_id` and the operator still picks the exact wine by hand, same
  discipline as everywhere else this matcher is used. A want-list wine
  evaluated here is flagged on the result exactly as `line.jsx` flags
  it, for the same reason: these are the names worth a second look
  before acting on a number.
- **Decision 0024's own discipline**, not its code: a person types facts
  they actually saw, each with a named source; nothing here scrapes.
  Unlike the four closed auction houses, the merchant list here is
  deliberately open — `ensure_manual_merchant` finds-or-creates a
  `merchant` row by name — because Wine-Searcher aggregates far more
  retailers than this app has adapters for, and a real source Doug names
  having actually seen the price there is real evidence regardless of
  whether this fleet has code for it.

## What's new

- **`app/evaluate/repo.py`**: `ensure_manual_merchant`, `ensure_
  evaluation_deal`, `add_evaluation_line`, `write_evaluation_comps`,
  `evaluate_offer` (the one call the screen makes), `InvalidEvaluation`.
- Every evaluation lands as one more line of a single, persistent deal
  — `"Buy-side evaluations"`, found-or-created idempotently — rather
  than a fresh one-line deal each time. Doug does this often; a growing
  history under one deal is how he would actually browse past
  evaluations, not a pile of deals with one line each.
- **No sell-side pricing runs at all.** `app.pricing.pricer` is never
  called. "Is this a good price" is answered by comparing the asking
  price against the Floor/Reference the benchmark produced — a frontend
  display computation (`gapPercent`, already used elsewhere in this app
  for exactly this kind of comparison), never a new backend pricing
  rule. The asking price itself is stored as `seller_line.cost` — the
  same field a sell-side line already uses for what the seller is
  asking — read back, never recomputed.
- **`POST /identity/want-list-match`** and **`POST /evaluate`**
  (`app/api/main.py`), the latter wrapped in one transaction so a
  rejected comp (`InvalidEvaluation` → 422) leaves nothing half-written.
- **`web/app/evaluate/page.jsx`**: the single box. Raw description (with
  live want-list suggestions as Doug types), an existing-wine dropdown
  or an inline "not in the list" create-wine form, vintage/format/
  quantity/asking price, and a repeatable comp row per source. On
  submit it shows the same Floor/Reference/Median/flags/comp-table
  `line.jsx` already shows for any other line — `RunSummary` (embedded
  in `LineOut`) has no per-comp breakdown, so the page makes a second
  call to the existing `GET /lines/{id}/benchmark` for the full `RunOut`,
  the same split `line.jsx` itself already lives with, rather than
  inventing a new response shape. The comp table filters out the
  internal `"comparable"` role (every passing offer before the
  per-merchant dedup) the same way `line.jsx`'s own table already does
  — found live, mid-verification: without the filter, a merchant with
  exactly one offer shows up twice, once as `"comparable"` and once as
  `"merchant_best"`, for the same price.

## What this is not

Not a new pricing rule, and not a new gate in `app/core/`: the want-list
flag it surfaces is read, not evaluated here, and nothing under
`app/core/` or `app/pricing/` was touched.

Not a merchant adapter, and not Wine Market Journal — both explicitly
ruled out when Doug set the scope for this phase. The coverage test
against the ten producers and seven existing adapters stays optional,
informational, idle-time-only, as he said; not run in this session.

Not a closed source list like decision 0024's four auction houses — any
name Doug types becomes a merchant row. This is a deliberate, named
difference from the auction pattern this decision otherwise follows,
because Wine-Searcher is itself an aggregator, not a single site with
terms to respect.

## Consequences

- `app/worker/jobs.py`: `_benchmark_with_band` → public `benchmark_
  with_band` (comment-only follow-on edits in `app/core/flags.py` and
  `tests/test_unit_derivation.py`).
- `app/evaluate/__init__.py`, `app/evaluate/repo.py` (new).
- `app/api/schemas.py`: `WantListMatchIn/Out`, `EvaluationCompIn`,
  `EvaluateOfferIn`.
- `app/api/main.py`: the two new endpoints.
- `web/app/evaluate/page.jsx` (new); `web/app/chrome.jsx` gains the
  "Evaluate" nav link.
- Tests: `tests/test_evaluate.py` (new) — 5 direct repo-level tests
  against Postgres (manual-merchant idempotency; a non-whole-pence comp
  refused, not rounded; a real two-merchant benchmark producing the
  correct Floor/Reference/Median and landing a second evaluation in the
  same persistent deal; the ONE_COMP rule applying unchanged; the
  asking price readable as the line's own `cost`) and 4 through the API
  (`/identity/want-list-match` with and without a hit; `/evaluate`
  end-to-end; a non-whole-pence comp refused with 422). Offline suite
  unaffected (493 passed, 188 skipped — up from 179 skipped, the 9 new
  tests all Postgres-gated). Full Postgres suite: 681 passed (was 672).
- Verified live via `desk.sh` + Playwright against the real desk
  database: a want-listed producer (Domaine Leroy) typed as free text
  surfaces the right suggestion; an existing wine is selectable and a
  new one can be created inline without leaving the page; a benchmark
  run combines REAL adapter-collected evidence already in the database
  (Bordeaux Index, Justerini & Brooks) with the manually-entered comps
  in the same run, exactly as intended — proving the "exactly the same
  screens" claim rather than just asserting it; a non-whole-pence price
  is refused with the schema's own validation error before it reaches
  `InvalidEvaluation` at all (`PositiveMoney` already enforces two
  decimal places, making the repo-level check a second, independent
  line of defence for callers that bypass the API, not dead code); all
  scratch wines, the scratch "Buy-side evaluations" deal, and the two
  scratch manual-merchant rows this verification pass created were
  removed from the live desk database afterward, leaving it exactly as
  found.
