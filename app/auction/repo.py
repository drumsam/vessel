"""Persistence for operator-entered auction evidence. Every write goes
through here; nothing under app/core/ or app/pricing/ may import this file
or app/auction/evidence.py (test_auction_evidence_never_reaches_benchmark).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import psycopg

from app.auction.evidence import (
    ALLOWED_HOUSES,
    AUCTION_HEALTH_WINDOW_DAYS,
    AuctionHealth,
    InvalidAuctionEvidence,
    auction_health,
    derive_hammer_gbp,
)


def record_auction_evidence(conn: psycopg.Connection, *, wine_id: str, vintage: int,
                            bottle_ml: int, bottles_in_lot: int, auction_house: str,
                            sale_date, lot_ref: str, source_url: str, currency: str,
                            amount: Decimal, amount_basis: str,
                            premium_rate: Optional[Decimal] = None,
                            fx_rate: Optional[Decimal] = None,
                            fx_source: Optional[str] = None,
                            is_mixed_lot: bool = False,
                            condition_notes: Optional[str] = None,
                            condition_flagged: bool = False,
                            entered_by: str, entered_at: Optional[datetime] = None) -> dict:
    """"A person reading a public results page and writing down the facts is
    ordinary use" — but the house is still checked against the closed list
    in Python, with a clear reason, before the database's own CHECK is ever
    reached (`auction_evidence_house_known` is the backstop, same
    discipline as everywhere else in this codebase: a Python guard first,
    a structural constraint behind it).
    """
    if auction_house not in ALLOWED_HOUSES:
        raise InvalidAuctionEvidence(
            f"{auction_house!r} is not an approved auction house (decision 0023); "
            f"approved: {', '.join(sorted(ALLOWED_HOUSES))}")
    if not source_url.startswith("https://"):
        raise InvalidAuctionEvidence("Source URL is required — evidence without a source cannot be checked")
    entered_at = entered_at or datetime.now(timezone.utc)
    hammer_gbp = derive_hammer_gbp(amount=amount, currency=currency, amount_basis=amount_basis,
                                   premium_rate=premium_rate, fx_rate=fx_rate)
    return conn.execute(
        """INSERT INTO auction_evidence
               (wine_id, vintage, bottle_ml, bottles_in_lot, auction_house, sale_date, lot_ref,
                source_url, currency, amount, amount_basis, premium_rate, hammer_gbp, fx_rate,
                fx_source, is_mixed_lot, condition_notes, condition_flagged, entered_by, entered_at)
           VALUES (%(wine_id)s, %(vintage)s, %(bottle_ml)s, %(bottles_in_lot)s, %(auction_house)s,
                   %(sale_date)s, %(lot_ref)s, %(source_url)s, %(currency)s, %(amount)s,
                   %(amount_basis)s, %(premium_rate)s, %(hammer_gbp)s, %(fx_rate)s, %(fx_source)s,
                   %(is_mixed_lot)s, %(condition_notes)s, %(condition_flagged)s, %(entered_by)s,
                   %(entered_at)s)
        RETURNING *""",
        {"wine_id": wine_id, "vintage": vintage, "bottle_ml": bottle_ml,
         "bottles_in_lot": bottles_in_lot, "auction_house": auction_house, "sale_date": sale_date,
         "lot_ref": lot_ref, "source_url": source_url, "currency": currency, "amount": amount,
         "amount_basis": amount_basis, "premium_rate": premium_rate, "hammer_gbp": hammer_gbp,
         "fx_rate": fx_rate, "fx_source": fx_source, "is_mixed_lot": is_mixed_lot,
         "condition_notes": condition_notes, "condition_flagged": condition_flagged,
         "entered_by": entered_by, "entered_at": entered_at},
    ).fetchone()


def retract_auction_evidence(conn: psycopg.Connection, auction_evidence_id: str, *,
                             retracted_by: str, reason: str,
                             as_of: Optional[datetime] = None) -> dict:
    """Never edited, never deleted: retracted, with a reason, and re-entered
    if the correction still matters."""
    if not reason or not reason.strip():
        raise InvalidAuctionEvidence("a retraction needs a reason")
    as_of = as_of or datetime.now(timezone.utc)
    row = conn.execute(
        """UPDATE auction_evidence
              SET retracted_at = %s, retracted_by = %s, retraction_reason = %s
            WHERE auction_evidence_id = %s AND retracted_at IS NULL
        RETURNING *""",
        (as_of, retracted_by, reason, auction_evidence_id)).fetchone()
    if row is None:
        raise LookupError(f"no live auction evidence {auction_evidence_id}")
    return row


def evidence_for_wine(conn: psycopg.Connection, wine_id: str, vintage: int, bottle_ml: int, *,
                      include_retracted: bool = False) -> list[dict]:
    """Every row entered for this exact wine, vintage and bottle size — the
    same identity match the health check uses, not a cross-vintage or
    cross-format search."""
    query = "SELECT * FROM auction_evidence WHERE wine_id = %s AND vintage = %s AND bottle_ml = %s"
    params = [wine_id, vintage, bottle_ml]
    if not include_retracted:
        query += " AND retracted_at IS NULL"
    query += " ORDER BY sale_date DESC"
    return conn.execute(query, params).fetchall()


def line_auction_health(conn: psycopg.Connection, line_id: str, *,
                        uk_reference_per_bottle: Optional[Decimal] = None,
                        as_of: Optional[datetime] = None) -> AuctionHealth:
    """wine_id/vintage/bottle_ml come from the seller_line's own approved
    identity — never re-typed, never guessable from the raw description."""
    as_of = as_of or datetime.now(timezone.utc)
    line = conn.execute(
        "SELECT wine_id, vintage, bottle_ml FROM seller_line WHERE line_id = %s",
        (line_id,)).fetchone()
    if line is None or line["wine_id"] is None:
        raise LookupError(f"line {line_id} has no approved identity")
    cutoff = (as_of - timedelta(days=AUCTION_HEALTH_WINDOW_DAYS)).date()
    lots = conn.execute(
        """SELECT * FROM auction_evidence
            WHERE wine_id = %s AND vintage = %s AND bottle_ml = %s
              AND retracted_at IS NULL AND NOT quarantined AND sale_date >= %s
            ORDER BY sale_date DESC""",
        (line["wine_id"], line["vintage"], line["bottle_ml"], cutoff)).fetchall()
    return auction_health(lots, uk_reference_per_bottle=uk_reference_per_bottle)
