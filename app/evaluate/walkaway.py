"""The walk-away price (`docs/research/buy-side-margin-test.md`, VESSEL
Pocket Screen 3, EVALUATE). Pure, Decimal-only, no database, no I/O --
`app.core.flags` supplies the two constants and nothing here duplicates
or re-derives `app.core.benchmark`'s own Floor; it is read, never
recomputed.

**Not a verdict.** This states the most Doug can pay and leaves him to
compare it with the ask -- no "good buy", no score, no traffic light.
Doug's own architecture review is explicit that EVALUATE renders no
verdict; a pass/fail against a threshold he set himself is not a
verdict, it is arithmetic done faster.

Everything here is per the line's OWN commercial unit -- whatever
`uk_floor` itself is already in (a case price if the line's pack_size is
a case, a bottle price if it is one) -- never assumed to be per bottle.
`app.core.benchmark.Offer.price` is documented as "for ONE unit as
defined by pack_size"; `uk_floor` inherits that basis directly, and so
does every figure this module derives from it.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional

from app.core.flags import MIN_BUYER_DISCOUNT, MIN_TRADE_MARGIN

CENT = Decimal("0.01")


def _round(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class WalkAway:
    """All four money fields are per the line's own commercial unit."""
    uk_floor: Decimal
    max_sell: Decimal       # Floor x (1 - MIN_BUYER_DISCOUNT), decision 0033's ceiling plus 0034's haircut
    walk_away: Decimal      # max_sell / (1 + MIN_TRADE_MARGIN) -- the most Doug can pay


def compute(uk_floor: Decimal) -> WalkAway:
    """The walk-away price is only as good as the Floor underneath it --
    callers are responsible for not calling this at all when there is no
    Floor (NO_MARKET), when the line is still REVIEW, or when a single-
    source Floor has not been acknowledged; this function has no
    opinion on any of that, it only does the arithmetic once given a
    real Floor to work from."""
    max_sell = _round(uk_floor * (1 - MIN_BUYER_DISCOUNT))
    walk_away = _round(max_sell / (1 + MIN_TRADE_MARGIN))
    return WalkAway(uk_floor=uk_floor, max_sell=max_sell, walk_away=walk_away)


def ask_per_unit(price: Decimal, basis: Optional[str], pack_size: int, quantity: int) -> Decimal:
    """Converts a confirmed ask (in whatever basis was stated) to price
    per commercial unit -- the same basis `uk_floor` is already in.

    `basis=None` is reachable only when pack_size*quantity == 1 (the
    confirm-identity endpoint blocks a null basis on any larger line):
    with exactly one bottle, one case and the total are the same number,
    so no assumption is made by returning the price unconverted."""
    if basis in (None, "per_case"):
        return price
    if basis == "per_bottle":
        return _round(price * pack_size)
    if basis == "total":
        return _round(price / quantity)
    raise ValueError(f"unknown asking_basis {basis!r}")


def margin_at_ask(max_sell: Decimal, ask_per_unit_: Decimal) -> Decimal:
    """(max_sell - ask) / ask -- the margin Doug would actually realise
    buying at this ask and selling at the best price decision 0033/0034
    allow (max_sell), not at the bare walk-away threshold itself."""
    if ask_per_unit_ <= 0:
        raise ValueError("ask must be positive")
    return ((max_sell - ask_per_unit_) / ask_per_unit_).quantize(Decimal("0.0001"),
                                                                  rounding=ROUND_HALF_EVEN)


def required_sell_for_margin(ask_per_unit_: Decimal) -> Decimal:
    """What a sell price would have to be to hit MIN_TRADE_MARGIN at this
    ask -- shown only when the ask is already above walk-away, to say
    exactly why: compare the result against uk_floor and against
    max_sell to say which guard it would breach."""
    return _round(ask_per_unit_ * (1 + MIN_TRADE_MARGIN))
