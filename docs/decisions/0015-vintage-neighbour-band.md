# 0015 — The vintage-neighbour band, and the one direction it may act in

**Status:** accepted, 24 September 2026. Doug's idea, specified in
`docs/research/vintage-neighbour-check-spec.md` and built from it.

## Context

2020 Mugneret-Gibourg Vosne-Romanée village, 6×75 In Bond: Lea & Sandeman
£1,200, Bordeaux Index £2,070. Two merchants, so the UK Reference is the dearer
one, and the line goes out READY to price off a number **72% above a live UK
ask**. Nothing in the pricing core can tell which is wrong, because it only ever
sees one wine and one vintage.

Bordeaux Index's own curve for that exact wine and unit says which:
2017 £1,489 · £1,520, 2018 £1,223, 2020 £2,070 · £2,074. And its own loose
bottle says it again: £197 for a 2020 bottle while pricing its six-pack at £345
a bottle.

## Decision

**The check lives in `app/market/vintage_band.py` and runs after the benchmark,
on its result.** `app/core/` is untouched. A band is never a price: a
neighbouring vintage never enters Floor, Reference or Median, is never
interpolated into a missing vintage, and never appears on a client document.

**Like for like only.** Same `wine_id`, same `bottle_ml`, same `pack_size`,
In Bond, ASK, GBP, buyable. No division, no multiplication, ever. A 3×75
neighbour says nothing about a 6×75 band.

**At least two neighbouring vintages, or no band at all.** One neighbour is an
anecdote. The operator sees "not enough neighbouring vintages to check".
Silence, not a guess.

**The asymmetry is the point.** A **dear** comp above `band_high × 1.35` is
excluded automatically: that moves the Reference *down*, so we pay less and sell
lower, and the line goes to a human anyway. A **cheap** comp below
`band_low × 0.65` is flagged and **kept**: removing it would push the Reference
*up*, which makes us overpay and lets us overprice a client — the failure this
whole system exists to prevent. Often the cheap comp is the true signal; a
merchant clearing stock is a real price.

**Every comparable is checked, not just the merchant-bests.** Bordeaux Index
lists the 2020 six-pack at £2,070 *and* £2,074. Excluding only the best of them
promotes the other: the Reference falls from £2,070 to £2,074 and the check
achieves nothing. Found while wiring the pipeline, and now a permanent
regression test (`test_excluding_only_the_merchant_best_promotes_its_twin`).

**Vintage quality widens the band; it never scales a price.**
`tier_up = 1 + 0.15 × max(0, neighbour_tier − target_tier)`, capped at 1.6, from
the operator-maintained `vintage_tier` table. No tiers recorded means no
widening, so the check speaks more often rather than less.

**Cross-format disagreement is evidence, not a comp.** Where one merchant's
other format implies a per-bottle figure more than 30% from the comp's, it is
recorded against that comp. Those per-bottle figures exist inside the check's
output and nowhere else: not on an offer, not exported, never shown as a price.

**Neighbours may be 90 days old; comps are still 14.** A band prices nothing, so
it may lean on older evidence — and a band built only from stale data says so.

**Every automatic exclusion is recorded like a manual correction**, in
`benchmark_comp_exclusion`: the offer as the run saw it, the edge it failed, the
multiple, and a one-click "put it back" that computes a **new** run and records
who asked and why. The original run is never edited.

## What is NOT decided here

Two things the spec asks for that need `app/core/flags.py`, which is frozen:

1. `COMP_EXCLUDED_VINTAGE_BAND` and `LOW_COMP_OUT_OF_BAND` are specified as
   **review flags**. They are currently informational strings in
   `app/market/vintage_band.py`, surfaced on the run and in the console but not
   in `REVIEW_FLAGS`, so they do not by themselves force review or gate an
   export. In the Mugneret case the line reaches review anyway, via `ONE_COMP`.
   A line where the exclusion leaves two merchants would not. **This needs
   Doug's approval to change, and it is a tightening, never a loosening.**
2. The constants (`HIGH_MULTIPLE` 1.35, `LOW_MULTIPLE` 0.65,
   `FORMAT_INCOHERENCE` 0.30) are specified to sit beside
   `WIDE_SPREAD_THRESHOLD` in `app/core/flags.py`. They live in
   `app/market/vintage_band.py` for the same reason.

The `WIDE_SPREAD`-at-depth-2 question (spec §8) stays open and unimplemented.
The suggested order holds: run this over the control set first, then decide that
rule on the evidence of how many lines it still catches.
