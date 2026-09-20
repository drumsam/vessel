"""The deterministic pricing step. Pure: no clock, no network, no LLM.

Inputs are the benchmark's figures and the operator's own numbers. Output is a
PricedLine: the sell price, the gross margin, and the commercial flags. Nothing
here decides identity, comparability or the benchmark figures.

Rules (docs/decisions/0007-pricing-rules-and-rounding.md):

    Sell from margin    Sell = Cost / (1 - target_margin)
    Sell from discount  Sell = UK Reference * (1 - discount)
    Gross margin        GM   = (Sell - Cost) / Sell      -- margin, never markup

Precedence: manual price > line margin > line discount > deal margin.

Two of the system's three rounding points are here: the FX conversion of a
non-GBP cost into GBP, and the final sell price. Both go to whole pence with
ROUND_HALF_EVEN. The third is the Median, in app/core/benchmark.py. Nothing
else rounds: GP is the difference of two 2dp figures, and the gross margin is a
ratio stored at its own scale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional

from app.core.flags import Flag

CENT = Decimal("0.01")
RATE = Decimal("0.0001")

#: The one rounding mode, shared with app/core/benchmark.py.
ROUNDING = ROUND_HALF_EVEN

#: Sell more than this far below UK Reference is DEEP_DISCOUNT. A default, not a
#: measured figure: set it per run until there is evidence for a better one.
DEEP_DISCOUNT_THRESHOLD = Decimal("0.25")


class CannotPrice(Exception):
    """The inputs do not determine a price. Never guessed at."""


@dataclass(frozen=True)
class PricedLine:
    price_basis: str                       # manual | line_margin | line_discount | global_margin
    sell_price: Decimal
    cost_gbp: Optional[Decimal]
    gp: Optional[Decimal]
    gross_margin: Optional[Decimal]
    target_margin: Optional[Decimal]
    discount: Optional[Decimal]
    deep_discount_threshold: Decimal
    flags: set[Flag] = field(default_factory=set)


def round_money(value: Decimal) -> Decimal:
    """Rounding point. Whole pence, banker's rounding."""
    return value.quantize(CENT, rounding=ROUNDING)


def convert_cost(cost: Decimal, cost_currency: str, *, fx_rate: Optional[Decimal]) -> Decimal:
    """Rounding point 1 of 2 here: a non-GBP cost in GBP, to whole pence.

    `fx_rate` is GBP per ONE unit of `cost_currency`, as published by the source
    recorded alongside it. Without a rate a non-GBP cost cannot be priced: the
    GP would not be reproducible.
    """
    if cost_currency == "GBP":
        return cost
    if fx_rate is None or fx_rate <= 0:
        raise CannotPrice(f"no FX rate for {cost_currency}")
    return round_money(cost * fx_rate)


def price_line(*, uk_reference: Optional[Decimal], cost: Optional[Decimal],
               cost_currency: Optional[str], fx_rate: Optional[Decimal] = None,
               manual_price: Optional[Decimal] = None,
               line_margin: Optional[Decimal] = None,
               line_discount: Optional[Decimal] = None,
               deal_margin: Optional[Decimal] = None,
               deep_discount_threshold: Decimal = DEEP_DISCOUNT_THRESHOLD) -> PricedLine:
    cost_gbp = (convert_cost(cost, cost_currency or "GBP", fx_rate=fx_rate)
                if cost is not None else None)

    basis, margin, discount = _basis(manual_price, line_margin, line_discount, deal_margin)
    if basis == "manual":
        sell = round_money(manual_price)
    elif discount is not None:
        if uk_reference is None:
            raise CannotPrice("a discount prices off UK Reference, and there is none")
        sell = round_money(uk_reference * (Decimal(1) - discount))
    else:
        if cost_gbp is None:
            raise CannotPrice("a margin prices off cost, and there is none")
        if margin >= 1:
            raise CannotPrice(f"target margin {margin} leaves no price")
        sell = round_money(cost_gbp / (Decimal(1) - margin))

    gp = sell - cost_gbp if cost_gbp is not None else None
    gross_margin = (gp / sell).quantize(RATE, rounding=ROUNDING) if gp is not None and sell else None

    flags: set[Flag] = set()
    if cost_gbp is not None and uk_reference is not None and cost_gbp > uk_reference:
        flags.add(Flag.COST_ABOVE_UK_REFERENCE)
    if uk_reference is not None and sell > uk_reference:
        flags.add(Flag.SELL_ABOVE_UK_REFERENCE)
    if gp is not None and gp < 0:
        flags.add(Flag.NEGATIVE_GP)
    if uk_reference is not None and sell < uk_reference * (Decimal(1) - deep_discount_threshold):
        flags.add(Flag.DEEP_DISCOUNT)

    return PricedLine(price_basis=basis, sell_price=sell, cost_gbp=cost_gbp, gp=gp,
                      gross_margin=gross_margin, target_margin=margin, discount=discount,
                      deep_discount_threshold=deep_discount_threshold, flags=flags)


def _basis(manual_price, line_margin, line_discount, deal_margin):
    """manual price > line margin > line discount > deal margin. The first one
    that is set wins outright; the others are not consulted."""
    if manual_price is not None:
        return "manual", None, None
    if line_margin is not None:
        return "line_margin", line_margin, None
    if line_discount is not None:
        return "line_discount", None, line_discount
    if deal_margin is not None:
        return "global_margin", deal_margin, None
    raise CannotPrice("no manual price, margin or discount applies to this line")
