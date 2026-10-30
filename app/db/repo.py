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
from app.core.benchmark import BenchmarkResult, DerivedComp, source_offer_id
from app.core.enums import ConditionFlag, DutyStatus, PriceKind, StockType
from app.core.flags import Flag
from app.core.models import Offer, SellerLine
from app.market.units import CasePair, case_pairs, derivation_note, is_measured_region
from app.market.vintage_band import FormatDisagreement, NeighbourVintage, VintageBandCheck
from app.pricing.pricer import PricedLine
from app.identity.resolver import (
    STRUCTURAL_EXCLUSIONS,
    Alias,
    CanonicalWine,
    Registry,
    norm,
    producers_excluded,
    wine_key,
)
from app.identity.want_list import is_want_list_producer

CENT = Decimal("0.01")
#: Rates (margins, discounts, "% below the UK market") are numeric(6,4). They
#: are not money: the three money rounding points are in decision 0007.
RATE = Decimal("0.0001")


class Conflict(Exception):
    """A write that would break an identity guard rail."""


class AmbiguousProducer(Conflict):
    """A producer-only alias where the producer has more than one wine."""

    def __init__(self, message: str, candidates: list[dict]):
        super().__init__(message)
        self.candidates = candidates


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
        CanonicalWine(str(r["wine_id"]), r["producer"], r["cuvee"], r["lwin7"],
                      r["release_code"])
        for r in conn.execute(
            "SELECT wine_id, producer, cuvee, lwin7, release_code FROM wine")
    ]
    aliases = [
        Alias(key=r["wine_key"], wine_id=str(r["wine_id"]), approved_by=r["approved_by"],
              approved_at=r["approved_at"].isoformat(), note=r["note"] or "")
        for r in conn.execute(
            "SELECT wine_key, wine_id, approved_by, approved_at, note FROM wine_alias")
    ]
    return Registry(wines, aliases)


def create_wine(conn: psycopg.Connection, *, producer: str, cuvee: str,
                region: str | None, colour: str | None, lwin7: str | None,
                release_code: str | None = None) -> dict:
    """`want_list` (decision 0038) is set here, once, from the producer
    field alone -- never from the cuvée, never re-derived on read. A
    producer added to the ten later needs its own migration to backfill
    existing rows; this only ever decides it going forward."""
    return conn.execute(
        """INSERT INTO wine (producer, cuvee, region, colour, lwin7, release_code, wine_key,
                             want_list)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (producer, cuvee, region, colour, lwin7, release_code,
         wine_key(producer, cuvee, release_code), is_want_list_producer(producer)),
    ).fetchone()


def get_wine(conn: psycopg.Connection, wine_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM wine WHERE wine_id = %s", (wine_id,)).fetchone()


def list_wines(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT * FROM wine ORDER BY producer, cuvee").fetchall()


def producer_wines(conn: psycopg.Connection, producer_key: str) -> list[dict]:
    """Every canonical wine of one normalised producer."""
    return conn.execute(
        """SELECT wine_id, producer, cuvee, wine_key FROM wine
            WHERE split_part(wine_key, '|', 1) = %s ORDER BY cuvee""",
        (producer_key,)).fetchall()


def create_alias(conn: psycopg.Connection, *, wine_id: str, producer_text: str,
                 cuvee_text: str, source: str, approved_by: str,
                 note: str | None, confirm_target: str | None = None) -> dict:
    """Enforce the guard rails at write time. An alias may never point a key at
    a wine other than the one that key already names, and may never bridge a
    structural exclusion (grand vin vs second wine, adjacent climats).

    A producer-only alias (no cuvee) catches every listing the merchant prints
    under that producer alone, so it carries two more rules: an operator must
    make it, never an AI proposal; and where the producer has more than one
    canonical wine it is refused unless the operator names the target again in
    `confirm_target`. Farr prints both "Veuve Clicquot" and "Veuve Clicquot
    Rosé": a careless one there attaches the Rosé to the Brut.
    """
    key = wine_key(producer_text, cuvee_text)
    target = get_wine(conn, wine_id)
    if target is None:
        raise LookupError(wine_id)

    if key.endswith("|"):
        if source != "operator":
            raise Conflict("a producer-only alias is operator-only, never an AI proposal")
        siblings = producer_wines(conn, key[:-1])
        if len(siblings) > 1 and str(confirm_target or "") != str(wine_id):
            raise AmbiguousProducer(
                f"{key[:-1]!r} has {len(siblings)} canonical wines; name the target "
                "again in confirm_target to create a producer-only alias",
                [{"wine_id": str(w["wine_id"]), "producer": w["producer"], "cuvee": w["cuvee"]}
                 for w in siblings])

    owner = conn.execute("SELECT wine_id FROM wine WHERE wine_key = %s", (key,)).fetchone()
    if owner and str(owner["wine_id"]) != str(wine_id):
        raise Conflict(f"{key!r} already belongs to a different wine")

    for a, b in STRUCTURAL_EXCLUSIONS:
        if {key, target["wine_key"]} == {a, b}:
            raise Conflict(f"{a!r} and {b!r} are a structural exclusion")

    # The same guard rail one level up: two growers whose names read alike are
    # not one grower, whatever cuvée the alias names.
    if producer_text and producers_excluded(producer_text, target["producer"]):
        raise Conflict(f"{producer_text!r} and {target['producer']!r} are different "
                       "producers that have been confused on live merchant data")

    if owner:
        excluded = conn.execute(
            """SELECT reason FROM wine_exclusion
               WHERE (wine_id_a = %(x)s AND wine_id_b = %(y)s)
                  OR (wine_id_a = %(y)s AND wine_id_b = %(x)s)""",
            {"x": owner["wine_id"], "y": wine_id},
        ).fetchone()
        if excluded:
            raise Conflict(f"these two wines are excluded from matching each other: "
                           f"{excluded['reason']}")

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


def list_aliases(conn: psycopg.Connection, *, producer_only: bool | None = None) -> list[dict]:
    where = "" if producer_only is None else "WHERE is_producer_only = %s"
    return conn.execute(f"SELECT * FROM wine_alias {where} ORDER BY wine_key",
                        (producer_only,) if producer_only is not None else None).fetchall()


def operator_refs(conn: psycopg.Connection, ids) -> dict[str, dict]:
    """operator_id -> who that is, for display. The id is what is stored: a
    display name can change without rewriting an audit row."""
    wanted = sorted({str(i) for i in ids if i})
    if not wanted:
        return {}
    rows = conn.execute(
        """SELECT operator_id, username, display_name FROM operator
            WHERE operator_id = ANY(%s::uuid[])""", (wanted,)).fetchall()
    return {str(r["operator_id"]): r for r in rows}


# --------------------------------------------------------------- merchants


def list_merchants(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT * FROM merchant ORDER BY merchant_id").fetchall()


# ------------------------------------------------------------ deals, lines


def create_deal(conn: psycopg.Connection, deal: dict, lines: list[dict]) -> dict:
    row = conn.execute(
        """INSERT INTO deal (name, seller, city, source_file, currency, target_margin,
                             buyer_discount, margin_on_sale, created_by)
           VALUES (%(name)s, %(seller)s, %(city)s, %(source_file)s, %(currency)s, %(target_margin)s,
                   %(buyer_discount)s, %(margin_on_sale)s, %(created_by)s)
           RETURNING *""",
        {**deal, "city": deal.get("city"), "buyer_discount": deal.get("buyer_discount"),
         "margin_on_sale": deal.get("margin_on_sale")},
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


def unresolved_raw(c: Candidate, raw: Optional[dict] = None) -> dict:
    """What an UNRESOLVED_IDENTITY reject keeps: the merchant's record exactly as
    published plus the names identity resolution was given, so the candidate can
    be re-resolved once an operator approves an alias (decision 0029: resolution
    happens once, at capture time, against whatever the registry was then, and
    never re-resolves on its own — `lwin7`/`release_code` are kept here, not
    just `producer_text`/`cuvee_text`, so a later re-resolve pass can use
    exactly what the original resolution attempt had, not a weaker subset).

    `raw` is the ORIGINAL record `adapter.normalise()` was called with — NOT
    `c.offer.raw`, which several adapters narrow to one output row (Bordeaux
    Index: `{"card": title, "offer_row": row}`, one row of a card with many).
    Re-running `normalise()` on that narrowed fragment would misparse it as a
    whole new record and fail closed all over again; `raw` defaults to
    `c.offer.raw` only for an adapter where the two really are the same thing.
    """
    return {"merchant_record": raw if raw is not None else c.offer.raw,
            "producer_text": c.producer_text,
            "cuvee_text": c.cuvee_text,
            "lwin7": c.lwin7,
            "release_code": c.release_code,
            "offer_id": c.offer.offer_id}


def unresolved_identity_rejects(conn: psycopg.Connection,
                                merchant_id: Optional[str] = None) -> list[dict]:
    """Every UNRESOLVED_IDENTITY reject still on disk, each with the snapshot's
    own captured_at (decision 0029) — the one timestamp `normalise()` needs to
    rebuild the Offer exactly as it would have been written at capture time.
    Pruned snapshots take their rejects with them (ON DELETE CASCADE), so this
    only ever sees what retention has kept."""
    sql = """SELECT r.reject_id, r.snapshot_id, r.merchant_id, r.raw, s.captured_at
               FROM offer_reject r JOIN snapshot s ON s.snapshot_id = r.snapshot_id
              WHERE r.reason = 'UNRESOLVED_IDENTITY'"""
    params: tuple = ()
    if merchant_id:
        sql += " AND r.merchant_id = %s"
        params = (merchant_id,)
    return conn.execute(sql, params).fetchall()


def delete_reject(conn: psycopg.Connection, reject_id: str) -> None:
    conn.execute("DELETE FROM offer_reject WHERE reject_id = %s", (reject_id,))


def merchant_already_offered(conn: psycopg.Connection, *, merchant_id: str, wine_id: str,
                             vintage: int, bottle_ml: int, pack_size: int,
                             exclude_snapshot_id: str, exclude_offer_id: str) -> Optional[dict]:
    """Did this merchant already have a comparable offer for this exact
    commercial unit before this one? The decision 0029 report's own
    "duplicates a price we already have" question, answered directly rather
    than guessed at: the caller is told the old price so it can see for
    itself whether a recovered offer only confirms what was already there.

    `offer_id` is only unique WITHIN a snapshot (`offer`'s own constraint is
    on the pair) — excluding by `offer_id` alone would also exclude a
    genuinely different, already-written offer from an earlier capture that
    happens to carry the same merchant code, which is exactly the case a
    re-resolved reject from a second capture of the same card produces.
    """
    return conn.execute(
        """SELECT price, offer_id FROM offer
            WHERE merchant_id = %(merchant_id)s AND wine_id = %(wine_id)s
              AND vintage = %(vintage)s AND bottle_ml = %(bottle_ml)s
              AND pack_size = %(pack_size)s
              AND NOT (snapshot_id = %(exclude_snapshot_id)s AND offer_id = %(exclude_offer_id)s)
            ORDER BY price ASC LIMIT 1""",
        {"merchant_id": merchant_id, "wine_id": wine_id, "vintage": vintage,
         "bottle_ml": bottle_ml, "pack_size": pack_size,
         "exclude_snapshot_id": exclude_snapshot_id, "exclude_offer_id": exclude_offer_id}
    ).fetchone()


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
       AND s.schema_version <> 'auction-import-1'
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

    @property
    def offer_by_id(self) -> dict[str, Offer]:
        return {o.offer_id: o for o in self.offers}


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


def derived_from_json(d: DerivedComp, region_key: Optional[str] = None) -> dict:
    """What a derived comparable was derived from. Never a price of its own.

    `region_key` decides the wording only (decision 0018): the same premium is
    applied everywhere derivation runs, but a region outside
    `MEASURED_REGIONS` is told honestly that the number is assumed, not
    measured, for it.
    """
    return {"offer_id": None, "merchant_id": d.source.merchant_id,
            "merchant": d.source.merchant, "price": str(exact_money(d.source.price)),
            "pack_size": d.source.pack_size, "bottle_ml": d.source.bottle_ml,
            "basis": d.basis, "premium_applied": d.premium_applied,
            "measured": is_measured_region(region_key) if region_key else None,
            "note": derivation_note(d, region_key)}


def offer_snapshot(o: Offer, merchant_offer_id: str,
                   per_bottle: Optional[Decimal] = None,
                   variance_vs_reference: Optional[Decimal] = None,
                   derived_from: Optional[dict] = None) -> dict:
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
        # indication, bid or last_trade only: how far that figure sat from
        # the Reference at the moment of the run. Context, never a price
        # (decisions 0013, 0026).
        "variance_vs_reference": (str(variance_vs_reference.quantize(RATE))
                                  if variance_vs_reference is not None else None),
        "merchant_count": (o.raw or {}).get("market", {}).get("merchantCount"),
        # Set only on a comparable DERIVED across case sizes (decision 0016).
        # The offer above carries the derived figure at the seller's unit; this
        # says what was really offered, at what unit, and by what arithmetic.
        # The 5% case premium is an assumption and the wording says so.
        "derived_from": derived_from,
    }


def save_benchmark(conn: psycopg.Connection, result: BenchmarkResult,
                   resolution: Resolution, region: Optional[str] = None) -> str:
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
        rows += [(o, "comparable", None, None, None) for o in result.comparables]
        rows += [(o, "merchant_best", None, None, None) for o in result.merchant_bests]
        rows += [(c.offer, "cross_unit", None, c.per_bottle, None) for c in result.cross_unit]
        rows += [(i.offer, "indication", None, None, i.variance_vs_reference)
                 for i in result.indications]
        rows += [(b.offer, "bid", None, None, b.variance_vs_reference) for b in result.bids]
        rows += [(t.offer, "last_trade", None, None, t.variance_vs_reference)
                 for t in result.last_trades]
        rows += [(r.offer, "rejected", r.reason.value, None, None) for r in result.rejections]

        # A derived comparable has no offer row of its own — it is a figure, not
        # something a merchant published. It is stored against the offer it was
        # derived FROM, so the provenance survives pruning like everything else.
        derived = {d.offer.offer_id: d for d in result.derived}

        def source_pk(offer_id: str) -> str:
            d = derived.get(offer_id)
            return d.source.offer_id if d else offer_id

        cur.executemany(
            """INSERT INTO benchmark_comp (run_id, offer_pk, role, reject_reason, offer_snapshot)
               VALUES (%s, %s, %s, %s, %s)""",
            [(run_id, source_pk(o.offer_id), role, reason,
              Jsonb(offer_snapshot(
                  o, resolution.merchant_offer_ids[source_pk(o.offer_id)], pb, variance,
                  derived_from_json(derived[o.offer_id], region)
                  if o.offer_id in derived else None)))
             for o, role, reason, pb, variance in rows])
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
    # buyer_price_gbp and seller_price_gbp are GENERATED columns (decision
    # 0017): Postgres refuses a value for them in the INSERT list, by design —
    # they can only ever be what sell_price/cost_gbp already are for this basis.
    return conn.execute(
        """INSERT INTO pricing_result
               (line_id, run_id, priced_by, uk_floor, uk_reference, uk_median, comp_count,
                auction_evidence, cost, cost_currency, fx_rate, fx_rate_date, fx_source,
                cost_gbp, price_basis, target_margin, discount, deep_discount_threshold,
                buyer_discount, margin_on_sale, sell_price, gp, gross_margin, flags, state)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s)
           RETURNING pricing_id""",
        (line_id, run["run_id"], priced_by, exact_money(run["uk_floor"]),
         exact_money(run["uk_reference"]), exact_money(run["uk_median"]), run["comp_count"],
         Jsonb(auction_evidence or []), exact_money(cost), cost_currency, fx_rate,
         fx_rate_date, fx_source, exact_money(priced.cost_gbp), priced.price_basis,
         priced.target_margin, priced.discount, priced.deep_discount_threshold,
         priced.buyer_discount, priced.margin_on_sale,
         exact_money(priced.sell_price), exact_money(priced.gp), priced.gross_margin,
         sorted({*run["flags"], *(f.value for f in priced.flags)}), run["state"]),
    ).fetchone()["pricing_id"]


def latest_pricing(conn: psycopg.Connection, line_id: str) -> Optional[dict]:
    row = conn.execute(
        """SELECT * FROM pricing_result WHERE line_id = %s
            ORDER BY priced_at DESC, pricing_id DESC LIMIT 1""", (line_id,)).fetchone()
    if row is not None:
        row["acknowledgement"] = conn.execute(
            "SELECT * FROM pricing_acknowledgement WHERE pricing_id = %s",
            (row["pricing_id"],)).fetchone()
    return row


#: Flags a named operator must accept before a price can be exported. Not
#: REVIEW_FLAGS, which is about evidence quality: these are commercial, and only
#: the two that would make the client document untrue or the trade a loss.
#: COST_ABOVE_UK_REFERENCE and DEEP_DISCOUNT stay context. See decision 0008.
EXPORT_GATE_FLAGS = ("NEGATIVE_GP", "SELL_ABOVE_UK_REFERENCE", "SELL_AT_OR_ABOVE_UK_FLOOR")

#: Benchmark states that also gate, for the other half of the question: not
#: "is this trade sensible" but "did we measure the market at all". See 0010.
EXPORT_GATE_STATES = ("NO_MARKET", "REVIEW")


#: Review-causing flags (REVIEW_FLAGS, app/core/flags.py) in plain English,
#: for the one place outside the Cellar Desk that still has to explain why
#: a line needs a person: an error message a human reads. ONE_COMP and
#: WIDE_SPREAD (at comp_count == 2) are handled separately in
#: `gate_reason_phrase`, below, because they need the comp count, not a
#: fixed phrase — the same split web/app/deals/[dealId]/page.jsx's own
#: `reasonFor()` uses for the Cellar Desk's "needs you" badge. The two are
#: independent implementations that happen to agree, by project
#: discipline, not by sharing code across the Python/JS boundary.
_REVIEW_REASON_PHRASES = {
    "DERIVED_FROM_CASE": "a comparison derived from a different case size",
    "CONDITION_REVIEW": "a condition flag on its comparables",
    "STOCK_BASIS_UNCONFIRMED": "an unconfirmed stock basis",
    "NAME_REVIEW": "a name that still needs confirming",
    "FORMAT_REVIEW": "a format that still needs confirming",
    "COMP_EXCLUDED_VINTAGE_BAND": "a comparable excluded as an outlier",
    "LOW_COMP_OUT_OF_BAND": "a comparable flagged as unusually cheap",
}

#: Commercial flags that also gate export (EXPORT_GATE_FLAGS, above), in
#: plain English.
_EXPORT_GATE_PHRASES = {
    "NEGATIVE_GP": "would lose money",
    "SELL_ABOVE_UK_REFERENCE": "is priced above the market",
    "SELL_AT_OR_ABOVE_UK_FLOOR": "is not actually priced below the market",
}


def gate_reason_phrase(pricing: dict) -> str:
    """One English clause for why a line still needs a person — built from
    the real flags behind `requires_acknowledgement`. Never a flag
    constant, never a bare state name: "A UUID and a flag constant... the
    API is behaving correctly and explaining it in its own vocabulary.
    Every error a human sees must name the wine and the action" (Doug, 21
    October 2026). His own example: "Krug Grande Cuvée 167ᵉ rests on one
    merchant and hasn't been accepted."
    """
    flags = set(pricing["flags"])
    clauses = []
    if pricing["comp_count"] == 1:
        clauses.append("rests on one merchant")
    elif pricing["comp_count"] == 2 and "WIDE_SPREAD" in flags:
        clauses.append("rests on two merchants far enough apart to need a look")
    for flag, phrase in _REVIEW_REASON_PHRASES.items():
        if flag in flags:
            clauses.append(f"rests on {phrase}")
    for flag, phrase in _EXPORT_GATE_PHRASES.items():
        if flag in flags:
            clauses.append(phrase)
    if not clauses and pricing.get("state") == "NO_MARKET":
        clauses.append("has no market found for it")
    return "; ".join(clauses) if clauses else "needs a look before it can be sent"


def acknowledge_pricing(conn: psycopg.Connection, pricing_id: str, *,
                        acknowledged_by: str, note: str | None) -> dict:
    row = conn.execute("SELECT * FROM pricing_result WHERE pricing_id = %s",
                       (pricing_id,)).fetchone()
    if row is None:
        raise LookupError(pricing_id)
    if not row["requires_acknowledgement"]:
        raise Conflict("this price carries nothing that gates export")
    return conn.execute(
        """INSERT INTO pricing_acknowledgement (pricing_id, flags, state, acknowledged_by, note)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (pricing_id, sorted(set(row["flags"]) & set(EXPORT_GATE_FLAGS)), row["state"],
         acknowledged_by, note)).fetchone()


def acknowledge_want_list(conn: psycopg.Connection, line_id: str, *, acknowledged_by: str) -> dict:
    """The one-time want-list acknowledgement (decision 0038) — tied to
    the line's own identity, not to any one pricing run: `acknowledge_
    pricing` above inserts a new row every time because the price it
    describes changes; this sets two columns on the line itself, once,
    because the fact it records ("a named operator confirmed this really
    is the want-list wine") does not change when the market does.
    Re-acknowledging is harmless and simply updates who and when."""
    line = get_line(conn, line_id)
    if line is None:
        raise LookupError("line not found")
    wine = get_wine(conn, line["wine_id"]) if line["wine_id"] else None
    if wine is None or not wine["want_list"]:
        raise Conflict("this line is not a want-list producer")
    return conn.execute(
        """UPDATE seller_line SET want_list_ack_by = %s, want_list_ack_at = now()
            WHERE line_id = %s RETURNING *""",
        (acknowledged_by, line_id)).fetchone()


# --------------------------------------------------------- alias suggestions


def alias_suggestions(conn: psycopg.Connection, min_occurrences: int = 2) -> list[dict]:
    """Seller wording an operator has resolved to the same wine more than once.

    Repeated corrections of the same text are exactly what an alias is for. This
    reports the evidence; creating the alias stays an operator action, because
    only the operator can say which producer and cuvee wording it should carry.
    """
    rows = conn.execute(
        """SELECT h.line_id, h.new_wine_id, h.changed_at, h.source, h.changed_by,
                  l.raw_description, w.producer, w.cuvee
             FROM seller_line_identity_history h
             JOIN seller_line l ON l.line_id = h.line_id
             JOIN wine w ON w.wine_id = h.new_wine_id
            ORDER BY h.changed_at""").fetchall()

    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (norm(r["raw_description"]), str(r["new_wine_id"]))
        g = groups.setdefault(key, {
            "seller_text": r["raw_description"], "normalised": key[0],
            "wine_id": key[1], "producer": r["producer"], "cuvee": r["cuvee"],
            "line_ids": [], "corrections": 0, "last_changed_at": r["changed_at"],
            "changed_by": []})
        if str(r["line_id"]) not in g["line_ids"]:
            g["line_ids"].append(str(r["line_id"]))
        g["corrections"] += 1
        g["last_changed_at"] = max(g["last_changed_at"], r["changed_at"])
        if r["changed_by"] not in g["changed_by"]:
            g["changed_by"].append(r["changed_by"])
    return sorted([g for g in groups.values() if len(g["line_ids"]) >= min_occurrences],
                  key=lambda g: (-len(g["line_ids"]), g["normalised"]))


# ------------------------------------------------------------------ pruning


def prune_snapshots(conn: psycopg.Connection, keep: int) -> list[str]:
    """Delete snapshots no merchant still needs, keeping the newest `keep`
    captures per merchant per outcome: the evidence, and recent failures as
    diagnostics. A merchant's latest successful capture is always kept, so
    pruning never changes which offers a new benchmark can see.

    Benchmark history is untouched: runs keep their own copy of every offer
    they used, and their snapshot pointers go NULL (decision 0004).
    """
    if keep < 1:
        raise ValueError("keep must be at least 1")
    rows = conn.execute(
        """WITH ranked AS (
               SELECT sm.snapshot_id, ROW_NUMBER() OVER (PARTITION BY sm.merchant_id, sm.status
                                     ORDER BY sm.captured_at DESC, sm.snapshot_id DESC) AS rn
                 FROM snapshot_merchant sm JOIN snapshot s USING(snapshot_id)
                 WHERE s.schema_version <> 'auction-import-1'),
                keep AS (SELECT DISTINCT snapshot_id FROM ranked WHERE rn <= %s)
           DELETE FROM snapshot s
            WHERE s.schema_version <> 'auction-import-1'
              AND NOT EXISTS (SELECT 1 FROM keep k WHERE k.snapshot_id = s.snapshot_id)
        RETURNING snapshot_id""", (keep,)).fetchall()
    return [str(r["snapshot_id"]) for r in rows]


# ------------------------------------------------------------- buyer offers


class LineNotReady(Exception):
    """A line whose price needs an operator's acknowledgement and has not
    had one, with a human description already attached — never a flag
    constant, never a UUID. Caught by `create_buyer_offer` so several
    unready lines are reported together, not one at a time across
    repeated submissions."""


def wine_display_name(line: dict, wine: Optional[dict]) -> str:
    """Producer + cuvée + vintage where identity is approved; the seller's
    own wording otherwise. The one name every error about a line uses to
    refer to it — never a line_id, never a wine_id."""
    if wine is None:
        return line["raw_description"]
    return " ".join(filter(None, [
        wine["producer"], wine["cuvee"],
        "NV" if line["vintage"] == 1000 else str(line["vintage"] or ""),
    ])).strip()


def _offer_line(conn: psycopg.Connection, line: dict, ask: dict) -> dict:
    """One line of an issued offer, from that line's latest price. Refuses
    rather than guesses: an unpriced line stops the whole document at once
    (`Conflict`); a price that needs an operator's acknowledgement and has
    not had one is collected instead (`LineNotReady`), so
    `create_buyer_offer` can name every such line in one message rather
    than stopping at the first.
    """
    line_id = str(line["line_id"])
    wine = get_wine(conn, line["wine_id"]) if line["wine_id"] else None
    name = wine_display_name(line, wine)
    pricing = latest_pricing(conn, line_id)
    if pricing is None or pricing["sell_price"] is None:
        raise Conflict(f"{name} has no price yet")
    if pricing["requires_acknowledgement"] and pricing["acknowledgement"] is None:
        raise LineNotReady(f"{name} {gate_reason_phrase(pricing)}")
    # decision 0038: a listing-side requirement, independent of the
    # pricing gate above — a want-list line can be READY, two merchants
    # agreeing, and still need the one-time identity check.
    if wine and wine["want_list"] and line["want_list_ack_at"] is None:
        raise LineNotReady(f"{name} is on the client want list and needs a one-time "
                           "identity check")
    quantity = ask.get("quantity") or line["quantity"]
    description = ask.get("description") or name
    return {
        "line_id": line_id, "pricing_id": pricing["pricing_id"], "description": description,
        "vintage": line["vintage"], "bottle_ml": line["bottle_ml"],
        "pack_size": line["pack_size"], "quantity": quantity,
        "unit_price": exact_money(pricing["sell_price"]),
        "line_total": exact_money(pricing["sell_price"] * quantity),
        "condition_notes": ask.get("condition_notes"),
        "pricing_requires_ack": pricing["requires_acknowledgement"],
        "ack_id": pricing["acknowledgement"]["ack_id"] if pricing["acknowledgement"] else None,
        "sell_currency": pricing["sell_currency"],
        # A market claim only exists where there is a UK Reference to claim
        # against AND the price is actually below it. No reference, or a price
        # above the market, means no row: nothing for a document to print.
        # A price above the market is not a negative discount, it is not a
        # discount (decision 0010). SELL_AT_OR_ABOVE_UK_FLOOR (decision 0033)
        # suppresses the claim unconditionally, acceptance of the export gate
        # or not: at or above the cheapest ask actually found, "below market"
        # is false regardless of who accepted it.
        "claim": (_claim(pricing) if pricing["uk_reference"]
                  and pricing["sell_price"] <= pricing["uk_reference"]
                  and "SELL_AT_OR_ABOVE_UK_FLOOR" not in pricing["flags"] else None),
    }


def _claim(pricing: dict) -> dict:
    return {"run_id": pricing["run_id"], "uk_reference": pricing["uk_reference"],
            "comp_count": pricing["comp_count"],
            "below_reference": ((pricing["uk_reference"] - pricing["sell_price"])
                                / pricing["uk_reference"]).quantize(RATE)}


def _not_accepted_message(problems: list[str]) -> str:
    """Doug's own example, generalised to several lines at once: name
    every wine and its reason, never truncate to the first failure.
    Singular wording at one line, plural at more than one."""
    if len(problems) == 1:
        return f"{problems[0]} and hasn't been accepted. Accept it or remove it from this offer."
    return ("; ".join(problems) + " — none of these have been accepted. "
            "Accept them or remove them from this offer.")


def create_buyer_offer(conn: psycopg.Connection, *, deal_id: str, client: str, currency: str,
                       terms: str | None, issued_by: str, asks: list[dict]) -> dict:
    """The offer as issued. Its line figures are copied from the pricing results
    they came from, so the document stays reproducible after the market moves."""
    by_id = {str(r["line_id"]): r for r in deal_lines(conn, deal_id)}
    rows = []
    not_ready = []
    for ask in asks:
        line = by_id.get(str(ask["line_id"]))
        if line is None:
            raise LookupError("one of the selected lines is not part of this deal")
        try:
            row = _offer_line(conn, line, ask)
        except LineNotReady as e:
            not_ready.append(str(e))
            continue
        if row.pop("sell_currency") != currency:
            raise Conflict(f"{row['description']} is priced in a currency other than this offer's")
        rows.append(row)
    if not_ready:
        raise Conflict(_not_accepted_message(not_ready))
    if not rows:
        raise Conflict("an offer needs at least one line")

    offer = conn.execute(
        """INSERT INTO buyer_offer (deal_id, client, currency, issued_at, issued_by, terms)
           VALUES (%s, %s, %s, now(), %s, %s) RETURNING *""",
        (deal_id, client, currency, issued_by, terms)).fetchone()
    numbered = [{**r, "buyer_offer_id": offer["buyer_offer_id"], "line_no": i}
                for i, r in enumerate(rows, 1)]
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO buyer_offer_line
                   (buyer_offer_id, line_no, line_id, pricing_id, description, vintage,
                    bottle_ml, pack_size, quantity, unit_price, line_total, condition_notes,
                    pricing_requires_ack, ack_id)
               VALUES (%(buyer_offer_id)s, %(line_no)s, %(line_id)s, %(pricing_id)s,
                       %(description)s, %(vintage)s, %(bottle_ml)s, %(pack_size)s,
                       %(quantity)s, %(unit_price)s, %(line_total)s, %(condition_notes)s,
                       %(pricing_requires_ack)s, %(ack_id)s)""", numbered)
        cur.executemany(
            """INSERT INTO buyer_offer_market_claim
                   (buyer_offer_id, line_no, run_id, as_of, uk_reference, comp_count,
                    below_reference)
               SELECT %(buyer_offer_id)s, %(line_no)s, %(run_id)s, r.as_of, %(uk_reference)s,
                      %(comp_count)s, %(below_reference)s
                 FROM benchmark_run r WHERE r.run_id = %(run_id)s""",
            [{**r["claim"], "buyer_offer_id": r["buyer_offer_id"], "line_no": r["line_no"]}
             for r in numbered if r["claim"]])
    return get_buyer_offer(conn, offer["buyer_offer_id"])


def get_buyer_offer(conn: psycopg.Connection, buyer_offer_id: str) -> Optional[dict]:
    offer = conn.execute("SELECT * FROM buyer_offer WHERE buyer_offer_id = %s",
                         (buyer_offer_id,)).fetchone()
    if offer is None:
        return None
    offer["lines"] = conn.execute(
        "SELECT * FROM buyer_offer_line WHERE buyer_offer_id = %s ORDER BY line_no",
        (buyer_offer_id,)).fetchall()
    # Assembled here rather than with to_jsonb: JSON would turn numeric into a
    # float, and money never passes through one.
    claims = {r["line_no"]: r for r in conn.execute(
        "SELECT * FROM buyer_offer_market_claim WHERE buyer_offer_id = %s",
        (buyer_offer_id,)).fetchall()}
    for line in offer["lines"]:
        line["market_claim"] = claims.get(line["line_no"])
    offer["total"] = sum((ln["line_total"] for ln in offer["lines"]), Decimal("0"))
    return offer


def deal_buyer_offers(conn: psycopg.Connection, deal_id: str) -> list[dict]:
    ids = conn.execute("""SELECT buyer_offer_id FROM buyer_offer WHERE deal_id = %s
                           ORDER BY issued_at DESC""", (deal_id,)).fetchall()
    return [get_buyer_offer(conn, r["buyer_offer_id"]) for r in ids]


# --------------------------------------------------------------- overviews


def list_deals(conn: psycopg.Connection) -> list[dict]:
    """Deal summaries with a count per line state. The states are derived here
    exactly as the deal view derives them: identity, then the latest run."""
    return conn.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (line_id) line_id, state
              FROM benchmark_run ORDER BY line_id, computed_at DESC, run_id DESC)
        SELECT d.*, count(l.line_id) AS lines,
               count(*) FILTER (WHERE l.wine_id IS NULL) AS identity_not_approved,
               count(*) FILTER (WHERE l.wine_id IS NOT NULL AND r.state IS NULL) AS not_searched,
               count(*) FILTER (WHERE r.state = 'READY') AS ready,
               count(*) FILTER (WHERE r.state = 'REVIEW') AS review,
               count(*) FILTER (WHERE r.state = 'NO_MARKET') AS no_market
          FROM deal d
          LEFT JOIN seller_line l USING (deal_id)
          LEFT JOIN latest r ON r.line_id = l.line_id
         GROUP BY d.deal_id ORDER BY d.created_at DESC""").fetchall()


def review_queue(conn: psycopg.Connection) -> list[dict]:
    """Every line waiting on a person, across every deal, with why."""
    return conn.execute("""
        WITH latest_run AS (
            SELECT DISTINCT ON (line_id) line_id, run_id, state, flags, uk_reference
              FROM benchmark_run ORDER BY line_id, computed_at DESC, run_id DESC),
             latest_price AS (
            SELECT DISTINCT ON (line_id) line_id, pricing_id, sell_price, flags AS pricing_flags,
                   requires_acknowledgement
              FROM pricing_result ORDER BY line_id, priced_at DESC, pricing_id DESC)
        SELECT l.line_id, l.deal_id, d.name AS deal_name, l.row_index, l.raw_description,
               l.quantity, l.wine_id, l.flags AS line_flags,
               r.state, r.flags AS benchmark_flags, r.uk_reference,
               p.sell_price, p.pricing_flags, p.requires_acknowledgement,
               EXISTS (SELECT 1 FROM pricing_acknowledgement a
                        WHERE a.pricing_id = p.pricing_id) AS acknowledged
          FROM seller_line l
          JOIN deal d USING (deal_id)
          LEFT JOIN latest_run r ON r.line_id = l.line_id
          LEFT JOIN latest_price p ON p.line_id = l.line_id
         WHERE l.wine_id IS NULL
            OR r.state IS NULL
            OR r.state <> 'READY'
            OR (p.requires_acknowledgement
                AND NOT EXISTS (SELECT 1 FROM pricing_acknowledgement a
                                 WHERE a.pricing_id = p.pricing_id))
         ORDER BY d.created_at DESC, l.row_index""").fetchall()


# ------------------------------------------------------------- search keys


def set_search_key(conn: psycopg.Connection, *, merchant_id: str, producer_key: str,
                   params: dict, source: str, set_by: str, note: str | None = None) -> dict:
    return conn.execute(
        """INSERT INTO merchant_search_key (merchant_id, producer_key, params, source,
                                            set_by, note)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (merchant_id, producer_key) DO UPDATE
              SET params = EXCLUDED.params, source = EXCLUDED.source,
                  set_by = EXCLUDED.set_by, set_at = now(), note = EXCLUDED.note
        RETURNING *""",
        (merchant_id, producer_key, Jsonb(params), source, set_by, note)).fetchone()


def search_key(conn: psycopg.Connection, merchant_id: str, producer_key: str) -> Optional[dict]:
    return conn.execute(
        "SELECT * FROM merchant_search_key WHERE merchant_id = %s AND producer_key = %s",
        (merchant_id, producer_key)).fetchone()


def list_search_keys(conn: psycopg.Connection, merchant_id: str | None = None) -> list[dict]:
    where = "WHERE merchant_id = %s" if merchant_id else ""
    return conn.execute(f"SELECT * FROM merchant_search_key {where} ORDER BY merchant_id, "
                        "producer_key", (merchant_id,) if merchant_id else None).fetchall()


def thin_targets(conn: psycopg.Connection, deal_id: str, min_comps: int = 2) -> list[dict]:
    """The (wine, vintage) pairs of a deal's lines that came back thin: fewer
    than `min_comps` merchants, or never searched at all. What DEEP MERCHANT
    SEARCH is pointed at."""
    return conn.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (line_id) line_id, comp_count
              FROM benchmark_run ORDER BY line_id, computed_at DESC, run_id DESC)
        SELECT DISTINCT l.wine_id, l.vintage, w.producer, w.wine_key,
               coalesce(min(r.comp_count), 0) AS comp_count
          FROM seller_line l
          JOIN wine w USING (wine_id)
          LEFT JOIN latest r ON r.line_id = l.line_id
         WHERE l.deal_id = %s AND l.wine_id IS NOT NULL
         GROUP BY l.wine_id, l.vintage, w.producer, w.wine_key
        HAVING coalesce(min(r.comp_count), 0) < %s
         ORDER BY w.producer, l.vintage""", (deal_id, min_comps)).fetchall()


# ------------------------------------------- the vintage-neighbour sanity check
#
# docs/research/vintage-neighbour-check-spec.md. Read by the review screens and
# by nothing else: no function below is called from pricing or from an export.


def register_key(region: Optional[str], colour: Optional[str]) -> Optional[str]:
    """The `vintage_tier.region` a wine is rated under: 'BURGUNDY_RED'.

    Colour is part of the key because the tiers diverge — 2014 Burgundy is tier
    3 red and tier 1 white, 2009 is tier 2 red and tier 4 white. A colour-blind
    register would produce nonsense bands. A wine missing either is unrated,
    and an unrated wine gets no band at all rather than a guessed one.
    """
    if not region or not colour:
        return None
    return f"{norm(region).replace(' ', '_')}_{norm(colour).replace(' ', '_')}".upper()


def wine_register_key(conn: psycopg.Connection, wine_id: str) -> Optional[str]:
    row = conn.execute("SELECT region, colour FROM wine WHERE wine_id = %s",
                       (wine_id,)).fetchone()
    return register_key(row["region"], row["colour"]) if row else None


def vintage_tiers(conn: psycopg.Connection, region: Optional[str]) -> dict[int, int]:
    """{vintage: tier} for one region-and-colour, or {} when it is not in the
    register. Empty means no band and no flag — silence, never a guess."""
    if not region:
        return {}
    return {r["vintage"]: r["tier"] for r in conn.execute(
        "SELECT vintage, tier FROM vintage_tier WHERE region = %s", (region,))}


def vintage_tier_rows(conn: psycopg.Connection, region: str) -> list[dict]:
    """The register as an operator sees it: the tier, its label and what was
    consulted. Read-only — the register is maintained as a file."""
    return conn.execute(
        """SELECT vintage, tier, tier_label, sources, note, set_by, set_at
             FROM vintage_tier WHERE region = %s ORDER BY vintage""", (region,)).fetchall()


def _neighbour_json(n: NeighbourVintage) -> dict:
    return {"vintage": n.vintage, "median": str(exact_money(n.median)),
            "merchants": n.merchants, "stale": n.stale, "tier": n.tier,
            "newest_captured_at": (n.newest_captured_at.isoformat()
                                   if n.newest_captured_at else None)}


def _outlier_json(ref) -> dict:
    return {"offer_id": ref.offer_id, "merchant_id": ref.merchant_id,
            "merchant": ref.merchant, "price": str(exact_money(ref.price)),
            "edge": str(exact_money(ref.edge)),
            "multiple": str(ref.multiple.quantize(RATE)), "flag": ref.flag}


def _incoherence_json(d: FormatDisagreement) -> dict:
    # The per-bottle figures exist inside this check's output and nowhere else:
    # they are never stored on an offer and never exported (spec 3b).
    return {"offer_id": d.offer_id, "merchant_id": d.merchant_id, "merchant": d.merchant,
            "comp_unit": d.comp_unit, "comp_per_bottle": str(d.comp_per_bottle.quantize(CENT)),
            "other_unit": d.other_unit, "other_per_bottle": str(d.other_per_bottle.quantize(CENT)),
            "difference": str(d.difference.quantize(RATE)), "flag": d.flag}


def save_vintage_band(conn: psycopg.Connection, run_id: str, check: VintageBandCheck,
                      resolution: Resolution) -> None:
    """The band for one run, and one exclusion row per comp it dropped."""
    conn.execute(
        """INSERT INTO vintage_band_check (run_id, unit, band_low, band_high, neighbours,
                                           low_outliers, format_incoherent, tiers_available, note)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (run_id, check.unit, exact_money(check.band_low), exact_money(check.band_high),
         Jsonb([_neighbour_json(n) for n in check.neighbours]),
         Jsonb([_outlier_json(o) for o in check.low_outliers]),
         Jsonb([_incoherence_json(d) for d in check.format_incoherent]),
         check.tiers_available, check.note))

    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO benchmark_comp_exclusion
                   (run_id, offer_pk, offer_snapshot, flag, band_edge, band_multiple)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            [(run_id, source_offer_id(ref.offer_id),
              Jsonb(offer_snapshot(
                  resolution.offer_by_id[source_offer_id(ref.offer_id)],
                  resolution.merchant_offer_ids[source_offer_id(ref.offer_id)])),
              ref.flag, exact_money(ref.edge), ref.multiple.quantize(RATE))
             for ref in check.high_outliers])


def run_band(conn: psycopg.Connection, run_id: str) -> Optional[dict]:
    return conn.execute(
        "SELECT * FROM vintage_band_check WHERE run_id = %s", (run_id,)).fetchone()


def run_exclusions(conn: psycopg.Connection, run_id: str) -> list[dict]:
    return conn.execute(
        """SELECT exclusion_id, offer_pk, offer_snapshot, flag, band_edge, band_multiple,
                  excluded_at, reinstated_at, reinstated_by, reinstated_reason,
                  replacement_run_id
             FROM benchmark_comp_exclusion WHERE run_id = %s
            ORDER BY (offer_snapshot->>'price')::numeric DESC, exclusion_id""",
        (run_id,)).fetchall()


def open_exclusion(conn: psycopg.Connection, exclusion_id: str) -> Optional[dict]:
    """An exclusion that has not been put back yet, with its line."""
    return conn.execute(
        """SELECT x.*, r.line_id, r.as_of
             FROM benchmark_comp_exclusion x
             JOIN benchmark_run r ON r.run_id = x.run_id
            WHERE x.exclusion_id = %s AND x.reinstated_at IS NULL""",
        (exclusion_id,)).fetchone()


def record_reinstatement(conn: psycopg.Connection, exclusion_id: str, *, reinstated_by: str,
                         reason: str, replacement_run_id: str) -> dict:
    """Who put the comp back, when, why, and the run that resulted.

    The original run is not edited: it stays exactly as it was computed, and the
    new run is what the line reads from now. Nothing is deleted.
    """
    row = conn.execute(
        """UPDATE benchmark_comp_exclusion
              SET reinstated_at = now(), reinstated_by = %s, reinstated_reason = %s,
                  replacement_run_id = %s
            WHERE exclusion_id = %s AND reinstated_at IS NULL
        RETURNING *""",
        (reinstated_by, reason, replacement_run_id, exclusion_id)).fetchone()
    if row is None:
        raise Conflict("this exclusion has already been put back")
    return row


# ------------------------------------------------- measuring the case premium


def record_case_pairs(conn: psycopg.Connection, snapshot_id: str, merchant_id: str,
                      pairs: list[CasePair], captured_at: datetime) -> int:
    """Store every wine this capture met in two pack sizes (decision 0016).

    Observation, not evidence for a price: nothing in the pricing path reads
    this table. It exists so CASE_PREMIUM can stop being a judgement call, and
    it is written while the traffic is happening anyway.
    """
    if not pairs:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO case_premium_pair
                   (snapshot_id, merchant_id, wine_id, vintage, bottle_ml, duty_status,
                    captured_at, smaller_pack, smaller_price, larger_pack, larger_price, ratio)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING""",
            [(snapshot_id, merchant_id, p.wine_id, p.vintage, p.bottle_ml, p.duty_status,
              captured_at, p.smaller_pack, exact_money(p.smaller_price),
              p.larger_pack, exact_money(p.larger_price), p.ratio) for p in pairs])
    return len(pairs)


def case_premium_summary(conn: psycopg.Connection, bottle_ml: int = 750) -> list[dict]:
    """The measurement as it stands, per merchant and overall, loose-vs-case only.

    The median is what CASE_PREMIUM should be; the spread is why a derived comp
    is flagged whatever the median says.
    """
    return conn.execute(
        # percentile_DISC, not _cont: it returns the numeric it was given rather
        # than a double, so no float touches this, and for an even count it
        # picks an observed ratio instead of averaging two into one nobody saw.
        """SELECT merchant_id, count(*) AS pairs,
                  percentile_disc(0.5) WITHIN GROUP (ORDER BY ratio) AS median,
                  avg(ratio) AS mean, min(ratio) AS low, max(ratio) AS high,
                  count(*) FILTER (WHERE abs(ratio - 1) > 0.05) AS beyond_5pct,
                  min(captured_at) AS first_seen, max(captured_at) AS last_seen
             FROM case_premium_pair
            WHERE is_loose_pair AND bottle_ml = %(ml)s
            GROUP BY ROLLUP (merchant_id)
            ORDER BY merchant_id NULLS LAST""", {"ml": bottle_ml}).fetchall()
