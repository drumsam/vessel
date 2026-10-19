# 0034 — every percentage claim is computed against Floor, never Reference

**Status:** accepted, 19 October 2026. Found by Doug on the Cellar Desk,
immediately after decision 0033 shipped — "your fix is right... but it has
exposed a real pricing hole" was 0033's own framing for the gate; this is
the same framing one level down, for the number printed next to a line
that is NOT gated.

## The gap

Decision 0033 stops a line SELLING at or above Floor. It says nothing about
a line selling a few pence below Floor while a document still claims "20%
below market" — true against the chain's own 20% `BUYER_DISCOUNT` off
Reference, false as a description of how this price compares to the
cheapest ask actually found.

Real evidence, the same sweep:

| Line | Floor | Offer | vs. Floor |
|---|---:|---:|---:|
| Dom Pérignon Vintage 2010 | £143.33 | £142.00 | 0.9% below |
| Louis Roederer Cristal 2007 | £158.33 | £152.00 | 4.0% below |

Neither line trips `SELL_AT_OR_ABOVE_UK_FLOOR` — both are genuinely below
Floor, so 0033's own gate is silent, correctly. But a document that still
prints "20% below market" next to either line is not describing a false
sale; it is describing a true sale with a false number, which is its own
way of being wrong. Averaged across the drop, it compounds: "across the 6
sendable lines the honest aggregate is 13%, not 20%."

## The fix

> The displayed and printed saving is ALWAYS `1 - sell_price/uk_floor`, per
> line, never derived from Reference and never averaged across a drop.
> Computed once, server-side, and stored/returned as that figure — not
> recomputed from Floor and sell price by a client that could get it wrong
> twice.

`app/core/flags.py` gains two pure functions, not flags — this is a number,
not a fact about whether the line is sendable:

- `floor_saving(sell_price, uk_floor)` — `(1 - sell/floor)`, `None` with no
  Floor to measure against. Quantized to four decimal places
  (`Decimal.quantize`, default `ROUND_HALF_EVEN`) for a stable, comparable
  figure — this is a ratio, not a price, and is not one of invariant 7's
  four money-rounding points; nothing here is Decimal arithmetic on a
  price that reaches a client document as currency.
- `claims_a_saving(sell_price, uk_floor)` — `floor_saving`, but also `None`
  when the real saving exists and is simply too small to print: a new
  constant, `MIN_CLAIM_THRESHOLD = Decimal("0.05")` — "I'd start at 5%,"
  Doug's own words, a starting value rather than a measured one, exactly
  the discipline `AGREEMENT_THRESHOLD` and `WIDE_SPREAD_THRESHOLD` already
  follow: a plain constant with its evidentiary origin in a comment,
  revisited once more real drops exist than this one.

A line below the threshold is not held back from sale — it is held back
from being ADVERTISED as a discount. "It can still be sold; it just cannot
be advertised as a discount" — same shape, same words almost exactly, as
invariant 15's own rule for a line with no UK Reference at all: absent,
not a number too small to matter. Over the API the two cases are
indistinguishable by design — `floor_saving_claim: null` either way — and
a client document or the Desk must treat them identically: no percentage
badge, full stop.

Exposed via `PricingOut.floor_saving_claim` (`app/api/schemas.py`),
computed once in `_pricing_out()` (`app/api/main.py`) from the two figures
already stored on `pricing_result` — `uk_floor` and `sell_price` — and
never recomputed anywhere downstream. The Desk and the new client document
both read this one field; neither computes a percentage of its own.

## What this is not

Not a retrofit of the existing `buyer_offer_market_claim` /
`_claim()` mechanism in `app/db/repo.py`. That mechanism is
Reference-based by design and belongs to the already-shipped,
separate direct-purchase `buyer_offer` chain (invariant 15); it is
untouched here. This decision's computation is new, deliberately
reusable, and built for the Cellar Desk and the new VESSEL-style client
document — the places Doug's own complaint was actually about. Retrofitting
the unrelated, already-shipped feature without being asked would be an
unscoped change to a working path; if Doug wants the existing buyer-offer
claim rebuilt on the same basis, that is a separate, explicit decision.

Not a change to decision 0033's own gate: `SELL_AT_OR_ABOVE_UK_FLOOR`
still fires exactly as before, on the same figures, for the same reason.
This decision only changes what number is allowed to be PRINTED on a line
that gate did not catch.

Not a change to `app/core/benchmark.py` or `REVIEW_FLAGS`: Floor,
Reference and Median are still exactly what invariant 4 says they are.
Nothing here recomputes a benchmark figure; it only governs what a client
document or the Desk may claim from figures that already exist.

## Consequences

- `app/core/flags.py`: new constant `MIN_CLAIM_THRESHOLD = Decimal("0.05")`;
  new functions `floor_saving()` and `claims_a_saving()`.
- `app/api/schemas.py`: `PricingOut.floor_saving_claim: Optional[Decimal]`.
- `app/api/main.py`: `_pricing_out()` computes it from the pricing row's own
  `uk_floor`/`sell_price`, once, server-side.
- Tests: `tests/test_pricing.py` gains 6 new tests using Doug's own cited
  real figures (Dom Pérignon Vintage 2010 at 0.9%, Louis Roederer Cristal
  2007 at 4.0%, both suppressed; a real 18.76%-below-Floor line, not
  suppressed). Full offline suite: 470 passed (was 464), 163 skipped.
- Follow-on, not yet built: the Cellar Desk and the new client offer
  document must read `floor_saving_claim` for their own percentage
  display, and the per-bottle-first redisplay (the other half of Doug's
  same message) is tracked separately.
