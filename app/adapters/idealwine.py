"""iDealwine — the direct shop only. Decision 0042: of the five houses
asked for, reconnaissance found this one (its shop side), Sotheby's and
Christie's genuinely reachable with a plain, honestly identified HTTP
client; Heritage and Zachys are both actively defended against exactly
that and were dropped (see the decision).

Investigated live 26 October 2026. robots.txt (www.idealwine.com)
disallows only `/api/*` (with a handful of accidental `Allow:` exceptions
for individually-deindexed URLs), `/p-a/`, `*/my_idealwine/` (the account
area) and `*/login?` — `/en/buy-wine` and `/en/buy-a-wine/...` are not
named. No scraping/automated-access clause was found in the general terms
("Conditions Générales"); its "Legal Notice" DOES separately and
explicitly claim French sui generis database rights over "current
estimations, historic estimations, wine notes and comments" by name —
exactly the licensed "estimate service" `auction-access-pack.md` already
named, and exactly what this adapter does NOT touch. iDealwine runs an
auction business and a direct fixed-price shop on the same site; this
adapter reads only the shop (`"auction": false` on every variant this
produces), confirmed public, confirmed free of that clause.

## Clean, separate, numeric fields — no size or vintage parsing at all

Unlike Sotheby's and Christie's, a product variant's own `__NEXT_DATA__`
record carries vintage (`productVintage.year`), bottle size
(`customVolume`), bottle count (`numberOfBottles`) and producer
(`product.owner`) as clean, separate, already-typed fields — confirmed
live. Nothing here is read out of a free-text title the way an auction
lot's own is; the only free text this module parses is `name` (e.g.
"Bourgogne Sylvain Pataille (Domaine) 2023"), and only to recover the
cuvée by subtracting the OWNER FIELD'S OWN TEXT and the vintage token from
it — the same subtract-the-known-piece idea Jeroboams and Berry Bros. &
Rudd both already use, applied here against a cleaner source than either
had.

## Currency is EUR, confirmed by what the page actually renders — not assumed from "priceByCountry"

`priceByCountry` carries a GB entry (2167, vs FR's 2600) that looks, at a
glance, like a GBP conversion. It is not: the country/tax-zone data on
the SAME response tags GB `taxZoneCategory: "EXPORT"` (ex-French-VAT) and
carries a SEPARATE UK customs-fee line (`apiShopCustomsFeeRatesGetCollection`,
20% + a flat per-bottle charge) — this is a TAX adjustment, not a currency
one, confirmed by fetching this exact page AS a GB-flagged request
(`requestCountryCode: "GB"` on the very same response) and finding the
rendered page still shows "€26", not "£21.67". This adapter reads the
plain `price` field (cents, EUR) and never `priceByCountry`, and emits
every offer as `currency="EUR"`.

## Consequence: this mostly lands as a retained rejection, not a comp, under the current invariants — and that is correct

duty_status is `UNKNOWN` on every offer this adapter produces — iDealwine
is a French retail shop with no "in bond"/bonded-warehouse concept to
read at all, never a guess made to look more useful — and the locked
core's own hard screen (invariant 5) requires both `DutyStatus.IN_BOND`
AND `currency == GBP` before an ASK counts as a priced comparable.
Neither will ever be true for a plain iDealwine shop listing, so a result
normalises to a real `Candidate` and is still retained, visible to an
operator in a line's own rejected-comps table (first on DUTY, which
`_screen` checks before CURRENCY) — never silently dropped, and never
forced to clear a screen it has not actually cleared.

## No live bulk crawl attempted here — product paths are supplied

`/en/buy-wine` is a real, paginated, server-rendered grid (confirmed
live: a plain GET returns every card's name, link and price with no
JavaScript) and could in principle be walked for bulk coverage. This
adapter does not do that: only a single product page's own
`__NEXT_DATA__` record was verified field-by-field, and building a
grid-card parser against an unverified shape would be exactly the kind of
guess this fleet refuses to make. `fetch()` takes already-known product
paths, same shape as Jeroboams' own `product_paths` — itself chosen for
the same reason, a merchant with no per-producer search endpoint.
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

BASE = "https://www.idealwine.com"

CENT = Decimal("0.01")


def cuvee_from_name(name: str, owner: str, vintage: Optional[int]) -> str:
    """"Bourgogne Sylvain Pataille (Domaine) 2023" minus the owner field's
    own text ("Sylvain Pataille (Domaine)") and the vintage token leaves
    "Bourgogne" — confirmed live. Subtracting a CONFIRMED field's own text
    rather than guessing a comma position, same idea Jeroboams and Berry
    Bros. & Rudd both already use."""
    text = (name or "").strip()
    if vintage is not None:
        text = re.sub(rf"\b{vintage}\b\s*$", "", text).strip()
    if owner:
        text = text.replace(owner, "").strip()
    return re.sub(r"\s{2,}", " ", text).strip()


def extract_product(html: str) -> Optional[dict]:  # pragma: no cover - thin DOM shim
    """The `syliusApiShopProductVariantGet` query's own `state.data` from
    the page's `__NEXT_DATA__` — a flat, already-typed record, not
    something this adapter has to assemble from several pieces the way
    Sotheby's and Christie's both do."""
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    queries = (((data.get("props") or {}).get("pageProps") or {})
              .get("dehydratedState") or {}).get("queries") or []
    for q in queries:
        key = q.get("queryKey") or []
        if key and key[0] == "syliusApiShopProductVariantGet":
            return (q.get("state") or {}).get("data")
    return None


class IdealwineAdapter(Adapter):
    id = "idealwine"
    merchant = "iDealwine"

    def fetch(self, product_paths: Sequence[str], *, client=None) -> Sequence[dict]:
        """One or more product URL paths, e.g.
        "en/buy-a-wine/2502373-1-bottle-Bourgogne-Sylvain-Pataille-Domaine-
        2023-Red" — resolved by the caller, never searched here (no
        per-producer search endpoint verified; see the module docstring)."""
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
                r = client.get(f"{BASE}/{path.lstrip('/')}")
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                product = extract_product(r.text)
                if product is not None:
                    out.append({**product, "_source_url": f"{BASE}/{path.lstrip('/')}"})
            return out
        finally:
            if owns_client:  # pragma: no cover - network
                client.close()

    def normalise(self, raw: dict, captured_at: datetime | None = None) -> Candidate | Rejected:
        if raw.get("auction"):
            return Rejected(raw, Reject.KIND, "auction lot, not a shop listing")

        variant_id = raw.get("id") or raw.get("code")
        product = raw.get("product") or {}
        owner = product.get("owner") or ""
        name = raw.get("name") or ""
        if not variant_id or not owner or not name:
            return Rejected(raw, Reject.ROW_UNREADABLE, "missing id/owner/name")

        vintage = (raw.get("productVintage") or {}).get("year")
        if not vintage:
            return Rejected(raw, Reject.VINTAGE, f"variant {variant_id}: no vintage year")

        bottle_ml = raw.get("customVolume") or raw.get("volume")
        pack_size = raw.get("numberOfBottles")
        if not bottle_ml or not pack_size:
            return Rejected(raw, Reject.SIZE,
                            f"variant {variant_id}: bottle_ml={bottle_ml!r} "
                            f"numberOfBottles={pack_size!r}")

        price_cents = raw.get("price")
        if price_cents is None or price_cents <= 0:
            return Rejected(raw, Reject.NON_POSITIVE_PRICE, f"variant {variant_id}: price {price_cents!r}")
        price = (Decimal(str(price_cents)) / 100).quantize(CENT)

        variation = (raw.get("variantVariations") or [{}])[0]
        available = variation.get("availableQuantity")
        if available is None:
            on_hand, on_hold = raw.get("onHand"), raw.get("onHold")
            available = (on_hand - on_hold) if on_hand is not None and on_hold is not None else None

        cuvee_text = cuvee_from_name(name, owner, vintage)

        offer = Offer(
            offer_id=f"idealwine:{variant_id}",
            merchant_id=self.id, merchant=self.merchant,
            wine_id="", vintage=int(vintage), bottle_ml=int(bottle_ml), pack_size=int(pack_size),
            price=price, currency="EUR",
            # Never IN_BOND: iDealwine is a French retail shop with no
            # bonded-warehouse concept to read, never a guess made to look
            # more useful. See the module docstring.
            duty_status=DutyStatus.UNKNOWN, price_kind=PriceKind.ASK,
            is_buyable=bool(raw.get("inStock")) and bool(available) and available > 0,
            offered_units=available,
            stock_type=StockType.MERCHANT_STOCK, stock_type_basis="declared",
            condition_flags=frozenset(), condition_notes=None,
            source_url=raw.get("_source_url"),
            captured_at=captured_at or datetime.now(timezone.utc),
            raw=raw,
        )
        return Candidate(offer=offer, producer_text=owner, cuvee_text=cuvee_text)
