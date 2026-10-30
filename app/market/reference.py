"""Pocket projection of existing persisted benchmarks. No pricing arithmetic."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from app.core.enums import Reject
from app.core.flags import MAX_OFFER_AGE_DAYS
from app.db import repo
from app.market.vintage_band import NEIGHBOUR_MAX_AGE_DAYS
from app.worker import jobs

POLICY = "pocket-evidence-1"


def age(at, now):
    if at is None:
        return None
    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    days = max(0, (now - at).days)
    return {
        "captured_at": at,
        "days": days,
        "label": "fresh"
        if days <= 14
        else "usable"
        if days <= 30
        else "stale"
        if days <= 90
        else "historical",
    }


def fingerprint(line, resolution, region, tiers, reinstated, now):
    # Eligibility, rather than the moving clock, changes only at a real boundary.
    eligibility = [
        (
            o.offer_id,
            [
                bool(o.captured_at and now - timedelta(days=n) <= o.captured_at <= now)
                for n in (MAX_OFFER_AGE_DAYS, NEIGHBOUR_MAX_AGE_DAYS)
            ],
        )
        for o in resolution.offers
    ]
    data = [
        POLICY,
        asdict(line),
        region,
        tiers,
        reinstated,
        sorted(resolution.sources, key=lambda s: s["merchant_id"]),
        sorted((asdict(o) for o in resolution.offers), key=lambda o: o["offer_id"]),
        sorted(eligibility),
    ]

    # frozensets must be sorted: their repr is not stable across processes.
    def encode(value):
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        return str(value)

    return hashlib.sha256(
        json.dumps(data, default=encode, sort_keys=True).encode()
    ).hexdigest()


def market_reference(conn, line_row, *, now=None, force=False):
    now = now or datetime.now(UTC)
    line = repo.seller_line_for_benchmark(line_row)
    if line is None:
        raise ValueError("Approved identity required")
    res = repo.resolve_offers(
        conn, wine_id=line.wine_id, vintage=line.vintage, as_of=now
    )
    region = repo.wine_register_key(conn, line.wine_id)
    restored = conn.execute(
        """SELECT e.offer_pk, e.reinstated_at, e.reinstated_reason
        FROM benchmark_comp_exclusion e JOIN benchmark_run b ON b.run_id=e.run_id
        WHERE b.line_id=%s AND e.reinstated_at IS NOT NULL ORDER BY e.exclusion_id""",
        (line.line_id,),
    ).fetchall()
    key = fingerprint(
        line, res, region, repo.vintage_tiers(conn, region), restored, now
    )
    run = repo.latest_run(conn, line.line_id)
    cached = bool(
        not force and run and run["as_of"] <= now and run.get("evidence_key") == key
    )
    if res.sources and not cached:
        run_id, _ = jobs.benchmark_with_band(
            conn,
            line,
            res,
            now,
            reinstated=[str(r["offer_pk"]) for r in restored if r["offer_pk"]],
        )
        conn.execute(
            "UPDATE benchmark_run SET evidence_key=%s WHERE run_id=%s", (key, run_id)
        )
        run = conn.execute(
            "SELECT * FROM benchmark_run WHERE run_id=%s", (run_id,)
        ).fetchone()
    if not res.sources:
        run = None  # Never revive an old run when its covering captures disappeared.
    comps = repo.run_comps(conn, str(run["run_id"])) if run else []
    bests = [r["offer_snapshot"] for r in comps if r["role"] == "merchant_best"]
    captures = [r["captured_at"] for r in bests if r.get("captured_at")]
    merchants = repo.list_merchants(conn)
    sources = [
        {
            **s,
            "name": next(
                (m["name"] for m in merchants if m["merchant_id"] == s["merchant_id"]),
                s["merchant_id"],
            ),
        }
        for s in res.sources
    ]
    attempts = conn.execute(
        """SELECT DISTINCT ON (sm.merchant_id) sm.merchant_id, m.name,
        sm.status, sm.error, sm.captured_at, sm.offers_written, sm.offers_rejected
        FROM snapshot_merchant sm JOIN snapshot s USING(snapshot_id) JOIN merchant m USING(merchant_id)
        WHERE m.approved AND NOT s.is_demo AND s.schema_version <> 'auction-import-1' AND sm.captured_at<=%s AND
        (sm.scope_producer_key IS NULL OR (sm.scope_producer_key=%s AND sm.scope_vintage=%s))
        ORDER BY sm.merchant_id,sm.captured_at DESC,sm.snapshot_id DESC""",
        (now, repo.producer_key_of(repo.get_wine(conn, line.wine_id)), line.vintage),
    ).fetchall()
    return {
        "state": run["state"] if run else "NOT_SEARCHED",
        "collection_state": "CHECK_FAILED"
        if any(a["status"] == "failed" for a in attempts)
        else "CHECKED"
        if res.sources
        else "NOT_SEARCHED",
        "run_id": str(run["run_id"]) if run else None,
        "cached": cached,
        "as_of": run["as_of"] if run else None,
        "flags": run["flags"] if run else [],
        "comp_count": run["comp_count"] if run else 0,
        "checked_merchants": [s["name"] for s in sources],
        "merchant": {
            "floor": run["uk_floor"] if run else None,
            "reference": run["uk_reference"] if run else None,
            "median": run["uk_median"] if run else None,
            "source_count": run["comp_count"] if run else 0,
            "currency": "GBP",
            "duty_status": "IB",
            "bottle_ml": line.bottle_ml,
            "pack_size": line.pack_size,
            "newest": age(max(captures), now) if captures else None,
            "oldest": age(min(captures), now) if captures else None,
            "evidence": bests,
            "historical": [
                r["offer_snapshot"]
                for r in comps
                if r["role"] == "rejected" and r["reject_reason"] == Reject.STALE.value
            ],
        },
        "collection": attempts,
    }
