# 0033 — a listed price may never equal or exceed the UK Floor

**Status:** accepted, 18 October 2026. Found by Doug, measured against the
real 9 October 2026 Champagne sweep the moment it was finally on screen
(decision pending, Cellar Desk) rather than three invented rows — "three
invented rows would never have produced a 57% spread."

## The gap

With exactly two comps, Reference is the second-lowest — the DEARER of
the two, by invariant 4's own definition. The market chain (decision
0017) prices the buyer at `Reference x (1 - BUYER_DISCOUNT)`, which is
guaranteed below Reference by construction, but never guaranteed below
Floor, the cheapest ask actually found. When the two comps disagree
enough, the chain's own 20% discount off the dearer one can still land at
or above the cheaper one's own ask — a line claiming to sell "below
market" while actually sitting above a real, live ask.

Measured against the real sweep, four lines did exactly this:

| Line | Cheapest ask (Floor) | Reference | Chain price | vs. Floor |
|---|---:|---:|---:|---:|
| Taittinger Comtes de Champagne 2006 | £94.99 | £149.17 | £119.34 | +25.6% |
| Taittinger Comtes de Champagne 2008 | £142.33 | £200.00 | £160.00 | +12.4% |
| Louis Roederer Cristal 2006 | £154.17 | £196.33 | £157.06 | +1.9% |
| Dom Pérignon Vintage 2004 | £138.83 | £176.50 | £141.20 | +1.7% |

Every one of these would have carried a "20% below market" claim on a
client document while a buyer who checked one line would find himself
overcharged relative to a price we ourselves had already found. Same
failure signature as the Mugneret-Gibourg Vosne-Romanée case this
project's own test suite already named (`tests/test_vintage_band.py`):
two merchants far apart means one of them is wrong, and the benchmark
cannot tell which — it is not entitled to average them into a number that
reads as safe.

## The fix

> A listed price may never equal or exceed the UK Floor. If
> `buyer_price >= uk_floor`, the line gates — whatever its other flags
> say — and no percentage claim may be printed on it.

A new flag, `Flag.SELL_AT_OR_ABOVE_UK_FLOOR` (`app/core/flags.py`),
computed in `price_line()` (`app/pricing/pricer.py`) from `sell >=
uk_floor` — the real Floor figure every other screen already shows,
never re-derived from Reference or the chain's own settings. It needs no
comp-count special-casing of its own: it is checked once, generically,
after every pricing basis (manual, margin, discount, chain) has already
produced a `sell_price`, and it fires regardless of which basis produced
that price. "Below market" meaning "below Floor" is a fact about the
market, not about which rule happened to set the number.

Same family as `NEGATIVE_GP` and `SELL_ABOVE_UK_REFERENCE`, same gate,
same place: added to `EXPORT_GATE_FLAGS` (`app/db/repo.py`) and to the
`requires_acknowledgement` GENERATED column's own flag array
(`app/db/schema.sql`, migration `0026_sell_at_or_above_floor` — Postgres
has no ALTER for a generated expression, so the column and its two
dependent constraints are dropped and re-added by name). A named operator
can still accept the gate and export the line, exactly as for a
NEGATIVE_GP line today — this is a judgement a person is allowed to make.

What a person may NOT do is have the document itself keep asserting a
false saving. `_claim()`'s own caller (`app/db/repo.py`'s `_offer_line`)
now additionally refuses to build a market claim whenever
`SELL_AT_OR_ABOVE_UK_FLOOR` is present, acceptance of the gate or not —
unconditional, unlike the gate itself. Invariant 15 already established
that a line with no UK Reference carries no claim, absent rather than
blank; this is the same rule extended to a line whose claim would simply
be untrue.

## WIDE_SPREAD gates when comp_count == 2 — a correction, not a reversal

`flags.py`'s own comment on `WIDE_SPREAD` already said "revisit if
operators disagree in practice." This is that revisit, and practice
disagreed. The reasoning — "with two or more independent merchants the
Reference is sound even when the tail is long" — is still exactly right
for three or more comps, where a long tail is one outlier against a body
of agreement. It is false for exactly two: there the tail IS the whole
sample, and Reference is just the dearer of two numbers that contradict
each other.

`BenchmarkResult.state` (`app/core/benchmark.py`) now adds `WIDE_SPREAD`
to its own gating set specifically when `self.comp_count == 2` — the same
place, and the same kind of override, decision 0028 already uses for
`DERIVED_FROM_CASE`'s own exception. `REVIEW_FLAGS` itself
(`app/core/flags.py`) is unchanged: `WIDE_SPREAD` is still not a member,
so a 3+-comp line with a long tail is still READY, exactly as before.

`tests/test_vintage_band.py::test_mugneret_gibourg_2020_six_pack_is_a_
high_outlier` encoded the OLD behaviour directly (`before.state is
State.READY` for a two-comp, 72%-apart line) and is updated to assert
REVIEW instead, with a note on why the vintage band check still matters
even though this decision alone now also catches that exact case.
`tests/test_traps.py` adds the two comp-count-boundary cases directly
(two comps gates, three does not) using the real Comtes de Champagne 2006
figures above, and `tests/test_pricing.py` adds the Floor-guard tests
using the same real evidence.

## What changed, measured

Re-benchmarked and re-priced the real 30-line sweep after this fix:
**READY fell from 11 to 7** — exactly the four lines in the table above,
every one of them now REVIEW with both `WIDE_SPREAD` and
`SELL_AT_OR_ABOVE_UK_FLOOR` set. No other line moved. "Expect READY to
fall from 11. That is the right direction — those lines were never safely
sendable."

## What this is not

Not a change to `DERIVED_FROM_CASE`'s own 0028 agreement exception, which
already requires 2+ comps to agree WITHIN 10% before it stops gating —
stricter than this decision's own floor check, and untouched. Not a
change to `COST_ABOVE_UK_REFERENCE` or `DEEP_DISCOUNT`, still context, not
gates — buying badly or discounting deep are commercial facts, not false
claims. Not a retreat from invariant 4 (Floor/Reference/Median are still
exactly what they always were) — this decision adds a rule about what may
be SOLD and CLAIMED relative to those figures, without changing how they
are computed.

## Consequences

- `app/core/flags.py`: new flag `SELL_AT_OR_ABOVE_UK_FLOOR`; the
  `WIDE_SPREAD` comment corrected to name the comp-count==2 exception and
  where it lives.
- `app/core/benchmark.py`: `BenchmarkResult.state` adds `WIDE_SPREAD` to
  its gating set when `comp_count == 2`.
- `app/pricing/pricer.py`: `price_line()` takes `uk_floor`, sets the new
  flag; module docstring corrected (the chain is NOT floor-safe by
  construction, only reference-safe).
- `app/worker/jobs.py`: `price_deal()` passes `uk_floor=run["uk_floor"]`.
- `app/db/repo.py`: `EXPORT_GATE_FLAGS` gains the new flag;
  `_offer_line`'s claim condition additionally requires its absence.
- `app/db/schema.sql` + migration `0026_sell_at_or_above_floor`:
  `requires_acknowledgement`'s GENERATED expression gains the new flag.
- Tests: `tests/test_pricing.py` (4 new), `tests/test_traps.py` (2 new),
  `tests/test_vintage_band.py` (1 corrected). Full suite: 464 passed
  offline (was 457), 499 passed against Postgres (was 492/493 across the
  session's own earlier counts).
