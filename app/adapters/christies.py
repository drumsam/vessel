"""Christie's — auction results. Decision 0042: of the five houses asked
for, reconnaissance found this one, Sotheby's and iDealwine's shop
genuinely reachable with a plain, honestly identified HTTP client; Heritage
and Zachys are both actively defended against exactly that and were
dropped, not built (see the decision).

Investigated live 26 October 2026. robots.txt (www.christies.com)
disallows the search UI itself (`/search`, `/searchresults.aspx`) but not
`/en/lot/lot-{id}` — individual lot pages are not named at all. Christie's
separate "online-only" platform (`onlineonly.christies.com.cn`)
intermittently returned the same DataDome challenge Heritage returns on
every request, confirmed live on a repeat fetch of the SAME already-
fetched URL — this adapter reads `/en/lot/` only and never touches the
online-only platform.

## Server-rendered Sitecore/Angular, with the lot's own record inline, twice over

A lot page embeds TWO different `"lots":[...]` JSON arrays in its own
markup: one carrying only the page's own lot (full detail — title, size,
estimate, `price_realised`), and a second, much longer one listing OTHER
lots in the same sale for a "browse the rest of this auction" sidebar
widget (confirmed live: 10 further object_ids on this exact fixture, each
with only a price and an image caption, no size or clean title field at
all). The page's own `<link rel="canonical">` is the one reliable way to
tell which `object_id` is actually this page's lot — picking "the first
`lots` array found" would have worked by luck on this fixture and nothing
else, since ordering between the two widgets is not a documented contract.

## Lot size is read from the literal unit Christie's already states — no abbreviation table needed

Unlike Sotheby's own closed vocabulary of format abbreviations (BT/MAG/
DM/IMP), Christie's spells the unit out: `title_tertiary_txt` reads
"1 x 18L bottle per lot" on this fixture's real lot (an 18-LITRE bottle —
an extraordinary single-bottle format, confirmed live, not assumed to be
a typo and silently "corrected"; this adapter parses the unit exactly as
published, same discipline as every other adapter's refusal to improve on
what a merchant actually printed). ML/CL/L are all read as stated,
generically — there is nothing here to maintain as new formats appear,
unlike Sotheby's.

## duty_status is UNKNOWN, always — collecting the price is the point, not the bond/duty split

Christie's own lot pages sometimes carry a footnote ("‡ Offered in bond,
available duty paid") naming a specific lot as bond-eligible — confirmed
live on this exact fixture. Simplified deliberately, on Doug's own
instruction ("not worry about a few pennies either way"): this adapter
does not parse for it. Every result is `DutyStatus.UNKNOWN`, same as
Sotheby's and iDealwine. The locked core still decides what that means
for pricing (invariant 5) — this adapter's only job is bringing the price
in.

## price_realised's own type is inconsistent across the two widgets on the same page, deliberately tolerated

The page's own lot widget carries `"price_realised":13475.0` (a JSON
number); the sidebar's OTHER lots on the same page carry
`"price_realised":"918"` (a JSON string) — confirmed live, both on this
one fixture. `Decimal(str(value))` reads either shape the same way; this
adapter only ever reads the first shape (the page's own lot), but is
written to tolerate the second regardless, since nothing here should
depend on a JSON-typing convention a site is not contractually keeping
even within one response.

## No live search — lot paths are supplied, never discovered here

`/search` and `/searchresults.aspx` are disallowed by robots.txt (see
above), and no sitemap-based static index was confirmed the way
Jeroboams' own `product-sitemap*.xml` was. Decision 0011's rule applies
again: search keys come from the merchant's own index, never guessed —
here there is no usable index at all with a plain HTTP client, so
`fetch()` takes already-known lot paths.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .http import user_agent

BASE = "https://www.christies.com"

_CANONICAL_RE = re.compile(r'<link rel="canonical" href="[^"]*?/lot/lot-(\d+)"')
_LOTS_KEY_RE = re.compile(r'"lots":\[')
_SALE_KEY_RE = re.compile(r'"sale":\s*\{')
_LABELS_KEY_RE = re.compile(r'"labels":\s*\{')

#: "1 x 18L bottle per lot", "6 x 75CL bottle per lot" -- the unit Christie's
#: actually prints, read generically rather than from an abbreviation table.
_SIZE_RE = re.compile(r"^\s*(?P<count>\d+)\s*x\s*(?P<size>[\d.]+)\s*(?P<unit>ML|CL|L)\b",
                     re.IGNORECASE)
_UNIT_ML = {"ML": 1, "CL": 10, "L": 1000}

_VINTAGE_TOKEN_RE = re.compile(r"\b(\d{4}|N\.?V\.?)\b")


def parse_lot_size(text: str) -> Optional[tuple[int, int]]:
    """(pack_size, bottle_ml) from "title_tertiary_txt", e.g. "1 x 18L
    bottle per lot" -> (1, 18000). The unit is read exactly as printed,
    not from a fixed vocabulary — see the module docstring."""
    match = _SIZE_RE.match(text or "")
    if not match:
        return None
    count = int(match.group("count"))
    ml = round(float(match.group("size")) * _UNIT_ML[match.group("unit").upper()])
    return (count, ml) if count > 0 and ml > 0 else None


def parse_vintage_and_name(title: str) -> tuple[Optional[int], str]:
    """The vintage token and everything else. "Château Cheval-Blanc 2003"
    -> (2003, "Château Cheval-Blanc"). None when no 4-digit year or NV
    token is found — never guessed."""
    text = (title or "").strip()
    matches = list(_VINTAGE_TOKEN_RE.finditer(text))
    if not matches:
        return None, text
    token = matches[-1]
    raw = token.group(1)
    vintage = 1000 if raw.upper().replace(".", "") == "NV" else int(raw)
    name = (text[:token.start()] + text[token.end():]).strip()
    return vintage, re.sub(r"\s{2,}", " ", name).strip(", ").strip()


def split_producer_cuvee(name: str) -> tuple[str, str]:
    """First comma separates producer from cuvée, producer-first, same
    convention as every other adapter here. Identity resolution's own
    closed-registry match is the backstop where this convention is wrong."""
    head, comma, rest = name.partition(",")
    return (name.strip(), "") if not comma else (head.strip(), rest.strip())


def _iter_lot_entries(html: str):
    decoder = json.JSONDecoder()
    for m in _LOTS_KEY_RE.finditer(html):
        try:
            value, _ = decoder.raw_decode(html, m.end() - 1)
        except ValueError:
            continue
        yield from value


def extract_lot(html: str) -> Optional[dict]:  # pragma: no cover - thin DOM shim
    """{"lot": {...}, "sale": {...}, "currency": str | None}, or None.

    The page's own `<link rel="canonical">` names which `object_id` is
    actually this page's lot — this platform embeds a SECOND `"lots":[...]`
    array for a "rest of this sale" sidebar widget, confirmed live to
    carry other lots entirely, so scanning for "any lots array" or taking
    "the first one" is not reliable (see the module docstring). Currency
    is not on the lot record at all — confirmed live, it is a sibling
    `"labels":{"currency_txt": ...}` object, read separately."""
    canon = _CANONICAL_RE.search(html)
    if not canon:
        return None
    object_id = canon.group(1)
    lot = next((entry for entry in _iter_lot_entries(html)
               if entry.get("object_id") == object_id), None)
    if lot is None:
        return None
    decoder = json.JSONDecoder()

    def _first(pattern: re.Pattern, *, having: str = "") -> dict:
        """The first JSON object this pattern finds — and, when `having` is
        given, the first one that actually carries that key. The page
        carries more than one same-named object (confirmed live: an
        unrelated, much smaller `"labels":{...}` sits in `window.chrGlobal`
        before the one with `currency_txt`), so a bare "first match" is not
        reliable the way it is for `"sale":{...}`, which only ever appears
        once."""
        for match in pattern.finditer(html):
            try:
                value, _ = decoder.raw_decode(html, match.end() - 1)
            except ValueError:
                continue
            if not having or having in value:
                return value
        return {}

    return {"lot": lot, "sale": _first(_SALE_KEY_RE),
            "currency": _first(_LABELS_KEY_RE, having="currency_txt").get("currency_txt")}


def _parse_iso(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


class ChristiesAdapter(Adapter):
    id = "christies"
    merchant = "Christie's"

    def fetch(self, lot_paths: Sequence[str], *, client=None) -> Sequence[dict]:
        """One or more lot URL paths, e.g. "en/lot/lot-6324831" — resolved
        by the caller, never searched here (see the module docstring)."""
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
        sale = raw.get("sale") or {}
        object_id = lot.get("object_id") or ""
        title = lot.get("title_primary_txt") or ""
        if not title or not object_id:
            return Rejected(raw, Reject.ROW_UNREADABLE, "missing title/object_id")

        if lot.get("is_unsold"):
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"lot {object_id}: unsold")

        vintage, name = parse_vintage_and_name(title)
        if vintage is None:
            return Rejected(raw, Reject.VINTAGE, f"unreadable vintage in {title!r}")

        size = parse_lot_size(lot.get("title_tertiary_txt") or "")
        if size is None:
            return Rejected(raw, Reject.SIZE,
                            f"unreadable lot size {lot.get('title_tertiary_txt')!r}")
        pack_size, bottle_ml = size

        amount = lot.get("price_realised")
        if amount in (None, ""):
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"lot {object_id}: no price realised")
        price = Decimal(str(amount))
        if price <= 0:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"lot {object_id}: price {amount!r}")

        currency = raw.get("currency")
        if not currency:
            return Rejected(raw, Reject.CURRENCY, f"lot {object_id}: no currency found")

        when = _parse_iso(sale.get("start_date")) or captured_at or datetime.now(timezone.utc)

        producer_text, cuvee_text = split_producer_cuvee(name)

        offer = Offer(
            offer_id=f"christies:{object_id}",
            merchant_id=self.id, merchant=self.merchant,
            wine_id="", vintage=vintage, bottle_ml=bottle_ml, pack_size=pack_size,
            price=price, currency=currency,
            duty_status=DutyStatus.UNKNOWN, price_kind=PriceKind.LAST_TRADE,
            is_buyable=False, offered_units=None,
            stock_type=StockType.UNKNOWN, stock_type_basis="unknown",
            condition_flags=frozenset(), condition_notes=None,
            source_url=lot.get("url") or f"{BASE}/en/lot/lot-{object_id}",
            captured_at=when,
            raw=raw,
        )
        return Candidate(offer=offer, producer_text=producer_text, cuvee_text=cuvee_text)
