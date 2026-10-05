# 0007 — Pricing rules, and the four places that round

**Status:** accepted, 20 September 2026. A fourth rounding point was added
24 September by decision 0016. The deep-discount threshold is a default, not a
measurement.

## The rules

    Sell from margin     Sell = Cost / (1 - target_margin)
    Sell from discount   Sell = UK Reference * (1 - discount)
    Gross margin         GM   = (Sell - Cost) / Sell

GM is a **margin, never a markup**. Cost £600 at a 25% target sells at £800, not
£750: markup would under-price by £50 and report a 25% margin that is really 20%.

**Precedence:** manual price > line margin > line discount > deal margin > the
market chain (decision 0017, for a line with nothing else set but a verified
UK Reference). The first one set wins outright and the rest are not
consulted. `price_basis` on `pricing_result` records which one it was.

**Flags** (context, not review gates — `REVIEW_FLAGS` in `app/core/flags.py`
remains the only definition of what forces review):

- `COST_ABOVE_UK_REFERENCE` — cost in GBP is above the Reference
- `SELL_ABOVE_UK_REFERENCE` — the sell price is above the Reference
- `NEGATIVE_GP` — the sell price is below cost
- `DEEP_DISCOUNT` — the sell price is more than `deep_discount_threshold`
  below the Reference. The default is 25%. It is a chosen figure with no
  evidence behind it yet, so it is configurable per run **and the value used is
  stored on the result**: a price has to be explicable a year later.

Nothing is guessed. A margin with no cost, a discount with no Reference, a
non-GBP cost with no FX rate, or a line with no rule at all is skipped with its
reason, and no price is written.

## The four rounding points

Every money figure is `numeric(14,2)`, so every division has to land somewhere.
There are exactly four places where rounding happens, and no others:

| # | Where | What |
|---|---|---|
| 1 | `app/core/benchmark.py` | the Median of an even number of merchant-bests |
| 2 | `app/pricing/pricer.convert_cost` | a non-GBP cost converted to GBP |
| 3 | `app/pricing/pricer.price_line` | the final sell price |
| 4 | `app/core/benchmark.derive_price` | a comparable derived across case sizes (0016) |

All four round to whole pence with `ROUND_HALF_EVEN`, so a run of half-penny
ties does not drift upwards. Each is tested in both directions.

The fourth is different in kind and worth saying out loud: it rounds a figure
**nobody offered**. That is allowed only because a derived comparable is never
presented as an observed price — it carries `DERIVED_FROM_CASE`, so the line
reaches a person, and the real offer it came from is shown beside it.

Everything else is exact or refused:

- **Floor and Reference** are real offer prices. A price that is not a whole
  number of pence is rejected as `NOT_WHOLE_PENCE`, in `benchmark()` and again
  when stored. Farr's feed publishes float32 artefacts such as `308.329986`;
  that is not a price anyone printed, and rounding it would be an estimate.
- **GP** is the difference of two already-rounded 2dp figures.
- **Gross margin** is a ratio, not money, stored at `numeric(6,4)`.
- **FX rate** is a rate, `numeric(18,8)`, GBP per one unit of the cost currency,
  stored with its date and source because a GP that cannot be reproduced is not
  a GP.

## Consequence

An earlier version of this working agreement said there was exactly one place
that rounds. That was too tight: the FX conversion and the sell price are
unavoidable, and pretending otherwise would have pushed rounding somewhere
undocumented. Named, tested places is the rule — three of them until decision
0016 added derivation, which needed a fourth and got one, in the open.
