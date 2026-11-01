"""Source-agnostic market-evidence import (proof, not yet wired to the API).

VESSEL consumes structured market evidence; acquiring it is somebody else's
job. Any provider (a licensed feed, Liv-ex, a merchant's own CSV turned into
JSON) hands over one batch; each observation becomes an adapter `Candidate`
and goes through `app.worker.jobs.ingest` UNCHANGED: identity resolution,
the whole-pence check, offer / offer_reject rows. The locked core then
decides, exactly as for any adapter, which offers may set Floor.

The acquisition source is recorded on every offer (`raw.acquisition_source`),
separately from the real merchant, which is mapped onto the merchant register
so one company is never two merchants (invariant 3). A merchant the register
does not know is created UNAPPROVED: its evidence is kept and visible but sets
no Floor until someone approves it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import psycopg

from app.adapters.base import Candidate, Rejected
from app.core.enums import DutyStatus, PriceKind, Reject, StockType
from app.core.models import Offer
from app.db import repo
from app.identity.resolver import norm
from app.worker import jobs

FEED_SCHEMA_VERSION = "feed-1"

#: CURRENT_LISTING is a merchant's ask. BOTTLE_EQUIVALENT is a per-bottle
#: figure a provider derived from a multi-bottle listing — real evidence, but
#: not a price anyone quoted, so it is stored as an INDICATION, which the
#: core's KIND screen keeps out of Floor whatever else is known (decision 0049).
_KINDS = {"CURRENT_LISTING": PriceKind.ASK, "BOTTLE_EQUIVALENT": PriceKind.INDICATION}

_DUTY = {"IN_BOND": DutyStatus.IN_BOND, "DUTY_PAID": DutyStatus.DUTY_PAID,
         "UNKNOWN": DutyStatus.UNKNOWN, None: DutyStatus.UNKNOWN}

#: Corporate noise only, never a distinguishing word: "Farr Vintners Ltd" is
#: "Farr Vintners", but "Vintners" itself is kept.
_MERCHANT_NOISE = {"ltd", "limited", "plc", "llp", "inc", "the", "&", "and", "co"}


class InvalidBatch(Exception):
    """The batch as a whole cannot be read — nothing is written."""


def merchant_key(name: str) -> str:
    return " ".join(t for t in norm(name).split() if t not in _MERCHANT_NOISE)


def map_merchant(conn: psycopg.Connection, name: str, *, source: str,
                 known: Optional[list[dict]] = None) -> tuple[str, bool, bool]:
    """(merchant_id, created, approved). An existing merchant matches on its name
    or its id under `merchant_key` and keeps its own approval state — an
    approved one (Farr, Goedhuis, Bordeaux Index) counts at once, an unapproved
    one stays unapproved. Anything genuinely new is created UNAPPROVED: kept and
    visible, never a Floor setter until someone approves it (decision 0048)."""
    key = merchant_key(name)
    rows = known if known is not None else conn.execute(
        "SELECT merchant_id, name, approved FROM merchant").fetchall()
    for m in rows:
        if key in (merchant_key(m["name"]), merchant_key(m["merchant_id"].replace("-", " "))):
            return m["merchant_id"], False, m["approved"]
    base = "-".join(key.split()) or "merchant"
    merchant_id, n = base, 1
    while conn.execute("SELECT 1 FROM merchant WHERE merchant_id = %s", (merchant_id,)).fetchone():
        n += 1
        merchant_id = f"{base}-{n}"
    conn.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) VALUES (%s, %s, false, %s)",
        (merchant_id, name, f"First seen in market feed {source!r}. Unapproved: its evidence "
                            "is kept and visible but sets no Floor until approved."))
    if known is not None:
        known.append({"merchant_id": merchant_id, "name": name, "approved": False})
    return merchant_id, True, False


def _vintage(v) -> Optional[int]:
    if isinstance(v, str) and v.strip().upper() == "NV":
        return 1000
    return v if isinstance(v, int) and 1800 <= v <= 2100 else None


def _lwin7(lwin) -> Optional[str]:
    digits = "".join(ch for ch in str(lwin or "") if ch.isdigit())
    return digits[:7] if len(digits) >= 7 else None


@dataclass
class FeedAdapter:
    """One merchant's observations from one batch, in the adapter shape `ingest`
    already consumes. `normalise` is pure: no network, no clock."""
    id: str
    merchant: str
    source: str
    default_observed_at: datetime

    def normalise(self, raw: dict, captured_at: datetime) -> Candidate | Rejected:
        obs = raw["observation"]
        wine = obs.get("wine") or {}
        vintage = _vintage(obs.get("vintage"))
        if vintage is None:
            return Rejected(raw, Reject.VINTAGE, f"vintage {obs.get('vintage')!r} is not a year or NV")
        kind = obs.get("kind", "CURRENT_LISTING")
        if kind not in _KINDS:
            return Rejected(raw, Reject.KIND, f"{kind}: kept as evidence, not a live ask")
        if not isinstance(obs.get("bottle_ml"), int) or obs["bottle_ml"] <= 0:
            return Rejected(raw, Reject.SIZE, "bottle size not stated")
        if not isinstance(obs.get("pack_size"), int) or obs["pack_size"] <= 0:
            return Rejected(raw, Reject.UNIT, "pack size not stated")
        if not isinstance(obs.get("price"), str):
            return Rejected(raw, Reject.ROW_UNREADABLE, "price must be a decimal string, never a number")
        try:
            price = Decimal(obs["price"])
        except InvalidOperation:
            return Rejected(raw, Reject.ROW_UNREADABLE, f"price {obs['price']!r} is not a number")
        duty = _DUTY.get(obs.get("duty_status"))
        if duty is None:
            return Rejected(raw, Reject.ROW_UNREADABLE, f"duty_status {obs['duty_status']!r} unknown")
        observed = obs.get("observed_at")
        observed_at = datetime.fromisoformat(observed) if observed else self.default_observed_at
        offer = Offer(
            offer_id=f"feed:{self.source}:{raw['index']}", merchant_id=self.id,
            merchant=self.merchant, wine_id="", vintage=vintage, bottle_ml=obs["bottle_ml"],
            pack_size=obs["pack_size"], price=price, currency=str(obs.get("currency") or ""),
            duty_status=duty, price_kind=_KINDS[kind],
            # A current listing is an offer for sale unless it says otherwise.
            is_buyable=obs.get("availability") != "OUT_OF_STOCK",
            offered_units=obs.get("quantity"), stock_type=StockType.UNKNOWN,
            source_url=obs.get("url") or (obs.get("merchant") or {}).get("reference"),
            captured_at=observed_at,
            raw={"acquisition_source": self.source, "observation": obs})
        return Candidate(offer=offer, producer_text=str(wine.get("producer") or ""),
                         cuvee_text=str(wine.get("name") or ""), lwin7=_lwin7(wine.get("lwin")))


#: A batch bigger than this is refused whole, not half-imported: the caller
#: splits it. ~1,000 wines at a handful of offers each.
MAX_OBSERVATIONS = 5000


def import_batch(conn: psycopg.Connection, batch: dict) -> dict:
    """One provider batch, grouped per real merchant and per resolved wine; each
    group is one snapshot (snapshot_merchant holds one capture per merchant per
    snapshot) whose capture is scoped to exactly that wine and vintage, so it can
    never mask a sibling wine (decision 0048). Ingested by the shared pipeline.
    Never raises on a single bad observation — that is a retained reject."""
    source = batch.get("source")
    observations = batch.get("observations")
    if not isinstance(source, str) or not source.strip() or not isinstance(observations, list):
        raise InvalidBatch("a batch needs a source and a list of observations")
    if len(observations) > MAX_OBSERVATIONS:
        raise InvalidBatch(f"{len(observations)} observations — split the batch "
                           f"(at most {MAX_OBSERVATIONS} per request)")
    try:
        observed_at = (datetime.fromisoformat(batch["observed_at"]) if batch.get("observed_at")
                       else datetime.now(timezone.utc))
    except (TypeError, ValueError):
        raise InvalidBatch(f"observed_at {batch.get('observed_at')!r} is not an ISO timestamp")
    source = source.strip()
    # Batch-level rejects (a disagreeing wine_id) land here.
    snapshot_id = repo.create_snapshot(conn, captured_at=observed_at,
                                       schema_version=FEED_SCHEMA_VERSION, is_demo=False)
    registry = repo.load_registry(conn)
    known = conn.execute("SELECT merchant_id, name, approved FROM merchant").fetchall()
    snapshots = [snapshot_id]
    mapped: dict[str, str] = {}
    created: list[str] = []
    approval: dict[str, bool] = {}
    written = rejected = 0
    unattributed: list[int] = []

    groups: dict[tuple, list[dict]] = defaultdict(list)
    adapters: dict[str, FeedAdapter] = {}
    for index, obs in enumerate(observations):
        record = {"index": index, "observation": obs}
        name = ((obs or {}).get("merchant") or {}).get("name") if isinstance(obs, dict) else None
        if not name:
            # Nothing to attribute it to (offer_reject needs a real merchant):
            # handed back to the provider by position instead of stored.
            unattributed.append(index)
            continue
        merchant_id, was_created, approved = map_merchant(conn, name, source=source, known=known)
        mapped[name] = merchant_id
        approval[merchant_id] = approved
        if was_created:
            created.append(merchant_id)
        adapter = adapters.setdefault(merchant_id, FeedAdapter(merchant_id, name, source, observed_at))
        out = adapter.normalise(record, observed_at)
        scope = None
        if isinstance(out, Candidate):
            wine_id = registry.resolve_candidate(out.producer_text, out.cuvee_text, out.lwin7)
            claimed = (obs.get("wine") or {}).get("wine_id")
            if wine_id and claimed and str(claimed) != wine_id:
                repo.write_reject(conn, snapshot_id, merchant_id, Reject.WINE.name,
                                  "provider's wine_id disagrees with VESSEL's own resolution",
                                  record)
                rejected += 1
                continue
            if wine_id:
                scope = (wine_id, out.offer.vintage)
        groups[(merchant_id, scope)].append(record)

    unapproved_written = 0
    for (merchant_id, scope), records in groups.items():
        group_snapshot = snapshot_id
        if scope is not None:
            group_snapshot = repo.create_snapshot(conn, captured_at=observed_at,
                                                  schema_version=FEED_SCHEMA_VERSION,
                                                  is_demo=False)
            snapshots.append(group_snapshot)
        w, r = jobs.ingest(conn, group_snapshot, adapters[merchant_id], records,
                           observed_at, registry)
        written += w
        rejected += r
        if not approval[merchant_id]:
            unapproved_written += w
        # A capture claims coverage only when it carries something that could
        # set Floor (an In Bond ask). Otherwise it would supersede the same
        # merchant's fuller capture of this wine — Farr's own In Bond price
        # hidden behind a feed row that cannot count — and lift the Floor.
        floor_capable = any(
            r_["observation"].get("duty_status") == "IN_BOND"
            and r_["observation"].get("kind", "CURRENT_LISTING") == "CURRENT_LISTING"
            for r_ in records)
        if scope is not None and floor_capable:
            wine_id, vintage = scope
            latest = max(datetime.fromisoformat(r_["observation"]["observed_at"])
                         if r_["observation"].get("observed_at") else observed_at
                         for r_ in records)
            repo.write_snapshot_merchant(
                conn, group_snapshot, merchant_id, captured_at=latest,
                scope_producer_key=repo.producer_key_of(repo.get_wine(conn, wine_id)),
                scope_vintage=vintage, scope_wine_id=wine_id,
                scope_params={"acquisition_source": source}, written=w, rejected=r)

    reasons = {row["reason"]: row["n"] for row in conn.execute(
        """SELECT reason, count(*) AS n FROM offer_reject WHERE snapshot_id = ANY(%s)
            GROUP BY reason ORDER BY reason""", ([str(x) for x in snapshots],)).fetchall()}
    return {
        "source": source,
        "observations": len(observations),
        "written": written,
        "rejected": rejected,
        "rejected_by_reason": reasons,
        "unattributed_observations": unattributed,
        "merchants_mapped": mapped,
        "merchants_created": created,
        "unapproved_merchants": sorted(m for m, ok in approval.items() if not ok),
        "written_to_unapproved_merchants": unapproved_written,
        "snapshots": len(snapshots),
    }
