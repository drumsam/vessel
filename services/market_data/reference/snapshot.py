"""Reproducible rails. Currency/market/tax/unit boundaries never cross."""
from datetime import timedelta
from decimal import Decimal
from statistics import median
import json
from ..observations.models import timestamp, utcnow

POLICY = "v1-latest-listing-per-source-reference-no-expiry"


def freshness(observed_at, now=None):
    if observed_at is None:
        return None
    days = max(0, ((now or utcnow()) - timestamp(observed_at)).days)
    label = "fresh" if days <= 14 else "usable" if days <= 30 else "stale" if days <= 90 else "historical"
    return {"as_of": observed_at, "age_days": days, "freshness": label}


def amount(row, unit):
    value = Decimal(row["price"])
    return value * unit.pack_size if row["price_basis"] == "BOTTLE" else value


def rails(rows, unit):
    latest = {}
    for row in rows:
        key = (row["source_id"], row["source_reference"], row["price_type"])
        if row["price_type"] in {"AUCTION_HAMMER", "AUCTION_ALL_IN", "LAST_TRADE", "VESSEL_TRADE"}:
            key += (row["observed_at"],)
        if key not in latest or row["observed_at"] >= latest[key]["observed_at"]:
            latest[key] = row
    rows = list(latest.values())

    def stats(selected, transactions=False):
        if not selected:
            return {"floor": None, "median": None, "low": None, "high": None,
                    "latest": None, "count": 0, "source_count": 0, "as_of": None,
                    "oldest_included": None, "observation_ids": []}
        prices = [amount(r, unit) for r in selected]
        newest = max(selected, key=lambda r: (r["observed_at"], r["observation_id"]))
        return {"floor": str(min(prices)), "median": str(median(prices)),
                "low": str(min(prices)), "high": str(max(prices)),
                "latest": {"price": str(amount(newest, unit)), "observation_id": newest["observation_id"],
                           "observed_at": newest["observed_at"]} if transactions else None,
                "count": len(selected), "source_count": len({r["source_id"] for r in selected}),
                "as_of": newest["observed_at"], "oldest_included": min(r["observed_at"] for r in selected),
                "observation_ids": sorted(r["observation_id"] for r in selected)}

    merchant = stats([r for r in rows if r["price_type"] in {"MERCHANT_ASK", "LIVE_OFFER"}])
    # Fees and transaction conventions differ: never blend hammer with all-in prices.
    transaction = {kind: stats([r for r in rows if r["price_type"] == kind], True)
                   for kind in ("AUCTION_HAMMER", "AUCTION_ALL_IN", "LAST_TRADE", "VESSEL_TRADE")}
    bids = [r for r in rows if r["price_type"] == "LIVE_BID"]
    offers = [r for r in rows if r["price_type"] == "LIVE_OFFER"]
    bid = max(bids, key=lambda r: amount(r, unit)) if bids else None
    offer = min(offers, key=lambda r: amount(r, unit)) if offers else None
    liquidity = {"best_bid": str(amount(bid, unit)) if bid else None,
                 "best_offer": str(amount(offer, unit)) if offer else None,
                 "spread": str(amount(offer, unit) - amount(bid, unit)) if bid and offer else None,
                 "bid_as_of": bid["observed_at"] if bid else None,
                 "offer_as_of": offer["observed_at"] if offer else None,
                 "bid_observation_id": bid["observation_id"] if bid else None,
                 "offer_observation_id": offer["observation_id"] if offer else None}
    return {"merchant": merchant, "transactions": transaction, "liquidity": liquidity}


def reference(store, unit, now=None):
    # Serialize cache generation with writers: a concurrent ingest cannot leave a stale cache.
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        cached = db.execute("SELECT payload FROM snapshots WHERE unit_key=?", (unit.key(),)).fetchone()
        if cached:
            result = json.loads(cached[0])
        else:
            observations = []
            for row in db.execute("SELECT observation_id,payload FROM observations WHERE unit_key=? ORDER BY created_at, observation_id", (unit.key(),)):
                observations.append({**json.loads(row["payload"]), "observation_id": row["observation_id"]})
            result = {"unit": json.loads(unit.key()), "policy": POLICY, "generated_at": utcnow().isoformat(),
                      **rails(observations, unit)}
            db.execute("INSERT INTO snapshots VALUES (?,?)", (unit.key(), json.dumps(result)))
    # Ages are computed at read time even when monetary summaries are cached.
    for rail in [result["merchant"], *result["transactions"].values()]:
        rail["age"] = freshness(rail["as_of"], now)
        rail["oldest_age"] = freshness(rail["oldest_included"], now)
    for side in ("bid", "offer"):
        result["liquidity"][side + "_age"] = freshness(result["liquidity"][side + "_as_of"], now)
    return result
