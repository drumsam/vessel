"""Buy-side, single-line evaluation (decision 0039): "Doug types what he
was offered and the market prices he found with each source named, and a
manually entered price goes through exactly the same screens as a
scraped one — same Offer model, same vintage-band check, same Floor/
Reference/Median, no fast path and no trusted-operator bypass."

The hard screens (whole pence, GBP, In Bond, ASK, buyable, not mixed
lot) are enforced inside `app.core.benchmark` itself, completely
unchanged — this module calls it, never re-derives it. The only new
code is writing structured, already-typed facts into the same tables an
adapter would have written to: there is no raw merchant text to parse
here, because Doug is reading one specific wine's own page, not a messy
listing, so he supplies `wine_id` directly rather than a producer/cuvée
string for the resolver to guess at.

Not sell-side: no margin, no discount, no buyer_discount chain runs
here. "Is this a good price" is answered by comparing the asking price
against the Floor/Reference this produces — in the frontend, a display
computation, not a new pricing rule, the same discipline `gapPercent`
already uses elsewhere in this codebase.

Every evaluation lands as one more line of a single, persistent deal
("Buy-side evaluations") rather than a fresh one-line deal each time —
Doug does this often, and a growing history under one deal is how he
would actually want to browse past evaluations, not a pile of deals
with one line each.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import psycopg
from psycopg.types.json import Jsonb

from app.adapters.base import whole_pence
from app.core.enums import DutyStatus, PriceKind
from app.core.models import Offer
from app.db.repo import exact_money
from app.db import repo
from app.worker import jobs

DEAL_NAME = "Buy-side evaluations"


class InvalidEvaluation(Exception):
    """A comp that cannot become real evidence — never silently dropped,
    never rounded, never guessed at."""


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "merchant"


def ensure_manual_merchant(conn: psycopg.Connection, name: str) -> str:
    """Find-or-create a merchant row by name. Wine-Searcher aggregates far
    more retailers than this app has adapters for, and this list is
    deliberately not closed the way decision 0024's four auction houses
    are — any real source Doug names, having actually seen the price
    there, is real evidence. The same discipline, not the same list."""
    row = conn.execute("SELECT merchant_id FROM merchant WHERE name = %s", (name,)).fetchone()
    if row:
        return row["merchant_id"]
    base = _slugify(name)
    merchant_id = base
    suffix = 1
    while conn.execute("SELECT 1 FROM merchant WHERE merchant_id = %s",
                       (merchant_id,)).fetchone():
        suffix += 1
        merchant_id = f"{base}-{suffix}"
    conn.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) VALUES (%s, %s, true, %s)",
        (merchant_id, name,
         "Manually entered for a buy-side evaluation (decision 0039) — no adapter."))
    return merchant_id


def ensure_evaluation_deal(conn: psycopg.Connection, *, created_by: str) -> str:
    row = conn.execute("SELECT deal_id FROM deal WHERE name = %s", (DEAL_NAME,)).fetchone()
    if row:
        return str(row["deal_id"])
    deal = repo.create_deal(conn, {
        "name": DEAL_NAME, "seller": None, "city": None, "source_file": None,
        "currency": None, "target_margin": None, "buyer_discount": None,
        "margin_on_sale": None, "created_by": created_by,
    }, [])
    return str(deal["deal_id"])


def add_evaluation_line(conn: psycopg.Connection, *, deal_id: str, raw_description: str,
                        wine_id: str, vintage: int, bottle_ml: int, pack_size: int,
                        quantity: int, asking_price: Decimal, asking_currency: str,
                        approved_by: str) -> str:
    """One line, identity already approved — `raw_description` is Doug's
    own words for the offer, never destroyed, same as any other line."""
    next_index = conn.execute(
        "SELECT COALESCE(MAX(row_index), -1) + 1 AS n FROM seller_line WHERE deal_id = %s",
        (deal_id,)).fetchone()["n"]
    line = conn.execute(
        """INSERT INTO seller_line (deal_id, row_index, raw_description, raw_row,
                                    quantity, cost, cost_currency)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (deal_id, next_index, raw_description, Jsonb({"raw_description": raw_description}),
         quantity, exact_money(asking_price), asking_currency)).fetchone()
    repo.set_line_identity(conn, str(line["line_id"]), wine_id=wine_id, vintage=vintage,
                           bottle_ml=bottle_ml, pack_size=pack_size, flags=[],
                           source="operator", approved_by=approved_by)
    return str(line["line_id"])


def write_evaluation_comps(conn: psycopg.Connection, *, wine_id: str, vintage: int,
                           comps: list[dict], as_of: Optional[datetime] = None) -> int:
    """Each comp becomes a REAL `offer` row, under its own fresh snapshot —
    the same table a merchant adapter would have written to, so
    `app.core.benchmark` (via `app.db.repo.resolve_offers`) can never tell
    the difference, and never needs to. `as_of` defaults to now; a comp's
    own `captured_at` is when Doug actually saw it, which may be earlier
    (decision 0003's freshness window still applies — an old capture is
    an old capture, hand-typed or not).

    Refuses rather than guesses, exactly like `app.worker.jobs.ingest`:
    a price that is not a whole number of pence is never rounded.
    """
    as_of = as_of or datetime.now(timezone.utc)
    snap = conn.execute(
        "INSERT INTO snapshot (captured_at, schema_version) VALUES (%s, 'evaluate-0039') "
        "RETURNING snapshot_id", (as_of,)).fetchone()
    merchants_done: set[str] = set()
    written = 0
    for i, comp in enumerate(comps):
        price = Decimal(str(comp["price"]))
        if not whole_pence(price):
            raise InvalidEvaluation(f"{comp['merchant']}'s price {price} is not a whole "
                                    "number of pence")
        merchant_id = ensure_manual_merchant(conn, comp["merchant"])
        captured_at = comp.get("captured_at") or as_of
        if merchant_id not in merchants_done:
            conn.execute(
                """INSERT INTO snapshot_merchant (snapshot_id, merchant_id, status,
                                                  captured_at, offers_written)
                   VALUES (%s, %s, 'ok', %s, 1)""",
                (snap["snapshot_id"], merchant_id, captured_at))
            merchants_done.add(merchant_id)
        offer = Offer(
            offer_id=f"manual:{merchant_id}:{i}", merchant_id=merchant_id,
            merchant=comp["merchant"], wine_id=wine_id, vintage=vintage,
            bottle_ml=comp["bottle_ml"], pack_size=comp["pack_size"], price=price,
            currency=comp["currency"], duty_status=DutyStatus(comp.get("duty_status", "IB")),
            price_kind=PriceKind(comp.get("price_kind", "ASK")),
            is_buyable=comp.get("is_buyable", True), offered_units=comp.get("offered_units"),
            source_url=comp.get("source_url"), captured_at=captured_at,
            raw={"entered_by": "operator", "decision": "0039"})
        repo.write_offer(conn, snap["snapshot_id"], offer)
        written += 1
    return written


def evaluate_offer(conn: psycopg.Connection, *, raw_description: str, wine_id: str,
                   vintage: int, bottle_ml: int, pack_size: int, quantity: int,
                   asking_price: Decimal, asking_currency: str, comps: list[dict],
                   evaluated_by: str) -> dict:
    """The one call the single-line evaluation screen makes: create the
    line, write the comps as real offers, and benchmark — synchronously,
    no RQ job, because this is one line, not a 561-line cellar, and
    `scripts/desk.sh` runs no worker at all. Returns the run_id so the
    caller can read it back exactly as `GET /lines/{id}/benchmark`
    already does for every other line in this app.
    """
    deal_id = ensure_evaluation_deal(conn, created_by=evaluated_by)
    line_id = add_evaluation_line(
        conn, deal_id=deal_id, raw_description=raw_description, wine_id=wine_id,
        vintage=vintage, bottle_ml=bottle_ml, pack_size=pack_size, quantity=quantity,
        asking_price=asking_price, asking_currency=asking_currency, approved_by=evaluated_by)
    write_evaluation_comps(conn, wine_id=wine_id, vintage=vintage, comps=comps)

    when = datetime.now(timezone.utc)
    row = repo.get_line(conn, line_id)
    line = repo.seller_line_for_benchmark(row)
    res = repo.resolve_offers(conn, wine_id=wine_id, vintage=vintage, as_of=when)
    if not res.sources:
        return {"deal_id": deal_id, "line_id": line_id, "run_id": None}
    run_id, _check = jobs.benchmark_with_band(conn, line, res, when)
    return {"deal_id": deal_id, "line_id": line_id, "run_id": str(run_id)}
