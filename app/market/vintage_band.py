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
3. No price is ever adjusted for vintage quality. A tier decides only WHICH
   vintages may be compared; it never scales a number. Neighbours are chosen by
   quality (same tier, widened once to ±1 if too few), because an ordinary
   vintage prices near another ordinary vintage even five years away and a
   great vintage never prices like an ordinary one. No tier for the region
   means no band and no flag.
4. The only thing in app/core/ this touches is the flag vocabulary: the two
   band flags are review flags (decision 0015) and are inherited back into the
   benchmark, so a line the band acted on always reaches a person. No screen,
   no arithmetic and no state rule in the core changes.

The asymmetry in section 5 of the spec is the important part. A high outlier is
excluded automatically, because dropping a dear comp moves the Reference down:
we pay less and we sell lower, and the line goes to a human anyway. A low
outlier is never excluded automatically, because dropping a cheap comp pushes
the Reference up, which makes us overpay and lets us overprice a client. Often
the cheap comp is the true signal — a merchant clearing stock is a real price.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable, Optional

from app.core.enums import DutyStatus, PriceKind
from app.core.flags import (
    FORMAT_INCOHERENCE, HIGH_MULTIPLE, LOW_MULTIPLE, MAX_OFFER_AGE_DAYS, Flag)
from app.core.models import GBP, Offer, SellerLine

#: Quality, not proximity, decides who is a neighbour (spec §4). Years only
#: break ties: a candidate must be within this many of V, because price drift
#: beyond it is real whatever the tiers say.
NEIGHBOUR_YEARS = 8
MIN_NEIGHBOUR_VINTAGES = 2
MAX_NEIGHBOUR_VINTAGES = 6

#: Same tier first. Widen ONCE to tier ±1 if fewer than two vintages qualify,
#: and never further: a tier-1 vintage is never compared with tier 3 or worse.
TIER_WIDEN_STEP = 1

#: Comps must be fresh (14 days, decision 0003). A band is allowed to lean on
#: older evidence — it prices nothing — but anything past the comp window is
#: labelled so the operator knows what they are looking at.
NEIGHBOUR_MAX_AGE_DAYS = 90

#: What the check can say about a comp. The first two are review flags in
#: app/core/flags.py (decision 0015) and are inherited back into the benchmark,
#: so a line the band acted on always reaches a person.
COMP_EXCLUDED_VINTAGE_BAND = Flag.COMP_EXCLUDED_VINTAGE_BAND.value
LOW_COMP_OUT_OF_BAND = Flag.LOW_COMP_OUT_OF_BAND.value
MERCHANT_FORMAT_INCOHERENT = "MERCHANT_FORMAT_INCOHERENT"


@dataclass(frozen=True)
class NeighbourVintage:
    vintage: int
    median: Decimal                  # median of that vintage's merchant-bests
    merchants: int
    newest_captured_at: Optional[datetime]
    stale: bool                      # nothing fresher than the comp window
    tier: Optional[int] = None       # 1 = great, 5 = weak, from vintage_tier


@dataclass(frozen=True)
class OfferRef:
    """A comp the band has something to say about."""
    offer_id: str
    merchant_id: str
    merchant: str
    price: Decimal
    edge: Decimal                    # the band edge it failed
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


def _vintage_medians(line: SellerLine, offers: Iterable[Offer], as_of: datetime,
                     ) -> dict[int, NeighbourVintage]:
    """Every candidate vintage of this wine and unit, priced the way the
    benchmark prices: merchant-best first, then the median across merchants."""
    by_vintage: dict[int, list[Offer]] = {}
    for offer in offers:
        if (offer.vintage != line.vintage and abs(offer.vintage - line.vintage) <= NEIGHBOUR_YEARS
                and _usable(offer, line, as_of)):
            by_vintage.setdefault(offer.vintage, []).append(offer)

    fresh_from = as_of - timedelta(days=MAX_OFFER_AGE_DAYS)
    out = {}
    for vintage, found in sorted(by_vintage.items()):
        best: dict[str, Offer] = {}
        for offer in found:
            current = best.get(offer.merchant_id)
            if current is None or offer.price < current.price:
                best[offer.merchant_id] = offer
        prices = sorted(o.price for o in best.values())
        newest = max(o.captured_at for o in best.values())
        out[vintage] = NeighbourVintage(
            vintage=vintage,
            median=Decimal(str(median(prices))),
            merchants=len(best),
            newest_captured_at=newest,
            stale=newest < fresh_from,
        )
    return out


def neighbour_vintages(line: SellerLine, offers: Iterable[Offer], as_of: datetime,
                       tiers: Optional[dict[int, int]] = None,
                       ) -> tuple[list[NeighbourVintage], Optional[str], Optional[str]]:
    """The vintages this one may be compared with, and why not when there are
    none. Quality decides membership; years only break ties (spec §4).

    Returns (neighbours, unrated_reason, widened_note). `unrated_reason` is set
    only when the register cannot answer at all — no tier for this wine's
    region, for its vintage, or for any candidate. That is no band and no flag:
    silence, never a guess.

    Doug's rule, and it is the right one: an ordinary vintage prices near
    another ordinary vintage even five years away, and a great vintage never
    prices like an ordinary one. Proximity in years is a poor proxy for
    comparability — 2004 red Burgundy (tier 5) sits one year from 2005 (tier 1),
    and pricing one off the other is how a real outlier gets through.
    """
    candidates = _vintage_medians(line, offers, as_of)
    if not tiers:
        return [], "no vintage quality data for this wine's region", None
    target = tiers.get(line.vintage)
    if target is None:
        return [], f"no vintage quality data for {line.vintage}", None

    rated = {v: n for v, n in candidates.items() if v in tiers}
    if candidates and not rated:
        return [], "no vintage quality data for any comparable vintage of this wine", None

    def within(step: int) -> list[NeighbourVintage]:
        return [n for v, n in rated.items() if abs(tiers[v] - target) <= step]

    chosen = within(0)
    widened = False
    if len(chosen) < MIN_NEIGHBOUR_VINTAGES:
        # One step, once. A tier-1 vintage is never compared with tier 3.
        wider = within(TIER_WIDEN_STEP)
        if len(wider) > len(chosen):
            chosen, widened = wider, True

    # Years break ties: when more than six qualify, keep the six nearest.
    if len(chosen) > MAX_NEIGHBOUR_VINTAGES:
        chosen = sorted(chosen, key=lambda n: (abs(n.vintage - line.vintage), n.vintage))
        chosen = chosen[:MAX_NEIGHBOUR_VINTAGES]

    chosen = [replace(n, tier=tiers[n.vintage]) for n in sorted(chosen, key=lambda n: n.vintage)]
    widened_note = (f"tier {target} vintages were too few, so tier "
                    f"{target}±{TIER_WIDEN_STEP} was used" if widened else None)
    return chosen, None, widened_note


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

    neighbours, unrated, widened = neighbour_vintages(line, neighbour_offers, as_of, tiers)
    if len(neighbours) < MIN_NEIGHBOUR_VINTAGES:
        # Two different silences, and the operator is owed the right one: the
        # register could not answer, or it answered and there was too little
        # comparable evidence behind it.
        return VintageBandCheck(
            wine_id=line.wine_id, vintage=line.vintage, unit=unit,
            band_low=None, band_high=None, neighbours=neighbours,
            format_incoherent=incoherent, tiers_available=bool(tiers),
            note=(unrated or f"not enough neighbouring vintages to check "
                             f"({len(neighbours)} of {MIN_NEIGHBOUR_VINTAGES} needed)"))

    # The neighbours are already quality-matched, so the band is used as it
    # stands. No widening, no adjustment: a tier never scales a price (spec §4).
    medians = [n.median for n in neighbours]
    band_low = min(medians)
    band_high = max(medians)

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
    if widened:
        notes.append(widened)
    if all(n.stale for n in neighbours):
        notes.append(f"every neighbouring vintage is older than {MAX_OFFER_AGE_DAYS} days")

    return VintageBandCheck(
        wine_id=line.wine_id, vintage=line.vintage, unit=unit,
        band_low=band_low, band_high=band_high, neighbours=neighbours,
        high_outliers=high, low_outliers=low, format_incoherent=incoherent,
        tiers_available=True, note="; ".join(notes) or None)


def without_high_outliers(offers: Iterable[Offer], check: VintageBandCheck) -> list[Offer]:
    """The offer list to re-benchmark with. Only high outliers are removed, and
    only ever here: a low outlier is the operator's call (spec §5)."""
    excluded = {ref.offer_id for ref in check.high_outliers}
    return [o for o in offers if o.offer_id not in excluded]


def band_flags(check: VintageBandCheck) -> frozenset[Flag]:
    """The review flags a run must carry because of this check.

    They go back into `benchmark()` through `SellerLine.inherited_flags`, which
    is the mechanism decision 0005 built for exactly this: only review flags may
    be inherited, so this can hold a line in review and can never release one.
    """
    flags = set()
    if check.high_outliers:
        flags.add(Flag.COMP_EXCLUDED_VINTAGE_BAND)
    if check.low_outliers:
        flags.add(Flag.LOW_COMP_OUT_OF_BAND)
    return frozenset(flags)
