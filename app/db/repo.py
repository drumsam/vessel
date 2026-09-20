"""Row <-> core-model conversion and every SQL statement the service runs.

Nothing here makes a pricing decision. It loads what the deterministic core
needs, hands it over, and persists exactly what the core returned.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

from app.adapters.base import Candidate
from app.core.benchmark import BenchmarkResult
from app.core.enums import ConditionFlag, DutyStatus, PriceKind, StockType
from app.core.flags import Flag
from app.core.models import Offer, SellerLine
from app.pricing.pricer import PricedLine
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
    """Every money value written to a numeric(14,2) column passes through here.
    numeric(14,2) would round a third decimal place silently on insert, so a
    value that is not whole pence is refused, never rounded. The one figure that
    is rounded (the Median) is rounded in app/core/benchmark.py, before it
    arrives here."""
    if value is None:
        return None
    if value != value.quantize(CENT):
        raise ValueError(f"{value} is not a whole number of pence")
    return value


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


def create_exclusion(conn: psycopg.Connection, wine_id_a: str, wine_id_b: str,
                     reason: str) -> dict:
    """A pair that must never collapse. Stored lower id first, once."""
    a, b = sorted([str(wine_id_a), str(wine_id_b)])
    if a == b:
        raise Conflict("a wine cannot be excluded from itself")
    return conn.execute(
        """INSERT INTO wine_exclusion (wine_id_a, wine_id_b, reason)
           VALUES (%s, %s, %s) RETURNING *""", (a, b, reason)).fetchone()


# ------------------------------------------------------------ LWIN conflicts


def untrusted_lwins(conn: psycopg.Connection, merchant_id: str) -> frozenset[str]:
    return frozenset(r["lwin7"] for r in conn.execute(
        "SELECT lwin7 FROM merchant_lwin_untrusted WHERE merchant_id = %s", (merchant_id,)))


def record_lwin_conflicts(conn: psycopg.Connection, merchant_id: str,
                          collisions: dict[str, list[str]]) -> None:
    """Open (or refresh) one review row per colliding LWIN. A conflict an
    operator has already resolved is not reopened."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO lwin_conflict (merchant_id, lwin7, names)
               VALUES (%s, %s, %s)
               ON CONFLICT (merchant_id, lwin7) DO UPDATE
                  SET names = EXCLUDED.names, last_seen_at = now()
                WHERE lwin_conflict.resolution IS NULL""",
            [(merchant_id, lwin7, Jsonb(names)) for lwin7, names in collisions.items()])


def list_lwin_conflicts(conn: psycopg.Connection, *, unresolved_only: bool = True) -> list[dict]:
    where = "WHERE resolution IS NULL" if unresolved_only else ""
    return conn.execute(
        f"SELECT * FROM lwin_conflict {where} ORDER BY last_seen_at DESC, lwin7").fetchall()


def get_lwin_conflict(conn: psycopg.Connection, conflict_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM lwin_conflict WHERE conflict_id = %s",
                        (conflict_id,)).fetchone()


def close_lwin_conflict(conn: psycopg.Connection, conflict_id: str, *, resolution: str,
                        resolved_by: str, note: str | None) -> dict:
    return conn.execute(
        """UPDATE lwin_conflict
              SET resolution = %s, resolved_by = %s, resolved_at = now(), note = %s
            WHERE conflict_id = %s RETURNING *""",
        (resolution, resolved_by, note, conflict_id)).fetchone()


def mark_lwin_untrusted(conn: psycopg.Connection, merchant_id: str, lwin7: str, *,
                        reason: str, marked_by: str) -> None:
    conn.execute(
        """INSERT INTO merchant_lwin_untrusted (merchant_id, lwin7, reason, marked_by)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (merchant_id, lwin7) DO UPDATE
              SET reason = EXCLUDED.reason, marked_by = EXCLUDED.marked_by, marked_at = now()""",
        (merchant_id, lwin7, reason, marked_by))


# --------------------------------------------------------------- merchants


def list_merchants(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT * FROM merchant ORDER BY merchant_id").fetchall()


# ------------------------------------------------------------ deals, lines


def create_deal(conn: psycopg.Connection, deal: dict, lines: list[dict]) -> dict:
    row = conn.execute(
        """INSERT INTO deal (name, seller, source_file, currency, target_margin, created_by)
           VALUES (%(name)s, %(seller)s, %(source_file)s, %(currency)s, %(target_margin)s,
                   %(created_by)s)
           RETURNING *""",
        deal,
    ).fetchone()
    for ln in lines:
        conn.execute(
            """INSERT INTO seller_line (deal_id, row_index, raw_description, raw_row,
                                        quantity, cost, cost_currency, target_margin,
                                        target_discount, manual_price)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (row["deal_id"], ln["row_index"], ln["raw_description"], Jsonb(ln["raw_row"]),
             ln["quantity"], exact_money(ln.get("cost")), ln.get("cost_currency"),
             ln.get("target_margin"), ln.get("target_discount"),
             exact_money(ln.get("manual_price"))),
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
                      vintage: int, bottle_ml: int, pack_size: int, flags: list[str],
                      source: str, approved_by: str) -> Optional[dict]:
    """Writes the approved identity, its approval and the line flags, and records
    the change, old and new, in seller_line_identity_history. raw_description
    and raw_row are not in either statement and cannot be touched by them."""
    prev = conn.execute("SELECT * FROM seller_line WHERE line_id = %s FOR UPDATE",
                        (line_id,)).fetchone()
    if prev is None:
        return None
    flags = sorted(set(flags))
    row = conn.execute(
        """UPDATE seller_line
              SET wine_id = %s, vintage = %s, bottle_ml = %s, pack_size = %s, flags = %s,
                  wine_id_source = %s, wine_id_approved_by = %s, wine_id_approved_at = now()
            WHERE line_id = %s
        RETURNING *""",
        (wine_id, vintage, bottle_ml, pack_size, flags, source, approved_by, line_id),
    ).fetchone()
    conn.execute(
        """INSERT INTO seller_line_identity_history
               (line_id, prev_wine_id, prev_vintage, prev_bottle_ml, prev_pack_size, prev_flags,
                new_wine_id, new_vintage, new_bottle_ml, new_pack_size, new_flags,
                source, changed_by, changed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (line_id, prev["wine_id"], prev["vintage"], prev["bottle_ml"], prev["pack_size"],
         prev["flags"], wine_id, vintage, bottle_ml, pack_size, flags, source, approved_by,
         row["wine_id_approved_at"]),
    )
    return row


def identity_history(conn: psycopg.Connection, line_id: str) -> list[dict]:
    return conn.execute(
        """SELECT * FROM seller_line_identity_history WHERE line_id = %s
            ORDER BY changed_at, history_id""", (line_id,)).fetchall()


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
        inherited_flags=frozenset(Flag(f) for f in row["flags"]),
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


def write_snapshot_merchant(conn: psycopg.Connection, snapshot_id: str, merchant_id: str, *,
                            captured_at: datetime, error: str | None = None,
                            scope_producer_key: str | None = None,
                            scope_vintage: int | None = None, scope_params: dict | None = None,
                            written: int = 0, rejected: int = 0) -> None:
    conn.execute(
        """INSERT INTO snapshot_merchant (snapshot_id, merchant_id, status, captured_at,
                                          scope_producer_key, scope_vintage, scope_params,
                                          offers_written, offers_rejected, error)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (snapshot_id, merchant_id, "failed" if error else "ok", captured_at,
         scope_producer_key, scope_vintage, Jsonb(scope_params or {}),
         written, rejected, error),
    )


def get_snapshot(conn: psycopg.Connection, snapshot_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM snapshot WHERE snapshot_id = %s",
                       (snapshot_id,)).fetchone()
    if row is not None:
        row["merchants"] = conn.execute(
            "SELECT * FROM snapshot_merchant WHERE snapshot_id = %s ORDER BY merchant_id",
            (snapshot_id,)).fetchall()
    return row


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
    o.captured_at, o.raw, o.offer_id AS merchant_offer_id"""


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


# Per merchant, independently: the latest successful capture at or before as_of
# whose scope covers this producer and vintage. A whole-book capture covers
# everything; a targeted search covers only what it searched. If a merchant's
# latest covering capture no longer lists the wine, the merchant contributes
# nothing: an older capture is never used to resurrect a sold listing.
_SOURCES_CTE = """
WITH ranked AS (
    SELECT sm.merchant_id, sm.snapshot_id, sm.captured_at,
           ROW_NUMBER() OVER (PARTITION BY sm.merchant_id
                              ORDER BY sm.captured_at DESC, sm.snapshot_id DESC) AS rn
      FROM snapshot_merchant sm
      JOIN snapshot s ON s.snapshot_id = sm.snapshot_id
      JOIN merchant m ON m.merchant_id = sm.merchant_id
     WHERE sm.status = 'ok' AND NOT s.is_demo AND m.approved
       AND sm.captured_at <= %(as_of)s
       AND (sm.scope_producer_key IS NULL
            OR (sm.scope_producer_key = %(producer_key)s AND sm.scope_vintage = %(vintage)s))
), src AS (SELECT merchant_id, snapshot_id, captured_at FROM ranked WHERE rn = 1)
"""


def producer_key_of(wine_row: dict) -> str:
    """The normalised producer, exactly as it appears in wine_key."""
    return wine_row["wine_key"].partition("|")[0]


@dataclass(frozen=True)
class Resolution:
    offers: list[Offer]
    sources: list[dict]                  # merchant_id, snapshot_id, captured_at
    merchant_offer_ids: dict[str, str]   # offer_pk -> the merchant's own offer id


def resolve_offers(conn: psycopg.Connection, *, wine_id: str, vintage: int,
                   as_of: datetime) -> Resolution:
    """Every offer for this approved wine from each
    merchant's resolved capture. All vintages and formats are loaded on purpose:
    the core decides comparability and records why each one was rejected."""
    wine = get_wine(conn, wine_id)
    params = {"as_of": as_of, "producer_key": producer_key_of(wine), "vintage": vintage,
              "wine_id": wine_id}
    sources = conn.execute(
        _SOURCES_CTE + "SELECT * FROM src ORDER BY merchant_id", params).fetchall()
    rows = conn.execute(
        _SOURCES_CTE + f"""
        SELECT {_OFFER_COLUMNS}
          FROM src
          JOIN offer o ON o.snapshot_id = src.snapshot_id AND o.merchant_id = src.merchant_id
          JOIN merchant m ON m.merchant_id = o.merchant_id
         WHERE o.wine_id = %(wine_id)s""", params).fetchall()
    return Resolution(offers=[offer_from_row(r) for r in rows], sources=sources,
                      merchant_offer_ids={str(r["offer_pk"]): r["merchant_offer_id"] for r in rows})


def offer_snapshot(o: Offer, merchant_offer_id: str,
                   per_bottle: Optional[Decimal] = None) -> dict:
    """The offer exactly as the benchmark used it. Money is a string, so it
    survives JSON without passing through a float. Migration 0003 builds the
    same document in SQL for runs that predate it."""
    return {
        "merchant_id": o.merchant_id, "merchant": o.merchant,
        "merchant_offer_id": merchant_offer_id,
        "wine_id": o.wine_id, "vintage": o.vintage, "bottle_ml": o.bottle_ml,
        "pack_size": o.pack_size, "price": str(exact_money(o.price)), "currency": o.currency,
        "duty_status": o.duty_status.value, "price_kind": o.price_kind.value,
        "is_buyable": o.is_buyable, "offered_units": o.offered_units,
        "is_mixed_lot": o.is_mixed_lot, "stock_type": o.stock_type.value,
        "stock_type_basis": o.stock_type_basis,
        "condition_flags": sorted(f.value for f in o.condition_flags),
        "condition_notes": o.condition_notes, "source_url": o.source_url,
        "captured_at": o.captured_at.isoformat() if o.captured_at else None,
        "per_bottle": str(per_bottle) if per_bottle is not None else None,
    }


def save_benchmark(conn: psycopg.Connection, result: BenchmarkResult,
                   resolution: Resolution) -> str:
    run_id = conn.execute(
        """INSERT INTO benchmark_run (line_id, as_of, uk_floor, uk_reference, uk_median,
                                      comp_count, duplicate_listings, flags, state,
                                      oldest_comp_age)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
        (result.line.line_id, result.as_of, exact_money(result.uk_floor),
         exact_money(result.uk_reference), exact_money(result.uk_median),
         result.comp_count, result.duplicate_listings,
         sorted(f.value for f in result.flags), result.state.value,
         result.oldest_comp_age),
    ).fetchone()["run_id"]

    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO benchmark_run_snapshot (run_id, merchant_id, snapshot_id, captured_at)
               VALUES (%s, %s, %s, %s)""",
            [(run_id, s["merchant_id"], s["snapshot_id"], s["captured_at"])
             for s in resolution.sources])

        rows: list[tuple[Any, ...]] = []
        rows += [(o, "comparable", None, None) for o in result.comparables]
        rows += [(o, "merchant_best", None, None) for o in result.merchant_bests]
        rows += [(c.offer, "cross_unit", None, c.per_bottle) for c in result.cross_unit]
        rows += [(r.offer, "rejected", r.reason.value, None) for r in result.rejections]
        cur.executemany(
            """INSERT INTO benchmark_comp (run_id, offer_pk, role, reject_reason, offer_snapshot)
               VALUES (%s, %s, %s, %s, %s)""",
            [(run_id, o.offer_id, role, reason,
              Jsonb(offer_snapshot(o, resolution.merchant_offer_ids[o.offer_id], pb)))
             for o, role, reason, pb in rows])
    return run_id


def latest_run(conn: psycopg.Connection, line_id: str) -> Optional[dict]:
    return conn.execute(
        """SELECT * FROM benchmark_run WHERE line_id = %s
            ORDER BY computed_at DESC, run_id DESC LIMIT 1""", (line_id,)).fetchone()


def run_sources(conn: psycopg.Connection, run_id: str) -> list[dict]:
    return conn.execute(
        """SELECT merchant_id, snapshot_id, captured_at FROM benchmark_run_snapshot
            WHERE run_id = %s ORDER BY merchant_id""", (run_id,)).fetchall()


def run_comps(conn: psycopg.Connection, run_id: str) -> list[dict]:
    """Read from the run alone. The offer rows may have been pruned."""
    return conn.execute(
        """SELECT role, reject_reason, offer_pk, offer_snapshot FROM benchmark_comp
            WHERE run_id = %s
            ORDER BY role, (offer_snapshot->>'price')::numeric, comp_id""",
        (run_id,)).fetchall()


# ----------------------------------------------------------------- pricing


def save_pricing(conn: psycopg.Connection, *, line_id: str, run: dict, priced: PricedLine,
                 priced_by: str, cost: Optional[Decimal], cost_currency: Optional[str],
                 fx_rate: Optional[Decimal], fx_rate_date=None, fx_source: str | None = None,
                 auction_evidence: Optional[list] = None) -> str:
    """The figures as they stood at the moment of pricing. The benchmark numbers
    are copied from the run, never joined back to it on read."""
    return conn.execute(
        """INSERT INTO pricing_result
               (line_id, run_id, priced_by, uk_floor, uk_reference, uk_median, comp_count,
                auction_evidence, cost, cost_currency, fx_rate, fx_rate_date, fx_source,
                cost_gbp, price_basis, target_margin, discount, deep_discount_threshold,
                sell_price, gp, gross_margin, flags, state)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s)
           RETURNING pricing_id""",
        (line_id, run["run_id"], priced_by, exact_money(run["uk_floor"]),
         exact_money(run["uk_reference"]), exact_money(run["uk_median"]), run["comp_count"],
         Jsonb(auction_evidence or []), exact_money(cost), cost_currency, fx_rate,
         fx_rate_date, fx_source, exact_money(priced.cost_gbp), priced.price_basis,
         priced.target_margin, priced.discount, priced.deep_discount_threshold,
         exact_money(priced.sell_price), exact_money(priced.gp), priced.gross_margin,
         sorted({*run["flags"], *(f.value for f in priced.flags)}), run["state"]),
    ).fetchone()["pricing_id"]


def latest_pricing(conn: psycopg.Connection, line_id: str) -> Optional[dict]:
    return conn.execute(
        """SELECT * FROM pricing_result WHERE line_id = %s
            ORDER BY priced_at DESC, pricing_id DESC LIMIT 1""", (line_id,)).fetchone()
