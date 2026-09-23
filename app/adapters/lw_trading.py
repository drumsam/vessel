"""Lay & Wheeler Trading — the WooCommerce Store API.

Route: GET https://laywheelertrading.com/wp-json/wc/store/v1/products
       ?search=<producer>&per_page=100&page=<n>
A deep-search source: it answers a producer term, so it is asked per producer
and vintage and never swept.

**A different estate from laywheeler.com**, which returns 403 to an honest
identifiable User-Agent and must not be touched. This host is the trading
business and answers normally.

**Terms and robots, read 23 September 2026.** `robots.txt` has a `User-agent: *`
group — the group our UA falls in — with `Crawl-delay: 10`, basket, account and
`/*?wc-ajax` paths disallowed, and `/*blackhole` traps that are never followed.
A second group names crawlers that are blocked outright (Scrapy, node-fetch,
FirecrawlAgent, and two dozen others); we are none of them and do not pretend
otherwise. The ten-second delay is honoured between every request.

Three things this adapter exists to get right:

1. **Prices are in minor units.** `prices.price` is `"141400"` with
   `currency_minor_unit: 2` — £1,414.00. Read as pounds it is a 100× error, and
   a single such row would become the Floor for every line it touched.

2. **Pagination is not optional.** Faiveley returns exactly 100 rows on page 1
   of 185 (`X-WP-TotalPages: 2`), and Drouhin the same. A single page looks like
   a complete answer, and the missing half is silent.

3. **Identity and format come from the attributes, never the SKU.** Two schemes
   are live: `LXSIB102760620190600750` (LWIN-7, vintage, pack, size) and
   `hub-VS10135589-6-IB-13287647`. A LWIN read out of a SKU is a proposal to the
   resolver and never resolves on its own (decision 0006); the SKU is never
   parsed for a price, a duty status or a size.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://laywheelertrading.com"
API_URL = BASE + "/wp-json/wc/store/v1/products"
ROBOTS_URL = BASE + "/robots.txt"

#: robots.txt says ten seconds, so ten seconds it is.
CRAWL_DELAY_SECONDS = 10
PER_PAGE = 100
MAX_PAGES = 40

_PACK = re.compile(r"^\s*(?P<pack>\d+)\s*x\s*(?P<size>[\d.]+)\s*(?P<unit>cl|ml|l)\s*$", re.I)
#: LXSIB + LWIN-7 + vintage + pack + size. A proposal only.
_SKU_LWIN = re.compile(r"^[A-Z]{5}(?P<lwin7>\d{7})\d{4}\d{2}\d{5}$")
_MIXED = re.compile(r"\bmixed\b|\bassort(?:ment|ed)?s?\b", re.I)

_DUTY = {"in bond": DutyStatus.IN_BOND, "duty paid": DutyStatus.DUTY_PAID}


def attributes(product: dict) -> dict[str, str]:
    """{attribute name: first term}. Read by name: position is not stable."""
    out = {}
    for attribute in product.get("attributes") or []:
        terms = [t.get("name") for t in attribute.get("terms") or [] if t.get("name")]
        if attribute.get("name") and terms:
            out[attribute["name"]] = terms[0]
    return out


def parse_pack(pack: str) -> Optional[tuple[int, int]]:
    """'6x75cl' -> (6, 750)."""
    match = _PACK.match(pack or "")
    if not match:
        return None
    factor = {"cl": 10, "ml": 1, "l": 1000}[match.group("unit").lower()]
    millilitres = int(round(float(match.group("size")) * factor))
    pack_size = int(match.group("pack"))
    return (pack_size, millilitres) if pack_size >= 1 and millilitres > 0 else None


def parse_price(prices: dict) -> Optional[Decimal]:
    """Minor units to pounds. "141400" with minor unit 2 is £1,414.00."""
    amount = (prices or {}).get("price")
    minor = (prices or {}).get("currency_minor_unit")
    if amount is None or minor is None:
        return None
    try:
        return Decimal(str(amount)).scaleb(-int(minor))
    except Exception:
        return None


def lwin_from_sku(sku: str) -> Optional[str]:
    """The LWIN a SKU claims, or None. A claim, never an identity: the resolver
    requires the name to agree (decision 0006)."""
    match = _SKU_LWIN.match((sku or "").strip().upper())
    return match.group("lwin7") if match else None


class LayWheelerTradingAdapter(Adapter):
    id = "lw-trading"
    merchant = "Lay & Wheeler Trading"

    def fetch(self, search: str | None = None, vintage: int | None = None, *,
              client=None, sleep=time.sleep) -> Sequence[dict]:
        """Every page for one producer term, filtered to one vintage.

        Pages until a page comes back short: a first page of exactly `per_page`
        rows is the shape that hides the rest.
        """
        if not search:
            raise ValueError("a producer search term is required")
        owns_client = client is None
        if owns_client:  # pragma: no cover - network
            import httpx
            client = httpx.Client(timeout=90, follow_redirects=True,
                                  headers={"User-Agent": user_agent()})
        try:
            rows: list[dict] = []
            for page in range(1, MAX_PAGES + 1):
                if page > 1:
                    sleep(CRAWL_DELAY_SECONDS)
                r = client.get(API_URL, params={"search": search, "per_page": PER_PAGE,
                                                "page": page})
                r.raise_for_status()
                products = r.json()
                rows += products
                if len(products) < PER_PAGE:
                    break
            if vintage is None:
                return rows
            return [p for p in rows if attributes(p).get("Vintage") == str(vintage)]
        finally:
            if owns_client:  # pragma: no cover - network
                client.close()

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        name = raw.get("name") or ""
        if _MIXED.search(name):
            return Rejected(raw, Reject.MIXED_LOT, name)

        attrs = attributes(raw)
        prices = raw.get("prices") or {}
        if prices.get("currency_code") != "GBP":
            return Rejected(raw, Reject.CURRENCY, f"priced in {prices.get('currency_code')!r}")

        price = parse_price(prices)
        if price is None or price <= 0:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"price {prices.get('price')!r}")

        stated_vintage = attrs.get("Vintage", "")
        vintage = (1000 if stated_vintage.upper() in ("NV", "N.V.")
                   else int(stated_vintage) if stated_vintage.isdigit() else None)
        if vintage is None:
            return Rejected(raw, Reject.VINTAGE, f"vintage attribute {stated_vintage!r}")

        size = parse_pack(attrs.get("Pack Size", ""))
        if size is None:
            return Rejected(raw, Reject.SIZE, f"pack size {attrs.get('Pack Size')!r}")
        pack_size, bottle_ml = size

        duty = _DUTY.get(attrs.get("Duty Status", "").strip().lower())
        if duty is None:
            # The duty status comes from the Duty Status attribute and nowhere
            # else — not from the SKU, which carries an "IB" of its own.
            return Rejected(raw, Reject.DUTY, f"duty status {attrs.get('Duty Status')!r}")

        availability = attrs.get("Availability", "")
        offer = Offer(
            offer_id=f"lw-trading:{raw.get('id')}",
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
            is_buyable=bool(raw.get("is_in_stock")) and bool(raw.get("is_purchasable")),
            offered_units=raw.get("low_stock_remaining"),
            stock_type=StockType.MERCHANT_STOCK,
            stock_type_basis="inferred",
            is_mixed_lot=False,
            condition_flags=frozenset(),
            condition_notes=None,
            source_url=raw.get("permalink"),
            captured_at=captured_at or datetime.now(timezone.utc),
            raw={"id": raw.get("id"), "sku": raw.get("sku"), "name": name,
                 # Future Arrival is still a buyable ask; the operator is told
                 # which it is rather than the line being quietly dropped.
                 "availability": availability, "attributes": attrs},
        )
        return Candidate(offer=offer, producer_text=attrs.get("Producer", ""),
                         cuvee_text=name, lwin7=lwin_from_sku(raw.get("sku", "")))
