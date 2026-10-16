"""Berry Bros. & Rudd — investigated live 10-11 October 2026, Doug's verbal
permission to fetch pricing recorded in docs/decisions/0030.

robots.txt: `Allow: /` with a handful of path disallows (cart, checkout,
my-account, search), `Crawl-delay: 10`, and the first `Visit-time: 0200-0700`
(UTC) seen anywhere in this fleet — enforced by app.worker.politeness, never
loosened by this adapter. Doug's permission is additive comfort, not an
override of either directive.

## The real pricing is not in the rendered HTML, and not in its JSON-LD either

A product page's own `<script type="application/ld+json">` ProductGroup block
shows `lowPrice: 0, highPrice: 0, offerCount: 0` — a stale placeholder, never
read here. The real data is a Vue/Nuxt SSR state dump, `window.__NUXT__=...`,
serialised as a minified JS expression (devalue-style), not JSON — it must be
evaluated, not parsed. `extract_hits()` locates the assignment, bounds it at
the closing `</script>`, and evaluates it in a throwaway Node subprocess with
a bare `global.window = {}` shim; nothing else about this adapter touches
Node, and `fetch()`/`normalise()` keep the ordinary network/pure split. The
state holds a full Algolia result (`algoliaState.prod_product.results[0]`)
for whichever producer page was requested.

## One producer page, every edition currently offered — with a hard ceiling

`/producer-<id>-<slug>` (ids and slugs read from `sitemap-category.xml`, never
guessed — Charles Heidsieck's sitemap gives `producer-9576-...`; a
differently-numbered `producer-3506-charles-heidsieck` also resolves but
returns `nbHits: 19912`, an unfiltered or mis-filtered catalogue, and must
never be used). The page server-renders only the FIRST page of Algolia
results — confirmed live: Krug's own page returns 24 of `nbHits: 58`, and the
24 returned are the newest editions, never this cellar's older ones. `?page=`
on the URL does not reach a second page (confirmed: still page 0 back).
`fetch()` raises `ProducerPageTruncated` rather than silently returning a
partial page with no sign of it — the caller cannot narrow a producer page
the way a search term narrows, so this merchant is incomplete for any
producer whose stock exceeds the page's own hits-per-page, until BBR's own
Algolia search key is found.

## Each hit's own `purchase_options[]` is the real ladder — the top-level fields are one entry, repeated

An Algolia hit's top-level `purchase_mode`/`stock_origin`/`prices`/`case_size`/
`bottle_volume` describe only the ONE variant Algolia promoted as that hit's
headline; `purchase_options` is the complete list for the SAME wine, and
every top-level hit's own fields reappear inside its own `purchase_options`
unchanged (confirmed live: zero top-level skus absent from some hit's nested
list). Reading only the top level would miss real depth — one Taittinger
2013 hit alone carried 8 nested listings, including a Jeroboam format never
promoted to any top-level hit on the page at all. `fetch()` therefore reads
`purchase_options` exclusively, flattens every entry across every hit on the
page, and dedupes by `bbx_listing_id` (a specific seller's specific listing)
or, for a BBR-direct entry with no listing id, by `(sku, purchase_mode)` —
the same entry is nested, verbatim, inside every top-level hit for that wine.

## Two stock origins, one merchant — BBR direct stock and BBR's own exchange

`stock_origin` is `"BBR"` (Berry Bros' own held stock) or `"BBX"` (its live
peer-to-peer exchange, each listing carrying its own `bbx_listing_id`). Both
are Berry Bros. & Rudd publishing its own book two ways, exactly the "one
company, two surfaces" reading already established for Bordeaux Index's
LiveTrade marketplace (decision 0026/0027) — both stock origins are read by
this ONE adapter and published under this ONE `merchant_id`; nothing here
needs OFFER_MERCHANT_ID or a second adapter id, because there was only ever
one fetch and one page. `stock_origin` only chooses `StockType`
(`MERCHANT_STOCK` / `MARKETPLACE`), never a separate comp.

## Price field selection is keyed by `purchase_mode`, never by `case_size`

Confirmed across every nested purchase_option collected (1,118 records, zero
exceptions): `purchase_mode == "In Bond"` always populates
`price_per_case_exact` (never `price_per_bottle_exact`) and the price is for
the whole `case_size`-bottle pack — so `pack_size = case_size`, even when
`case_size == 1` (a single Jeroboam is still "a case of one"). `purchase_mode
== "Delivery"` (duty paid, BBR retail) always populates
`price_per_bottle_exact` instead, for ONE bottle regardless of the SKU's own
case_size — so `pack_size = 1` for that mode. Every "Delivery" entry still
becomes a Candidate at `DutyStatus.DUTY_PAID`, same discipline as every other
adapter in this fleet (lw_trading.py's own "duty paid" mapping): proposed
here, rejected by the deterministic core's hard screen (invariant 5), never
pre-filtered by this adapter.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from app.identity.resolver import norm_producer, split_release_code
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://www.bbr.com"

_DUTY = {"in bond": DutyStatus.IN_BOND, "delivery": DutyStatus.DUTY_PAID}
_STOCK_TYPE = {"BBR": StockType.MERCHANT_STOCK, "BBX": StockType.MARKETPLACE}

_CHAMPAGNE_PREFIX_RE = re.compile(r"^Champagne\s+", re.IGNORECASE)
_TRAILING_BRUT_RE = re.compile(r",\s*Brut$", re.IGNORECASE)
_VOLUME_RE = re.compile(r"^([\d.]+)\s*cl$", re.IGNORECASE)


class ProducerPageTruncated(Exception):
    """The page returned fewer hits than Algolia's own `nbHits` for this
    producer: some editions are missing, uncounted, with no pagination
    control that reaches them. See the module docstring."""


def extract_hits(html: str) -> tuple[list[dict], int]:  # pragma: no cover - thin Node shim
    """(hits, nbHits) from the page's own `window.__NUXT__` state. Evaluated in
    a throwaway Node subprocess because the state is a JS expression
    (devalue-style), not JSON — `global.window = {}` is the only shim it
    needs, confirmed against several real captured pages."""
    start = html.find("window.__NUXT__=")
    if start < 0:
        return [], 0
    end = html.find("</script>", start)
    if end < 0:
        return [], 0
    blob = html[start:end]
    script = (
        "global.window = {};\n"
        + blob + "\n"
        "const data = global.window.__NUXT__;\n"
        "const st = (data.algoliaState || {}).prod_product;\n"
        "const r = st && st.results && st.results[0];\n"
        "process.stdout.write(JSON.stringify(r ? {hits: r.hits, nbHits: r.nbHits} "
        "                                     : {hits: [], nbHits: 0}));\n"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"BBR __NUXT__ evaluation failed: {result.stderr[:500]}")
    data = json.loads(result.stdout)
    return data["hits"], data["nbHits"]


def parse_bottle_volume(text: Optional[str]) -> Optional[int]:
    """"75 cl" -> 750. None if unreadable."""
    match = _VOLUME_RE.match((text or "").strip())
    if not match:
        return None
    ml = round(float(match.group(1)) * 10)
    return ml if ml > 0 else None


def parse_cuvee(name: str, producer: str, vintage: Optional[int]) -> tuple[str, Optional[str]]:
    """BBR writes "<vintage> Champagne <producer>, <cuvee>, Brut" — vintage and
    "Champagne" are sometimes absent (an NV hit, or a producer field that is
    already bare, e.g. "Krug" against "Champagne Taittinger" on another
    page); each is stripped only when actually present, never assumed.
    Trailing ", Brut" is BBR's own generic sweetness suffix on almost every
    listing and is stripped the same way — but only as a standalone trailing
    clause after a comma, never out of a genuine modifier like "Extra Brut",
    which carries no leading comma of its own.
    """
    text = name or ""
    if vintage is not None:
        text = re.sub(rf"^{vintage}\s+", "", text)
    text = _CHAMPAGNE_PREFIX_RE.sub("", text)
    producer_bare = _CHAMPAGNE_PREFIX_RE.sub("", producer or "").strip()
    head, comma, rest = text.partition(",")
    if comma and norm_producer(head) == norm_producer(producer_bare):
        text = rest.strip()
    if text.strip().lower() == "brut":
        text = ""
    else:
        text = _TRAILING_BRUT_RE.sub("", text).strip()
    cuvee, release_code = split_release_code(text)
    return cuvee.rstrip(", ").strip(), release_code


def _listing_key(po: dict) -> str:
    listing_id = po.get("bbx_listing_id")
    if listing_id:
        return f"bbx:{listing_id}"
    return f"bbr:{po.get('sku')}:{po.get('purchase_mode')}"


class BerryBrosRuddAdapter(Adapter):
    id = "berry-bros-rudd"
    merchant = "Berry Bros. & Rudd"

    def fetch(self, producer_slugs: Sequence[str], vintage: int | None = None, *,
              client=None, sleep=time.sleep) -> Sequence[dict]:
        """One or more `producer-<id>-<slug>` paths, read from the merchant's
        own `sitemap-category.xml` (decision 0011: search keys come from the
        merchant's own index, never guessed). `vintage` is accepted only to
        match the shared `(adapter, params, vintage)` call shape
        (`app.worker.jobs.TARGETED`) — one producer page returns every
        edition and vintage it currently lists, same reasoning as the
        Justerini & Brooks and Bordeaux Index LiveTrade adapters' own fetches.

        Each raw record returned is one flattened, deduplicated
        `purchase_options` entry carrying its parent hit's own `name`,
        `producer`, `vintage` and `product_url` alongside it — see the module
        docstring for why the top-level hit fields are never read directly.
        """
        if not producer_slugs:
            raise ValueError("at least one producer slug is required")
        owns_client = client is None
        if owns_client:  # pragma: no cover - network
            import httpx
            client = httpx.Client(timeout=30, follow_redirects=True,
                                  headers={"User-Agent": user_agent()})
        try:
            out: list[dict] = []
            seen: set[str] = set()
            for i, slug in enumerate(producer_slugs):
                if i > 0:
                    sleep(10)
                r = client.get(f"{BASE}/{slug}")
                r.raise_for_status()
                hits, nb_hits = extract_hits(r.text)
                if nb_hits > len(hits):
                    raise ProducerPageTruncated(
                        f"{slug!r} returned {len(hits)} of {nb_hits} hits — some editions "
                        "are missing, uncounted, with no pagination control that reaches "
                        "them.")
                for hit in hits:
                    context = {
                        "name": hit.get("name"),
                        "producer": hit.get("producer"),
                        "vintage": hit.get("vintage"),
                        "product_url": hit.get("product_url"),
                    }
                    for po in hit.get("purchase_options") or []:
                        key = _listing_key(po)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append({**context, **po})
            return out
        finally:
            if owns_client:  # pragma: no cover - network
                client.close()

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        name = raw.get("name") or ""
        producer = raw.get("producer") or ""
        if not name or not producer:
            return Rejected(raw, Reject.ROW_UNREADABLE, "missing name/producer")

        duty = _DUTY.get((raw.get("purchase_mode") or "").strip().lower())
        if duty is None:
            return Rejected(raw, Reject.DUTY,
                            f"unrecognised purchase_mode {raw.get('purchase_mode')!r}")

        stock_type = _STOCK_TYPE.get(raw.get("stock_origin"))
        if stock_type is None:
            return Rejected(raw, Reject.ROW_UNREADABLE,
                            f"unrecognised stock_origin {raw.get('stock_origin')!r}")

        bottle_ml = parse_bottle_volume(raw.get("bottle_volume"))
        if bottle_ml is None:
            return Rejected(raw, Reject.SIZE,
                            f"unreadable bottle_volume {raw.get('bottle_volume')!r}")

        case_size = raw.get("case_size")
        if not isinstance(case_size, int) or case_size < 1:
            return Rejected(raw, Reject.SIZE, f"unreadable case_size {case_size!r}")

        prices = raw.get("prices") or {}
        if duty is DutyStatus.IN_BOND:
            price_raw, pack_size = prices.get("price_per_case_exact"), case_size
        else:
            price_raw, pack_size = prices.get("price_per_bottle_exact"), 1
        if price_raw is None or price_raw <= 0:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"price {price_raw!r}")

        vintage_raw = raw.get("vintage")
        vintage = 1000 if vintage_raw is None else int(vintage_raw)

        producer_text = _CHAMPAGNE_PREFIX_RE.sub("", producer).strip()
        cuvee_text, release_code = parse_cuvee(name, producer, vintage_raw)

        offer = Offer(
            offer_id=f"bbr:{_listing_key(raw)}",
            merchant_id=self.id, merchant=self.merchant,
            wine_id="", vintage=vintage, bottle_ml=bottle_ml, pack_size=pack_size,
            price=Decimal(str(price_raw)), currency="GBP",
            duty_status=duty, price_kind=PriceKind.ASK,
            is_buyable=True, offered_units=None,
            stock_type=stock_type, stock_type_basis="declared",
            condition_flags=frozenset(), condition_notes=None,
            source_url=(BASE + raw["product_url"]) if raw.get("product_url") else None,
            captured_at=captured_at or datetime.now(timezone.utc),
            raw=raw,
        )
        return Candidate(offer=offer, producer_text=producer_text, cuvee_text=cuvee_text,
                         release_code=release_code)
