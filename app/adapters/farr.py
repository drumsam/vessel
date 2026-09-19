"""Farr Vintners — official JSON feed.

Endpoint: https://www.farrvintners.com/winelist_json.php  (also CSV/TXT/XLSX at /downloads)
Shape:    {"data": [ {...}, ... ]}

Verified live 2026-09-19.

Two things this adapter exists to get right:

1. **Burgundy is named cuvee-first.** `Wine` reads "Chambertin, Domaine Armand
   Rousseau" and "Musigny VV, Domaine Comte Georges de Vogüé", while Bordeaux is
   chateau-first. Splitting on the LAST comma gives producer; everything before
   it is the cuvee. A producer-first assumption silently drops all of Burgundy.

2. **Never parse the HTML offer page.** It renders two separate parcels into one
   cell as "£2,000.00 / £1,800.00" — a 6x75cl case at £12,000 and a single
   bottle at £1,800, not a price range or a quantity break. The feed keeps them
   as distinct records. Use the feed.

Also: Burgundy grand cru carries LWIN-7 = null here while Bordeaux carries it.
That is expected, not an error — identity falls through to wine_key.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .condition import normalise_condition

FEED_URL = "https://www.farrvintners.com/winelist_json.php"

# Farr writes the multiplication sign as U+00D7, not the letter x.
_SIZE = re.compile(r"^\s*(\d+)\s*[×x]\s*([\d.]+)\s*(cl|l|ml)\s*$", re.I)

_MIXED = re.compile(r"\bmixed\s+(case|lot)\b|\bcontains\b|\bassortment\b|\bselection\s+case\b", re.I)


def parse_size(size: str) -> tuple[int, int] | None:
    """'12×75cl' -> (12, 750).  '1×1.5L' -> (1, 1500).  Returns None if unreadable."""
    m = _SIZE.match(size or "")
    if not m:
        return None
    pack = int(m.group(1))
    value, unit = float(m.group(2)), m.group(3).lower()
    ml = {"cl": value * 10, "l": value * 1000, "ml": value}[unit]
    if pack < 1 or ml <= 0:
        return None
    return pack, int(round(ml))


def split_wine_field(wine: str) -> tuple[str, str]:
    """'Chambertin, Domaine Armand Rousseau' -> ('Domaine Armand Rousseau', 'Chambertin')

    Split on the LAST comma: cuvee names contain commas far less often than
    producer names contain them not at all in this feed.
    """
    if "," not in wine:
        return wine.strip(), ""
    head, _, tail = wine.rpartition(",")
    return tail.strip(), head.strip()


class FarrAdapter(Adapter):
    id = "farr"
    merchant = "Farr Vintners"

    def fetch(self) -> Sequence[dict]:  # pragma: no cover - network
        import httpx
        r = httpx.get(FEED_URL, timeout=60, headers={"User-Agent": self._ua()})
        r.raise_for_status()
        return r.json()["data"]

    @staticmethod
    def _ua() -> str:
        return "UKFineWinePricer/1.0 (+https://example.invalid/contact)"

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        wine = (raw.get("Wine") or "").strip()
        variation = raw.get("Variation") or None

        if _MIXED.search(wine) or _MIXED.search(variation or ""):
            return Rejected(raw, Reject.MIXED_LOT, wine)

        size = parse_size(raw.get("Size") or "")
        if size is None:
            return Rejected(raw, Reject.SIZE, f"unparseable Size {raw.get('Size')!r}")
        pack, ml = size

        try:
            vintage = int(str(raw.get("Vintage")).strip())
        except (TypeError, ValueError):
            return Rejected(raw, Reject.VINTAGE, f"non-integer Vintage {raw.get('Vintage')!r}")

        price_raw = raw.get("SellGBP")
        if price_raw is None:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, "SellGBP missing")
        price = Decimal(str(price_raw))

        # `Per` is the number of bottles the SellGBP figure covers. It must agree
        # with the pack size parsed from `Size`, or we do not understand the row.
        per = raw.get("Per")
        if per is not None and int(per) != pack:
            return Rejected(raw, Reject.UNIT, f"Per={per} disagrees with Size={raw.get('Size')!r}")

        units = raw.get("Units")
        offered = int(units) if units is not None else None

        producer_text, cuvee_text = split_wine_field(wine)

        offer = Offer(
            offer_id=f"farr:{raw.get('WineId')}",
            merchant_id=self.id,
            merchant=self.merchant,
            wine_id="",                       # identity resolution fills this
            vintage=vintage,
            bottle_ml=ml,
            pack_size=pack,
            price=price,
            currency="GBP",
            duty_status=DutyStatus.IN_BOND,   # Farr's list is In Bond throughout
            price_kind=PriceKind.ASK,
            is_buyable=bool(offered and offered > 0),
            offered_units=offered,
            stock_type=StockType.MERCHANT_STOCK,
            stock_type_basis="inferred",      # own offer book, no per-line flag
            is_mixed_lot=False,
            condition_flags=normalise_condition(variation),
            condition_notes=variation,
            source_url=raw.get("Url"),
            captured_at=captured_at or datetime.now(timezone.utc),
            raw=raw,
        )
        return Candidate(offer=offer, producer_text=producer_text, cuvee_text=cuvee_text)
