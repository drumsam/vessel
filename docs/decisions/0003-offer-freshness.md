# 0003 — Offer freshness is a pricing invariant

**Status:** accepted, 19 September 2026. The threshold is deliberately revisitable; the screen is not.

## Context

Nothing stopped an old capture from becoming a UK Reference. A merchant's March
listing of a wine that sold out in April would still be the Floor in September,
as long as it was the cheapest thing on file. The figure would look exactly
like a current market price. That is the failure this system exists to prevent:
a wrong price that looks right.

## Decision

`MAX_OFFER_AGE_DAYS = 14` in `app/core/flags.py`, and a `Reject.STALE` screen in
`benchmark()`.

- `benchmark(line, offers, *, as_of)` takes the instant it is measuring
  against. It is a required, timezone-aware argument, never the clock, so the
  function stays pure and a run can be replayed exactly.
- An offer is comparable only if `as_of − 14 days ≤ captured_at ≤ as_of`.
  The boundary is inclusive.
- **An undated offer is rejected.** It cannot be shown to be fresh.
- **An offer captured after `as_of` is rejected.** A benchmark "as of 1 September"
  must not see 3 September's market.
- Stale offers are also excluded from cross-unit evidence. A stale case shown
  per bottle beside a fresh line would read as current.
- The result carries `oldest_comp_age`: `as_of` minus the capture time of the
  oldest merchant-best. It is stored on `benchmark_run` and shown to the operator.
  It is context, not a flag. A 13-day-old Reference passes the screen, but the
  operator should be able to see that it is 13 days old.

Every stale offer stays in the run as a rejection with its reason, like every
other screen.

## Where 14 comes from

It is a chosen number, not a measured one. The live captures in this repository
cover a single day, so no rate of listing turnover can be derived from them.
Fourteen days is long enough that a weekly collection cadence never starves a
line, and short enough that the market cannot have turned over.

Revisit it when there are enough snapshots to measure how often a merchant's
listing for the same wine, vintage and format changes price or disappears
between captures. Change the constant and this record together.

## Consequence

The Burgundy proof is a replay. Every offer in it carries the evidence file's
`captured_at`, and the proof runs `as_of` that same instant. Its output is
unchanged: READY 0, REVIEW 5, NO_MARKET 15.

A line whose only evidence is stale reads `NO_MARKET`, with the stale offers
visible as rejections. A line with no capture at all is not benchmarked; see
0004.
