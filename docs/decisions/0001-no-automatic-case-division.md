# 0001 — No automatic case-to-bottle division

**Status:** accepted, 19 September 2026
**Supersedes:** the earlier "divide by case size and deduct 5% to remove the full-case premium" rule.

## Context

Burgundy frequently trades by the individual bottle while the UK merchant market
holds mostly 6×75cl cases. A conversion rule would lift coverage sharply. An
earlier instruction was to divide the case price by the pack size and deduct 5%.

## Evidence

Measured on live data, 19 September 2026. Same merchant, same wine, same vintage,
a loose bottle and a case offered side by side:

| Merchant | Wine | Vintage | Loose bottle | Case ÷ pack | Loose vs pro-rata |
|---|---|---|---|---|---|
| Bordeaux Index | Rousseau Charmes-Chambertin | 2011 | £610 | £738 | −17.3% |
| Bordeaux Index | Rousseau Ruchottes-Chambertin | 2012 | £980 | £817 | **+20.0%** |
| Bordeaux Index | Rousseau Ruchottes-Chambertin | 2013 | £900 | £900 | 0.0% |
| Farr Vintners | Rousseau Chambertin | 2014 | £1,800 | £2,000 | −10.0% |

## Decision

Cross-unit evidence is **never** converted automatically. `benchmark()` returns
it as `cross_unit` — the offer plus its per-bottle arithmetic — for the operator
to see. It does not enter Floor, Reference or Median.

Derivation remains available as an **explicit per-line operator action** which
stamps `DERIVED_FROM_CASE` on the line. `DERIVED_FROM_CASE` is in `REVIEW_FLAGS`,
so a derived line can never reach READY silently.

## Rationale

The sample is four observations, which is small — but the **sign flips**. No
constant adjustment can be correct when the true one runs from −17% to +20%. A
5% haircut would have been wrong by 15 points on one of these and 25 on another,
inside a client-facing price, with no signal that anything had been assumed.

## Consequence

Coverage is lower and honest. On the 20-wine Burgundy proof, automatic derivation
would have "covered" 11 additional lines. That is the size of the temptation and
the size of the exposure.
