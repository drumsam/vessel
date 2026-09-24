"""Which lines may derive a comparable across case sizes, and what the operator is told.

Decision 0016. The pricing core does not know what Burgundy is and never will
(invariant 1), so it is told: `SellerLine.derive_units` is set here, from the
wine's region, before the benchmark runs.

The case premium is **measured**: 27 paired same-day observations put the median
at 1.0000, so a case is priced at the same rate per bottle as a loose bottle
(docs/research/case-premium-measurement.md). What a measurement cannot fix is
the spread — a quarter of those pairs sit more than 5% from parity, with tails
at -30% and +15% — so every place a derived figure is shown says what it is and
how far out it could be. A number that looks observed and is not is exactly the
failure this system exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable, Optional

from app.core.benchmark import DerivedComp
from app.core.enums import PriceKind
from app.core.flags import CASE_PREMIUM
from app.core.models import GBP, Offer

#: Regions where a comparable may be derived across case sizes. Burgundy only,
#: by Doug's decision of 24 September 2026, and on the evidence of the control
#: set: refusing to compare 3x75 with 6x75 was costing us most of what we had.
#: Adding a region means measuring its basis first and recording a decision.
DERIVABLE_REGIONS = frozenset({"BURGUNDY_RED", "BURGUNDY_WHITE"})

#: The measurement behind CASE_PREMIUM, for the operator and the record.
#: Bordeaux Index, In Bond, 750ml, 24 September 2026.
PREMIUM_EVIDENCE = {"median": Decimal("1.0000"), "mean": Decimal("0.9737"), "pairs": 27,
                    "low": Decimal("0.7038"), "high": Decimal("1.1525"),
                    "merchant": "Bordeaux Index", "measured_on": "2026-09-24"}

#: What the operator reads beside any derived figure. Never abbreviated away,
#: and written from the constant so it cannot drift away from what the code does.
PREMIUM_CAVEAT = (
    ("Cases and loose bottles are priced at the same rate per bottle"
     if CASE_PREMIUM == 1 else
     f"Case premium of {(CASE_PREMIUM - 1) * 100:.0f}% applied")
    + f" — measured median {PREMIUM_EVIDENCE['median']} across "
      f"{PREMIUM_EVIDENCE['pairs']} paired observations at "
      f"{PREMIUM_EVIDENCE['merchant']}. A quarter of those sat more than 5% out "
      f"({PREMIUM_EVIDENCE['low']} to {PREMIUM_EVIDENCE['high']}), so this is not "
      "a fact about this wine.")


def derivation_allowed(register_key: Optional[str]) -> bool:
    """True when this wine's region permits derivation. Unknown region, or a
    wine with no region recorded, means no: the exact-unit rule of 0001."""
    return bool(register_key) and register_key in DERIVABLE_REGIONS


def derivation_note(derived: DerivedComp) -> str:
    """The sentence shown on a line priced from a derived comp.

    The source offer, its real unit and its real price are named, so the
    operator can always see what was actually offered.
    """
    source = derived.source
    unit = f"{source.pack_size}x{source.bottle_ml // 10}cl"
    sentence = (f"Derived from a {unit} at {source.price} from {source.merchant}: "
                f"{derived.offer.price} at "
                f"{derived.offer.pack_size}x{derived.offer.bottle_ml // 10}cl.")
    return f"{sentence} {PREMIUM_CAVEAT}" if derived.premium_applied else (
        f"{sentence} No premium applied: case to case.")


# --------------------------------------------------- measuring the premium itself
#
# "Every adapter that meets a wine in two units on the same day should record
# the pair. After a few hundred observations across five or six merchants the
# constant stops being a judgement call."
#   — docs/research/case-premium-measurement.md
#
# That is what the rest of this module is for. It is pure: no clock, no network,
# no database. The collection step hands it the offers it just normalised.

#: A pair is only evidence if both sides are the same thing bought two ways, so
#: both must be a live GBP ask for the same wine, vintage, bottle size AND duty
#: status. A Duty Paid bottle against an In Bond case measures the duty, not the
#: case.
@dataclass(frozen=True)
class CasePair:
    """The same wine in two pack sizes, seen by one merchant in one fetch.

    `ratio` is the larger pack's price per bottle over the smaller's. Above 1
    means the bigger unit costs more per bottle; below 1 means it costs less.
    It is a ratio, not money.
    """
    wine_id: str
    vintage: int
    bottle_ml: int
    duty_status: str
    smaller_pack: int
    smaller_price: Decimal
    smaller_offer_id: str
    larger_pack: int
    larger_price: Decimal
    larger_offer_id: str
    ratio: Decimal

    @property
    def is_loose_pair(self) -> bool:
        """True when the baseline is a single bottle — the pair the CASE_PREMIUM
        constant is actually about. A 3-pack against a 6-pack measures something
        else (and is why case-to-case derivation applies no premium at all)."""
        return self.smaller_pack == 1


RATIO = Decimal("0.000001")


def _usable_for_pairing(offer: Offer) -> bool:
    return bool(
        offer.wine_id
        and not offer.is_mixed_lot
        and offer.price_kind is PriceKind.ASK        # an indication is not a price
        and offer.currency == GBP
        and offer.is_buyable is True
        and offer.price is not None
        and offer.price > Decimal("0")
        and offer.price == offer.price.quantize(Decimal("0.01"))
        and offer.pack_size >= 1
        and offer.bottle_ml > 0
    )


def case_pairs(offers: Iterable[Offer]) -> list[CasePair]:
    """Every same-wine, same-vintage, same-size, same-duty pair of pack sizes.

    The best (lowest) price wins for each pack size, as in the measurement
    method — a merchant listing one wine three times is one observation, not
    three. Each pack size is paired against the SMALLEST one present, so three
    pack sizes give two pairs rather than three: one baseline, no double
    counting, and where a loose bottle exists the baseline is the loose bottle,
    which is the ratio the constant is about.
    """
    best: dict[tuple, Offer] = {}
    for offer in offers:
        if not _usable_for_pairing(offer):
            continue
        key = (offer.wine_id, offer.vintage, offer.bottle_ml,
               offer.duty_status.value, offer.pack_size)
        current = best.get(key)
        if current is None or offer.price < current.price:
            best[key] = offer

    by_wine: dict[tuple, list[Offer]] = {}
    for (wine_id, vintage, bottle_ml, duty, _), offer in best.items():
        by_wine.setdefault((wine_id, vintage, bottle_ml, duty), []).append(offer)

    out = []
    for (wine_id, vintage, bottle_ml, duty), found in sorted(by_wine.items()):
        if len(found) < 2:
            continue
        found.sort(key=lambda o: o.pack_size)
        baseline = found[0]
        base_per_bottle = baseline.price / baseline.pack_size
        for other in found[1:]:
            ratio = ((other.price / other.pack_size) / base_per_bottle)
            out.append(CasePair(
                wine_id=wine_id, vintage=vintage, bottle_ml=bottle_ml, duty_status=duty,
                smaller_pack=baseline.pack_size, smaller_price=baseline.price,
                smaller_offer_id=baseline.offer_id,
                larger_pack=other.pack_size, larger_price=other.price,
                larger_offer_id=other.offer_id,
                ratio=ratio.quantize(RATIO, rounding=ROUND_HALF_EVEN)))
    return out
