"""Sotheby's — auction results. Decision 0042: of the five houses Doug asked
for, reconnaissance found three genuinely reachable with a plain, honestly
identified HTTP client (this one, Christie's, iDealwine's shop) and two
actively defended against exactly that with a deployed bot-detection
challenge (Heritage, Zachys) — dropped, not built, see the decision.

Investigated live 26 October 2026. robots.txt (www.sothebys.com) disallows
only PDF exports, a style guide, `/bsp-api/*` and a docs folder — no lot,
search or buy page is named. No scraping/automated-access clause was found
in the site's privacy policy or its "Conditions of Business for Buyers"
PDF; no distinct general "terms of use" page could be located at all.

## Server-rendered Next.js, with the record in Apollo's own normalised cache

A lot page's `<script id="__NEXT_DATA__">` carries
`props.pageProps.apolloCache`: a flat `{"Typename:id": {...}}` dict with
`__ref` pointers in place of nesting, not the rendered page a person reads.
The one lot a page is actually about is found generically, never by
filtering the cache for the right typename (several unrelated `LotV2`-
shaped entries can be reachable from `previousLot`/`nextLot` links on the
same page) — `ROOT_QUERY`'s own `lotV2({...})` key carries the one real
`__ref`.

## price_realised is the settled figure; JSON-LD's own `offers.price` is not

The page ALSO carries a schema.org JSON-LD block, and on this exact fixture
its `offers.price` reads "1800.00" — `current_bid`, the last bid BEFORE the
lot closed, not what it actually sold for. The real settled figure lives
only in the Apollo cache, under `BidState.sold.premiums.finalPriceV2.amount`
("3250" on the same lot). This adapter reads the Apollo cache exclusively
and never touches JSON-LD, for exactly this reason — confirmed live, not
assumed from the field's name.

## Lot size is read from a closed, confirmed vocabulary, never guessed

Every title ends in a parenthetical lot-size token, e.g. "Krug 1985  (4 BT)"
— confirmed across 570 distinct titles in one auction's own fixture: `BT`
(bottle, 750ml), `MAG` (magnum, 1500ml), `DM` (demi, 375ml), `IMP`
(imperial, 6000ml). Two tokens seen and deliberately NOT mapped: `HB` (one
single 1811 Cognac lot — ambiguous against `DM`'s own "half" meaning, and
this cellar trades wine) and `JM50` (five Bordeaux lots, "1 JM50" each — an
unconfirmed large format). Both reject on SIZE rather than guess a
millilitre figure nobody confirmed. A parenthetical naming more than one
format at once ("4 BT, 1 MAG", confirmed live on a 1996 Château Haut
Marbuzet lot) is a mixed lot.

## No clean producer/cuvee split — Sotheby's titles carry no separate producer field at all

Unlike Jeroboams or Justerini & Brooks, nothing in the Apollo cache names
the producer separately from the free-text `title`, so there is no clean
field to cross-check a comma split against. Most of this cellar's actual
interest (Champagne, Bordeaux, Burgundy négociants) has no comma at all —
"Krug 1985", "Petrus 1981" — and the whole pre-vintage string is the
producer with an empty cuvée, which `resolve_candidate` already handles.
Where a comma IS present ("Laurent Perrier, Cuvée Grand Siecle NV") it is
read producer-first, same convention as every other adapter in this fleet
— confirmed right for this cellar's own shape of wine, confirmed WRONG for
at least one Italian lot ("Brunello di Montalcino, Tenuta Nuova 2004
Casanova Di Neri", producer trailing at the very end). Not special-cased:
identity resolution's own closed-registry match is the real safety net
here, the same way it is for every adapter's raw text — a garbled
producer string fails to resolve rather than silently matching the wrong
wine, and lands in NAME_REVIEW for a person, never a wrong price.

## Vintage must be a real year or NV — "MV" is neither and is refused

Vega Sicilia 'Unico' Reserva Especial is a genuine multi-vintage blend,
printed as "... MV  (4 BT)" — confirmed live. `MV` is not a 4-digit year
and not `NV`; treating it as either would be a guess this adapter refuses
to make, so it rejects on VINTAGE instead.

## duty_status is UNKNOWN, honestly, which mostly ends in a DUTY rejection

Nothing in a lot's own data states whether it was sold in bond — and this
fixture's own sale was held in Paris, priced in EUR, which is not even a
UK sale to begin with. `_is_last_trade` (the locked core) requires
`DutyStatus.IN_BOND` before a settled price counts as corroboration at
all (decision 0026), and that is correct, not a gap to work around: a
French sale's hammer price reflects French tax treatment, not the UK
In Bond market this whole benchmark is scoped to. Most Sotheby's results
will therefore land as a plain, retained DUTY rejection — visible to an
operator in the line's own rejected-comps table, never surfaced as
corroboration — until a future lot is found whose own listing states an
In Bond status explicitly. Nothing here guesses one to make the number
more useful.

## No live search — lot paths are supplied, never discovered here

Sotheby's cross-sale producer search is Algolia-backed and client-side; a
plain `?pfilters.dateRange=past` query string on `/en/search` was
confirmed, live, to be ignored by the server (it 307-redirects back to
`dateRange=upcoming`). Decision 0011's own rule applies again: search keys
come from the merchant's own index, never guessed — here, there is no
usable index to search at all with a plain HTTP client, so `fetch()` takes
already-known lot paths, same shape as Jeroboams' `product_paths`.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://www.sothebys.com"

#: Confirmed live across 570 distinct lot titles in one auction (26 October
#: 2026) — see the module docstring for the two tokens seen and deliberately
#: left out (HB, JM50).
_FORMAT_ML = {"BT": 750, "MAG": 1500, "DM": 375, "IMP": 6000}

_LOT_SIZE_RE = re.compile(r"\((?P<body>[^()]+)\)\s*$")
_VINTAGE_TOKEN_RE = re.compile(r"\b(\d{4}|N\.?V\.?)\b")


def is_mixed_format(title: str) -> bool:
    """"Château Haut Marbuzet 1996  (4 BT, 1 MAG)" — more than one format
    named for a single lot. Confirmed live."""
    match = _LOT_SIZE_RE.search(title or "")
    return bool(match and "," in match.group("body"))


def parse_lot_size(title: str) -> Optional[tuple[int, int]]:
    """(pack_size, bottle_ml) from the title's own trailing parenthetical.
    None if unreadable, mixed (caller checks `is_mixed_format` first), or
    naming a format outside the confirmed vocabulary."""
    match = _LOT_SIZE_RE.search(title or "")
    if not match or "," in match.group("body"):
        return None
    piece = re.match(r"(\d+)\s*([A-Za-z]+)$", match.group("body").strip())
    if not piece:
        return None
    ml = _FORMAT_ML.get(piece.group(2).upper())
    return None if ml is None else (int(piece.group(1)), ml)


def parse_vintage_and_name(title: str) -> tuple[Optional[int], str]:
    """The vintage token and everything else. "Krug 1985  (4 BT)" ->
    (1985, "Krug"). "Krug Grande Cuvée NV  (1 BT)" -> (1000, "Krug Grande
    Cuvée"). Vintage is None when the title's own token is neither a
    4-digit year nor NV (e.g. "MV" — a real but different thing, see the
    module docstring) — never guessed at as either."""
    body = _LOT_SIZE_RE.sub("", title or "").strip()
    matches = list(_VINTAGE_TOKEN_RE.finditer(body))
    if not matches:
        return None, body
    token = matches[-1]
    text = token.group(1)
    vintage = 1000 if text.upper().replace(".", "") == "NV" else int(text)
    name = (body[:token.start()] + body[token.end():]).strip()
    name = re.sub(r"\s{2,}", " ", name).strip(", ").strip()
    return vintage, name


def split_producer_cuvee(name: str) -> tuple[str, str]:
    """First comma separates producer from cuvée, producer-first — same
    convention as every other adapter here. See the module docstring for
    where this is confirmed right and where it is confirmed wrong; identity
    resolution's own closed-registry match is the backstop either way."""
    head, comma, rest = name.partition(",")
    return (name.strip(), "") if not comma else (head.strip(), rest.strip())


def _deref(cache: dict, value) -> Optional[dict]:
    if isinstance(value, dict) and "__ref" in value:
        return cache.get(value["__ref"])
    return value if isinstance(value, dict) else None


def extract_lot(html: str) -> Optional[dict]:  # pragma: no cover - thin DOM shim
    """{"lot": LotV2, "auction": Auction, "bid_state": BidState}, or None if
    the page carries no lot at all. The ONE real lot is found via
    `ROOT_QUERY`'s own `lotV2({...})` key, never by scanning the cache for
    any `LotV2`-shaped entry — `previousLot`/`nextLot` links on the same
    page can make more than one reachable."""
    import json
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    cache = ((data.get("props") or {}).get("pageProps") or {}).get("apolloCache") or {}
    root = cache.get("ROOT_QUERY") or {}
    lot_key = next((k for k in root if k.startswith("lotV2(")), None)
    lot = _deref(cache, root.get(lot_key)) if lot_key else None
    if lot is None:
        return None
    return {"lot": lot, "auction": _deref(cache, lot.get("auction")) or {},
            "bid_state": _deref(cache, lot.get("bidState")) or {}}


def _parse_iso(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


class SothebysAdapter(Adapter):
    id = "sothebys"
    merchant = "Sotheby's"

    def fetch(self, lot_paths: Sequence[str], *, client=None) -> Sequence[dict]:
        """One or more lot URL paths, e.g.
        "en/buy/auction/2024/finest-rarest-wines-2/krug-1985-4-bt" — resolved
        by the caller, never searched here (see the module docstring:
        Sotheby's own cross-sale search does not honour a plain query
        string, confirmed live)."""
        if not lot_paths:
            raise ValueError("at least one lot path is required")
        owns_client = client is None
        if owns_client:  # pragma: no cover - network
            import httpx
            client = httpx.Client(timeout=30, follow_redirects=True,
                                  headers={"User-Agent": user_agent()})
        try:
            out: list[dict] = []
            for path in lot_paths:
                r = client.get(f"{BASE}/{path.lstrip('/')}")
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                lot = extract_lot(r.text)
                if lot is not None:
                    out.append(lot)
            return out
        finally:
            if owns_client:  # pragma: no cover - network
                client.close()

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        lot = raw.get("lot") or {}
        auction = raw.get("auction") or {}
        bid_state = raw.get("bid_state") or {}
        title = lot.get("title") or ""
        lot_id = lot.get("lotId") or ""
        if not title or not lot_id:
            return Rejected(raw, Reject.ROW_UNREADABLE, "missing title/lotId")

        if is_mixed_format(title):
            return Rejected(raw, Reject.MIXED_LOT, title)

        vintage, name = parse_vintage_and_name(title)
        if vintage is None:
            return Rejected(raw, Reject.VINTAGE, f"unreadable vintage in {title!r}")

        size = parse_lot_size(title)
        if size is None:
            return Rejected(raw, Reject.SIZE, f"unreadable lot size in {title!r}")
        pack_size, bottle_ml = size

        sold = bid_state.get("sold") or {}
        if not sold.get("isSold"):
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"lot {lot_id}: not sold")
        amount = ((sold.get("premiums") or {}).get("finalPriceV2") or {}).get("amount")
        if amount is None:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE,
                            f"lot {lot_id}: sold with no settled price")
        price = Decimal(str(amount))
        if price <= 0:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"lot {lot_id}: price {amount!r}")

        currency = auction.get("currency") or auction.get("currencyV2")
        if not currency:
            return Rejected(raw, Reject.CURRENCY, f"lot {lot_id}: no currency on its auction")

        closed = (_parse_iso((auction.get("dates") or {}).get("closed"))
                 or _parse_iso(bid_state.get("closingTime")))
        if closed is None:
            return Rejected(raw, Reject.STALE, f"lot {lot_id}: no sale close date")

        producer_text, cuvee_text = split_producer_cuvee(name)
        slug = auction.get("slug") or {}
        year, sale_name, lot_slug = slug.get("year"), slug.get("name"), lot.get("slug")
        source_url = (f"{BASE}/en/buy/auction/{year}/{sale_name}/{lot_slug}"
                     if year and sale_name and lot_slug else None)

        offer = Offer(
            offer_id=f"sothebys:{lot_id}",
            merchant_id=self.id, merchant=self.merchant,
            wine_id="", vintage=vintage, bottle_ml=bottle_ml, pack_size=pack_size,
            price=price, currency=currency,
            # Not a guess made right: see the module docstring. Most results
            # land as a DUTY rejection, retained and visible, never a comp.
            duty_status=DutyStatus.UNKNOWN, price_kind=PriceKind.LAST_TRADE,
            is_buyable=False, offered_units=None,
            stock_type=StockType.UNKNOWN, stock_type_basis="unknown",
            condition_flags=frozenset(), condition_notes=None,
            source_url=source_url, captured_at=closed,
            raw=raw,
        )
        return Candidate(offer=offer, producer_text=producer_text, cuvee_text=cuvee_text)
