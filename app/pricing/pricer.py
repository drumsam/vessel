"""The deterministic pricing step. Pure: no clock, no network, no LLM.

Inputs are the benchmark's figures and the operator's own numbers. Output is a
PricedLine: the sell price, the gross margin, and the commercial flags. Nothing
here decides identity, comparability or the benchmark figures.

Rules (docs/decisions/0007-pricing-rules-and-rounding.md):

    Sell from margin    Sell = Cost / (1 - target_margin)
    Sell from discount  Sell = UK Reference * (1 - discount)
    Gross margin        GM   = (Sell - Cost) / Sell      -- margin, never markup

Precedence: manual price > line margin > line discount > deal margin > the
market chain (decision 0017, below).

## The market chain

A private cellar's lines mostly arrive with no manual price, no line margin and
no line discount, and often no deal margin either — the operator has nothing but
a verified UK Reference. Before decision 0017 such a line could not be priced at
all. Doug's model (5 October 2026):

    UK market reference (per bottle)      M
    buyer price            = M * (1 - BUYER_DISCOUNT)   -- what a trade buyer pays
    seller receives         = buyer price * (1 - MARGIN_ON_SALE)  -- what we pay the seller
                            = M * (1 - BUYER_DISCOUNT) * (1 - MARGIN_ON_SALE)

Two sales, not one: a trade buyer PURCHASES below market, and the seller SELLS
below that again, and conflating the two into a single flat "discount" hides
where the margin actually lives. `sell_price` IS the buyer price and `cost_gbp`
IS what we pay the seller for this basis — the same two fields every other basis
already uses for GP, flags and export, so nothing downstream had to change to
understand the chain. `buyer_price_gbp`/`seller_price_gbp` are the same two
numbers under names that cannot be misread.

`BUYER_DISCOUNT` and `MARGIN_ON_SALE` are per-deal overridable (never per-line:
Doug's spec). Both actual values used are recorded on `PricedLine` and then on
`pricing_result`, so a reprice is a diff against what was used, not a new guess.
This basis never produces `NEGATIVE_GP`, `COST_ABOVE_UK_REFERENCE` or
`SELL_ABOVE_UK_REFERENCE`: both prices derive from one chain, so the seller
price is always below Reference and the buyer price always below Reference, by
construction. `DEEP_DISCOUNT` still fires if a deal sets `buyer_discount` deeper
than `deep_discount_threshold` — that is still worth a look.

It CAN still produce `SELL_AT_OR_ABOVE_UK_FLOOR` (decision 0033) — "below
Reference by construction" is not "below Floor by construction". With
exactly two comps, Reference is the dearer of the two, so `uk_reference *
(1 - BUYER_DISCOUNT)` can land at or above the cheaper one's own ask: found
live on four real Champagne lines, one of them only 1.7% above Floor. The
flag is computed from `uk_floor` directly, the same real figure every
other screen already shows, never re-derived from the chain's own numbers.

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

#: The market chain (decision 0017). Doug's figures, 5 October 2026: trade
#: buyers move parcels 20% below the UK market reference, and we take an 8% fee
#: on that buyer price. Both are per-deal overridable; see docs/decisions/0017.
BUYER_DISCOUNT = Decimal("0.20")
MARGIN_ON_SALE = Decimal("0.08")


class CannotPrice(Exception):
    """The inputs do not determine a price. Never guessed at."""


@dataclass(frozen=True)
class PricedLine:
    # manual | line_margin | line_discount | global_margin | buyer_discount
    price_basis: str
    sell_price: Decimal
    cost_gbp: Optional[Decimal]
    gp: Optional[Decimal]
    gross_margin: Optional[Decimal]
    target_margin: Optional[Decimal]
    discount: Optional[Decimal]
    deep_discount_threshold: Decimal
    flags: set[Flag] = field(default_factory=set)

    #: Set only when price_basis == "buyer_discount": the two settings actually
    #: used, and the same two prices under names that cannot be misread — one
    #: is a sale, the other is a purchase (decision 0017).
    buyer_discount: Optional[Decimal] = None
    margin_on_sale: Optional[Decimal] = None
    buyer_price_gbp: Optional[Decimal] = None
    seller_price_gbp: Optional[Decimal] = None


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
               cost_currency: Optional[str], uk_floor: Optional[Decimal] = None,
               fx_rate: Optional[Decimal] = None,
               manual_price: Optional[Decimal] = None,
               line_margin: Optional[Decimal] = None,
               line_discount: Optional[Decimal] = None,
               deal_margin: Optional[Decimal] = None,
               buyer_discount: Optional[Decimal] = None,
               margin_on_sale: Optional[Decimal] = None,
               deep_discount_threshold: Decimal = DEEP_DISCOUNT_THRESHOLD) -> PricedLine:
    cost_gbp = (convert_cost(cost, cost_currency or "GBP", fx_rate=fx_rate)
                if cost is not None else None)

    basis, margin, discount = _basis(manual_price, line_margin, line_discount, deal_margin,
                                     chain_available=uk_reference is not None)

    chain_buyer_discount = chain_margin_on_sale = None
    if basis == "manual":
        sell = round_money(manual_price)
    elif basis == "buyer_discount":
        # The chain computes BOTH numbers from the market reference; any
        # externally supplied cost is not consulted — that is what distinguishes
        # this basis from line_margin/global_margin, which price off a cost the
        # operator already knows.
        chain_buyer_discount = buyer_discount if buyer_discount is not None else BUYER_DISCOUNT
        chain_margin_on_sale = margin_on_sale if margin_on_sale is not None else MARGIN_ON_SALE
        if chain_buyer_discount >= 1:
            raise CannotPrice(f"buyer discount {chain_buyer_discount} leaves no price")
        if chain_margin_on_sale >= 1:
            raise CannotPrice(f"margin on sale {chain_margin_on_sale} leaves no price")
        buyer_price = round_money(uk_reference * (Decimal(1) - chain_buyer_discount))
        seller_price = round_money(buyer_price * (Decimal(1) - chain_margin_on_sale))
        sell = buyer_price
        cost_gbp = seller_price
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
    # Decision 0033: with exactly two comps, Reference is the DEARER of the
    # two, so a price below Reference can still sit at or above the
    # cheapest ask actually found — "below market" must mean below the
    # Floor, not below whichever number the benchmark called Reference.
    if uk_floor is not None and sell >= uk_floor:
        flags.add(Flag.SELL_AT_OR_ABOVE_UK_FLOOR)
    if gp is not None and gp < 0:
        flags.add(Flag.NEGATIVE_GP)
    if uk_reference is not None and sell < uk_reference * (Decimal(1) - deep_discount_threshold):
        flags.add(Flag.DEEP_DISCOUNT)

    return PricedLine(
        price_basis=basis, sell_price=sell, cost_gbp=cost_gbp, gp=gp,
        gross_margin=gross_margin, target_margin=margin, discount=discount,
        deep_discount_threshold=deep_discount_threshold, flags=flags,
        buyer_discount=chain_buyer_discount, margin_on_sale=chain_margin_on_sale,
        buyer_price_gbp=sell if basis == "buyer_discount" else None,
        seller_price_gbp=cost_gbp if basis == "buyer_discount" else None,
    )


def _basis(manual_price, line_margin, line_discount, deal_margin, *, chain_available: bool):
    """manual price > line margin > line discount > deal margin > the market
    chain. The first one that is set wins outright; the others are not
    consulted. The chain is the fallback for a line with nothing set but a
    verified UK Reference — decision 0017, built because that used to be
    exactly the case where this function raised CannotPrice."""
    if manual_price is not None:
        return "manual", None, None
    if line_margin is not None:
        return "line_margin", line_margin, None
    if line_discount is not None:
        return "line_discount", None, line_discount
    if deal_margin is not None:
        return "global_margin", deal_margin, None
    if chain_available:
        return "buyer_discount", None, None
    raise CannotPrice("no manual price, margin, discount or market reference applies "
                      "to this line")
