# 0029 — re-resolve the reject queue when an alias is approved

**Status:** accepted, 10-11 October 2026. Found while auditing whether any
of the seven original Champagne-sweep adapters already captured a
loose-bottle offer we were silently dropping (they do not — six of seven
already separate loose from case and read it correctly, and the market
itself does not carry most of this cellar's back-vintages at 1×75cl). The
audit's own method — re-running `registry.resolve_candidate` against
`offer_reject.raw` for a merchant already on disk — surfaced something
bigger than the question it was asked: "identity resolution happens once,
at capture time, against whatever the registry was then, and never
re-resolves retroactively." Eleven of thirty-three LiveTrade rejects
checked resolved instantly once the current registry was used instead of
the one live at capture time — purely because aliases this session added
*after* that capture (Henri Giraud, Taittinger Comtes de Champagne
Blanc de Blancs, …) didn't exist yet when `ingest()` ran. Doug: "That is a
permanent leak, not a one-off… a mechanism that recovers depth for free is
worth more than it looks."

## The rule

A new job, `app.worker.jobs.reresolve_rejects(merchant_id=None)`:

1. Reads every `UNRESOLVED_IDENTITY` row in `offer_reject`
   (`repo.unresolved_identity_rejects`), each with the snapshot's own
   `captured_at`.
2. For each, calls the SAME adapter's `normalise()` again, on
   `raw["merchant_record"]` — the ORIGINAL record `ingest()` called it
   with, not the narrowed `Candidate.offer.raw` some adapters trim to one
   output row. No network: `normalise()` is pure, and the record is
   already on disk.
3. Resolves the resulting `Candidate`(s) against the CURRENT registry
   (`repo.load_registry`, freshly loaded — not the one cached at capture
   time).
4. Where it now resolves, writes the `Offer` under the ORIGINAL
   `snapshot_id` (the data really was captured then; freshness is judged
   against that true timestamp, same as anything else) and deletes the
   reject row.
5. Reports, per recovery, whether that exact merchant already had an
   offer for that exact commercial unit before this one
   (`repo.merchant_already_offered`) and at what price — the question
   that actually matters, answered directly rather than guessed at: a
   recovery that duplicates a price already on the run changes nothing: a
   new merchant, or a materially different price from the same merchant,
   might.

Enqueued automatically by both places an alias gets created:
`POST /wines/{wine_id}/aliases` and the "same wine" branch of
`POST /lwin-conflicts/{conflict_id}/resolve`. Fire-and-forget — the API
response doesn't wait on it, same as `learn_search_keys`.

## What it actually recovered, this time

Run against the live Champagne sweep's own reject queue (merchant_id
`bordeaux-index-livetrade`): 33 single-bottle candidates re-checked, 11
resolved under the current registry, 1 matched a vintage this cellar
holds — Henri Giraud Aÿ Grand Cru Argonne Brut 2012, £479.00. That exact
wine, vintage and price were already on the run from the regular Bordeaux
Index listing adapter, under the SAME `merchant_id` (decision 0026/0027:
LiveTrade and the listing pages are one company). Recovering it changed
nothing — comp_count stays 1, Floor stays £479.00. Reported honestly
rather than oversold: this time the mechanism found a genuine identity
match and a duplicate price in the same breath, which is exactly why the
report distinguishes the two rather than just stating a recovered count.
"This time it duplicated. Next time it may not" — Doug.

## Why the bug this fixes was found doing something else

`unresolved_raw(c)` stored `c.offer.raw` as `"merchant_record"`. For
Bordeaux Index's regular listing adapter, one card normalises into several
candidates — one per `.offer` row — and each candidate's own
`offer.raw` is narrowed to `{"card": title, "offer_row": that one row}`,
not the whole card. Re-running `normalise()` on that fragment reads
`raw.get("title")` as `None` and fails exactly the way an empty title
always fails: closed, but for the wrong reason, and silently, since
nothing had ever tried to re-normalise a reject before this job existed.
Fixed at the source: `unresolved_raw(c, raw)` now takes the ORIGINAL
record explicitly (every call site in `ingest()` already has it in
scope), and only falls back to `c.offer.raw` for an adapter where the two
really are the same thing.

## Why this is retrospective and not a new collection

Nothing here fetches anything. `offer_reject.raw` is the merchant's own
record, captured once, kept verbatim (`jsonb`, `ON DELETE CASCADE` from
`snapshot` — pruned snapshots take their rejects with them, same
retention boundary as everything else). `normalise()` is pure by
contract (`CLAUDE.md`: "Adapter tests run offline against committed
fixtures… no network, no clock, no randomness"), so running it twice
against the same record on two different days is exactly as valid the
second time, with whatever registry exists that day. This is why the job
needs no `client`, no `robots`, no rate limit of its own — it is a
database operation wearing an adapter's clothes for one call.

## What this is not

Not a change to identity resolution's own rule that a producer+cuvee
candidate must still match or alias to an approved canonical wine
(`Registry.resolve_candidate`) — the job changes WHEN resolution is tried
again, never what counts as a match. Not a guess: a reject that still
fails to resolve under the current registry is left exactly where it was,
reported as `still_unresolved`, not deleted, not guessed at. Not a
benchmark re-run: the job writes offers and leaves them for the next
`benchmark_deal` to pick up, same as any other capture — it does not
re-benchmark any deal itself, because it has no `deal_id` to re-benchmark
and guessing at one would be exactly the kind of scope the job does not
need.

## Consequences

- `app/db/repo.py`: `unresolved_raw(c, raw=None)` takes the original
  record explicitly; `unresolved_identity_rejects()`,
  `delete_reject()`, `merchant_already_offered()` (new).
- `app/worker/jobs.py`: `reresolve_rejects()` (new); both `write_reject`
  call sites in `ingest()` pass `raw` through to `unresolved_raw`.
- `app/api/main.py`: `POST /wines/{wine_id}/aliases` and the "same_wine"
  branch of `POST /lwin-conflicts/{conflict_id}/resolve` each enqueue
  `app.worker.jobs.reresolve_rejects`.
- Tests: `tests/test_service.py` — two new (`@pg`): the alias endpoint
  recovering an already-captured rejection with no second collection, and
  the report correctly distinguishing a genuinely new merchant from one
  that already held the unit. 422 offline (unchanged), 585 with Postgres
  (was 583).
