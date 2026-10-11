# 0028 — DERIVED_FROM_CASE: region-independent source agreement, correcting 0023

**Status:** accepted, 10 October 2026. Doug, against the live Champagne
sweep: "My specification was wrong: I expressed agreement via the vintage
band, which exists only for Burgundy, so the exemption can never fire
outside it. The intent was always that SOURCE AGREEMENT bounds derivation
error. Express it directly."

## What was wrong with 0023

Decision 0023 built exactly what was specified: `DERIVED_FROM_CASE` stops
gating a 2+-comp line once the vintage band (decision 0015) finds nothing
to exclude or flag. That band exists for Burgundy only
(`docs/research/vintage-tiers.csv`) — every other region's
`check_vintage_band` returns `band_low=None`, and 0023's own rule refused
the exemption whenever that happened, "the same conservative default as
the single-comp case." For a region with no register at all, that default
is permanent, not conservative: no amount of real merchant agreement could
ever release the gate.

The Champagne sweep (9 October 2026, `docs/research/cellar-wfs-normalised.csv`)
is what exposed it. Doug: "Without this, a loose-bottle cellar priced from
UK case sellers can NEVER produce a READY line. That is a structural dead
end, and it's a gate bug, not a data problem." 454 bottles of Krug, and
every other Champagne position in the cellar, were sitting behind a gate
that nothing could ever open, because the only key 0023 cut fits a lock
Champagne does not have.

## The rule, corrected

`DERIVED_FROM_CASE` stops gating a line — never stops being added, never
stops being shown — when:

1. the line's `comp_count` (merchants, not listings) is 2 or more, **and**
2. every one of its `merchant_bests` prices sits within `AGREEMENT_
   THRESHOLD` (10%) of the lowest one, **and**
3. if a vintage band exists for the line's region, it found nothing to
   exclude or flag on either side (unchanged from 0023 — see below).

Test 2 is new, is computed inside `app/core/benchmark.py`
(`BenchmarkResult.state`) directly from `merchant_bests`, and needs
nothing from any caller: it is the region-independent test Doug asked
for, expressed directly rather than through a proxy that only exists for
one region. Test 3 is still decided outside the core
(`app/worker/jobs._benchmark_with_band`, `scripts/rerun_burgundy_proof.py`)
and fed back through `SellerLine.derivation_confirmed`, exactly as 0023
built it — except that field's meaning has narrowed to match: it is no
longer "the band confirmed agreement," it is "the band, if one exists,
raised no objection" — **vacuously true where no band exists to ask.**
That one-word change (refused → vacuous pass) is the entire correction:
nothing about the band mechanism itself moved.

```python
# app/core/benchmark.py — BenchmarkResult.state
if Flag.DERIVED_FROM_CASE in gating and self.comp_count >= 2 and self.line.derivation_confirmed:
    prices = sorted(o.price for o in self.merchant_bests)
    floor = prices[0]
    if floor > 0 and all((p - floor) / floor <= AGREEMENT_THRESHOLD for p in prices):
        gating = gating - {Flag.DERIVED_FROM_CASE}
```

```python
# app/worker/jobs.py — _benchmark_with_band
result.line = replace(result.line, derivation_confirmed=(
    check.band_low is None or (not check.high_outliers and not check.low_outliers)))
```

With one comp, it stays gating, exactly as before: there is no second
source to agree WITH. A high or low outlier the band excludes already
gates independently through `COMP_EXCLUDED_VINTAGE_BAND` /
`LOW_COMP_OUT_OF_BAND`, so a band that objects still refuses the
exemption, same as 0023.

## Why 10%, not 25% or the premium's own spread

`WIDE_SPREAD_THRESHOLD` (0.25, informational — a line can be READY and
`WIDE_SPREAD`) was never a candidate: it answers a different question
(how dispersed is the market) and was never evidence about derivation
error specifically. `CASE_PREMIUM`'s own measured spread (27 Burgundy
pairs, median 1.0000, a quarter more than 5% out, tails at -30%/+15%) is
about the CONSTANT's reliability, not about what two or more real asks
agreeing tells you — those are different questions with different
answers, and 0023's whole point was to stop leaning on the constant for
this one.

The number came from the live Champagne sweep itself: every 2+-merchant
line found, Floor to Reference, sorted:

| Line | % apart |
|---|---|
| Dom Pérignon Rosé 2006 | 5.7 |
| Louis Roederer Cristal 2005 | 8.7 |
| Taittinger Comtes de Champagne Rosé 2009 | 12.6 |
| Charles Heidsieck Blanc de Millenaires 2006 | 18.5 |
| Louis Roederer Cristal 2007 | 20.0 |
| Dom Pérignon Vintage 2010 | 23.8 |
| Dom Pérignon Vintage 2004 | 27.1 |
| Louis Roederer Cristal 2006 | 27.3 |
| Taittinger Comtes de Champagne 2008 | 40.5 |
| Taittinger Comtes de Champagne 2006 | 57.0 |

10% draws the line cleanly after the first two and holds every other real
gap found, including both Taittinger Comtes de Champagne lines at 40.5%
and 57.0% — two merchants that far apart are not agreement, however many
of them there are. Re-running the full sweep at this threshold:
**exactly 2 of 62 line-shapes move to READY** — Dom Pérignon Rosé 2006
(12 bottles) and Louis Roederer Cristal 2005 (24 bottles) — both held
exactly where the ladder says they should be, nothing either side of the
line moved. `tests/test_unit_derivation.py`'s
`test_the_live_champagne_sweep_spread_is_the_evidence_for_the_10pct_line`
runs the full ladder as a parametrized regression test, so the threshold
stays tied to the evidence that set it rather than floating free of it.

## Where the line is still drawn, and why not moved into `app/core/`

The source-agreement test moved INTO the core because it needed nothing
outside it — `merchant_bests` prices are already there, and the test is
by construction region-independent, so there was no reason left to keep
it as an external fact fed back in. The band test did NOT move, because
the core still cannot know what a vintage band is (invariant 1, and
`app/market/`'s own charter — "nothing in it may change a figure the core
produced"). `SellerLine.derivation_confirmed` is still how that one,
narrower fact crosses the boundary; it has simply stopped being asked to
carry the agreement test too, now that the core can ask that question
itself.

## What this is not

Not a change to `CASE_PREMIUM`, to how a comp is derived, or to the
ranking that always puts a derived comp behind a real one at the seller's
own unit. Not a change to `ONE_COMP`, `COMP_EXCLUDED_VINTAGE_BAND` or
`LOW_COMP_OUT_OF_BAND`'s own gating — all three are untouched and still
independently sufficient to hold a line in review. Not a relaxation for
Burgundy: a Burgundy line with a working band still needs the band to
agree AS WELL AS the comps — "the band is strictly more information,"
Doug, "don't lose it for Burgundy" — and `scripts/rerun_burgundy_proof.py`
confirms it: still `READY 0 REVIEW 15 NO_MARKET 5`, unchanged, because its
two 2-comp derived lines (L4, L17) disagree by more than 10% (L4: 19.9%)
even before any band is asked.

## Consequences

- `app/core/flags.py`: `AGREEMENT_THRESHOLD = Decimal("0.10")`, with the
  live ladder as its own comment; `CASE_PREMIUM`'s comment block and the
  module's opening paragraph updated to name 0028 rather than 0023 alone.
- `app/core/benchmark.py`: `BenchmarkResult.state` computes source
  agreement directly from `merchant_bests`; module docstring (invariant 3)
  updated.
- `app/core/models.py`: `SellerLine.derivation_confirmed`'s docstring
  narrowed to "the band, if any, objected" rather than "the band
  confirmed agreement."
- `app/worker/jobs._benchmark_with_band`: sets `derivation_confirmed`
  unconditionally now (band_low is None, or no outliers either side) —
  the unused `Flag` import dropped.
- `scripts/rerun_burgundy_proof.py`: same change, same reasoning; still
  produces `READY 0 REVIEW 15 NO_MARKET 5`.
- Tests: `tests/test_unit_derivation.py` — the 0023 section's helper and
  three existing tests updated for the new two-part condition; two new
  tests (no band + agreement → READY; no band + disagreement → stays
  REVIEW) plus a 10-case parametrized regression running the live ladder
  itself. `tests/test_service.py`'s one Burgundy integration test of the
  old behaviour (two comps, 0% apart, no band for that one vintage)
  renamed and its expectation corrected from REVIEW to READY — it was
  asserting exactly the bug this decision fixes. 397 offline (was 386),
  558 with Postgres (was 547).
- Re-running the live Champagne sweep: 2 of 62 line-shapes move
  NO_MARKET-adjacent REVIEW → READY (Dom Pérignon Rosé 2006, Louis
  Roederer Cristal 2005); 28 REVIEW, 32 NO_MARKET remain, unchanged in
  cause.
