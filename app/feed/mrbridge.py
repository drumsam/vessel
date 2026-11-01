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

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from urllib.parse import parse_qsl, urlparse

import psycopg

from app.core.flags import MAX_OFFER_AGE_DAYS
from app.identity.resolver import norm

SOURCE = "wine-searcher-via-mrbridge"

#: Wine-Searcher's own winery spellings that differ from the register's
#: producer for the SAME house — a source naming quirk, fixed here in the
#: adapter rather than as dozens of per-wine aliases (decision 0049). Keyed
#: by norm(); the register's display name is never changed.
_WINERY_TO_REGISTER = {
    "domaine du comte liger belair": "Comte Liger-Belair",
}

#: The bottle size a Wine-Searcher URL states EXPLICITLY through its own
#: `Xbottle_size` filter (the parameter its robots.txt names). Only these
#: values are read as 750ml; anything else — including a price MrBridge
#: merely normalised to 75cl — leaves the size unknown. The value spellings
#: are unconfirmed against a live filtered URL: fail closed until they are.
_URL_750 = {"750", "750ml", "75cl"}


def bottle_ml_from_url(url: Optional[str]) -> Optional[int]:
    if not url:
        return None
    for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if key.lower() == "xbottle_size" and value.strip().lower() in _URL_750:
            return 750
    return None

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
    producer = _WINERY_TO_REGISTER.get(norm(winery), winery)
    return producer, " ".join(tokens)


def _observation(row: dict) -> dict:
    vintage = row.get("vintage")
    producer, cuvee = split_name(row.get("wineName") or "", row.get("wineryName") or "", vintage)
    per_unit = row.get("bottlesPerUnit")
    amount = row.get("cheapestPriceAmount")
    # A real listing only when the URL itself confirms 750ml AND the listing is
    # one bottle: then the normalised price is that bottle's price. Anything
    # else is a per-75cl EQUIVALENT — MrBridge's own normalisation, or a
    # multi-bottle listing divided — context only, never evidence of format,
    # never multiplied back into a price nobody printed.
    price = f"{Decimal(str(amount)):.2f}" if amount is not None else None
    stated_ml = bottle_ml_from_url(row.get("wineSearcherUrl"))
    listing = per_unit == 1 and stated_ml == 750
    return {
        "kind": "CURRENT_LISTING" if listing else "EQUIVALENT_75CL",
        "wine": {"producer": producer, "name": cuvee},
        "vintage": vintage,
        "bottle_ml": stated_ml if listing else None,
        "pack_size": 1,
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
            | {"price_basis": "cheapest offer, normalised per 75cl bottle",
               "format_stated": stated_ml is not None,
               "bottle_equivalent_of": per_unit if per_unit and per_unit > 1 else None},
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


def steer(conn: psycopg.Connection, *, wine_id: str, vintage: int, bottle_ml: int,
          as_of: Optional[datetime] = None) -> Optional[dict]:
    """The latest fresh Wine-Searcher observation for exactly this wine and
    vintage — context for the MARKET row, never Floor (decision 0049). Two kinds:

    - a listing whose URL confirmed 750ml (an `offer`, shown "/btl"), only for a
      line of that same bottle size;
    - a 75cl EQUIVALENT (a retained reject carrying its resolved wine, shown
      "/75cl eq"), never read as evidence of any format.

    Merchant approval decides Floor, not visibility, so it is not filtered
    here. Freshness is the same MAX_OFFER_AGE_DAYS the core applies, measured
    from when the source observed the price."""
    as_of = as_of or datetime.now(timezone.utc)
    oldest = as_of - timedelta(days=MAX_OFFER_AGE_DAYS)
    row = conn.execute(
        """SELECT o.price, o.currency, o.captured_at AS observed_at, o.raw, m.name AS merchant,
                  'btl' AS unit
             FROM offer o
             JOIN snapshot s ON s.snapshot_id = o.snapshot_id
             JOIN merchant m ON m.merchant_id = o.merchant_id
            WHERE o.wine_id = %(wine_id)s::uuid AND o.vintage = %(vintage)s AND o.bottle_ml = %(ml)s
              AND o.raw->>'acquisition_source' = %(source)s AND NOT s.is_demo
              AND o.captured_at <= %(as_of)s AND o.captured_at > %(oldest)s
           UNION ALL
           SELECT (r.raw->'observation'->>'price')::numeric, r.raw->'observation'->>'currency',
                  (r.raw->'observation'->>'observed_at')::timestamptz, r.raw, m.name, '75cl eq'
             FROM offer_reject r
             JOIN snapshot s ON s.snapshot_id = r.snapshot_id
             JOIN merchant m ON m.merchant_id = r.merchant_id
            WHERE r.reason = %(reason)s AND NOT s.is_demo
              AND r.raw->>'acquisition_source' = %(source)s
              AND r.raw->>'resolved_wine_id' = %(wine_id)s::text
              AND (r.raw->>'vintage')::int = %(vintage)s
              AND r.raw->'observation'->'raw'->>'status' = 'ok'
              AND r.raw->'observation'->>'observed_at' IS NOT NULL
              AND (r.raw->'observation'->>'observed_at')::timestamptz <= %(as_of)s
              AND (r.raw->'observation'->>'observed_at')::timestamptz > %(oldest)s
           ORDER BY observed_at DESC, price ASC LIMIT 1""",
        {"wine_id": str(wine_id), "vintage": vintage, "ml": bottle_ml, "source": SOURCE,
         "as_of": as_of, "oldest": oldest, "reason": "EQUIVALENT_ONLY"}).fetchone()
    if row is None:
        return None
    source_raw = (row["raw"].get("observation") or {}).get("raw") or {}
    return {
        "source": "Wine-Searcher",
        "merchant": row["merchant"],
        "price": Decimal(str(row["price"])).quantize(Decimal("0.01")),
        "unit": row["unit"],
        "currency": row["currency"],
        "offers_count": source_raw.get("offersCount"),
        "bottle_equivalent_of": source_raw.get("bottle_equivalent_of"),
        "observed_at": row["observed_at"],
    }
