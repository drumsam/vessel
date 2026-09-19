"""Row <-> core-model conversion and every SQL statement the service runs.

Nothing here makes a pricing decision. It loads what the deterministic core
needs, hands it over, and persists exactly what the core returned.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

from app.adapters.base import Candidate
from app.core.benchmark import BenchmarkResult
from app.core.enums import ConditionFlag, DutyStatus, PriceKind, StockType
from app.core.models import Offer, SellerLine
from app.identity.resolver import (
    STRUCTURAL_EXCLUSIONS,
    Alias,
    CanonicalWine,
    Registry,
    wine_key,
)

CENT = Decimal("0.01")


class Conflict(Exception):
    """A write that would break an identity guard rail."""


# ------------------------------------------------------------------- money


def exact_money(value: Optional[Decimal]) -> Optional[Decimal]:
    """A price that must already be whole pence. numeric(14,2) would round a
    third decimal place silently on insert, so refuse instead."""
    if value is None:
        return None
    if value != value.quantize(CENT):
        raise ValueError(f"{value} is not a whole number of pence")
    return value


def median_money(value: Optional[Decimal]) -> Optional[Decimal]:
    """The median of an even number of merchant-bests can land on half a penny
    (e.g. £100.01 and £100.02). uk_median is numeric(14,2), so round it here,
    explicitly and banker's-rounded, rather than let Postgres do it silently.
    The median is internal evidence; Floor and Reference are always exact."""
    if value is None:
        return None
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------- identity


def load_registry(conn: psycopg.Connection) -> Registry:
    wines = [
        CanonicalWine(str(r["wine_id"]), r["producer"], r["cuvee"], r["lwin7"])
        for r in conn.execute("SELECT wine_id, producer, cuvee, lwin7 FROM wine")
    ]
    aliases = [
        Alias(key=r["wine_key"], wine_id=str(r["wine_id"]), approved_by=r["approved_by"],
              approved_at=r["approved_at"].isoformat(), note=r["note"] or "")
        for r in conn.execute(
            "SELECT wine_key, wine_id, approved_by, approved_at, note FROM wine_alias")
    ]
    return Registry(wines, aliases)


def create_wine(conn: psycopg.Connection, *, producer: str, cuvee: str,
                region: str | None, colour: str | None, lwin7: str | None) -> dict:
    return conn.execute(
        """INSERT INTO wine (producer, cuvee, region, colour, lwin7, wine_key)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (producer, cuvee, region, colour, lwin7, wine_key(producer, cuvee)),
    ).fetchone()


def get_wine(conn: psycopg.Connection, wine_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM wine WHERE wine_id = %s", (wine_id,)).fetchone()


def list_wines(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT * FROM wine ORDER BY producer, cuvee").fetchall()


def create_alias(conn: psycopg.Connection, *, wine_id: str, producer_text: str,
                 cuvee_text: str, source: str, approved_by: str,
                 note: str | None) -> dict:
    """Enforce the guard rails at write time. An alias may never point a key at
    a wine other than the one that key already names, and may never bridge a
    structural exclusion (grand vin vs second wine, adjacent climats)."""
    key = wine_key(producer_text, cuvee_text)
    target = get_wine(conn, wine_id)
    if target is None:
        raise LookupError(wine_id)

    owner = conn.execute("SELECT wine_id FROM wine WHERE wine_key = %s", (key,)).fetchone()
    if owner and str(owner["wine_id"]) != str(wine_id):
        raise Conflict(f"{key!r} is the canonical key of wine {owner['wine_id']}")

    for a, b in STRUCTURAL_EXCLUSIONS:
        if {key, target["wine_key"]} == {a, b}:
            raise Conflict(f"{a!r} and {b!r} are a structural exclusion")

    if owner:
        excluded = conn.execute(
            """SELECT reason FROM wine_exclusion
               WHERE (wine_id_a = %(x)s AND wine_id_b = %(y)s)
                  OR (wine_id_a = %(y)s AND wine_id_b = %(x)s)""",
            {"x": owner["wine_id"], "y": wine_id},
        ).fetchone()
        if excluded:
            raise Conflict(f"wine_exclusion: {excluded['reason']}")

    return conn.execute(
        """INSERT INTO wine_alias (wine_key, wine_id, source, approved_by, note)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (key, wine_id, source, approved_by, note),
    ).fetchone()


# --------------------------------------------------------------- merchants


def list_merchants(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT * FROM merchant ORDER BY merchant_id").fetchall()


# ------------------------------------------------------------ deals, lines


def create_deal(conn: psycopg.Connection, deal: dict, lines: list[dict]) -> dict:
    row = conn.execute(
        """INSERT INTO deal (name, seller, source_file, currency, created_by)
           VALUES (%(name)s, %(seller)s, %(source_file)s, %(currency)s, %(created_by)s)
           RETURNING *""",
        deal,
    ).fetchone()
    for ln in lines:
        conn.execute(
            """INSERT INTO seller_line (deal_id, row_index, raw_description, raw_row,
                                        quantity, cost, cost_currency)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (row["deal_id"], ln["row_index"], ln["raw_description"], Jsonb(ln["raw_row"]),
             ln["quantity"], exact_money(ln.get("cost")), ln.get("cost_currency")),
        )
    return row


def get_deal(conn: psycopg.Connection, deal_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM deal WHERE deal_id = %s", (deal_id,)).fetchone()


def deal_lines(conn: psycopg.Connection, deal_id: str) -> list[dict]:
    return conn.execute(
        "SELECT * FROM seller_line WHERE deal_id = %s ORDER BY row_index", (deal_id,)
    ).fetchall()


def get_line(conn: psycopg.Connection, line_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM seller_line WHERE line_id = %s", (line_id,)).fetchone()


def set_line_identity(conn: psycopg.Connection, line_id: str, *, wine_id: str,
                      vintage: int, bottle_ml: int, pack_size: int) -> Optional[dict]:
    """Writes the approved identity columns and nothing else. raw_description
    and raw_row are not in this statement and cannot be touched by it."""
    return conn.execute(
        """UPDATE seller_line
              SET wine_id = %s, vintage = %s, bottle_ml = %s, pack_size = %s
            WHERE line_id = %s
        RETURNING *""",
        (wine_id, vintage, bottle_ml, pack_size, line_id),
    ).fetchone()


def seller_line_for_benchmark(row: dict) -> Optional[SellerLine]:
    """None when identity or format has not been approved. Such a line is not
    benchmarked at all; it is not NO_MARKET, because nobody looked."""
    if any(row[k] is None for k in ("wine_id", "vintage", "bottle_ml", "pack_size")):
        return None
    return SellerLine(
        line_id=str(row["line_id"]),
        raw_description=row["raw_description"],
        wine_id=str(row["wine_id"]),
        vintage=row["vintage"],
        bottle_ml=row["bottle_ml"],
        pack_size=row["pack_size"],
        quantity=row["quantity"],
        cost=row["cost"],
        cost_currency=row["cost_currency"],
    )


# --------------------------------------------------------------- snapshots


def create_snapshot(conn: psycopg.Connection, *, captured_at: datetime,
                    schema_version: str, is_demo: bool) -> str:
    return conn.execute(
        """INSERT INTO snapshot (captured_at, schema_version, is_demo)
           VALUES (%s, %s, %s) RETURNING snapshot_id""",
        (captured_at, schema_version, is_demo),
    ).fetchone()["snapshot_id"]


def finish_snapshot(conn: psycopg.Connection, snapshot_id: str, *, attempted: int,
                    succeeded: int, written: int, rejected: int, failures: list[dict]) -> None:
    conn.execute(
        """UPDATE snapshot
              SET adapters_attempted = %s, adapters_succeeded = %s,
                  offers_written = %s, offers_rejected = %s, failures = %s
            WHERE snapshot_id = %s""",
        (attempted, succeeded, written, rejected, Jsonb(failures), snapshot_id),
    )


def get_snapshot(conn: psycopg.Connection, snapshot_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM snapshot WHERE snapshot_id = %s",
                        (snapshot_id,)).fetchone()


def latest_snapshot_id(conn: psycopg.Connection) -> Optional[str]:
    row = conn.execute(
        """SELECT snapshot_id FROM snapshot
            WHERE NOT is_demo AND adapters_succeeded > 0
            ORDER BY captured_at DESC LIMIT 1""").fetchone()
    return row and row["snapshot_id"]


def write_offer(conn: psycopg.Connection, snapshot_id: str, o: Offer) -> None:
    conn.execute(
        """INSERT INTO offer (snapshot_id, offer_id, merchant_id, wine_id, vintage,
                              bottle_ml, pack_size, price, currency, duty_status,
                              price_kind, is_buyable, offered_units, is_mixed_lot,
                              stock_type, stock_type_basis, condition_flags,
                              condition_notes, source_url, captured_at, raw)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s)""",
        (snapshot_id, o.offer_id, o.merchant_id, o.wine_id, o.vintage, o.bottle_ml,
         o.pack_size, exact_money(o.price), o.currency, o.duty_status.value,
         o.price_kind.value, o.is_buyable, o.offered_units, o.is_mixed_lot,
         o.stock_type.value, o.stock_type_basis,
         sorted(f.value for f in o.condition_flags), o.condition_notes,
         o.source_url, o.captured_at, Jsonb(o.raw)),
    )


def write_reject(conn: psycopg.Connection, snapshot_id: str, merchant_id: str,
                 reason: str, detail: str, raw: dict) -> None:
    conn.execute(
        """INSERT INTO offer_reject (snapshot_id, merchant_id, reason, detail, raw)
           VALUES (%s, %s, %s, %s, %s)""",
        (snapshot_id, merchant_id, reason, detail, Jsonb(raw)),
    )


def unresolved_raw(c: Candidate) -> dict:
    """What an UNRESOLVED_IDENTITY reject keeps: the merchant's record exactly as
    published plus the names identity resolution was given, so the candidate can
    be re-resolved once an operator approves an alias."""
    return {"merchant_record": c.offer.raw,
            "producer_text": c.producer_text,
            "cuvee_text": c.cuvee_text,
            "offer_id": c.offer.offer_id}


# --------------------------------------------------------------- benchmark


_OFFER_COLUMNS = """o.offer_pk, o.merchant_id, m.name AS merchant_name, o.wine_id,
    o.vintage, o.bottle_ml, o.pack_size, o.price, o.currency, o.duty_status,
    o.price_kind, o.is_buyable, o.offered_units, o.is_mixed_lot, o.stock_type,
    o.stock_type_basis, o.condition_flags, o.condition_notes, o.source_url,
    o.captured_at, o.raw"""


def offer_from_row(r: dict) -> Offer:
    """`offer_id` on the core model carries offer_pk, so a benchmark result can
    be persisted back against the exact row it was computed from."""
    return Offer(
        offer_id=str(r["offer_pk"]),
        merchant_id=r["merchant_id"],
        merchant=r["merchant_name"],
        wine_id=str(r["wine_id"]) if r["wine_id"] else "",
        vintage=r["vintage"],
        bottle_ml=r["bottle_ml"],
        pack_size=r["pack_size"],
        price=r["price"],
        currency=r["currency"],
        duty_status=DutyStatus(r["duty_status"]),
        price_kind=PriceKind(r["price_kind"]),
        is_buyable=r["is_buyable"],
        offered_units=r["offered_units"],
        stock_type=StockType(r["stock_type"]),
        stock_type_basis=r["stock_type_basis"],
        is_mixed_lot=r["is_mixed_lot"],
        condition_flags=frozenset(ConditionFlag(f) for f in r["condition_flags"]),
        condition_notes=r["condition_notes"],
        source_url=r["source_url"],
        captured_at=r["captured_at"],
        raw=r["raw"],
    )


def offers_for_wine(conn: psycopg.Connection, snapshot_id: str, wine_id: str) -> list[Offer]:
    """Every offer in the snapshot for this approved wine, from approved
    merchants only. All vintages and formats are loaded on purpose: the core
    decides comparability and records why each one was rejected."""
    rows = conn.execute(
        f"""SELECT {_OFFER_COLUMNS}
              FROM offer o JOIN merchant m USING (merchant_id)
             WHERE o.snapshot_id = %s AND o.wine_id = %s AND m.approved""",
        (snapshot_id, wine_id),
    ).fetchall()
    return [offer_from_row(r) for r in rows]


def save_benchmark(conn: psycopg.Connection, result: BenchmarkResult,
                   snapshot_id: str) -> str:
    run_id = conn.execute(
        """INSERT INTO benchmark_run (line_id, snapshot_id, uk_floor, uk_reference,
                                      uk_median, comp_count, duplicate_listings,
                                      flags, state)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
        (result.line.line_id, snapshot_id, exact_money(result.uk_floor),
         exact_money(result.uk_reference), median_money(result.uk_median),
         result.comp_count, result.duplicate_listings,
         sorted(f.value for f in result.flags), result.state.value),
    ).fetchone()["run_id"]

    rows: list[tuple[Any, ...]] = []
    rows += [(run_id, o.offer_id, "comparable", None) for o in result.comparables]
    rows += [(run_id, o.offer_id, "merchant_best", None) for o in result.merchant_bests]
    rows += [(run_id, c.offer.offer_id, "cross_unit", None) for c in result.cross_unit]
    rows += [(run_id, r.offer.offer_id, "rejected", r.reason.value) for r in result.rejections]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO benchmark_comp (run_id, offer_pk, role, reject_reason)
               VALUES (%s, %s, %s, %s)""", rows)
    return run_id


def latest_run(conn: psycopg.Connection, line_id: str) -> Optional[dict]:
    return conn.execute(
        """SELECT * FROM benchmark_run WHERE line_id = %s
            ORDER BY computed_at DESC LIMIT 1""", (line_id,)).fetchone()


def run_comps(conn: psycopg.Connection, run_id: str) -> list[dict]:
    return conn.execute(
        f"""SELECT c.role, c.reject_reason, {_OFFER_COLUMNS}, o.offer_id AS merchant_offer_id
              FROM benchmark_comp c
              JOIN offer o USING (offer_pk)
              JOIN merchant m ON m.merchant_id = o.merchant_id
             WHERE c.run_id = %s
             ORDER BY c.role, o.price""", (run_id,)).fetchall()
