"""Two merchants, one price, possibly one parcel.

Control set L68 (21 September 2026): Goedhuis lists a brokered offer (SKU
`-BR-`) at £1,300.00 and Lea & Sandeman lists the same wine and unit at
£1,300.00 — to the penny. Two listings. Possibly one parcel, seen twice.

**This is not a mark against brokers.** Much of the trade brokes now, a brokered
offer is a real offer, and it is often the only visible price on a thin wine.
Brokered comps stay in the benchmark, and depth still counts them (decision
0014). The point is narrower: identical prices may be one parcel seen twice, so
"two merchants" may overstate how many places the wine can actually be bought.

So this is **an operator note and nothing else**. It never gates, never excludes
a comp, never changes depth, never moves the Floor, the Reference or the Median,
and never reaches a client document. It tells a person what to look at.

A near-identical price is not interesting and is not reported: £1,300.00 against
£1,299.00 is two merchants pricing keenly. Only equality to the penny is the
shape that suggests one parcel.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.core.enums import StockType
from app.core.models import Offer

#: Informational. Deliberately NOT in app/core/flags.REVIEW_FLAGS: a coincidence
#: of price is a reason to look, not a reason to stop.
SAME_PRICE_AS_ANOTHER_MERCHANT = "SAME_PRICE_AS_ANOTHER_MERCHANT"


@dataclass(frozen=True)
class PriceCoincidence:
    """One price that two or more merchants quote exactly."""
    price: Decimal
    merchants: list[str]             # display names, sorted, as the merchants write them
    merchant_ids: list[str]
    offer_ids: list[str]
    any_brokered: bool               # at least one side is declared broking
    flag: str = SAME_PRICE_AS_ANOTHER_MERCHANT

    @property
    def note(self) -> str:
        return (f"same price as another merchant ({', '.join(self.merchants)} "
                f"at {self.price}) — may be the same parcel")


def price_coincidences(merchant_bests: Iterable[Offer]) -> list[PriceCoincidence]:
    """Operator notes for a line, from the benchmark's own merchant-bests.

    Takes merchant-bests rather than every comparable, so one merchant listing
    the same wine twice at one price is not reported against itself: that is a
    duplicate listing, which the benchmark already collapses.
    """
    by_price: dict[Decimal, list[Offer]] = {}
    for offer in merchant_bests:
        by_price.setdefault(offer.price, []).append(offer)

    out = []
    for price, offers in sorted(by_price.items()):
        if len({o.merchant_id for o in offers}) < 2:
            continue
        offers = sorted(offers, key=lambda o: (o.merchant, o.offer_id))
        out.append(PriceCoincidence(
            price=price,
            merchants=[o.merchant for o in offers],
            merchant_ids=[o.merchant_id for o in offers],
            offer_ids=[o.offer_id for o in offers],
            any_brokered=any(o.stock_type is StockType.BROKERED for o in offers),
        ))
    return out
