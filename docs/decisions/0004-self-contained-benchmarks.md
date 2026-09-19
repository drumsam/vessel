# 0004 — Benchmarks resolve per merchant and are self-contained; snapshots are a cache

**Status:** accepted, 19 September 2026.

## Context

A benchmark run referenced exactly one snapshot, so every merchant had to be
collected into the same snapshot or market depth was undercounted. Bordeaux
Index can only be searched by producer and vintage, so it could never join a
whole-book collection, and was logged as a failure instead.

Separately, `benchmark_comp.offer_pk` referenced `offer` with no delete rule.
Deleting a snapshot cascades to its offers, so once any run had used a
snapshot, that snapshot could never be deleted. `SNAPSHOT_RETENTION` could not
work.

## Decision

**Resolution per merchant.** A run resolves, for each approved merchant
independently, the latest successful capture at or before `as_of` whose scope
covers the line:

- A whole-book capture (Farr, Goedhuis) covers every wine.
- A targeted capture (Bordeaux Index) covers one producer, normalised as in
  `wine_key`, in one vintage. Its search terms are kept in
  `snapshot_merchant.scope_params`.

Each offer keeps its own `captured_at`. `snapshot_merchant` records every
attempt: scope, capture time, counts, and the error if it failed.

**No resurrection.** If a merchant's latest covering capture no longer lists
the wine, that merchant contributes nothing. An older capture is never used to
bring back a listing that has since sold.

**Nobody looked is not NO_MARKET.** If no approved merchant has any covering
capture, the line is not benchmarked. The job reports it under `no_coverage`,
and no run is written. `NO_MARKET` means someone looked and found nothing.

**A run is self-contained.**

- `benchmark_run.as_of` is `NOT NULL`.
- `benchmark_run_snapshot` holds one row per contributing merchant:
  `merchant_id`, `captured_at`, and `snapshot_id`, which is set to NULL when the
  snapshot is pruned.
- `benchmark_comp.offer_snapshot` holds the offer exactly as used: merchant,
  price, currency, duty status, price kind, pack and bottle size, stock basis,
  condition flags and wording, URL, `captured_at`, and for cross-unit evidence
  the per-bottle arithmetic. Money in it is a string, never a JSON number.
- `benchmark_comp.offer_pk` is nullable, `ON DELETE SET NULL`, with a surrogate
  key `comp_id`, because a primary key column cannot be NULL.
- The API reads a run only from these tables.

## Why not cascades

`ON DELETE CASCADE` from offer to comp would make pruning work by deleting the
evidence behind every past benchmark. A run that cannot say which offers it
used, at what price, from whom, is not auditable. The run must outlive the
cache.

## Consequence

- Snapshots can be pruned. Past runs read the same afterwards; only the pointers
  go NULL. There is a test for this.
- Retention policy is not built. Whatever policy is chosen must be
  per-merchant-aware. Pruning a merchant's only covering capture does not change
  past runs, but it does remove that merchant from future ones.
- Migration 0003 carries old runs forward. It builds their `offer_snapshot` from
  the offers they used, and records every merchant that succeeded in their
  single snapshot as a source.
