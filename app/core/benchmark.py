"""The deterministic UK benchmark.

No LLM. No network. No name matching. No unit conversion. Pure function of
(SellerLine, [Offer]) -> BenchmarkResult.

These invariants are the part of the system that must not drift as adapters are
added. The adapter contract may evolve; this must not.

  1. An offer is comparable only if EVERY screen passes. Screens are exclusive
     and each rejection is recorded with its reason.
  2. Identity is compared by approved canonical `wine_id` only. This module does
     not know what a producer or a cuvee is.
  3. Commercial unit equality is exact: 1x75cl matches 1x75cl, 6x75cl matches
     6x75cl. No division, no multiplication, ever. Cross-unit evidence is
     returned separately as excluded evidence for the operator to see.
  4. Market depth is counted in MERCHANTS. A merchant that lists the same wine
     twice never becomes its own second-lowest reference.
  5. Floor = lowest merchant-best. Reference = second-lowest merchant-best, or
     the only one when depth is 1 (flag ONE_COMP). Median = median of
     merchant-bests. Reference is what drives pricing; Floor and Median are
     internal evidence.
  6. Zero comparables => NO_MARKET. Never a guess, never a substitute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median
from typing import Iterable, Optional

from .enums import DutyStatus, PriceKind, Reject, State
from .flags import (
    CONDITION_REVIEW_FLAGS,
    REQUIRE_QUANTITY_COVER,
    REVIEW_FLAGS,
    WIDE_SPREAD_THRESHOLD,
    Flag,
)
from .models import GBP, Offer, SellerLine


@dataclass(frozen=True)
class Rejection:
    offer: Offer
    reason: Reject


@dataclass(frozen=True)
class CrossUnitEvidence:
    """Same wine, same vintage, same bottle size, DIFFERENT commercial unit.
    Shown to the operator with the arithmetic spelled out. Never used to price.

    The observed loose-vs-pro-rata basis ranges from -17% to +20% in live data
    (see docs/decisions/0001-no-automatic-case-division.md), so no constant
    conversion is defensible.
    """
    offer: Offer
    per_bottle: Decimal            # offer.price / pack_size, for display only


@dataclass
class BenchmarkResult:
    line: SellerLine
    comparables: list[Offer] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    cross_unit: list[CrossUnitEvidence] = field(default_factory=list)

    merchant_bests: list[Offer] = field(default_factory=list)
    duplicate_listings: int = 0

    uk_floor: Optional[Decimal] = None
    uk_reference: Optional[Decimal] = None
    uk_median: Optional[Decimal] = None

    flags: set[Flag] = field(default_factory=set)

    @property
    def comp_count(self) -> int:
        """Depth in merchants — the number always shown to the operator."""
        return len(self.merchant_bests)

    @property
    def state(self) -> State:
        if not self.merchant_bests:
            return State.NO_MARKET
        return State.REVIEW if (self.flags & REVIEW_FLAGS) else State.READY


def _screen(line: SellerLine, o: Offer) -> Optional[Reject]:
    """Return the reason this offer is not comparable, or None if it is.

    Order matters only for which reason gets reported; the outcome does not.
    Identity first so rejection counts stay readable.
    """
    if not o.wine_id:
        return Reject.UNRESOLVED_IDENTITY
    if o.wine_id != line.wine_id:
        return Reject.WINE
    if o.is_mixed_lot:
        return Reject.MIXED_LOT
    if o.vintage != line.vintage:
        return Reject.VINTAGE
    if o.bottle_ml != line.bottle_ml:
        return Reject.SIZE
    if o.pack_size != line.pack_size:
        return Reject.UNIT
    if o.duty_status is not DutyStatus.IN_BOND:
        return Reject.DUTY
    if o.price_kind is not PriceKind.ASK:
        return Reject.KIND
    if o.currency != GBP:
        return Reject.CURRENCY
    if o.is_buyable is not True:
        return Reject.NOT_BUYABLE
    if o.offered_units is not None and o.offered_units <= 0:
        return Reject.NO_QUANTITY
    if o.price is None or o.price <= Decimal("0"):
        return Reject.NON_POSITIVE_PRICE
    if REQUIRE_QUANTITY_COVER and (o.offered_units or 0) < line.quantity:
        return Reject.NO_QUANTITY
    return None


def _is_cross_unit(line: SellerLine, o: Offer) -> bool:
    """Right wine, right vintage, right bottle size, wrong commercial unit —
    and otherwise a valid In Bond ask."""
    return (
        o.wine_id == line.wine_id
        and not o.is_mixed_lot
        and o.vintage == line.vintage
        and o.bottle_ml == line.bottle_ml
        and o.pack_size != line.pack_size
        and o.duty_status is DutyStatus.IN_BOND
        and o.price_kind is PriceKind.ASK
        and o.currency == GBP
        and o.is_buyable is True
        and o.price is not None
        and o.price > Decimal("0")
    )


def benchmark(line: SellerLine, offers: Iterable[Offer]) -> BenchmarkResult:
    result = BenchmarkResult(line=line)

    for o in offers:
        reason = _screen(line, o)
        if reason is None:
            result.comparables.append(o)
            continue
        result.rejections.append(Rejection(offer=o, reason=reason))
        if reason is Reject.UNIT and _is_cross_unit(line, o):
            result.cross_unit.append(
                CrossUnitEvidence(offer=o, per_bottle=o.price / o.pack_size)
            )

    # --- depth in merchants, not listings -------------------------------
    best: dict[str, Offer] = {}
    for o in result.comparables:
        cur = best.get(o.merchant_id)
        if cur is None or o.price < cur.price:
            best[o.merchant_id] = o
    result.merchant_bests = sorted(best.values(), key=lambda x: x.price)
    result.duplicate_listings = len(result.comparables) - len(result.merchant_bests)

    if not result.merchant_bests:
        result.flags.add(Flag.NO_MARKET)
        return result

    prices = [o.price for o in result.merchant_bests]
    result.uk_floor = prices[0]
    result.uk_median = Decimal(str(median(prices)))
    result.uk_reference = prices[0] if len(prices) == 1 else prices[1]

    if len(prices) == 1:
        result.flags.add(Flag.ONE_COMP)
    elif (prices[-1] - prices[0]) / prices[0] > Decimal(str(WIDE_SPREAD_THRESHOLD)):
        result.flags.add(Flag.WIDE_SPREAD)

    for o in result.merchant_bests:
        if o.condition_flags & CONDITION_REVIEW_FLAGS:
            result.flags.add(Flag.CONDITION_REVIEW)
        if o.stock_type_basis == "unconfirmed":
            result.flags.add(Flag.STOCK_BASIS_UNCONFIRMED)

    covering = [o for o in result.merchant_bests
                if o.offered_units is None or o.offered_units >= line.quantity]
    if not covering:
        result.flags.add(Flag.QUANTITY_SHORTFALL)

    return result
