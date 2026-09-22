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
     A brokerage INDICATION is excluded by the KIND screen in the same way and
     returned as corroboration: a price nobody has offered stock at cannot be a
     Floor, a Reference or a Median. See docs/decisions/0013.
  4. Market depth is counted in MERCHANTS. A merchant that lists the same wine
     twice never becomes its own second-lowest reference.
  5. Floor = lowest merchant-best. Reference = second-lowest merchant-best, or
     the only one when depth is 1 (flag ONE_COMP). Median = median of
     merchant-bests. Reference is what drives pricing; Floor and Median are
     internal evidence.
  6. Zero comparables => NO_MARKET. Never a guess, never a substitute.
  7. Freshness. An offer is comparable only if it was captured within
     MAX_OFFER_AGE_DAYS before `as_of`, and not after it. An undated offer is
     not provably fresh and is rejected. `as_of` is an argument, never the
     clock: this function stays pure. See docs/decisions/0003.
  8. Inherited line flags (NAME_REVIEW, FORMAT_REVIEW, DERIVED_FROM_CASE) are
     unioned into the result before state is derived. Only review flags may be
     inherited, so inheriting can add a reason for review and never remove one.
     See docs/decisions/0005.

Rounding. Exactly one figure is ever rounded here: the Median, which for an even
number of merchant-bests is the mean of the middle two and can land on half a
penny (£610.01, £610.02 -> £610.015). It is quantised to whole pence with
ROUND_HALF_EVEN (banker's rounding: £610.015 -> £610.02, £610.025 -> £610.02),
so a run of ties does not drift upwards.

Floor and Reference are real offer prices and are NEVER rounded. An offer whose
price is not a whole number of pence is rejected as NOT_WHOLE_PENCE and cannot
become either. Farr's feed publishes float32 artefacts such as 308.329986; that
is not a price anyone printed, and rounding it would be an estimate. The same
refusal is applied again when a figure is stored.

The system's other two rounding points are outside this module and are named in
docs/decisions/0007: FX conversion of a non-GBP cost, and the final sell price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from statistics import median
from typing import Iterable, Optional

from .enums import DutyStatus, PriceKind, Reject, State
from .flags import (
    CONDITION_REVIEW_FLAGS,
    MAX_OFFER_AGE_DAYS,
    REQUIRE_QUANTITY_COVER,
    REVIEW_FLAGS,
    WIDE_SPREAD_THRESHOLD,
    Flag,
)
from .models import GBP, Offer, SellerLine

CENT = Decimal("0.01")

#: The one rounding mode in the pricing core. Applied to the Median only.
MEDIAN_ROUNDING = ROUND_HALF_EVEN

MAX_OFFER_AGE = timedelta(days=MAX_OFFER_AGE_DAYS)


@dataclass(frozen=True)
class Rejection:
    offer: Offer
    reason: Reject


@dataclass(frozen=True)
class IndicationEvidence:
    """A brokerage's aggregated indication of where a wine would broker, and how
    far it sits from the Reference. Corroboration, never a price: the indication
    does not imply the wine exists, and the merchant that published it holds no
    stock at that price. Shown to the operator, never on a client document.
    """
    offer: Offer
    variance_vs_reference: Optional[Decimal]     # (indication - reference) / reference


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
    as_of: datetime
    comparables: list[Offer] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    cross_unit: list[CrossUnitEvidence] = field(default_factory=list)
    indications: list[IndicationEvidence] = field(default_factory=list)

    merchant_bests: list[Offer] = field(default_factory=list)
    duplicate_listings: int = 0

    uk_floor: Optional[Decimal] = None
    uk_reference: Optional[Decimal] = None
    uk_median: Optional[Decimal] = None

    flags: set[Flag] = field(default_factory=set)

    #: as_of minus the capture time of the OLDEST merchant-best: how old the
    #: stalest evidence behind these figures is. None when there is none.
    oldest_comp_age: Optional[timedelta] = None

    @property
    def comp_count(self) -> int:
        """Depth in merchants — the number always shown to the operator."""
        return len(self.merchant_bests)

    @property
    def state(self) -> State:
        if not self.merchant_bests:
            return State.NO_MARKET
        return State.REVIEW if (self.flags & REVIEW_FLAGS) else State.READY


def _is_fresh(o: Offer, as_of: datetime) -> bool:
    return o.captured_at is not None and as_of - MAX_OFFER_AGE <= o.captured_at <= as_of


def _screen(line: SellerLine, o: Offer, as_of: datetime) -> Optional[Reject]:
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
    if not _is_fresh(o, as_of):
        return Reject.STALE
    if o.price != o.price.quantize(CENT):
        return Reject.NOT_WHOLE_PENCE
    if REQUIRE_QUANTITY_COVER and (o.offered_units or 0) < line.quantity:
        return Reject.NO_QUANTITY
    return None


def _is_indication(line: SellerLine, o: Offer, as_of: datetime) -> bool:
    """Right wine, right vintage, right format, and a live brokerage indication.

    Buyability and duty status are deliberately NOT required: an indication is
    never stock, so every one of them is unbuyable by definition. That is what
    makes it corroboration rather than a comparable.
    """
    return (
        o.price_kind is PriceKind.INDICATION
        and o.wine_id == line.wine_id
        and not o.is_mixed_lot
        and o.vintage == line.vintage
        and o.bottle_ml == line.bottle_ml
        and o.pack_size == line.pack_size
        and o.currency == GBP
        and o.price is not None
        and o.price > Decimal("0")
        and o.price == o.price.quantize(CENT)
        and _is_fresh(o, as_of)
    )


def _is_cross_unit(line: SellerLine, o: Offer, as_of: datetime) -> bool:
    """Right wine, right vintage, right bottle size, wrong commercial unit —
    and otherwise a valid, fresh In Bond ask."""
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
        and o.price == o.price.quantize(CENT)
        and _is_fresh(o, as_of)
    )


def benchmark(line: SellerLine, offers: Iterable[Offer], *, as_of: datetime) -> BenchmarkResult:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    not_review = set(line.inherited_flags) - REVIEW_FLAGS
    if not_review:
        raise ValueError(f"only review flags can be inherited, got {sorted(f.value for f in not_review)}")

    result = BenchmarkResult(line=line, as_of=as_of)
    result.flags |= line.inherited_flags

    indications: list[Offer] = []
    for o in offers:
        reason = _screen(line, o, as_of)
        if reason is None:
            result.comparables.append(o)
            continue
        result.rejections.append(Rejection(offer=o, reason=reason))
        if reason is Reject.UNIT and _is_cross_unit(line, o, as_of):
            result.cross_unit.append(
                CrossUnitEvidence(offer=o, per_bottle=o.price / o.pack_size)
            )
        elif _is_indication(line, o, as_of):
            # Not tied to which screen fired: KIND excludes an indication from
            # pricing, but one with an unknown duty status is rejected by DUTY
            # first. Either way it is still corroboration, and the predicate
            # itself admits nothing but an INDICATION.
            indications.append(o)

    # --- depth in merchants, not listings -------------------------------
    best: dict[str, Offer] = {}
    for o in result.comparables:
        cur = best.get(o.merchant_id)
        if cur is None or o.price < cur.price:
            best[o.merchant_id] = o
    result.merchant_bests = sorted(best.values(), key=lambda x: x.price)
    result.duplicate_listings = len(result.comparables) - len(result.merchant_bests)

    def with_variance(reference: Optional[Decimal]) -> list[IndicationEvidence]:
        return [IndicationEvidence(offer=o,
                                   variance_vs_reference=((o.price - reference) / reference)
                                   if reference else None)
                for o in sorted(indications, key=lambda x: x.price)]

    if not result.merchant_bests:
        result.indications = with_variance(None)
        result.flags.add(Flag.NO_MARKET)
        return result

    prices = [o.price for o in result.merchant_bests]
    result.uk_floor = prices[0]
    result.uk_median = Decimal(str(median(prices))).quantize(CENT, rounding=MEDIAN_ROUNDING)
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

    result.oldest_comp_age = as_of - min(o.captured_at for o in result.merchant_bests)

    result.indications = with_variance(result.uk_reference)

    covering = [o for o in result.merchant_bests
                if o.offered_units is None or o.offered_units >= line.quantity]
    if not covering:
        result.flags.add(Flag.QUANTITY_SHORTFALL)

    return result
