"""MrBridge Wine-Searcher dataset → the generic market-evidence batch
(decision 0049). A pure format converter: it never calls the Actor, and it
passes on only what a row actually states. Whatever it does not state stays
unknown, and the unchanged importer and pricing core decide what that means.

What a row states, read from the real dataset (tests/fixtures/mrbridge/):
the cheapest current offer only — `cheapestPriceAmount` in
`cheapestPriceCurrency` from `cheapestPriceMerchant` — with `bottlesPerUnit`,
`offersCount`, `vintage` (null on a generic wine page), `wineName` and
`wineryName`. What it does not state: the bottle size, the duty status, and
any offer but the cheapest. The amount is normalised per 75cl bottle (2001
Leroy Clos de Vougeot: 3333.33 with bottlesPerUnit 6, i.e. a 6-bottle
listing ÷ 6), so a multi-bottle listing's own price cannot be restored
exactly and is never reconstructed here.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.identity.resolver import norm

SOURCE = "wine-searcher-via-mrbridge"

#: Words a Wine-Searcher name carries between the winery and the cuvée, or
#: after it, that are never part of a register cuvée. Stripped only at those
#: two edges, never from the middle of a name.
_LEADING_NOISE = (("pere", "et", "fils"), ("et", "fils"), ("freres",), ("pere", "fils"))
_TRAILING_NOISE = (("grand", "cru", "monopole"), ("grand", "cru"), ("monopole",))


def split_name(wine_name: str, winery: str, vintage: Optional[int]) -> tuple[str, str]:
    """(producer, cuvée) for the resolver. The producer is Wine-Searcher's own
    winery; the cuvée is the wine name without the vintage, the winery (or its
    trailing words: "Leroy" for "Domaine Leroy") and edge noise. Never empty
    of producer — the resolver's producer-less substring mode would let
    "...Chambertin Clos de Beze" match plain Chambertin."""
    tokens = norm(wine_name).split()
    if vintage is not None and tokens and tokens[0] == str(vintage):
        tokens = tokens[1:]
    w = norm(winery).split()
    for k in range(len(w)):
        suffix = w[k:]
        if suffix and tokens[:len(suffix)] == suffix:
            tokens = tokens[len(suffix):]
            break
    for lead in _LEADING_NOISE:
        if tuple(tokens[:len(lead)]) == lead:
            tokens = tokens[len(lead):]
            break
    for tail in _TRAILING_NOISE:
        if len(tokens) > len(tail) and tuple(tokens[-len(tail):]) == tail:
            tokens = tokens[:-len(tail)]
            break
    return winery, " ".join(tokens)


def _observation(row: dict) -> dict:
    vintage = row.get("vintage")
    producer, cuvee = split_name(row.get("wineName") or "", row.get("wineryName") or "", vintage)
    per_unit = row.get("bottlesPerUnit")
    amount = row.get("cheapestPriceAmount")
    # A single-bottle listing's normalised price IS its price. A multi-bottle
    # listing's price is only known divided and rounded — never multiplied
    # back into a figure the merchant did not print.
    price = (f"{Decimal(str(amount)):.2f}" if per_unit == 1 and amount is not None else None)
    return {
        "kind": "CURRENT_LISTING",
        "wine": {"producer": producer, "name": cuvee},
        "vintage": vintage,
        "bottle_ml": None,                 # not stated by this source
        "pack_size": per_unit,
        "merchant": {"name": row.get("cheapestPriceMerchant"),
                     "reference": row.get("wineSearcherUrl")},
        "price": price,
        "currency": row.get("cheapestPriceCurrency"),
        "duty_status": "UNKNOWN",          # not stated by this source
        "observed_at": row.get("scrapedAt"),
        "url": row.get("wineSearcherUrl"),
        "raw": {k: row.get(k) for k in (
            "inputValue", "inputType", "wineSearcherUrl", "wineName", "wineryName",
            "appellation", "vintage", "cheapestPriceAmount", "cheapestPriceCurrency",
            "cheapestPriceConverted", "cheapestPriceEur", "targetCurrency",
            "cheapestPriceMerchant", "bottlesPerUnit", "offersCount", "offersPages",
            "scrapedAt", "status")}
            | {"price_basis": "cheapest offer, normalised per 75cl bottle"},
    }


def to_batch(rows: list[dict]) -> tuple[dict, list[dict]]:
    """(batch for POST /market-evidence/batches, rows not converted). A row whose
    own status is not "ok" carries no offer at all and is handed back."""
    observations, skipped = [], []
    for index, row in enumerate(rows):
        if row.get("status") != "ok":
            skipped.append({"index": index, "inputValue": row.get("inputValue"),
                            "reason": f"status {row.get('status')!r}"})
            continue
        observations.append(_observation(row))
    return {"source": SOURCE, "observations": observations}, skipped
