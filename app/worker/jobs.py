"""Background jobs. Each is a plain function with structured input and output.

RQ imports these by dotted path, so every job takes only ids and simple
values and opens its own database connection.

    SNAPSHOT LOOKUP ......... collect_snapshot  (whole-book merchant feeds)
    DEEP MERCHANT SEARCH .... collect_targeted  (producer + vintage searches)
    DETERMINISTIC BENCHMARK . benchmark_deal
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional, Sequence

import psycopg

from app.adapters.base import Adapter, Candidate, Rejected, whole_pence
from app.adapters.bordeaux_index import LIST_URL as BI_URL, BordeauxIndexAdapter
from app.adapters.farr import FEED_URL as FARR_URL, FarrAdapter
from app.adapters.goedhuis import PRODUCTS_URL as GOEDHUIS_URL, GoedhuisAdapter
from app.core.benchmark import benchmark
from app.core.enums import Reject
from app.db import repo
from app.db.connection import transaction
from app.identity.resolver import ambiguous_lwins
from app.worker.politeness import check_robots

#: Bumped when the adapter output contract changes shape.
SNAPSHOT_SCHEMA_VERSION = "2"

#: Ingest-level rejection reasons. They are about the record as a whole, not a
#: pricing screen, so they are not members of app.core.enums.Reject.
NOT_WHOLE_PENCE = "NOT_WHOLE_PENCE"
NO_OFFER_ROWS = "NO_OFFER_ROWS"


@dataclass(frozen=True)
class WholeBook:
    """A merchant whose adapter fetches its entire offer book in one call."""
    adapter: Callable[[], Adapter]
    robots_url: str


@dataclass(frozen=True)
class Targeted:
    """A merchant that can only be searched by producer and vintage.
    `params` names the merchant-specific search terms the caller must supply."""
    adapter: Callable[[], Adapter]
    robots_url: str
    params: tuple[str, ...]


WHOLE_BOOK: dict[str, WholeBook] = {
    "farr": WholeBook(FarrAdapter, FARR_URL),
    "goedhuis": WholeBook(GoedhuisAdapter, GOEDHUIS_URL),
}

TARGETED: dict[str, Targeted] = {
    "bordeaux-index": Targeted(BordeauxIndexAdapter, BI_URL, ("producer_slug",)),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- collection


def _outputs(adapter: Adapter, raw: dict, captured_at: datetime) -> list[Candidate | Rejected]:
    out = adapter.normalise(raw, captured_at=captured_at)
    return out if isinstance(out, list) else [out]


def ingest(conn: psycopg.Connection, snapshot_id: str, adapter: Adapter,
           records: Iterable[dict], captured_at: datetime,
           registry=None) -> tuple[int, int]:
    """Normalise, resolve identity, persist. Returns (written, rejected).

    Every raw record ends as at least one `offer` or `offer_reject` row: a
    Bordeaux Index card with no parsable offer row is itself a reject.
    A candidate whose identity cannot be approved is an UNRESOLVED_IDENTITY
    reject, never an offer (offer.wine_id is NOT NULL).
    """
    registry = registry or repo.load_registry(conn)
    normalised = [(raw, _outputs(adapter, raw, captured_at)) for raw in records]
    candidates = [c for _, outs in normalised for c in outs if isinstance(c, Candidate)]
    # An LWIN the merchant applies to two different names in this capture
    # identifies neither of them.
    ambiguous = ambiguous_lwins([(c.lwin7, c.producer_text, c.cuvee_text) for c in candidates])

    written = rejected = 0
    for raw, outs in normalised:
        if not outs:
            repo.write_reject(conn, snapshot_id, adapter.id, NO_OFFER_ROWS,
                              "no offer row could be parsed", raw)
            rejected += 1
        for out in outs:
            if isinstance(out, Rejected):
                repo.write_reject(conn, snapshot_id, adapter.id, out.reason.name,
                                  out.detail, out.raw)
                rejected += 1
                continue
            if not whole_pence(out.offer.price):
                repo.write_reject(conn, snapshot_id, adapter.id, NOT_WHOLE_PENCE,
                                  f"price {out.offer.price} is not a whole number of pence",
                                  repo.unresolved_raw(out))
                rejected += 1
                continue
            lwin7 = None if out.lwin7 in ambiguous else out.lwin7
            wine_id = registry.resolve_candidate(out.producer_text, out.cuvee_text, lwin7)
            if wine_id is None:
                detail = f"{out.producer_text!r} / {out.cuvee_text!r}"
                if out.lwin7:
                    detail += f" / LWIN-7 {out.lwin7}" + (" (ambiguous)" if out.lwin7 in ambiguous else "")
                repo.write_reject(conn, snapshot_id, adapter.id,
                                  Reject.UNRESOLVED_IDENTITY.name, detail,
                                  repo.unresolved_raw(out))
                rejected += 1
                continue
            repo.write_offer(conn, snapshot_id, replace(out.offer, wine_id=wine_id))
            written += 1
    return written, rejected


def _finish(snapshot_id: str, outcomes: list[dict]) -> None:
    with transaction() as conn:
        repo.finish_snapshot(
            conn, snapshot_id,
            attempted=len(outcomes),
            succeeded=sum(1 for o in outcomes if not o.get("error")),
            written=sum(o.get("written", 0) for o in outcomes),
            rejected=sum(o.get("rejected", 0) for o in outcomes),
            failures=[{"merchant_id": o["merchant_id"], "error": o["error"]}
                      for o in outcomes if o.get("error")])


def _capture(snapshot_id: str, merchant_id: str, adapter: Adapter, robots_url: str,
             fetch: Callable[[], Sequence[dict]], robots: Callable[[str], None],
             scope: dict) -> dict:
    """Fetch and ingest one merchant into its own transaction, stamped with its
    own capture time. A failure is recorded against that merchant only."""
    captured_at = _now()
    try:
        robots(robots_url)
        records = fetch()
        with transaction() as conn:
            written, rejected = ingest(conn, snapshot_id, adapter, records, captured_at)
            repo.write_snapshot_merchant(conn, snapshot_id, merchant_id,
                                         captured_at=captured_at, written=written,
                                         rejected=rejected, **scope)
        return {"merchant_id": merchant_id, "written": written, "rejected": rejected}
    except Exception as e:  # recorded, never swallowed silently
        error = f"{type(e).__name__}: {e}"
        with transaction() as conn:
            repo.write_snapshot_merchant(conn, snapshot_id, merchant_id,
                                         captured_at=captured_at, error=error, **scope)
        return {"merchant_id": merchant_id, "error": error}


def _approved(conn: psycopg.Connection) -> set[str]:
    return {m["merchant_id"] for m in repo.list_merchants(conn) if m["approved"]}


def collect_snapshot(merchant_ids: Optional[Sequence[str]] = None, *,
                     is_demo: bool = False,
                     fetch: Optional[Callable[[Adapter], Sequence[dict]]] = None,
                     robots: Callable[[str], None] = check_robots) -> str:
    """Fetch whole-book merchants into a new snapshot, one capture each.

    Benchmarks resolve each merchant's latest covering capture independently,
    so a snapshot need not hold every merchant.
    """
    wanted = list(merchant_ids) if merchant_ids else list(WHOLE_BOOK)
    fetch = fetch or (lambda a: a.fetch())
    with transaction() as conn:
        snapshot_id = repo.create_snapshot(conn, captured_at=_now(),
                                           schema_version=SNAPSHOT_SCHEMA_VERSION,
                                           is_demo=is_demo)
        approved = _approved(conn)

    outcomes = []
    for mid in wanted:
        if mid not in approved:
            outcomes.append({"merchant_id": mid, "error": "not an approved merchant"})
        elif mid in TARGETED:
            outcomes.append({"merchant_id": mid,
                             "error": "searched by producer and vintage: use collect_targeted"})
        elif mid not in WHOLE_BOOK:
            outcomes.append({"merchant_id": mid, "error": "no adapter"})
        else:
            spec = WHOLE_BOOK[mid]
            adapter = spec.adapter()
            outcomes.append(_capture(snapshot_id, mid, adapter, spec.robots_url,
                                     lambda: fetch(adapter), robots, {}))
    _finish(snapshot_id, outcomes)
    return str(snapshot_id)


def collect_targeted(merchant_id: str, wine_id: str, vintage: int, params: dict, *,
                     is_demo: bool = False,
                     fetch: Optional[Callable[[Adapter, dict, int], Sequence[dict]]] = None,
                     robots: Callable[[str], None] = check_robots) -> str:
    """Search one merchant for one producer and vintage (DEEP MERCHANT SEARCH).

    The capture's scope is that producer (as normalised in wine_key) and that
    vintage. It covers every wine of the producer in that vintage, and nothing
    else, when benchmarks resolve sources.
    """
    spec = TARGETED.get(merchant_id)
    if spec is None:
        raise ValueError(f"{merchant_id!r} has no targeted search")
    missing = [k for k in spec.params if not params.get(k)]
    if missing:
        raise ValueError(f"{merchant_id} search needs {missing}")
    fetch = fetch or (lambda a, p, v: a.fetch(p["producer_slug"], v))

    with transaction() as conn:
        wine = repo.get_wine(conn, wine_id)
        if wine is None:
            raise LookupError(f"wine {wine_id} not found")
        if merchant_id not in _approved(conn):
            raise ValueError(f"{merchant_id!r} is not an approved merchant")
        snapshot_id = repo.create_snapshot(conn, captured_at=_now(),
                                           schema_version=SNAPSHOT_SCHEMA_VERSION,
                                           is_demo=is_demo)

    adapter = spec.adapter()
    scope = {"scope_producer_key": repo.producer_key_of(wine), "scope_vintage": vintage,
             "scope_params": dict(params)}
    outcome = _capture(snapshot_id, merchant_id, adapter, spec.robots_url,
                       lambda: fetch(adapter, params, vintage), robots, scope)
    _finish(snapshot_id, [outcome])
    return str(snapshot_id)


# ----------------------------------------------------------------- benchmark


def benchmark_deal(deal_id: str, as_of: Optional[str] = None) -> dict:
    """Benchmark every line of a deal as of one instant (default: now).

    A line is skipped, not marked NO_MARKET, when its identity is unapproved or
    when no approved merchant has any capture covering it: in both cases nobody
    has looked, and NO_MARKET would claim that somebody did.
    """
    when = datetime.fromisoformat(as_of) if as_of else _now()
    runs, unapproved, no_coverage = {}, [], []
    with transaction() as conn:
        if repo.get_deal(conn, deal_id) is None:
            raise LookupError(f"deal {deal_id} not found")
        for row in repo.deal_lines(conn, deal_id):
            line = repo.seller_line_for_benchmark(row)
            if line is None:
                unapproved.append(str(row["line_id"]))
                continue
            res = repo.resolve_offers(conn, wine_id=line.wine_id, vintage=line.vintage,
                                      as_of=when)
            if not res.sources:
                no_coverage.append(line.line_id)
                continue
            result = benchmark(line, res.offers, as_of=when)
            runs[line.line_id] = str(repo.save_benchmark(conn, result, res))
    return {"as_of": when.isoformat(), "runs": runs,
            "unapproved_identity": unapproved, "no_coverage": no_coverage}
