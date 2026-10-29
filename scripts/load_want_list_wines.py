#!/usr/bin/env python
"""Load the want-list wine register from its CSV into `wine`.

    python scripts/load_want_list_wines.py
    python scripts/load_want_list_wines.py --file docs/research/want-list-wines.csv --dry-run

Decision 0043, over Doug's own instruction: "STORE IT PROPERLY — not as a
CSV in docs/." The CSV (docs/research/want-list-wines.csv) stays — it is
the seed input and the audit trail, reviewed as a pull request same as
`vintage-tiers.csv` is — but the DATABASE is the artefact an operator or
the resolver actually reads. Migration 0029 already added `wine.want_list`
and the acknowledgement fields (decision 0038); migration 0033 added the
five columns this script actually writes (appellation, classification,
monopole, source, notes) — this script is the DATA for that structure, not
a new one.

The load is idempotent — one row per `wine_key` (producer|cuvee,
normalised), replaced on conflict — and runs in one transaction. A row
whose `source` starts "UNVERIFIED" is loaded exactly like any other: the
distinction is visible to a person reading `wine.source`, not hidden by
refusing to load it, and not blurred by loading it silently either.

register row != pricing identity. `wine.release_code` stays NULL for
every row this script writes: the register lists the CUVÉES a producer
makes, not a specific release-coded instance (a Krug edition, a Dom
Pérignon Plénitude). A live merchant offer that carries one still goes
through the ordinary identity-resolution path (decision 0019) and gets
its own, separate `wine` row the first time it is seen, approved by an
operator exactly as any new wine is — this script never invents one.

`want_list` is set from `is_want_list_producer`, the same function
`create_wine` uses at write time (decision 0038) — never hardcoded true,
so a producer-name mismatch between this CSV and `app.identity.want_list`
is a loud KeyError-shaped failure here, not a silent gap in the gate.

`--alias-operator <username>` also loads `ALIASES` below into
`wine_alias` — Berry Bros prints "Mazy-Chambertin" where the appellation
is Mazis; without the alias, Rousseau's real Mazis-Chambertin line never
matches this register's own row. `wine_alias.approved_by` is a real
`operator_id` FK (invariant 14: who did something is the server's
answer, never invented by a script) with `source='import'` — the one
value the column's own CHECK constraint allows for exactly this case —
so this is skipped, loudly, rather than guessed, when no operator is
named.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_CSV = ROOT / "docs/research/want-list-wines.csv"
COLUMNS = ("producer", "cuvee", "appellation", "classification", "colour",
          "monopole", "source", "notes")

#: The three Champagne producers decision 0043 added; everything else in
#: the register is Burgundy. Not derived from appellation text (a Krug
#: Clos du Mesnil's own appellation names the lieu-dit, not "Champagne")
#: — this is the one place that distinction is made, and it is a closed,
#: short list because the register itself is.
CHAMPAGNE_PRODUCERS = frozenset({"krug", "jacques selosse", "dom perignon"})

_VALID_MONOPOLE = {"yes": True, "no": False, "unconfirmed": False}
_VALID_COLOUR = {"red", "white", "rose", "rosé"}

#: (producer, merchant's own spelling, cuvee this register uses) — every
#: live-data alias found while building the register (decision 0043).
#: Loaded into `wine_alias` only when `--alias-operator` names a real
#: operator; see the module docstring for why that cannot be guessed.
ALIASES: tuple[tuple[str, str, str], ...] = (
    ("Domaine Armand Rousseau", "Mazy-Chambertin", "Mazis-Chambertin"),
)


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = set(COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"{path}: missing column(s) {', '.join(sorted(missing))}")
        rows = list(reader)

    from app.identity.resolver import norm, wine_key

    seen: set[str] = set()
    out = []
    for n, row in enumerate(rows, start=2):
        producer = (row["producer"] or "").strip()
        cuvee = (row["cuvee"] or "").strip()
        if not producer or not cuvee:
            raise SystemExit(f"{path}:{n}: producer and cuvee are both required")
        key = wine_key(producer, cuvee)
        if key in seen:
            raise SystemExit(f"{path}:{n}: {producer} / {cuvee} appears twice")
        seen.add(key)

        colour = (row["colour"] or "").strip()
        if colour and colour.lower() not in _VALID_COLOUR:
            raise SystemExit(f"{path}:{n}: colour {colour!r} is not Red/White/Rosé")

        monopole_raw = (row["monopole"] or "no").strip().lower()
        if monopole_raw not in _VALID_MONOPOLE:
            raise SystemExit(
                f"{path}:{n}: monopole {monopole_raw!r} must be yes/no/unconfirmed")

        source = (row["source"] or "").strip()
        if not source:
            raise SystemExit(f"{path}:{n}: source is required — an unsourced row is a guess")
        notes = (row["notes"] or "").strip()
        if monopole_raw == "unconfirmed":
            notes = f"{notes} [monopole: unconfirmed]".strip()

        region = "Champagne" if norm(producer) in CHAMPAGNE_PRODUCERS else "Burgundy"

        out.append({
            "producer": producer, "cuvee": cuvee, "wine_key": key, "region": region,
            "appellation": (row["appellation"] or "").strip() or None,
            "classification": (row["classification"] or "").strip() or None,
            "colour": colour or None,
            "monopole": _VALID_MONOPOLE[monopole_raw],
            "source": source, "notes": notes or None,
        })
    return out


def revision_of(path: Path) -> str:
    """The file's git revision, so a row can be traced to the version
    that set it — same discipline as `load_vintage_tiers.py`."""
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


def load(rows: list[dict], loaded_from: str) -> tuple[int, int]:
    from app.identity.want_list import is_want_list_producer
    from app.db.connection import transaction

    with transaction() as conn:
        before = conn.execute("SELECT count(*) AS n FROM wine").fetchone()["n"]
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO wine
                       (producer, cuvee, region, colour, wine_key, want_list,
                        appellation, classification, monopole, source, notes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (wine_key) DO UPDATE
                      SET region = EXCLUDED.region, colour = EXCLUDED.colour,
                          appellation = EXCLUDED.appellation,
                          classification = EXCLUDED.classification,
                          monopole = EXCLUDED.monopole, source = EXCLUDED.source,
                          notes = EXCLUDED.notes
                      -- producer, cuvee and want_list are NEVER overwritten here:
                      -- an operator may have corrected a live wine's own producer/
                      -- cuvee text since this row was first loaded, and this script
                      -- must not silently revert that correction on a re-run.
                """,
                [(r["producer"], r["cuvee"], r["region"], r["colour"], r["wine_key"],
                  is_want_list_producer(r["producer"]), r["appellation"],
                  r["classification"], r["monopole"], f"{r['source']} (via {loaded_from})",
                  r["notes"])
                 for r in rows])
        after = conn.execute("SELECT count(*) AS n FROM wine").fetchone()["n"]
    return before, after


def load_aliases(operator_username: str) -> int:
    """`ALIASES` into `wine_alias`, `source='import'`, `approved_by` the
    named operator's real id. Raises if the operator or the target wine
    (producer, right_cuvee) is not found — both are "this cannot be
    guessed" failures, not something to skip quietly."""
    from app.identity.resolver import wine_key as make_key
    from app.db.connection import transaction

    with transaction() as conn:
        op = conn.execute("SELECT operator_id FROM operator WHERE username = %s",
                          (operator_username,)).fetchone()
        if op is None:
            raise SystemExit(f"no operator named {operator_username!r}")
        operator_id = op["operator_id"]

        n = 0
        for producer, wrong_cuvee, right_cuvee in ALIASES:
            target = conn.execute("SELECT wine_id FROM wine WHERE wine_key = %s",
                                  (make_key(producer, right_cuvee),)).fetchone()
            if target is None:
                raise SystemExit(
                    f"alias target not found: {producer} / {right_cuvee} "
                    "— load the register itself first")
            conn.execute(
                """INSERT INTO wine_alias (wine_key, wine_id, source, approved_by, note)
                   VALUES (%s, %s, 'import', %s, %s)
                   ON CONFLICT (wine_key) DO UPDATE
                      SET wine_id = EXCLUDED.wine_id, approved_by = EXCLUDED.approved_by,
                          approved_at = now(), note = EXCLUDED.note""",
                (make_key(producer, wrong_cuvee), target["wine_id"], operator_id,
                 f"{producer}'s own spelling confirmed live: {wrong_cuvee!r} is this "
                 f"register's {right_cuvee!r} (decision 0043)"))
            n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the file and print what would be written")
    ap.add_argument("--alias-operator",
                    help="username to attribute ALIASES to in wine_alias (decision 0043); "
                         "omit to skip loading aliases")
    args = ap.parse_args()

    rows = read_rows(args.file)
    producers = sorted({r["producer"] for r in rows})
    unverified = sum(1 for r in rows if r["source"].upper().startswith("UNVERIFIED"))
    monopoles = sum(1 for r in rows if r["monopole"])
    print(f"{args.file}: {len(rows)} wines, {len(producers)} producer(s), "
         f"{unverified} unverified, {monopoles} monopole(s)")
    for producer in producers:
        count = sum(1 for r in rows if r["producer"] == producer)
        print(f"  {producer}: {count}")

    if args.dry_run:
        print(f"would also load {len(ALIASES)} alias(es)" if args.alias_operator
             else f"{len(ALIASES)} alias(es) defined, no --alias-operator given, would skip")
        print("dry run: nothing written")
        return
    before, after = load(rows, revision_of(args.file))
    print(f"wine: {before} rows before, {after} after")

    if args.alias_operator:
        n = load_aliases(args.alias_operator)
        print(f"wine_alias: {n} alias(es) loaded, attributed to {args.alias_operator!r}")
    else:
        print(f"{len(ALIASES)} alias(es) defined but not loaded — pass "
             "--alias-operator <username> to load them")


if __name__ == "__main__":
    main()
