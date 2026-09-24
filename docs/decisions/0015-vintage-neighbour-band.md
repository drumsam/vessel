# 0015 — The vintage-neighbour band, and the one direction it may act in

**Status:** accepted, 24 September 2026, and revised the same day when the
quality register arrived. Doug's idea, specified in
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
on its result.** The core computes no band and reads no tier; the only thing
it gained is the flag vocabulary below. A band is never a price: a
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
regression test (`test_band_runs_over_every_comparable_not_merchant_bests`).

**Neighbours are chosen by quality, not by proximity in years.** This replaced
the original ±3-year window on 24 September, and it is the better rule: an
ordinary vintage prices near another ordinary vintage even five years away, and
a great vintage never prices like an ordinary one. 2004 red Burgundy is tier 5
and 2005 is tier 1 — one year apart and not comparable at any price.

Selection: same wine and unit, within ±8 years (drift beyond that is real),
**same tier**; widened **once** to tier ±1 if fewer than two vintages qualify,
never further; the six nearest years if more than six qualify. Years break ties;
they do not decide membership.

**A tier never scales a price.** It decides only which vintages may be compared.
There is no widening factor and no adjustment: the band is used as it stands,
because the neighbours are already quality-matched.

**No tier, no band, no flag.** A region absent from the register — Bordeaux,
Champagne, the Rhône, Piedmont, Tuscany, all still missing — means the check
stays quiet and says so. That is the correct failure.

**The register is a file, not a screen.** `docs/research/vintage-tiers.csv`,
58 rows, Burgundy red and white, 1995–2023, loaded by
`scripts/load_vintage_tiers.py` (migration 0012). Changing a tier is a pull
request: it decides which prices are treated as outliers, so it belongs in
history where it can be argued with. The stored number is ours — the consensus
of several published charts, each ranked within itself — and the source names
are recorded per row without reproducing anyone's scores.

**Keyed by region AND colour.** 2014 Burgundy is tier 3 red and tier 1 white;
2009 is tier 2 red and tier 4 white; 2003 is tier 4 red and tier 5 white. A
colour-blind register would pair a great vintage with an ordinary one and call
the difference an outlier. A wine with no colour recorded is unrated, and an
unrated wine gets no band rather than a guessed one.

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

## The one approved change to the locked core

Doug, 24 September: **both band flags are review flags.**
`COMP_EXCLUDED_VINTAGE_BAND` and `LOW_COMP_OUT_OF_BAND` are in `REVIEW_FLAGS`,
and `HIGH_MULTIPLE`, `LOW_MULTIPLE` and `FORMAT_INCOHERENCE` sit beside
`WIDE_SPREAD_THRESHOLD` in `app/core/flags.py`.

This only ever tightens. A line where a dear comp was thrown out, or where a
cheap one looks wrong, now always reaches a person — not only when `ONE_COMP`
happens to catch it, which is what would have happened whenever the exclusion
left two merchants standing.

The flags reach the run through `SellerLine.inherited_flags`, which decision
0005 built for exactly this: only review flags may be inherited, so the band can
hold a line in review and can never release one. No screen, no arithmetic and no
state rule in the core changed.

## WIDE_SPREAD — decided, not deferred

No depth-2 gating rule. `WIDE_SPREAD` stays informational. A wide gap is
answered by comparing against quality-matched vintages, which says *why* the
spread is wide; a second flag saying only *that* it is wide adds nothing.

## What it did to the evidence we have

Run over both sets on 24 September, it moved nothing — which is the right
outcome for evidence that was already checked by eye.

- **Burgundy proof (20 lines):** READY 0 · REVIEW 5 · NO_MARKET 15, unchanged.
  Six lines got a band; the only one that also had a comp was L15 Rousseau
  Ruchottes 2013 at £900 against a £830–£1,170 band — inside it, so quiet.
- **Control set (70 lines):** 8 READY · 62 REVIEW before and after. Five lines
  got a band, all of them Courcel Pommard Grand Clos des Épenots, whose 2014,
  2015, 2016, 2018 and 2019 are the only real vintage curve in the set. Every
  price sat inside its band. The other 65 lines are quiet for the honest
  reason: one neighbouring vintage is an anecdote, not a band.

So on this evidence the check costs nothing and catches nothing. That is what a
sanity check looks like when the data is sound; the Mugneret-Gibourg £2,070 it
was built for is a regression test, and the next bad number it meets will be a
live one.
