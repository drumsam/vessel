"""Jeroboams — investigated live 11-16 October 2026. Third of the three
houses Doug asked to be investigated for UK breadth, one at a time (see
app/adapters/justerini_brooks.py and app/adapters/berry_bros_rudd.py).

robots.txt (checked 16 October 2026): `Allow: /` with ordinary path
disallows (cart, checkout, account, wishlist, `/graphql`), explicit
`Allow:` carve-outs for query strings on faceted/paginated listing routes,
and a blanket `Disallow: /*?*` for everything else — no `Crawl-delay`, no
`Visit-time`. `/about-us/terms-and-conditions-of-sale` was read in full and
carries no automated-collection clause (checked for "robot", "scrape",
"crawl", "automat", "bot", "spider", "data mining" — none present). Both
conditions Doug's own instruction required before building ("check robots
and terms BEFORE building") are satisfied; `/graphql` stays untouched even
though it almost certainly carries richer data, because it is disallowed.

## Server-rendered Next.js, with the data as plain JSON this time

Unlike Berry Bros' devalue-style `__NUXT__` state, a product page's own
`<script id="__NEXT_DATA__">` is standard JSON — no Node subprocess, no
eval, just `json.loads`. `extract_product()` reads
`props.pageProps.initialProduct` (the product record) and
`props.pageProps.initialUniqueItems` (the real, priced variants).

## Two different page shapes for what is, underneath, the same catalogue

A wine with `attribute_set_id: 11` (every In Bond listing checked) is a
configurable product: `initialUniqueItems` holds a USELESS zero-price
"-MAIN" placeholder (`case_size`/`bottle_size`/`volume` all null — it
naturally fails the SIZE screen and needs no special-casing) alongside one
or more REAL priced variants, each a separate commercial unit. A duty-paid
retail listing (`attribute_set_id: 10`, no "ib-" URL prefix — e.g. the
Sancerre fixture) is a plain simple product: a flat price straight on
`initialProduct`, sometimes with its own single `initialUniqueItems` entry
too, and no "-MAIN" split at all. Duty status is read from the DATA, never
the URL: a `sku` ending `...IB` (optionally followed by a UUID, e.g.
`"...0600750IB-263522a7-..."`) is In Bond; a bare numeric `sku` with no
`IB` suffix is duty paid. Fetching a non-"ib-" URL by mistake still comes
out right — it reads as `DutyStatus.DUTY_PAID` and the core's own hard
screen (invariant 5) rejects it, same discipline every other adapter in
this fleet already gives a recognised-but-not-in-bond status.

## The one thing this cellar has not found anywhere else: a real loose bottle, back vintage, In Bond

Confirmed live: `ib-2012-henri-giraud-argonne-rose-...0100750` lists
`case_size: "1 x Bottle"`, a single 750ml bottle, In Bond, £1,531 — not a
case divided down, a genuinely quoted single-bottle price. Every other UK
merchant adapter built so far (Farr, Goedhuis, Lea & Sandeman, Bordeaux
Index, FINE+RARE, Lay & Wheeler Trading, Justerini & Brooks, Berry Bros. &
Rudd) sells this cellar's back-vintage Champagne almost exclusively by the
case (see `docs/research/uk-trade-current-releases-vs-back-vintage-
cellars.md`). Jeroboams' own product catalogue carries real single-bottle
In Bond listings for exactly the kind of older, already-drinking stock
this cellar holds — confirmed again on several more producers in the
fixture. This is the reason the adapter was worth building at all, not an
incidental case among many.

## A real float-noise trap, the same shape as Farr's, caught centrally — not here

Confirmed live: a duty-paid listing's own flat price is sometimes
`204.999996` or `45.948001` — float noise, not a price anyone printed.
This adapter does not special-case it: `app.worker.jobs`'s own ingest path
already calls `whole_pence()` on every adapter's output and refuses
`NOT_WHOLE_PENCE` centrally (same as it already does for Farr's float32
noise) — the Decimal is passed through unchanged here, exactly as it
arrived.

## Name order is not reliable either way — same lesson as Justerini & Brooks

`name` sometimes leads with the producer ("2012 Henri Giraud, Argonne
Rose") and sometimes with the cuvée ("2002 Vintage Brut, Champagne Krug";
"N.V. Grande Cuvee 173eme Edition, Champagne Krug") — confirmed live
across producers in the fixture, no pattern reliable enough to assume
either way. `parse_cuvee()` checks BOTH comma segments against the
product's own clean `producer` field (from `item_attribute`, never
guessed) and keeps whichever one does not match; if neither matches, the
whole string is kept rather than an invented split.

## An assortment case is a real, named mixed lot — not an inferred one

`ib-2008-krug-soloist-orchestra-assortment-case-...` bundles several
distinct Krug single-vineyard cuvées under one SKU; nothing in the data
(`mixed_products`, `case_only` — both null on every record checked, this
one included) flags it structurally. The name itself does: the same
`mixed`/`assort(ment)` regex `lw_trading.py` already uses for exactly this
reason catches it here too.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from app.identity.resolver import norm_producer, split_release_code
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://jeroboams.co.uk"

_CHAMPAGNE_PREFIX_RE = re.compile(r"^Champagne\s+", re.IGNORECASE)
_VOLUME_RE = re.compile(r"^([\d.]+)\s*cl$", re.IGNORECASE)
_CASE_SIZE_RE = re.compile(r"^(\d+)\s*x\b", re.IGNORECASE)
_VINTAGE_TOKEN_RE = re.compile(r"^(\d{4}|N\.?V\.?)\b", re.IGNORECASE)
_IN_BOND_SKU_RE = re.compile(r"^\d+IB(-.*)?$")
#: Same pattern lw_trading.py already uses for exactly this reason — an
#: assortment of several distinct cuvées under one SKU, confirmed live on
#: "2008 Krug Soloist Orchestra Assortment Case".
_MIXED = re.compile(r"\bmixed\b|\bassort(?:ment|ed)?s?\b", re.I)


def extract_product(html: str) -> Optional[dict]:  # pragma: no cover - thin DOM shim
    """{"product": initialProduct, "items": initialUniqueItems} from the
    page's own `__NEXT_DATA__`, or None if the page carries no product at
    all (e.g. a 404 rendered as 200, never seen live but not assumed away).
    """
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    page_props = ((data.get("props") or {}).get("pageProps")) or {}
    product = page_props.get("initialProduct")
    if product is None:
        return None
    return {"product": product, "items": page_props.get("initialUniqueItems") or []}


def parse_bottle_volume(label: Optional[str]) -> Optional[int]:
    """"75 cl" -> 750. None if unreadable."""
    match = _VOLUME_RE.match((label or "").strip())
    if not match:
        return None
    ml = round(float(match.group(1)) * 10)
    return ml if ml > 0 else None


def parse_case_size(label: Optional[str]) -> Optional[int]:
    """"6 x Bottle" -> 6. "1 x Bottle" -> 1. None if unreadable (the "-MAIN"
    placeholder's own case_size label is always null, and lands here)."""
    match = _CASE_SIZE_RE.match((label or "").strip())
    return int(match.group(1)) if match else None


def parse_vintage_label(label) -> Optional[int]:
    """"N.V." -> 1000. "2012" -> 2012. None if unreadable."""
    if label is None:
        return None
    text = str(label).strip()
    if text.upper().replace(".", "") == "NV":
        return 1000
    return int(text) if text.isdigit() and len(text) == 4 else None


def producer_and_vintage_label(product: dict) -> tuple[str, Optional[str]]:
    """The product's own clean fields, read with a fallback for the plain
    duty-paid shape, which carries no `item_attribute` list at all and an
    opaque `vintage` option code rather than a label — `name`'s own leading
    token is the only vintage signal left in that shape."""
    attrs = {a.get("attribute_code"): a.get("option_label")
            for a in (product.get("item_attribute") or [])}
    producer = attrs.get("producer") or product.get("producer") or ""
    vintage_label = attrs.get("vintage")
    if vintage_label is None:
        match = _VINTAGE_TOKEN_RE.match(product.get("name") or "")
        vintage_label = match.group(1) if match else None
    return producer, vintage_label


def parse_cuvee(name: str, producer: str) -> tuple[str, Optional[str]]:
    """`name` is NOT reliably producer-first or cuvée-first — confirmed live,
    see the module docstring. Both comma segments are checked against the
    product's own clean producer field; whichever one matches is stripped,
    and the other becomes the cuvée. Neither matching keeps the string
    whole rather than inventing a split.
    """
    text = name or ""
    match = _VINTAGE_TOKEN_RE.match(text)
    if match:
        # Slice past the matched token rather than `.sub()` with `\b`: "N.V."
        # backtracks to match "N.V" (the trailing period breaks the word
        # boundary), leaving a stray ". " that `.sub()` would never remove.
        text = text[match.end():].lstrip(". ").lstrip()
    producer_bare = _CHAMPAGNE_PREFIX_RE.sub("", producer or "").strip()
    head, comma, rest = text.partition(",")
    head_bare = _CHAMPAGNE_PREFIX_RE.sub("", head.strip())
    rest_bare = _CHAMPAGNE_PREFIX_RE.sub("", rest.strip())
    if comma and norm_producer(head_bare) == norm_producer(producer_bare):
        cuvee = rest.strip()
    elif comma and norm_producer(rest_bare) == norm_producer(producer_bare):
        cuvee = head.strip()
    else:
        cuvee = text.strip()
    cuvee, release_code = split_release_code(cuvee)
    return cuvee.rstrip(", ").strip(), release_code


class JeroboamsAdapter(Adapter):
    id = "jeroboams"
    merchant = "Jeroboams"

    def fetch(self, product_paths: Sequence[str], *, client=None) -> Sequence[dict]:
        """One or more product URL slugs (e.g.
        "ib-2012-henri-giraud-argonne-rose-..."), read from the merchant's own
        `product-sitemap*.xml` and chosen ahead of time, never guessed
        (decision 0011) — Jeroboams publishes no per-producer search
        endpoint, only a static sitemap naming every product, so the
        producer-to-path resolution happens once, outside this adapter, the
        same way Justerini & Brooks' family paths are resolved outside
        theirs.

        Each raw record returned is one flattened `initialUniqueItems` entry
        carrying its parent product's own `name`, resolved `producer` and
        vintage label, and `url_key` alongside it.
        """
        if not product_paths:
            raise ValueError("at least one product path is required")
        owns_client = client is None
        if owns_client:  # pragma: no cover - network
            import httpx
            client = httpx.Client(timeout=30, follow_redirects=True,
                                  headers={"User-Agent": user_agent()})
        try:
            out: list[dict] = []
            for path in product_paths:
                r = client.get(f"{BASE}/product/{path}")
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                parsed = extract_product(r.text)
                if parsed is None:
                    continue
                product = parsed["product"]
                producer, vintage_label = producer_and_vintage_label(product)
                context = {
                    "name": product.get("name"),
                    "producer": producer,
                    "vintage_label": vintage_label,
                    "url_key": product.get("url_key"),
                }
                for item in parsed["items"]:
                    out.append({**context, **item})
            return out
        finally:
            if owns_client:  # pragma: no cover - network
                client.close()

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        name = raw.get("name") or ""
        producer = raw.get("producer") or ""
        if not name or not producer:
            return Rejected(raw, Reject.ROW_UNREADABLE, "missing name/producer")

        if _MIXED.search(name):
            return Rejected(raw, Reject.MIXED_LOT, name)

        vintage = parse_vintage_label(raw.get("vintage_label"))
        if vintage is None:
            return Rejected(raw, Reject.VINTAGE, f"unreadable vintage {raw.get('vintage_label')!r}")

        case_label = (raw.get("case_size") or {}).get("data", {}).get("label")
        pack_size = parse_case_size(case_label)
        if pack_size is None:
            return Rejected(raw, Reject.SIZE, f"unreadable case_size {case_label!r}")

        volume_label = (raw.get("volume") or {}).get("data", {}).get("label")
        bottle_ml = parse_bottle_volume(volume_label)
        if bottle_ml is None:
            return Rejected(raw, Reject.SIZE, f"unreadable volume {volume_label!r}")

        price_raw = (raw.get("price") or {}).get("amount", {}).get("value")
        if price_raw is None or price_raw <= 0:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"price {price_raw!r}")

        sku = raw.get("sku") or ""
        duty = DutyStatus.IN_BOND if _IN_BOND_SKU_RE.match(sku) else DutyStatus.DUTY_PAID

        producer_text = _CHAMPAGNE_PREFIX_RE.sub("", producer).strip()
        cuvee_text, release_code = parse_cuvee(name, producer)

        qty = raw.get("qty")
        offer = Offer(
            offer_id=f"jeroboams:{sku}",
            merchant_id=self.id, merchant=self.merchant,
            wine_id="", vintage=vintage, bottle_ml=bottle_ml, pack_size=pack_size,
            price=Decimal(str(price_raw)), currency="GBP",
            duty_status=duty, price_kind=PriceKind.ASK,
            is_buyable=bool(qty and qty > 0), offered_units=qty,
            stock_type=StockType.MERCHANT_STOCK, stock_type_basis="declared",
            condition_flags=frozenset(), condition_notes=None,
            source_url=(f"{BASE}/product/{raw['url_key']}") if raw.get("url_key") else None,
            captured_at=captured_at or datetime.now(timezone.utc),
            raw=raw,
        )
        return Candidate(offer=offer, producer_text=producer_text, cuvee_text=cuvee_text,
                         release_code=release_code)
