"""The vintage-neighbour sanity check.

Spec: docs/research/vintage-neighbour-check-spec.md.

2020 Mugneret-Gibourg Vosne-Romanée village, 6×75 In Bond: Lea & Sandeman
£1,200, Bordeaux Index £2,070. Two merchants, so the UK Reference is the dearer
of them, and the line goes out ready to price off a number 72% above a live UK
ask. The pricing core cannot tell which one is wrong, because it only ever sees
one wine and one vintage.

This runs **after** the benchmark, on its result, and is a sanity check on comps
we already hold. It is not a price source:

1. A neighbouring vintage never enters Floor, Reference or Median, never appears
   on a client document, and is never interpolated into a missing vintage.
2. No arithmetic across commercial units. 6×75 is compared with 6×75. The
   cross-format signal is displayed as evidence and never converted into a comp.
3. No price is ever adjusted for vintage quality. A better or worse vintage
   WIDENS the acceptance band; it never scales a number.
4. Nothing in app/core/ changes.

The asymmetry in section 5 of the spec is the important part. A high outlier is
excluded automatically, because dropping a dear comp moves the Reference down:
we pay less and we sell lower, and the line goes to a human anyway. A low
outlier is never excluded automatically, because dropping a cheap comp pushes
the Reference up, which makes us overpay and lets us overprice a client. Often
the cheap comp is the true signal — a merchant clearing stock is a real price.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable, Optional

from app.core.enums import DutyStatus, PriceKind
from app.core.flags import MAX_OFFER_AGE_DAYS
from app.core.models import GBP, Offer, SellerLine

#: The spec asks for these to sit beside WIDE_SPREAD_THRESHOLD in
#: app/core/flags.py. app/core/ is frozen, so they live here instead, documented
#: in the same way. Moving them is a core change and needs to be asked for.
HIGH_MULTIPLE = Decimal("1.35")      # above band_high x this -> high outlier
LOW_MULTIPLE = Decimal("0.65")       # below band_low x this  -> low outlier
FORMAT_INCOHERENCE = Decimal("0.30")  # per-bottle disagreement within one merchant

#: Neighbours are V±1 .. V±3, and at least two distinct vintages are required:
#: one neighbour is an anecdote, not a band.
NEIGHBOUR_SPAN = 3
MIN_NEIGHBOUR_VINTAGES = 2

#: Comps must be fresh (14 days, decision 0003). A band is allowed to lean on
#: older evidence — it prices nothing — but anything past the comp window is
#: labelled so the operator knows what they are looking at.
NEIGHBOUR_MAX_AGE_DAYS = 90

#: tier 1 = greatest. A tier apart widens the band by 15%, capped at 1.6.
TIER_STEP = Decimal("0.15")
TIER_CAP = Decimal("1.6")

#: What the check can say about a comp. These are not core REVIEW_FLAGS: making
#: them gate review means adding them to app/core/flags.py, which is frozen.
COMP_EXCLUDED_VINTAGE_BAND = "COMP_EXCLUDED_VINTAGE_BAND"
LOW_COMP_OUT_OF_BAND = "LOW_COMP_OUT_OF_BAND"
MERCHANT_FORMAT_INCOHERENT = "MERCHANT_FORMAT_INCOHERENT"


@dataclass(frozen=True)
class NeighbourVintage:
    vintage: int
    median: Decimal                  # median of that vintage's merchant-bests
    merchants: int
    newest_captured_at: Optional[datetime]
    stale: bool                      # nothing fresher than the comp window


@dataclass(frozen=True)
class OfferRef:
    """A comp the band has something to say about."""
    offer_id: str
    merchant_id: str
    merchant: str
    price: Decimal
    edge: Decimal                    # the band edge it failed, after widening
    multiple: Decimal                # price / edge, for the operator to see
    flag: str


@dataclass(frozen=True)
class FormatDisagreement:
    """One merchant disagreeing with itself across formats. Display only: the
    per-bottle figures exist inside this check and nowhere else."""
    offer_id: str
    merchant_id: str
    merchant: str
    comp_unit: str
    comp_per_bottle: Decimal
    other_unit: str
    other_per_bottle: Decimal
    difference: Decimal
    flag: str = MERCHANT_FORMAT_INCOHERENT


@dataclass(frozen=True)
class VintageBandCheck:
    wine_id: str
    vintage: int
    unit: str                        # "6x750" — display only, never arithmetic
    band_low: Optional[Decimal]
    band_high: Optional[Decimal]
    neighbours: list[NeighbourVintage] = field(default_factory=list)
    high_outliers: list[OfferRef] = field(default_factory=list)
    low_outliers: list[OfferRef] = field(default_factory=list)
    format_incoherent: list[FormatDisagreement] = field(default_factory=list)
    tiers_available: bool = False
    note: Optional[str] = None       # why the check was not run, or what it leans on

    @property
    def ran(self) -> bool:
        return self.band_low is not None and self.band_high is not None


def unit_label(pack_size: int, bottle_ml: int) -> str:
    return f"{pack_size}x{bottle_ml}"


def _usable(offer: Offer, line: SellerLine, as_of: datetime) -> bool:
    """The same screens the benchmark applies, except the vintage — and a
    longer freshness window, because a band prices nothing."""
    return (
        offer.wine_id == line.wine_id
        and not offer.is_mixed_lot
        and offer.bottle_ml == line.bottle_ml
        and offer.pack_size == line.pack_size          # never across units
        and offer.duty_status is DutyStatus.IN_BOND
        and offer.price_kind is PriceKind.ASK
        and offer.currency == GBP
        and offer.is_buyable is True
        and offer.price is not None
        and offer.price > Decimal("0")
        and offer.captured_at is not None
        and as_of - timedelta(days=NEIGHBOUR_MAX_AGE_DAYS) <= offer.captured_at <= as_of
    )


def neighbour_vintages(line: SellerLine, offers: Iterable[Offer], as_of: datetime,
                       ) -> list[NeighbourVintage]:
    """One entry per neighbouring vintage, priced the way the benchmark prices:
    the merchant-best first, then the median across merchants."""
    wanted = {line.vintage + step for step in range(-NEIGHBOUR_SPAN, NEIGHBOUR_SPAN + 1)}
    wanted.discard(line.vintage)

    by_vintage: dict[int, list[Offer]] = {}
    for offer in offers:
        if offer.vintage in wanted and _usable(offer, line, as_of):
            by_vintage.setdefault(offer.vintage, []).append(offer)

    fresh_from = as_of - timedelta(days=MAX_OFFER_AGE_DAYS)
    out = []
    for vintage, found in sorted(by_vintage.items()):
        best: dict[str, Offer] = {}
        for offer in found:
            current = best.get(offer.merchant_id)
            if current is None or offer.price < current.price:
                best[offer.merchant_id] = offer
        prices = sorted(o.price for o in best.values())
        newest = max(o.captured_at for o in best.values())
        out.append(NeighbourVintage(
            vintage=vintage,
            median=Decimal(str(median(prices))),
            merchants=len(best),
            newest_captured_at=newest,
            stale=newest < fresh_from,
        ))
    return out


def tier_widening(line_vintage: int, neighbours: list[NeighbourVintage],
                  tiers: Optional[dict[int, int]]) -> tuple[Decimal, Decimal, bool]:
    """(tier_up, tier_down, tiers_available).

    A great vintage beside an ordinary one widens the band so the check stays
    quiet. It never multiplies a price into an estimate.
    """
    if not tiers or line_vintage not in tiers:
        return Decimal(1), Decimal(1), False
    target = tiers[line_vintage]
    known = [tiers[n.vintage] for n in neighbours if n.vintage in tiers]
    if not known:
        return Decimal(1), Decimal(1), False

    up_steps = max((tier - target for tier in known), default=0)      # worse neighbours
    down_steps = max((target - tier for tier in known), default=0)    # better neighbours
    up = min(Decimal(1) + TIER_STEP * max(0, up_steps), TIER_CAP)
    down = min(Decimal(1) + TIER_STEP * max(0, down_steps), TIER_CAP)
    return up, down, True


def format_disagreements(comps: Iterable[Offer], other_formats: Iterable[Offer],
                         ) -> list[FormatDisagreement]:
    """The same merchant, the same wine and vintage, two formats that do not
    agree per bottle. Bordeaux Index priced a single 2020 Mugneret-Gibourg
    bottle at £197 while pricing its own six-pack at £345 a bottle."""
    others = list(other_formats)
    out = []
    for comp in comps:
        comp_per_bottle = comp.price / comp.pack_size
        for other in others:
            if (other.merchant_id != comp.merchant_id or other.wine_id != comp.wine_id
                    or other.vintage != comp.vintage or other.pack_size == comp.pack_size):
                continue
            other_per_bottle = other.price / other.pack_size
            difference = abs(other_per_bottle - comp_per_bottle) / comp_per_bottle
            if difference > FORMAT_INCOHERENCE:
                out.append(FormatDisagreement(
                    offer_id=comp.offer_id, merchant_id=comp.merchant_id,
                    merchant=comp.merchant,
                    comp_unit=unit_label(comp.pack_size, comp.bottle_ml),
                    comp_per_bottle=comp_per_bottle,
                    other_unit=unit_label(other.pack_size, other.bottle_ml),
                    other_per_bottle=other_per_bottle,
                    difference=difference))
    return out


def check_vintage_band(line: SellerLine, comps: Iterable[Offer], *,
                       neighbour_offers: Iterable[Offer],
                       other_format_offers: Iterable[Offer] = (),
                       as_of: datetime,
                       tiers: Optional[dict[int, int]] = None) -> VintageBandCheck:
    """Run the check on comps the benchmark already accepted."""
    comps = list(comps)
    unit = unit_label(line.pack_size, line.bottle_ml)
    incoherent = format_disagreements(comps, other_format_offers)

    neighbours = neighbour_vintages(line, neighbour_offers, as_of)
    if len(neighbours) < MIN_NEIGHBOUR_VINTAGES:
        return VintageBandCheck(
            wine_id=line.wine_id, vintage=line.vintage, unit=unit,
            band_low=None, band_high=None, neighbours=neighbours,
            format_incoherent=incoherent, tiers_available=bool(tiers),
            note=(f"not enough neighbouring vintages to check "
                  f"({len(neighbours)} of {MIN_NEIGHBOUR_VINTAGES} needed)"))

    medians = [n.median for n in neighbours]
    up, down, tiers_available = tier_widening(line.vintage, neighbours, tiers)
    band_low = min(medians) / down
    band_high = max(medians) * up

    high, low = [], []
    for comp in comps:
        high_edge = band_high * HIGH_MULTIPLE
        low_edge = band_low * LOW_MULTIPLE
        if comp.price > high_edge:
            high.append(OfferRef(comp.offer_id, comp.merchant_id, comp.merchant, comp.price,
                                 high_edge, comp.price / high_edge,
                                 COMP_EXCLUDED_VINTAGE_BAND))
        elif comp.price < low_edge:
            low.append(OfferRef(comp.offer_id, comp.merchant_id, comp.merchant, comp.price,
                                low_edge, comp.price / low_edge, LOW_COMP_OUT_OF_BAND))

    notes = []
    if all(n.stale for n in neighbours):
        notes.append(f"every neighbouring vintage is older than {MAX_OFFER_AGE_DAYS} days")
    if not tiers_available:
        notes.append("no vintage tiers recorded")

    return VintageBandCheck(
        wine_id=line.wine_id, vintage=line.vintage, unit=unit,
        band_low=band_low, band_high=band_high, neighbours=neighbours,
        high_outliers=high, low_outliers=low, format_incoherent=incoherent,
        tiers_available=tiers_available, note="; ".join(notes) or None)


def without_high_outliers(offers: Iterable[Offer], check: VintageBandCheck) -> list[Offer]:
    """The offer list to re-benchmark with. Only high outliers are removed, and
    only ever here: a low outlier is the operator's call (spec §5)."""
    excluded = {ref.offer_id for ref in check.high_outliers}
    return [o for o in offers if o.offer_id not in excluded]
