"""Logical dump/restore for the real evidence store.

No pg_dump, no psql, no pg_restore: embedded-postgres (what scripts/desk.sh
drives) ships only postgres/initdb/pg_ctl, and Doug's machine has no system
Postgres client tools at all. This uses psycopg alone, which the project
already depends on, and is the actual backup mechanism decision 0032
describes: a dump taken after each deal, written to Dropbox, off the laptop.

Dump: every table, in foreign-key dependency order (parents before
children, read from the schema itself, never hand-maintained), as JSON
Lines -- one file. Decimal, UUID and datetime values are written as plain
strings, never through a float (invariant 7): a Decimal is tagged
{"__decimal__": "162.83"} so restore can tell it apart from an ordinary
string column and hand it back to psycopg as a Decimal, not a float, not a
guess. Generated columns (buyer_price_gbp, seller_price_gbp) are skipped
entirely -- Postgres computes them, and the dump doesn't carry a value
that would just be refused on restore.

Restore: run migrations first (recreates the schema from nothing), then
this re-inserts the dump's rows in the same table order.

    python scripts/evidence_backup.py dump <DATABASE_URL>
    python scripts/evidence_backup.py dump <DATABASE_URL> path/to/file.jsonl   # explicit path
    python scripts/evidence_backup.py restore <path/to/file.jsonl> <DATABASE_URL>

With no path, dump writes into DEFAULT_BACKUP_DIR below (Dropbox, off the
laptop, per decision 0032) with a timestamped name -- the right place is
the default so nobody has to remember it or pick a path by hand.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


#: Alembic's own bookkeeping, not evidence -- restore already has its own
#: row for it the moment migrations run, so dumping and reinserting it
#: would just collide on the primary key.
EXCLUDED_TABLES = {"alembic_version"}

#: Off the laptop, per decision 0032: a second file on the same disk is not
#: a second copy. Dropbox already syncs on Doug's machine, so a dump
#: written here is backed up the moment it's written, with no extra step.
DEFAULT_BACKUP_DIR = os.path.expanduser(
    "~/Library/CloudStorage/Dropbox/Workspace_Archive/UK_Fine_Wine_Pricer_Backups")


def table_order(conn: psycopg.Connection) -> list[str]:
    """Every public table, parents before children. A foreign-key cycle
    (none exist today) raises rather than looping forever or guessing."""
    tables = [r["table_name"] for r in conn.execute(
        """SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'""").fetchall()
        if r["table_name"] not in EXCLUDED_TABLES]
    depends_on: dict[str, set[str]] = {t: set() for t in tables}
    for r in conn.execute("""
        SELECT tc.table_name AS child, ccu.table_name AS parent
          FROM information_schema.table_constraints tc
          JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
         WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
    """).fetchall():
        if r["child"] != r["parent"]:
            depends_on[r["child"]].add(r["parent"])

    ordered: list[str] = []
    done: set[str] = set()

    def visit(table: str, trail: list[str]) -> None:
        if table in done:
            return
        if table in trail:
            raise RuntimeError(f"foreign key cycle: {' -> '.join(trail + [table])}")
        for parent in depends_on.get(table, ()):
            visit(parent, trail + [table])
        done.add(table)
        ordered.append(table)

    for t in tables:
        visit(t, [])
    return ordered


def generated_columns(conn: psycopg.Connection, table: str) -> set[str]:
    return {r["column_name"] for r in conn.execute(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND is_generated = 'ALWAYS'""",
        (table,)).fetchall()}


def column_types(conn: psycopg.Connection, table: str) -> dict[str, str]:
    return {r["column_name"]: r["data_type"] for r in conn.execute(
        """SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s""", (table,)).fetchall()}


def _json_default(value):
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return {"__timedelta_seconds__": value.total_seconds()}
    raise TypeError(f"cannot serialise {type(value)!r}")


def _restore_value(value, data_type: str):
    if data_type == "jsonb":
        return Jsonb(value) if value is not None else None
    if isinstance(value, dict) and set(value.keys()) == {"__decimal__"}:
        return Decimal(value["__decimal__"])
    if isinstance(value, dict) and set(value.keys()) == {"__timedelta_seconds__"}:
        return timedelta(seconds=value["__timedelta_seconds__"])
    return value


def dump(database_url: str, out_path: str) -> None:
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        tables = table_order(conn)
        counts: dict[str, int] = {}
        with open(out_path, "w") as f:
            for table in tables:
                gen = generated_columns(conn, table)
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
                f.write(json.dumps({"table": table, "count": len(rows)}) + "\n")
                for row in rows:
                    f.write(json.dumps({k: v for k, v in row.items() if k not in gen},
                                       default=_json_default) + "\n")
                counts[table] = len(rows)
    print(f"Dumped {sum(counts.values())} rows across {len(tables)} tables to {out_path}")
    for table, n in counts.items():
        if n:
            print(f"  {table}: {n}")


def restore(in_path: str, database_url: str) -> None:
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        counts: dict[str, int] = {}
        types_cache: dict[str, dict[str, str]] = {}
        current_table: str | None = None
        buffer: list[dict] = []

        def flush() -> None:
            if current_table is None or not buffer:
                return
            types = types_cache.setdefault(current_table, column_types(conn, current_table))
            for row in buffer:
                cols = list(row.keys())
                values = [_restore_value(row[c], types.get(c, "")) for c in cols]
                collist = ", ".join(f'"{c}"' for c in cols)
                placeholders = ", ".join(["%s"] * len(cols))
                # ON CONFLICT DO NOTHING: reference rows some migrations seed
                # themselves (merchant, vintage_tier) already exist on a
                # freshly-migrated target. Real evidence has no such seed, so
                # this never masks a genuine duplicate in practice.
                conn.execute(
                    f'INSERT INTO "{current_table}" ({collist}) VALUES ({placeholders}) '
                    "ON CONFLICT DO NOTHING", values)
            counts[current_table] = counts.get(current_table, 0) + len(buffer)
            buffer.clear()

        with open(in_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if set(obj.keys()) == {"table", "count"}:
                    flush()
                    current_table = obj["table"]
                else:
                    buffer.append(obj)
            flush()
        conn.commit()
    print(f"Restored {sum(counts.values())} rows across {len(counts)} tables from {in_path}")
    for table, n in counts.items():
        if n:
            print(f"  {table}: {n}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("dump")
    d.add_argument("database_url")
    d.add_argument("out_path", nargs="?", default=None)
    r = sub.add_parser("restore")
    r.add_argument("in_path")
    r.add_argument("database_url")
    args = parser.parse_args()
    if args.command == "dump":
        out_path = args.out_path
        if out_path is None:
            os.makedirs(DEFAULT_BACKUP_DIR, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
            out_path = os.path.join(DEFAULT_BACKUP_DIR, f"evidence-{stamp}.jsonl")
        dump(args.database_url, out_path)
    else:
        restore(args.in_path, args.database_url)


if __name__ == "__main__":
    main()
