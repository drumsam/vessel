"""Bordeaux Index — server-rendered product listings.

Deep-search query shape (verified live 2026-09-19):
    /fine-wine/all?producer=<slug>&vintage=<year>
Product page:
    /fine-wine/france/burgundy/<code>-<vintage>
robots.txt allows /fine-wine and /livetrade/marketplace; it disallows
/livetrade/watch-list, /tight-spreads, /my-orders, /my-trades and /account.

Four traps, all of which produce a wrong price rather than a missing one.

1. **Duty-paid offers are nested inside the In Bond block.** 2009 Rousseau
   Gevrey-Chambertin lists, in the same panel:
       Case (1 x 75cl) ... STATUS In-Bond   ... £590.00
       Bottle (75cl)   ... STATUS Duty Paid ... £420.00
   The duty-paid row is cheaper, so a section-level filter takes it as the
   floor and under-prices by 29%. Duty status is read PER OFFER ROW.

2. **The card class differs between page types.** Product pages use
   `.product_wrapper.in-bond`; listing pages use a bare `.product_wrapper`
   containing `.wine-inbond`. `.wine-inbond` / `.wine-delivery` is the pair that
   is stable across both. The duty-paid markup is present in the DOM either way
   (`d-none`), so selecting by visibility is not a filter.

3. **Merchant codes do not encode the cuvee the way they look.** `roush-2005`
   is CHARMES-Chambertin; `rouc-2011` is Chambertin. `vogbb-2005` is Bourgogne
   Blanc, not Musigny Blanc. Identity comes from the printed title only; the
   code is an opaque key.

4. **Prices are session-currency scoped** via /currency-set/<CCY>. An adapter
   that does not pin GBP can capture HKD or USD in a currency-free template.
   We set the currency cookie and assert the parsed symbol.

The headline `.product-table__row` price is the cheapest pack for the headline
format, not the cheapest per bottle. Every `.offer` row is emitted separately.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterator, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .condition import condition_evidence
from .http import user_agent

BASE = "https://bordeauxindex.com"
LIST_URL = BASE + "/fine-wine/all"
CURRENCY_URL = BASE + "/currency-set/GBP"
PRODUCER_INDEX_URL = BASE + "/fine-wine"

# Bordeaux Index's own producer index: /fine-wine/producer/<slug>. The slug form
# matters and cannot be guessed from the name — `domaine_armand_rousseau` works
# and `domaine-armand-rousseau` is a 404 (verified live 2026-09-20). These are
# read from the merchant's own index and stored in merchant_search_key.
_PRODUCER_LINK = re.compile(r'href="/fine-wine/producer/([^"]+)"[^>]*>([^<]+)</a>', re.I)


def parse_producer_index(html: str) -> dict[str, str]:
    """{printed producer name: the merchant's slug for it}."""
    import html as html_module
    return {html_module.unescape(name).strip(): slug
            for slug, name in _PRODUCER_LINK.findall(html or "")}

# "Case (6 x 75cl)" | "Case (1 x 150cl)" | "Bottle (75cl)"
_PACK = re.compile(r"(?:Case\s*\(\s*(?P<pack>\d+)\s*x\s*(?P<csize>\d+)\s*cl\s*\)"
                   r"|Bottle\s*\(\s*(?P<bsize>\d+)\s*cl\s*\))", re.I)
_STATUS = re.compile(r"STATUS\s+(?P<status>In-?Bond|Duty\s*Paid)", re.I)
_CONDITION = re.compile(r"CONDITION\s+(?P<cond>.+?)\s+STATUS", re.I | re.S)
_PRICE = re.compile(r"(?:You\s+buy|Buy\s+at)\s*£\s*(?P<price>[\d,]+(?:\.\d{2})?)", re.I)
_QTY = re.compile(r"(?P<n>\d+)\s+(?:Case|Bottle)\(s\)\s+(?:Remaining|Available)", re.I)
# Non-LiveTrade third-party marker seen on some cards; basis unconfirmed with BI.
_BR = re.compile(r"\bBR\b")
_TITLE = re.compile(r"^\s*(?P<vintage>\d{4}|NV)\s+(?P<rest>.+?)\s*$")


def parse_title(title: str) -> dict | None:
    """'2005 Domaine Armand Rousseau, Charmes-Chambertin Grand Cru'
       -> vintage 2005, producer 'Domaine Armand Rousseau',
          cuvee 'Charmes-Chambertin Grand Cru'

    BI is producer-FIRST (the opposite of Farr). Split on the first comma.
    """
    m = _TITLE.match(title or "")
    if not m:
        return None
    rest = m.group("rest")
    producer, _, cuvee = rest.partition(",")
    return {
        "vintage": 1000 if m.group("vintage").upper() == "NV" else int(m.group("vintage")),
        "producer": producer.strip(),
        "cuvee": cuvee.strip() or producer.strip(),
    }


def parse_offer_row(text: str) -> dict | None:
    """Parse one `.offer` row's flattened text into a normalised dict."""
    pack_m = _PACK.search(text)
    status_m = _STATUS.search(text)
    price_m = _PRICE.search(text)
    if not (pack_m and status_m and price_m):
        return None

    if pack_m.group("pack"):
        pack = int(pack_m.group("pack"))
        ml = int(pack_m.group("csize")) * 10
    else:
        pack = 1
        ml = int(pack_m.group("bsize")) * 10

    status = re.sub(r"\s|-", "", status_m.group("status")).lower()
    duty = DutyStatus.IN_BOND if status == "inbond" else DutyStatus.DUTY_PAID

    cond_m = _CONDITION.search(text)
    qty_m = _QTY.search(text)

    return {
        "pack_size": pack,
        "bottle_ml": ml,
        "duty_status": duty,
        "price": Decimal(price_m.group("price").replace(",", "")),
        "condition_notes": cond_m.group("cond").strip() if cond_m else None,
        "offered_units": int(qty_m.group("n")) if qty_m else None,
        "third_party_marker": bool(_BR.search(text)) and "LIVETRADE" not in text.upper(),
    }


class BordeauxIndexAdapter(Adapter):
    id = "bordeaux-index"
    merchant = "Bordeaux Index"

    def fetch(self, producer_slug: str, vintage: int) -> Sequence[dict]:  # pragma: no cover
        import httpx
        with httpx.Client(timeout=60, follow_redirects=True,
                          headers={"User-Agent": user_agent()}) as c:
            c.get(CURRENCY_URL)                     # pin GBP for this session
            r = c.get(LIST_URL, params={"producer": producer_slug, "vintage": vintage})
            r.raise_for_status()
            return list(extract_cards(r.text))

    def search_keys(self) -> dict[str, str]:  # pragma: no cover - network
        """The merchant's own producer index, for merchant_search_key."""
        import httpx
        r = httpx.get(PRODUCER_INDEX_URL, timeout=60, follow_redirects=True,
                      headers={"User-Agent": user_agent()})
        r.raise_for_status()
        return parse_producer_index(r.text)

    def normalise(self, raw: dict, captured_at: datetime | None = None):
        """`raw` is one card: {"title": str, "offers": [str, ...], "url": str}.

        Returns one result per offer row: a Candidate, or a Rejected carrying
        that row's text. A card yields as many results as it has rows."""
        t = parse_title(raw.get("title", ""))
        if t is None:
            return Rejected(raw, Reject.UNRESOLVED_IDENTITY, f"unparseable title {raw.get('title')!r}")

        out: list[Candidate | Rejected] = []
        for i, row in enumerate(raw.get("offers", [])):
            p = parse_offer_row(row)
            if p is None:
                # Never dropped silently: a row we cannot read is a rejection
                # with the row's own text, like every other rejection.
                out.append(Rejected({"card": raw.get("title"), "offer_row": row},
                                    Reject.ROW_UNREADABLE, row[:200]))
                continue
            if p["price"] <= 0:
                out.append(Rejected({"card": raw.get("title"), "offer_row": row},
                                    Reject.NON_POSITIVE_PRICE, row[:200]))
                continue
            flags, _ = condition_evidence(p["condition_notes"])
            out.append(Candidate(
                offer=Offer(
                    offer_id=f"bi:{raw.get('code') or raw.get('url')}:{i}",
                    merchant_id=self.id,
                    merchant=self.merchant,
                    wine_id="",
                    vintage=t["vintage"],
                    bottle_ml=p["bottle_ml"],
                    pack_size=p["pack_size"],
                    price=p["price"],
                    currency="GBP",
                    duty_status=p["duty_status"],
                    price_kind=PriceKind.ASK,
                    is_buyable=bool(p["offered_units"] and p["offered_units"] > 0),
                    offered_units=p["offered_units"],
                    stock_type=StockType.UNKNOWN if p["third_party_marker"] else StockType.MERCHANT_STOCK,
                    stock_type_basis="unconfirmed" if p["third_party_marker"] else "inferred",
                    condition_flags=flags,
                    condition_notes=p["condition_notes"],   # all of CONDITION, flagged or not
                    source_url=raw.get("url"),
                    captured_at=captured_at or datetime.now(timezone.utc),
                    raw={"card": raw.get("title"), "offer_row": row},
                ),
                producer_text=t["producer"],
                cuvee_text=t["cuvee"],
            ))
        return out


def extract_cards(html: str) -> Iterator[dict]:  # pragma: no cover - thin DOM shim
    """Select `.wine-inbond` cards (stable across product and listing pages) and
    flatten each `.offer` row. Duty status is still read per row afterwards —
    the wrapper class is NOT a duty filter."""
    from selectolax.parser import HTMLParser
    tree = HTMLParser(html)
    for card in tree.css(".wine-inbond"):
        title_el = card.css_first("h2.wine-name") or card.css_first("h2")
        lt = card.css_first("a.livetrade")
        yield {
            "title": (title_el.text() if title_el else "").strip(),
            "code": (lt.attributes.get("href", "").rsplit("/", 1)[-1] if lt else None),
            "url": (lt.attributes.get("href") if lt else None),
            "offers": [" ".join(o.text().split()) for o in card.css(".offer")],
        }
