"""Lea & Sandeman — the live In Bond list, one request.

Route: GET https://www.leaandsandeman.co.uk/fine-wine.html?resultsPerPage=192
Server-rendered HTML table, 174 rows on 23 September 2026. The site's own
"show 192" control appends `page=`, and `/*page=*` is disallowed, so this
adapter never paginates: the whole list comes back in the one request.

**Terms and robots, read 23 September 2026.** `/content/terms.html` is
conditions of sale only — delivery, payment, storage, cancellation — with no
website-use or anti-automation clause. `robots.txt` has a single `User-agent: *`
group, which is the group our UA falls in; it disallows account and basket
paths, `/*page=*`, `/*term=*`, `/*producer=*`, `/*categoryFilter=*` and
`/search.html?*`, and does not mention `resultsPerPage`. No `Crawl-delay`.
robots.txt is not a licence, but nothing in the terms restricts reading the
list. (The earlier collector brief listed L&S as anti-automation; the terms and
robots read here do not support that, and it is recorded so the next person can
re-check rather than re-guess.)

**Product pages are never collected.** They quote duty-paid retail per bottle —
£68.95 a bottle against £675.00 for 6×75cl In Bond on the list for the same
wine. `normalise()` refuses anything that is not a list row.

Four things this adapter exists to get right:

1. **Thirteen cells, twelve headers.** The stock code sits in an unlabelled
   cell at index 4, so every header after "Wine" is one place to the left of its
   value. Mapping by header name reads `inc VAT` as the price: 2021 Henri
   Germain Morgeot 6×75 IB is £435.00 ex VAT and £542.74 inc VAT, a 24.8%
   overstatement. Cells are read by position.

2. **Duty status is per row, not per wine.** 2020 Volnay 1er Roncerets 6×75
   appears twice under one stock code (41846): DP at £502.91 and IB at £485.00.
   Only the IB row may become an In Bond offer, and the DP row is not a cheaper
   version of it.

3. **A Jeroboam is not one size.** L&S writes `N x Jero` for both: 3000ml in
   Burgundy and Champagne, 4500ml in Bordeaux. With no region there is no
   answer, and the row is rejected rather than assumed. `N x Neb` is rejected
   outright until a live row confirms the size.

4. **Rows repeat.** 2021 Germain Morgeot appears twice, identical. Identical
   rows are one listing; the Roncerets pair above is not, because the duty
   status differs.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://www.leaandsandeman.co.uk"
#: One request, the whole list. Never add `page=`: `/*page=*` is disallowed.
LIST_URL = BASE + "/fine-wine.html?resultsPerPage=192"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")

#: The cells, by position. The names are ours; the table's own headers are one
#: short and must not be used to find them.
REGION, COLOUR, VINTAGE, WINE, STOCK_CODE, PACK, QTY, PRICE, INC_VAT, DUTY, RATING = range(11)
BUY = 12
CELLS_PER_ROW = 13

#: "6 x 75cl" | "1 x Mags" | "3 x DM" | "1 x Jero" | "1 x Neb"
_PACK = re.compile(r"^\s*(?P<pack>\d+)\s*x\s*(?P<size>[\d.]+\s*cl|[\d.]+\s*ml|Mags?|DM|Jero|Neb)\s*$",
                   re.I)

#: Jeroboam is 3000ml in Burgundy and Champagne, 4500ml in Bordeaux.
JEROBOAM_ML = {"burgundy": 3000, "champagne": 3000, "bordeaux": 4500}

_MIXED = re.compile(r"\bmixed\b|\bassort(?:ment|ed)?s?\b", re.I)
_DUTY = {"IB": DutyStatus.IN_BOND, "DP": DutyStatus.DUTY_PAID}


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub(" ", html)).replace("&nbsp;", " ").strip()


def parse_rows(html: str) -> list[dict]:
    """Every list row, as cells. A page with no 13-cell rows yields nothing,
    which is what a product page is."""
    rows = []
    for row_html in _ROW.findall(html or ""):
        cells = [_text(c) for c in _CELL.findall(row_html)]
        if len(cells) == CELLS_PER_ROW:
            rows.append({"cells": cells, "source_url": LIST_URL})
    return rows


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """Identical rows are one listing. Two rows that differ in duty status, or
    price, or pack are not: 2020 Roncerets is one stock code with an IB row and
    a DP row, and losing either would lose a real offer."""
    seen: dict[tuple, dict] = {}
    for row in rows:
        cells = row["cells"]
        key = (cells[STOCK_CODE], cells[DUTY], cells[PACK], cells[PRICE], cells[VINTAGE])
        seen.setdefault(key, row)
    return list(seen.values())


def parse_pack(pack: str, region: str) -> Optional[tuple[int, int]]:
    """'6 x 75cl' -> (6, 750). Returns None when the size cannot be established
    without assuming something."""
    match = _PACK.match(pack or "")
    if not match:
        return None
    size = match.group("size").strip().lower()
    if size.endswith("cl"):
        millilitres = int(round(float(size[:-2].strip()) * 10))
    elif size.endswith("ml"):
        millilitres = int(round(float(size[:-2].strip())))
    elif size.startswith("mag"):
        millilitres = 1500
    elif size == "dm":
        millilitres = 3000                      # double magnum
    elif size == "jero":
        millilitres = JEROBOAM_ML.get((region or "").strip().lower())
        if millilitres is None:
            return None                         # Burgundy 3000 or Bordeaux 4500: no guess
    else:
        return None                             # Neb and anything else: unconfirmed
    return int(match.group("pack")), millilitres


def parse_vintage(text: str) -> Optional[int]:
    stated = (text or "").strip()
    if stated.upper() in ("NV", "N.V."):
        return 1000
    return int(stated) if stated.isdigit() and len(stated) == 4 else None


def parse_money(text: str) -> Optional[Decimal]:
    cleaned = (text or "").replace(",", "").replace("£", "").strip()
    try:
        value = Decimal(cleaned)
    except Exception:
        return None
    return value if value > 0 else None


class LeaSandemanAdapter(Adapter):
    id = "lea-sandeman"
    merchant = "Lea & Sandeman"

    def fetch(self) -> Sequence[dict]:  # pragma: no cover - network
        import httpx
        r = httpx.get(LIST_URL, timeout=90, follow_redirects=True,
                      headers={"User-Agent": user_agent()})
        r.raise_for_status()
        return dedupe_rows(parse_rows(r.text))

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        cells = raw.get("cells") or []
        if len(cells) != CELLS_PER_ROW:
            # Not a list row. A product page is the dangerous case: it quotes
            # duty-paid retail per bottle, which is not this merchant's In Bond
            # trade price for the same wine.
            return Rejected(raw, Reject.ROW_UNREADABLE,
                            f"not a list row ({len(cells)} cells)")

        title = cells[WINE]
        if _MIXED.search(title):
            return Rejected(raw, Reject.MIXED_LOT, title)

        vintage = parse_vintage(cells[VINTAGE])
        if vintage is None:
            return Rejected(raw, Reject.VINTAGE, f"unreadable vintage {cells[VINTAGE]!r}")

        size = parse_pack(cells[PACK], cells[REGION])
        if size is None:
            return Rejected(raw, Reject.SIZE,
                            f"unreadable pack {cells[PACK]!r} in region {cells[REGION]!r}")
        pack_size, bottle_ml = size

        price = parse_money(cells[PRICE])            # ex VAT, by position, never by header
        if price is None:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"price {cells[PRICE]!r}")

        duty = _DUTY.get(cells[DUTY].strip().upper())
        if duty is None:
            return Rejected(raw, Reject.DUTY, f"duty status {cells[DUTY]!r}")

        units = cells[QTY].strip()

        offer = Offer(
            offer_id=f"lea-sandeman:{cells[STOCK_CODE]}:{cells[DUTY].strip().upper()}",
            merchant_id=self.id,
            merchant=self.merchant,
            wine_id="",
            vintage=vintage,
            bottle_ml=bottle_ml,
            pack_size=pack_size,
            price=price,
            currency="GBP",
            duty_status=duty,
            price_kind=PriceKind.ASK,
            is_buyable="ADD" in cells[BUY].upper(),
            offered_units=int(units) if units.isdigit() else None,
            stock_type=StockType.MERCHANT_STOCK,
            stock_type_basis="inferred",         # own offer book, no per-row marker
            is_mixed_lot=False,
            # The list carries no condition wording at all: no OWC, no ullage,
            # nothing. An empty set is the honest answer, not an absent one.
            condition_flags=frozenset(),
            condition_notes=None,
            source_url=raw.get("source_url", LIST_URL),
            captured_at=captured_at or datetime.now(timezone.utc),
            raw={"cells": cells, "region": cells[REGION], "colour": cells[COLOUR],
                 "stock_code": cells[STOCK_CODE], "inc_vat": cells[INC_VAT],
                 "rating": cells[RATING]},
        )
        # The whole title is the merchant's wording: appellation, climat and
        # producer in one uppercase string. Splitting it is the resolver's job.
        return Candidate(offer=offer, producer_text="", cuvee_text=title)
