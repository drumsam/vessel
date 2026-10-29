"""SQLite persistence with append-only evidence and atomic cache invalidation."""
from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import sqlite3
from uuid import uuid4
from .models import Candidate, MarketUnit, UnresolvedIdentity, utcnow

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS observations (
 observation_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
 unit_key TEXT, resolution_state TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observation_unit ON observations(unit_key);
CREATE TABLE IF NOT EXISTS snapshots (unit_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_runs (
 run_id TEXT PRIMARY KEY, source TEXT NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, status TEXT NOT NULL, observations_written INTEGER NOT NULL DEFAULT 0,
 observations_rejected INTEGER NOT NULL DEFAULT 0, error TEXT
);
CREATE TABLE IF NOT EXISTS universe (
 unit_key TEXT PRIMARY KEY, universe TEXT NOT NULL, priority TEXT,
 last_attempt TEXT, last_success TEXT
);
CREATE TABLE IF NOT EXISTS refresh_requests (
 unit_key TEXT PRIMARY KEY, requested_at TEXT NOT NULL
);
'''


class Store:
    def __init__(self, path, resolver=None):
        self.path = str(path)
        self.resolver = resolver or UnresolvedIdentity()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, candidate: Candidate):
        candidate.validate()
        unit = self.resolver.resolve(dict(candidate.identity))
        if unit is not None and not isinstance(unit, MarketUnit):
            raise ValueError("Canonical resolver must return MarketUnit or None")
        if unit and unit.currency != candidate.currency:
            raise ValueError("Resolver currency disagrees with observation")
        payload = asdict(candidate)
        payload["price"] = str(candidate.price)
        payload["unit"] = asdict(unit) if unit else None
        # Identity resolution can change later; original evidence deduplicates independently.
        evidence = {k: v for k, v in payload.items() if k != "unit"}
        fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        oid = str(uuid4())
        with self.connection() as db:
            result = db.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)",
                (oid, fingerprint, unit.key() if unit else None,
                 "RESOLVED" if unit else "UNRESOLVED", json.dumps(payload), utcnow().isoformat()))
            if not result.rowcount:
                return None
            if unit:
                db.execute("DELETE FROM snapshots WHERE unit_key=?", (unit.key(),))
        return oid

    def observations(self, unit=None, unresolved=False):
        sql = "SELECT * FROM observations"
        params = ()
        if unit:
            sql += " WHERE unit_key=?"
            params = (unit.key(),)
        elif unresolved:
            sql += " WHERE resolution_state='UNRESOLVED'"
        sql += " ORDER BY created_at, observation_id"
        with self.connection() as db:
            rows = db.execute(sql, params).fetchall()
        return [{**json.loads(r["payload"]), "observation_id": r["observation_id"],
                 "resolution_state": r["resolution_state"], "created_at": r["created_at"]} for r in rows]

    def resolve_pending(self):
        resolved = 0
        for row in self.observations(unresolved=True):
            unit = self.resolver.resolve(dict(row["identity"]))
            if unit is None:
                continue
            if not isinstance(unit, MarketUnit) or unit.currency != row["currency"]:
                raise ValueError("Invalid canonical resolution")
            with self.connection() as db:
                original = json.loads(db.execute("SELECT payload FROM observations WHERE observation_id=?",
                                               (row["observation_id"],)).fetchone()[0])
                original["unit"] = asdict(unit)
                db.execute("UPDATE observations SET unit_key=?, resolution_state='RESOLVED', payload=? WHERE observation_id=?",
                           (unit.key(), json.dumps(original), row["observation_id"]))
                db.execute("DELETE FROM snapshots WHERE unit_key=?", (unit.key(),))
            resolved += 1
        return resolved

    def set_universe(self, unit, universe="DISCOVERY", priority=None):
        if universe not in {"CORE", "DISCOVERY"} or (universe == "CORE" and priority not in {"A", "B", "C"}):
            raise ValueError("CORE requires A/B/C priority")
        if universe == "DISCOVERY":
            priority = None
        with self.connection() as db:
            db.execute('''INSERT INTO universe(unit_key,universe,priority) VALUES (?,?,?)
             ON CONFLICT(unit_key) DO UPDATE SET universe=excluded.universe, priority=excluded.priority''',
                       (unit.key(), universe, priority))

    def request_refresh(self, unit):
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO refresh_requests VALUES (?,?)", (unit.key(), utcnow().isoformat()))

    def runs(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM source_runs ORDER BY started_at DESC")]
