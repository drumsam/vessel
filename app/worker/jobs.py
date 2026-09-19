"""Background jobs. Each is a plain function with structured input and output.

RQ imports these by dotted path, so every job takes only ids and simple
values and opens its own database connection.

    SNAPSHOT LOOKUP ......... collect_snapshot  (full-list merchant feeds)
    DETERMINISTIC BENCHMARK . benchmark_deal / benchmark_line_in
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, Sequence

import psycopg

from app.adapters.base import Adapter, Candidate, Rejected
from app.adapters.farr import FEED_URL as FARR_URL, FarrAdapter
from app.adapters.goedhuis import PRODUCTS_URL as GOEDHUIS_URL, GoedhuisAdapter
from app.core.benchmark import benchmark
from app.core.enums import Reject
from app.db import repo
from app.db.connection import transaction
from app.worker.politeness import check_robots

#: Bumped when the adapter output contract changes shape.
SNAPSHOT_SCHEMA_VERSION = "1"

#: Merchants whose adapter can fetch the whole offer book in one call, with the
#: URL whose robots.txt governs that fetch.
FULL_LIST: dict[str, tuple[Callable[[], Adapter], str]] = {
    "farr": (FarrAdapter, FARR_URL),
    "goedhuis": (GoedhuisAdapter, GOEDHUIS_URL),
}

#: Merchants that can only be searched per producer and vintage. They belong to
#: DEEP MERCHANT SEARCH, which is not built yet; a snapshot records them as a
#: failure rather than silently leaving them out.
TARGETED_ONLY = {"bordeaux-index": "fetch requires producer_slug and vintage"}


class NoSnapshot(Exception):
    """There is no usable snapshot. Benchmarking without one would report
    NO_MARKET for a market nobody looked at."""


# ---------------------------------------------------------------- collection


def ingest(conn: psycopg.Connection, snapshot_id: str, adapter: Adapter,
           records: Iterable[dict], captured_at: datetime,
           registry=None) -> tuple[int, int]:
    """Normalise, resolve identity, persist. Returns (written, rejected).

    Every raw record ends as exactly one `offer` or one `offer_reject` row.
    A candidate whose identity cannot be approved is an UNRESOLVED_IDENTITY
    reject, never an offer: see the Offer docstring in app/core/models.py.
    """
    registry = registry or repo.load_registry(conn)
    written = rejected = 0
    for raw in records:
        out = adapter.normalise(raw, captured_at=captured_at)
        if isinstance(out, Rejected):
            repo.write_reject(conn, snapshot_id, adapter.id, out.reason.name,
                              out.detail, out.raw)
            rejected += 1
            continue
        assert isinstance(out, Candidate)
        # The Candidate contract carries no LWIN yet, so resolution runs on
        # wine_key and controlled aliases only.
        wine_id = registry.resolve_candidate(out.producer_text, out.cuvee_text)
        if wine_id is None:
            repo.write_reject(conn, snapshot_id, adapter.id,
                              Reject.UNRESOLVED_IDENTITY.name,
                              f"{out.producer_text!r} / {out.cuvee_text!r}",
                              repo.unresolved_raw(out))
            rejected += 1
            continue
        repo.write_offer(conn, snapshot_id, replace(out.offer, wine_id=wine_id))
        written += 1
    return written, rejected


def collect_snapshot(merchant_ids: Optional[Sequence[str]] = None, *,
                     is_demo: bool = False,
                     fetch: Optional[Callable[[Adapter], Sequence[dict]]] = None,
                     robots: Callable[[str], None] = check_robots) -> str:
    """Fetch every requested merchant into ONE new snapshot.

    One snapshot must hold the whole merchant universe, because a benchmark run
    references a single snapshot: a Farr-only snapshot would undercount depth.
    A merchant that fails is recorded in `snapshot.failures`, and the other
    merchants' offers are still written.
    """
    wanted = list(merchant_ids) if merchant_ids else [*FULL_LIST, *TARGETED_ONLY]
    captured_at = datetime.now(timezone.utc)
    fetch = fetch or (lambda a: a.fetch())

    with transaction() as conn:
        snapshot_id = repo.create_snapshot(conn, captured_at=captured_at,
                                           schema_version=SNAPSHOT_SCHEMA_VERSION,
                                           is_demo=is_demo)
        approved = {m["merchant_id"] for m in repo.list_merchants(conn) if m["approved"]}

    attempted = succeeded = written = rejected = 0
    failures: list[dict] = []
    for mid in wanted:
        attempted += 1
        if mid not in approved:
            failures.append({"merchant_id": mid, "error": "not an approved merchant"})
            continue
        if mid in TARGETED_ONLY:
            failures.append({"merchant_id": mid, "error": TARGETED_ONLY[mid]})
            continue
        if mid not in FULL_LIST:
            failures.append({"merchant_id": mid, "error": "no adapter"})
            continue
        factory, url = FULL_LIST[mid]
        adapter = factory()
        try:
            robots(url)
            records = fetch(adapter)
            # Each merchant commits on its own: one merchant's bad record
            # cannot erase another merchant's evidence.
            with transaction() as conn:
                w, r = ingest(conn, snapshot_id, adapter, records, captured_at)
        except Exception as e:  # recorded, never swallowed silently
            failures.append({"merchant_id": mid, "error": f"{type(e).__name__}: {e}"})
            continue
        succeeded += 1
        written += w
        rejected += r

    with transaction() as conn:
        repo.finish_snapshot(conn, snapshot_id, attempted=attempted, succeeded=succeeded,
                             written=written, rejected=rejected, failures=failures)
    return str(snapshot_id)


# ----------------------------------------------------------------- benchmark


def benchmark_line_in(conn: psycopg.Connection, line_row: dict,
                      snapshot_id: str) -> Optional[str]:
    """Run the deterministic core for one line and persist exactly what it
    returned. Returns the run id, or None if the line has no approved identity."""
    line = repo.seller_line_for_benchmark(line_row)
    if line is None:
        return None
    result = benchmark(line, repo.offers_for_wine(conn, snapshot_id, line.wine_id))
    return str(repo.save_benchmark(conn, result, snapshot_id))


def benchmark_deal(deal_id: str, snapshot_id: Optional[str] = None) -> dict:
    with transaction() as conn:
        if repo.get_deal(conn, deal_id) is None:
            raise LookupError(f"deal {deal_id} not found")
        snapshot_id = snapshot_id or repo.latest_snapshot_id(conn)
        if snapshot_id is None:
            raise NoSnapshot("no non-demo snapshot with a successful adapter")
        runs, skipped = {}, []
        for row in repo.deal_lines(conn, deal_id):
            run_id = benchmark_line_in(conn, row, snapshot_id)
            if run_id is None:
                skipped.append(str(row["line_id"]))
            else:
                runs[str(row["line_id"])] = run_id
    return {"snapshot_id": str(snapshot_id), "runs": runs, "unapproved_identity": skipped}
