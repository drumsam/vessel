"""Feed adapters implement collect(unit) -> Iterable[Candidate]. No Pocket coupling."""
from dataclasses import dataclass
from datetime import timedelta
import json
from typing import Iterable, Protocol
from uuid import uuid4
from ..observations.models import Candidate, MarketUnit, timestamp, utcnow


class Collector(Protocol):
    source_id: str
    def collect(self, unit: MarketUnit) -> Iterable[Candidate]: ...


def run_source(store, collector, unit):
    run_id = str(uuid4())
    written = rejected = 0
    error = None
    with store.connection() as db:
        db.execute("INSERT INTO source_runs(run_id,source,started_at,status) VALUES (?,?,?,'RUNNING')",
                   (run_id, collector.source_id, utcnow().isoformat()))
    try:
        for candidate in collector.collect(unit):
            try:
                if candidate.source_id != collector.source_id:
                    raise ValueError("Adapter source mismatch")
                written += int(store.ingest(candidate) is not None)
            except (ValueError, TypeError):
                rejected += 1
    except Exception:
        # Do not persist exception messages that may contain authenticated URLs or secrets.
        error = "Collector failed; inspect adapter diagnostics with credentials redacted"
    status = "FAILED" if error else "PARTIAL" if rejected else "SUCCEEDED"
    with store.connection() as db:
        db.execute('''UPDATE source_runs SET finished_at=?,status=?,observations_written=?,
                      observations_rejected=?,error=? WHERE run_id=?''',
                   (utcnow().isoformat(), status, written, rejected, error, run_id))
    return {"run_id": run_id, "status": status, "written": written, "rejected": rejected}


def due_units(store, now=None):
    now = now or utcnow()
    with store.connection() as db:
        rows = db.execute("SELECT * FROM universe WHERE universe='CORE'").fetchall()
        requested = {r[0] for r in db.execute("SELECT unit_key FROM refresh_requests")}
    due = set(requested)
    for row in rows:
        interval = {"A": 7, "B": 14, "C": 30}[row["priority"]]
        if row["last_success"] is None or now - timestamp(row["last_success"]) >= timedelta(days=interval):
            due.add(row["unit_key"])
    return [MarketUnit(**json.loads(key)) for key in sorted(due)]


def refresh(store, collectors, now=None):
    now = now or utcnow()
    results = []
    for unit in due_units(store, now):
        runs = [run_source(store, c, unit) for c in collectors]
        ok = bool(runs) and all(r["status"] == "SUCCEEDED" for r in runs)
        with store.connection() as db:
            db.execute("UPDATE universe SET last_attempt=? WHERE unit_key=?", (now.isoformat(), unit.key()))
            if ok:
                db.execute("UPDATE universe SET last_success=? WHERE unit_key=?", (now.isoformat(), unit.key()))
                db.execute("DELETE FROM refresh_requests WHERE unit_key=?", (unit.key(),))
        results.append({"unit": json.loads(unit.key()), "runs": runs, "complete": ok})
    return results
