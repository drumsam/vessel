"""Bordeaux Index LiveTrade — a two-sided marketplace, read separately from
the regular fine-wine listing pages (app/adapters/bordeaux_index.py), but
published under the SAME merchant identity. See
docs/research/bi-livetrade-champagne-findings.md and docs/decisions/0026,
0027.

Verified live 8 October 2026. robots.txt allows /livetrade/marketplace
(same file the sibling adapter already reads; it disallows
/livetrade/watch-list, /tight-spreads, /my-orders, /my-trades and
/account, none of which this adapter touches).

Query shape:
    /livetrade/marketplace/<free text>          -- server-rendered, no JS
    e.g. /livetrade/marketplace/krug

The research's own "client-rendered" read was of one item's own page; the
SEARCH page itself needs no Playwright — confirmed by fetching it with a
plain GET and finding the data already there, server-side, as JSON.

The data is NOT scraped from `.bid-button`/`.offer-button` display text.
Every `.livetrade-item` carries a `data-item="{...}"` attribute with the
complete record — identity, format, duty status, and the full bid/offer/
last-trade picture for that one listing — as clean JSON, six times over
(desktop/mobile/tablet x bid-button/offer-button). Reading the attribute
is both more reliable and less code than parsing rendered text, and it is
the same lesson BI's own `/search/auto-complete-ajax` endpoint already
teaches: prefer the structured answer the page already computed over the
one meant for a human eye.

Two traps found, both producing a wrong price or a missing one, not a
loud failure.

1. **BI names the SAME wine two different ways, in two fields of the SAME
   JSON record.** `productName`: "Krug Grande Cuvee Edition 162" (edition
   number last). `lwinProductName`: "Krug, Grande Cuvee 162eme Edition"
   (edition number in the middle, producer comma-separated). This adapter
   reads `lwinProductName` for the producer/cuvee split (it is comma-
   structured, matching this codebase's own producer-first convention)
   and the LWIN registry wording besides — `productName` is kept only as
   a fallback when `lwinProductName` is absent.
2. **The search caps at 100 items with no pagination.** Confirmed live:
   `/livetrade/marketplace/krug` returns exactly 100 unique variants.
   Silence past the cap is not "nothing more exists" — it is simply
   uncounted. `fetch()` raises `SearchTooBroad` rather than returning a
   capture that might be missing results with no sign of it; the caller
   narrows the search term (e.g. "krug grande cuvee" instead of "krug").
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .bordeaux_index import BordeauxIndexAdapter
from .condition import condition_evidence
from .http import user_agent

BASE = "https://bordeauxindex.com"
MARKETPLACE_URL = BASE + "/livetrade/marketplace"

#: BI's own duty-status codes map straight onto DutyStatus's own values —
#: confirmed by inspection, not assumed: every item read live was "IB", but
#: the mapping is read per item regardless, never defaulted to IN_BOND.
_DUTY = {"IB": DutyStatus.IN_BOND, "DP": DutyStatus.DUTY_PAID}

#: Verified live 8 October 2026: the page's own cap, with no pagination
#: control found. See trap 2 above.
MAX_ITEMS = 100


class SearchTooBroad(Exception):
    """Hit the page's own 100-item cap, with no pagination: some results may
    be missing, uncounted. Narrow the search term rather than trust it."""


def extract_livetrade_items(html: str) -> list[dict]:  # pragma: no cover - thin DOM shim
    """Every `.livetrade-item`'s `data-item` JSON blob is read directly — no
    `.bid-button`/`.offer-button` text parsing. Six near-identical copies
    exist per item (desktop/mobile/tablet x bid-button/offer-button, all the
    same JSON); dedupe by `variantId`, first occurrence wins."""
    from selectolax.parser import HTMLParser
    tree = HTMLParser(html)
    seen: dict[int, dict] = {}
    for el in tree.css("[data-item]"):
        raw = el.attributes.get("data-item")
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        seen.setdefault(item.get("variantId"), item)
    return list(seen.values())


def _parse_bi_datetime(text: Optional[str]) -> Optional[datetime]:
    """"2026-06-10T09:39:05.64" — no offset published. Assumed UTC, the same
    assumption every `as_of`/`captured_at` in this system already makes
    when nothing says otherwise; never silently left naive, which
    `_is_fresh`/`benchmark` would refuse outright (`as_of must be
    timezone-aware`)."""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class BordeauxIndexLiveTradeAdapter(Adapter):
    id = "bordeaux-index-livetrade"
    merchant = "Bordeaux Index"

    #: Every Offer this adapter produces carries this merchant_id — NOT
    #: `self.id` above. LiveTrade and the fine-wine listing pages are one
    #: company publishing two different views of its own book; `id` only
    #: separates them for collection bookkeeping (snapshots, robots, LWIN-
    #: conflict tracking — see TARGETED in app/worker/jobs.py), never for
    #: pricing. Depth counts merchants (invariant 4), and a view rather
    #: than stock still counts as one merchant whatever name it trades
    #: under (invariant 17, decision 0013) — two rows both saying
    #: "Bordeaux Index" must never become two comps. Setting this to
    #: `self.id` instead would silently double-count the one company that
    #: happens to publish both.
    OFFER_MERCHANT_ID = "bordeaux-index"

    def fetch(self, search: str, vintage: int | None = None, *, client=None) -> Sequence[dict]:
        """One free-text search, e.g. "krug" or the narrower "krug grande
        cuvee". `vintage` is accepted only to match the shared
        `Targeted._by_search` call shape (app/worker/jobs.py) — LiveTrade's
        search has no vintage filter; every edition and vintage the term
        matches comes back, and each is screened on its own vintage
        downstream, same as the sibling adapter's own listing pages.
        """
        if not search:
            raise ValueError("a search term is required")
        owns_client = client is None
        if owns_client:  # pragma: no cover - network
            import httpx
            client = httpx.Client(timeout=60, follow_redirects=True,
                                  headers={"User-Agent": user_agent()})
        try:
            r = client.get(f"{MARKETPLACE_URL}/{search}")
            r.raise_for_status()
            items = extract_livetrade_items(r.text)
            if len(items) >= MAX_ITEMS:
                raise SearchTooBroad(
                    f"{search!r} returned {len(items)} items, the page's own cap, with no "
                    "pagination — some may be missing. Narrow the search term.")
            return items
        finally:
            if owns_client:  # pragma: no cover - network
                client.close()

    def search_keys(self, client=None) -> dict[str, str]:
        """LiveTrade searches by producer name, same as the sibling
        adapter's own listing pages — the same company, the same producer
        index (decision 0011: search keys come from the merchant's own
        index, never guessed). Delegated rather than duplicated."""
        return BordeauxIndexAdapter().search_keys(client=client)

    def normalise(self, raw: dict, captured_at: datetime | None = None):
        """`raw` is one item's parsed `data-item` JSON. Up to three results
        — the lowest offer (ASK), the best bid (BID), and the last trade
        (LAST_TRADE) — never more than one of each: the ladder beneath the
        best bid is confirmatory context, not additional comps (the
        research that prompted this adapter already checked it; nothing
        here needs to check it again).
        """
        producer = (raw.get("productProducer") or "").strip()
        name = raw.get("lwinProductName") or raw.get("productName") or ""
        _, _, after_comma = name.partition(",")
        cuvee = after_comma.strip() or name.strip()
        vintage = raw.get("vintageYear")
        item_code = raw.get("itemCode") or raw.get("variantId")
        if not producer or not cuvee or vintage is None:
            return Rejected(raw, Reject.UNRESOLVED_IDENTITY,
                            f"no producer/cuvee/vintage in item {item_code!r}")

        from app.identity.resolver import split_release_code
        cuvee, release_code = split_release_code(cuvee)

        bottle_ml = (raw.get("itemVolume") or 0) * 10
        pack_size = raw.get("packSize") or 1
        if not bottle_ml or not pack_size:
            return Rejected(raw, Reject.UNRESOLVED_IDENTITY,
                            f"no size/pack in item {item_code!r}")
        duty = _DUTY.get(raw.get("dutyStatusCode"), DutyStatus.UNKNOWN)
        lwin16 = raw.get("lwin16")
        lwin7 = lwin16[:7] if lwin16 and len(lwin16) >= 7 else None
        condition_flags, condition_notes = condition_evidence(
            raw.get("caseConditionDescription"), raw.get("bottleConditionDescription"))
        variant_id = raw.get("variantId")
        page_captured_at = captured_at or datetime.now(timezone.utc)

        def offer(suffix: str, price_kind: PriceKind, price, offered_units,
                 is_buyable: bool, when: datetime) -> Offer:
            return Offer(
                offer_id=f"bi-lt:{variant_id}:{suffix}",
                merchant_id=self.OFFER_MERCHANT_ID, merchant=self.merchant,
                wine_id="", vintage=vintage, bottle_ml=bottle_ml, pack_size=pack_size,
                price=Decimal(str(price)), currency="GBP", duty_status=duty,
                price_kind=price_kind, is_buyable=is_buyable, offered_units=offered_units,
                stock_type=StockType.MERCHANT_STOCK, stock_type_basis="declared",
                condition_flags=condition_flags, condition_notes=condition_notes,
                source_url=f"{MARKETPLACE_URL}/{raw.get('vintageWebUrl') or ''}",
                captured_at=when, raw=raw)

        out: list[Candidate | Rejected] = []

        offers = [o for o in (raw.get("offers") or []) if o.get("casePrice")]
        if offers:
            lowest = min(offers, key=lambda o: o["casePrice"])
            out.append(Candidate(
                offer=offer("ask", PriceKind.ASK, lowest["casePrice"],
                           lowest.get("quantityAvailable"),
                           bool(lowest.get("quantityAvailable")), page_captured_at),
                producer_text=producer, cuvee_text=cuvee, lwin7=lwin7,
                release_code=release_code))

        bids = [b for b in (raw.get("bids") or []) if b.get("casePrice")]
        if bids:
            best = max(bids, key=lambda b: b["casePrice"])
            out.append(Candidate(
                offer=offer("bid", PriceKind.BID, best["casePrice"],
                           best.get("quantityAvailable"), False, page_captured_at),
                producer_text=producer, cuvee_text=cuvee, lwin7=lwin7,
                release_code=release_code))

        last_trade = raw.get("lastTrade") or {}
        traded_at = _parse_bi_datetime(last_trade.get("dateTime"))
        if last_trade.get("casePrice") and traded_at:
            out.append(Candidate(
                offer=offer("trade", PriceKind.LAST_TRADE, last_trade["casePrice"],
                           None, False, traded_at),
                producer_text=producer, cuvee_text=cuvee, lwin7=lwin7,
                release_code=release_code))

        if not out:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE,
                            f"item {item_code!r}: no offer, bid or usable last trade")
        return out
