"""Goedhuis Waddesdon — Shopify products.json.

Endpoint: https://goedhuiswaddesdon.com/products.json?limit=250&page=N
robots.txt disallows /search; /products.json and collection pages are allowed.
The "Checkouts are for humans" banner is Shopify boilerplate about agentic
CHECKOUT, not about reading the catalogue. We never transact.

The SKU is the contract, and it is the trap.

    09A6CCBR1PK-IB-InBond-ExcVAT      £2,350.00   available: false
    09A6CCBR1PK-DP-InBond-ExcVAT      £2,353.10   available: true
    09B8NGMMU6PK-IB-BR-675-InBond-ExcVAT          available: true

Both of the first two contain the string "InBond". Only the first is an In Bond
price. Read positionally:

    <product code> - <IB|DP> [ - BR - <broker price> ] - <InBond|Retail> - <IncVAT|ExcVAT>

  * segment 2 is the DUTY STATUS OF THE STOCK
  * an optional BR segment marks BROKING and carries the broker's ask
  * the trailing pair is the PRICE PRESENTATION

The only variant that is an eligible In Bond ex-VAT ask is
`IB [+BR] + InBond + ExcVAT`. Everything else is rejected, including
`IB-Retail-IncVAT`, which is the same stock quoted a different way.

Sold-out variants are published at 0.00. A truthiness check turns that into a
floor of zero, so non-positive prices are rejected explicitly.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from .base import Adapter, Candidate, Rejected
from .condition import normalise_condition

PRODUCTS_URL = "https://goedhuiswaddesdon.com/products.json"

_SKU = re.compile(
    r"-(?P<duty>IB|DP)"
    r"(?:-BR-(?P<broker>\d+(?:\.\d+)?))?"
    r"-(?P<basis>InBond|Retail)"
    r"-(?P<vat>IncVAT|ExcVAT)$",
    re.I,
)

# "09A6CCBR1PK _ 2006 - Chambertin Clos de Beze Grand Cru Armand Rousseau - 1x75cl"
_TITLE = re.compile(
    r"^\s*(?P<code>\S+)\s*_\s*(?P<vintage>\d{4}|NV)\s*-\s*(?P<wine>.+?)\s*-\s*"
    r"(?P<pack>\d+)\s*x\s*(?P<size>\d+)(?P<unit>cl|ml)\s*$",
    re.I,
)

_MIXED = re.compile(r"\bmixed\b|\bassorted\b|\bcase\s+of\s+mixed\b", re.I)


class SkuParts(dict):
    pass


def parse_sku(sku: str) -> dict | None:
    m = _SKU.search(sku or "")
    if not m:
        return None
    d = m.groupdict()
    return {
        "duty": d["duty"].upper(),
        "broker_price": Decimal(d["broker"]) if d["broker"] else None,
        "basis": d["basis"],
        "vat": d["vat"],
    }


def is_eligible_variant(parts: dict) -> bool:
    """The In Bond, ex-VAT ask. Broking is allowed (spec section 8)."""
    return (
        parts["duty"] == "IB"
        and parts["basis"].lower() == "inbond"
        and parts["vat"].lower() == "excvat"
    )


def parse_title(title: str) -> dict | None:
    m = _TITLE.match(title or "")
    if not m:
        return None
    ml = int(m.group("size")) * (10 if m.group("unit").lower() == "cl" else 1)
    return {
        "code": m.group("code"),
        "vintage": 1000 if m.group("vintage").upper() == "NV" else int(m.group("vintage")),
        "wine": m.group("wine").strip(),
        "pack": int(m.group("pack")),
        "bottle_ml": ml,
    }


class GoedhuisAdapter(Adapter):
    id = "goedhuis"
    merchant = "Goedhuis Waddesdon"

    def fetch(self) -> Sequence[dict]:  # pragma: no cover - network
        import httpx, time
        out, page = [], 1
        while page <= 40:
            r = httpx.get(PRODUCTS_URL, params={"limit": 250, "page": page},
                          timeout=60, headers={"User-Agent": "UKFineWinePricer/1.0"})
            r.raise_for_status()
            products = r.json().get("products", [])
            if not products:
                break
            out.extend(products)
            page += 1
            time.sleep(0.5)
        return out

    def normalise(self, raw: dict, captured_at: datetime | None = None):
        """One Shopify product yields at most ONE eligible offer (its IB ex-VAT ask)."""
        title = raw.get("title") or ""
        if _MIXED.search(title):
            return Rejected(raw, Reject.MIXED_LOT, title)

        t = parse_title(title)
        if t is None:
            return Rejected(raw, Reject.UNRESOLVED_IDENTITY, f"unparseable title {title!r}")

        for v in raw.get("variants", []):
            parts = parse_sku(v.get("sku") or "")
            if not parts or not is_eligible_variant(parts):
                continue
            price = Decimal(str(v.get("price") or "0"))
            if price <= 0:
                # sold-out placeholder; keep looking, do not emit a zero floor
                continue

            brokered = parts["broker_price"] is not None
            return Candidate(
                offer=Offer(
                    offer_id=f"goedhuis:{v.get('sku')}",
                    merchant_id=self.id,
                    merchant=self.merchant,
                    wine_id="",
                    vintage=t["vintage"],
                    bottle_ml=t["bottle_ml"],
                    pack_size=t["pack"],
                    price=price,
                    currency="GBP",
                    duty_status=DutyStatus.IN_BOND,
                    price_kind=PriceKind.ASK,
                    is_buyable=bool(v.get("available")),
                    offered_units=None,          # Shopify does not publish a count here
                    stock_type=StockType.BROKERED if brokered else StockType.MERCHANT_STOCK,
                    stock_type_basis="declared",  # the SKU states it
                    condition_flags=normalise_condition(t["wine"]),
                    condition_notes=t["wine"] if "Non OC" in t["wine"] else None,
                    source_url=f"https://goedhuiswaddesdon.com/products/{raw.get('handle')}",
                    captured_at=captured_at or datetime.now(timezone.utc),
                    raw={"product": {k: raw.get(k) for k in ("id", "handle", "title", "vendor")},
                         "variant": v},
                ),
                producer_text="",              # Goedhuis packs producer into the wine string
                cuvee_text=t["wine"],
            )

        return Rejected(raw, Reject.NOT_BUYABLE, "no In Bond ex-VAT variant with a positive price")
