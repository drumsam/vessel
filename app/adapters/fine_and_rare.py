"""FINE+RARE — a brokerage, not a stockholder.

Endpoint: https://www.frw.co.uk/product/<id>/<slug>, server-rendered Next.js.
The page carries everything in `__NEXT_DATA__`, so plain httpx is enough and no
browser is needed. Verified live 2026-09-22.

Deep-search key index: /sitemap-producers.xml (19,655 producers). Product URLs
come from /sitemap-products-N.xml and are shaped
`/product/<id>/<vintage>-<wine>-<producer-slug>`, so a producer and vintage can
be selected exactly rather than searched for.

**What this merchant publishes is not stock.** `productMarketInfo.unitPrice` is
an aggregated pan-European broking indication: where FINE+RARE believes the wine
would broker, gathered across merchants. Nobody has said they hold it at that
price, which is why every variant reads `quantity: 0`. It is normalised as
PriceKind.INDICATION and DutyStatus.UNKNOWN, so the pricing core excludes it
from Floor, Reference and Median twice over, and surfaces it as corroboration.
See docs/decisions/0013-brokerage-indications.md.

Three things this adapter exists to get right:

1. **An indication is never an ASK.** Publishing it as one would put a price
   nobody offered stock at straight into the Reference. £590 for 2011 Rousseau
   Charmes sits beside Farr at £610 and Bordeaux Index at £650 — close enough to
   look like a comparable, and it is not one.

2. **`merchantCount` is context, not depth.** The 2011 Chambertin indication is
   drawn from 8 merchants; that is one FINE+RARE record, and FINE+RARE counts
   once. Depth counts merchants we have an offer from, not merchants somebody
   else says they polled.

3. **Assortment cases are mixed lots.** FINE+RARE writes them as "Assortment"
   ("2002 DRC Assortment (2xEZ, 2xGDE, ...)"), never "mixed", so a pattern that
   only looks for "mixed" ingests a 12-bottle assortment as one wine.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://www.frw.co.uk"
PRODUCER_INDEX_URL = BASE + "/sitemap-producers.xml"
SITEMAP_INDEX_URL = BASE + "/sitemap.xml"

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_PRODUCER_URL = re.compile(r"<loc>[^<]*/producer/[^/]+/([^<]+)</loc>", re.I)
_LOC = re.compile(r"<loc>([^<]+)</loc>")

#: "2002 DRC Assortment (2xEZ, ...)" is a mixed lot, and so is a "mixed case".
_MIXED = re.compile(r"\bmixed\b|\bassort(?:ment|ed)?s?\b", re.I)

#: "2011 Charmes Chambertin" / "NV Trimbach Mixed Case".
_VINTAGE = re.compile(r"^\s*(?P<vintage>\d{4}|NV)\b", re.I)

#: How long a product sitemap is reused before being fetched again. The index
#: is ~400,000 URLs across nine files; a deep search asks about a handful of
#: producers, so it is downloaded once and kept (CLAUDE.md: cache aggressively).
SITEMAP_TTL_SECONDS = 3600

_sitemap_cache: dict[str, tuple[float, list[str]]] = {}


def parse_next_data(html: str) -> dict:
    """The page's own props. Returns {} when the page is not a Next.js page."""
    match = _NEXT_DATA.search(html or "")
    if not match:
        return {}
    return json.loads(match.group(1)).get("props", {}).get("pageProps", {})


def parse_producer_index(xml: str) -> dict[str, str]:
    """{producer as the slug spells it: the merchant's slug}, from
    /sitemap-producers.xml. The slug is the producer name hyphenated, so it
    normalises to the same producer key as the canonical name."""
    return {slug.replace("-", " "): slug for slug in _PRODUCER_URL.findall(xml or "")}


def product_urls(xml: str, producer_slug: str, vintage: int) -> list[str]:
    """The product pages for one producer in one vintage.

    A product URL ends `/<vintage>-<wine>-<producer-slug>`, so this is an exact
    selection and not a search. NV products are written `nv-...`.
    """
    prefix = "nv-" if vintage == 1000 else f"{vintage}-"
    return [url for url in _LOC.findall(xml or "")
            if url.rstrip("/").endswith(producer_slug)
            and url.rsplit("/", 1)[-1].lower().startswith(prefix)]


def parse_unit(size: object, unit: object) -> int | None:
    """('75', 'cl') -> 750. The indication is quoted per single unit."""
    try:
        value = float(str(size))
    except (TypeError, ValueError):
        return None
    factor = {"cl": 10, "l": 1000, "ml": 1}.get(str(unit or "").lower())
    if factor is None or value <= 0:
        return None
    return int(round(value * factor))


class FineAndRareAdapter(Adapter):
    id = "fine-rare"
    merchant = "FINE+RARE"

    def fetch(self, producer_slug: str | None = None, vintage: int | None = None, *,
             producer_slugs: Sequence[str] | None = None) -> Sequence[dict]:  # pragma: no cover
        """One producer in one vintage, or several slugs for one producer.

        Same union-of-slugs contract as the Bordeaux Index adapter
        (`producer_slugs`), for the same reason: FINE+RARE's own sitemap lists
        "louis-roederer" and "louis-roederer-et-philippe-starck" as two
        different producer slugs for one house, same as BI's own
        "pol_roger"/"pol_roger_(berry_bros._&_rudd)" split (Champagne sweep,
        9 October 2026) — dropping one silently halves that producer's depth.
        `app.worker.jobs._by_slug` always passes `producer_slugs` as a kwarg
        (whether or not the caller wanted a union), which is what exposed the
        missing parameter here: this adapter had never been run through
        `collect_targeted` against its own real signature, every test having
        patched `fetch` itself.
        """
        slugs = list(producer_slugs or ([producer_slug] if producer_slug else []))
        if not slugs:
            raise ValueError("a producer slug is required")
        import httpx
        with httpx.Client(timeout=60, follow_redirects=True,
                          headers={"User-Agent": user_agent()}) as client:
            urls: dict[str, None] = {}
            sitemaps = self._product_sitemaps(client)
            for slug in slugs:
                for sitemap in sitemaps:
                    for url in product_urls(self._cached(client, sitemap), slug, vintage):
                        urls.setdefault(url, None)
            return [self._product(client, url) for url in urls]

    def search_keys(self) -> dict[str, str]:  # pragma: no cover - network
        import httpx
        r = httpx.get(PRODUCER_INDEX_URL, timeout=120, follow_redirects=True,
                      headers={"User-Agent": user_agent()})
        r.raise_for_status()
        return parse_producer_index(r.text)

    def _product_sitemaps(self, client) -> list[str]:  # pragma: no cover - network
        index = self._cached(client, SITEMAP_INDEX_URL)
        return [url for url in _LOC.findall(index) if "sitemap-products" in url]

    def _cached(self, client, url: str) -> str:  # pragma: no cover - network
        cached = _sitemap_cache.get(url)
        if cached and time.monotonic() - cached[0] < SITEMAP_TTL_SECONDS:
            return cached[1]
        r = client.get(url)
        r.raise_for_status()
        _sitemap_cache[url] = (time.monotonic(), r.text)
        return r.text

    def _product(self, client, url: str) -> dict:  # pragma: no cover - network
        r = client.get(url)
        r.raise_for_status()
        props = parse_next_data(r.text)
        return {"url": url, "product": props.get("product"),
                "productMarketInfo": props.get("productMarketInfo")}

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        product = raw.get("product") or {}
        parent = product.get("parent") or {}
        name = product.get("name") or ""
        cuvee = parent.get("name") or ""
        producer = (parent.get("producer") or {}).get("name") or ""

        if _MIXED.search(name) or _MIXED.search(cuvee):
            return Rejected(raw, Reject.MIXED_LOT, name)

        match = _VINTAGE.match(name)
        if match is None:
            return Rejected(raw, Reject.VINTAGE, f"unreadable name {name!r}")
        stated = match.group("vintage").upper()
        vintage = 1000 if stated == "NV" else int(stated)

        market = raw.get("productMarketInfo") or {}
        indication = (market.get("unitPrice") or {}).get("amount")
        if indication is None:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, "no broking indication published")
        price = Decimal(str(indication))
        if price <= 0:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"indication {indication!r}")

        currency = (market.get("unitPrice") or {}).get("currencyCode")
        if currency != "GBP":
            return Rejected(raw, Reject.CURRENCY, f"indication in {currency!r}")

        bottle_ml = parse_unit(market.get("unitSize"), market.get("unit"))
        if bottle_ml is None:
            return Rejected(raw, Reject.SIZE,
                            f"unreadable unit {market.get('unitSize')!r} {market.get('unit')!r}")

        offer = Offer(
            offer_id=f"fine-rare:{product.get('_id')}",
            merchant_id=self.id,
            merchant=self.merchant,
            wine_id="",
            vintage=vintage,
            bottle_ml=bottle_ml,
            pack_size=1,                      # the indication is quoted per unit
            price=price,
            currency="GBP",
            # Nobody has said they hold it, In Bond or otherwise.
            duty_status=DutyStatus.UNKNOWN,
            price_kind=PriceKind.INDICATION,
            is_buyable=False,
            offered_units=0,
            stock_type=StockType.BROKERED,
            stock_type_basis="declared",      # the merchant says so itself
            is_mixed_lot=False,
            condition_flags=frozenset(),
            condition_notes=None,
            source_url=raw.get("url"),
            captured_at=captured_at or datetime.now(timezone.utc),
            raw={"product_id": product.get("_id"), "url": raw.get("url"), "name": name,
                 "producer": producer, "cuvee": cuvee,
                 # Context only: how many merchants FINE+RARE aggregated. It is
                 # not depth — FINE+RARE counts once (decision 0013).
                 "market": market},
        )
        from app.identity.resolver import split_release_code
        split_cuvee, release_code = split_release_code(cuvee)
        return Candidate(offer=offer, producer_text=producer, cuvee_text=split_cuvee,
                         release_code=release_code)


def indications(records: Iterable[dict], adapter: FineAndRareAdapter | None = None):
    """Convenience for scripts: normalise a run of raw records."""
    adapter = adapter or FineAndRareAdapter()
    return [adapter.normalise(record) for record in records]
