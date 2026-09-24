#!/usr/bin/env python
"""Load the vintage quality register from its CSV into `vintage_tier`.

    python scripts/load_vintage_tiers.py
    python scripts/load_vintage_tiers.py --file docs/research/vintage-tiers.csv --dry-run

The register is a file in the repo (docs/research/vintage-tiers.csv), reviewed
as a pull request, not a console screen: a tier change decides which prices are
treated as outliers, so it belongs in history where it can be argued with.

The load is idempotent — a row per (region, vintage), replaced on conflict — and
runs in one transaction. `set_by` records the file and the revision it came
from, because no person types into this table.

A region absent from the register has no band at all: the check stays quiet for
it rather than comparing a great vintage with a weak one. That is the correct
failure, so this script never invents a row for a missing year.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CSV = ROOT / "docs/research/vintage-tiers.csv"
COLUMNS = ("region", "vintage", "tier", "tier_label", "sources", "note")
LABELS = {1: "great", 2: "excellent", 3: "solid", 4: "ordinary", 5: "weak"}


def revision_of(path: Path) -> str:
    """The file's git revision, so a row can be traced to the version that set
    it. An uncommitted file says so rather than claiming a revision."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h %cs", "--", str(path)],
                             cwd=ROOT, capture_output=True, text=True, check=True)
        revision = out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = ""
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(path)],
                           cwd=ROOT, capture_output=True, text=True).stdout.strip()
    name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    if dirty or not revision:
        return f"{name} (uncommitted)"
    return f"{name} @ {revision}"


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = set(COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{path}: missing column(s) {', '.join(sorted(missing))}")
        rows = list(reader)

    seen, out = set(), []
    for n, row in enumerate(rows, start=2):
        region = (row["region"] or "").strip().upper()
        try:
            vintage, tier = int(row["vintage"]), int(row["tier"])
        except ValueError:
            raise SystemExit(f"{path}:{n}: vintage and tier must be whole numbers")
        if not region:
            raise SystemExit(f"{path}:{n}: region is required")
        if not 1 <= tier <= 5:
            raise SystemExit(f"{path}:{n}: tier {tier} is outside 1-5")
        label = (row["tier_label"] or "").strip().lower()
        if label != LABELS[tier]:
            raise SystemExit(f"{path}:{n}: tier {tier} is {LABELS[tier]!r}, not {label!r}")
        if not (row["sources"] or "").strip():
            raise SystemExit(f"{path}:{n}: sources is required — an unsourced tier is an opinion")
        if (region, vintage) in seen:
            raise SystemExit(f"{path}:{n}: {region} {vintage} appears twice")
        seen.add((region, vintage))
        out.append({"region": region, "vintage": vintage, "tier": tier, "tier_label": label,
                    "sources": row["sources"].strip(), "note": (row["note"] or "").strip() or None})
    return out


def load(rows: list[dict], set_by: str) -> tuple[int, int]:
    from app.db.connection import transaction

    with transaction() as conn:
        before = conn.execute("SELECT count(*) AS n FROM vintage_tier").fetchone()["n"]
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO vintage_tier
                       (region, vintage, tier, tier_label, sources, note, set_by, set_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                   ON CONFLICT (region, vintage) DO UPDATE
                      SET tier = EXCLUDED.tier, tier_label = EXCLUDED.tier_label,
                          sources = EXCLUDED.sources, note = EXCLUDED.note,
                          set_by = EXCLUDED.set_by, set_at = now()""",
                [(r["region"], r["vintage"], r["tier"], r["tier_label"], r["sources"],
                  r["note"], set_by) for r in rows])
        after = conn.execute("SELECT count(*) AS n FROM vintage_tier").fetchone()["n"]
    return before, after


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the file and print what would be written")
    args = ap.parse_args()

    rows = read_rows(args.file)
    regions = sorted({r["region"] for r in rows})
    print(f"{args.file}: {len(rows)} rows, {len(regions)} region(s): {', '.join(regions)}")
    for region in regions:
        years = sorted(r["vintage"] for r in rows if r["region"] == region)
        print(f"  {region}: {years[0]}-{years[-1]}")

    if args.dry_run:
        print("dry run: nothing written")
        return
    before, after = load(rows, revision_of(args.file))
    print(f"vintage_tier: {before} rows before, {after} after")


if __name__ == "__main__":
    main()
