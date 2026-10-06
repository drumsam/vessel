"""VESSEL Private Sale routes.

Two audiences, two routers. `router` is unauthenticated: the seller-approval,
drop, wine and buy/pay screens have no login system behind them in drop one —
reachable by anyone with the link (a UUID), the same simplification v3/v4
leave as an open operational item (KYC on buyers, a door policy) rather than
a developer's call to make silently. `operator_router` requires the existing
internal operator session: recommending lines, creating drops, and recording
a payment an operator has seen land are all internal actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.api import vessel_schemas as s
from app.api.deps import current_operator, db, translate
from app.db import repo as db_repo
from app.vessel import engine, repo

router = APIRouter(prefix="/vessel", tags=["vessel"])
operator_router = APIRouter(prefix="/vessel", tags=["vessel"],
                            dependencies=[Depends(current_operator)])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------ recommending


@operator_router.post("/deals/{deal_id}/recommend", response_model=s.RecommendOut)
def recommend(deal_id: UUID, body: s.RecommendIn, conn: psycopg.Connection = Depends(db)):
    kwargs = {}
    if body.minimum_gbp is not None:
        kwargs["minimum_gbp"] = body.minimum_gbp
    try:
        with conn.transaction():
            listings, excluded = repo.recommend_lines(
                conn, str(deal_id), currency=body.currency, fx_rate=body.fx_rate,
                fx_source=body.fx_source, fx_rate_date=body.fx_rate_date,
                stock_location=body.stock_location, warehouse=body.warehouse,
                line_choices={str(c.line_id): {"band": c.band, "discount": c.discount}
                             for c in body.line_choices},
                held_back=frozenset(str(i) for i in body.held_back_line_ids),
                **kwargs)
    except (engine.CannotList, ValueError) as e:
        raise HTTPException(422, str(e))
    except psycopg.Error as e:
        raise translate(e)
    return s.RecommendOut(listings=listings, excluded_counts=repo.why_not_recommended(excluded))


@router.get("/deals/{deal_id}/recommended", response_model=s.RecommendOut)
def get_recommended(deal_id: UUID, conn: psycopg.Connection = Depends(db)):
    """The seller-approval screen's data: only the lines being recommended,
    plus counts for the rest. No floor field — declining is the floor."""
    listings = repo.recommended_listings(conn, str(deal_id))
    return s.RecommendOut(listings=listings,
                          excluded_counts=repo.excluded_summary(conn, str(deal_id)))


# ------------------------------------------------------------------ mandate


@router.post("/deals/{deal_id}/approve", response_model=s.MandateOut)
def approve(deal_id: UUID, body: s.ApproveMandateIn, conn: psycopg.Connection = Depends(db)):
    """One Approve button. Everything it does happens in one transaction:
    write the mandate once, move every MOVEd listing under it, decline the
    rest."""
    try:
        with conn.transaction():
            mandate = repo.approve_mandate(
                conn, str(deal_id),
                move_line_ids=[str(i) for i in body.move_line_ids],
                keep_line_ids=[str(i) for i in body.keep_line_ids],
                approved_by_name=body.approved_by_name, window_days=body.window_days)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except psycopg.Error as e:
        raise translate(e)
    estimate = repo.mandate_estimate(conn, str(mandate["mandate_id"]))
    return s.MandateOut(**mandate, estimate=estimate)


# -------------------------------------------------------------------- drops


@operator_router.post("/drops", response_model=s.DropOut)
def create_drop(body: s.DropIn, conn: psycopg.Connection = Depends(db),
                operator: dict = Depends(current_operator)):
    return repo.create_drop(conn, label=body.label, drop_date=body.drop_date,
                            created_by=operator["operator_id"])


@operator_router.post("/drops/{drop_id}/listings", response_model=s.DropOut)
def add_to_drop(drop_id: UUID, body: s.AddToDropIn, conn: psycopg.Connection = Depends(db)):
    added = repo.add_to_drop(conn, str(drop_id), [str(i) for i in body.listing_ids])
    if added == 0:
        raise HTTPException(409, "none of these listings were APPROVED")
    drop = conn.execute("SELECT * FROM vessel_drop WHERE drop_id = %s",
                        (str(drop_id),)).fetchone()
    return drop


@router.get("/drops/{drop_id}", response_model=list[s.ListingOut])
def get_drop(drop_id: UUID, conn: psycopg.Connection = Depends(db)):
    """A drop can be empty. SOLD listings stay on the page, greyed, for the
    life of the drop — this returns them in state PAID/TRANSFERRING/SETTLED
    with sold_at set, same list, no separate endpoint."""
    return repo.drop_listings(conn, str(drop_id))


# --------------------------------------------------------------- wine page


@router.get("/listings/{listing_id}", response_model=s.ListingOut)
def get_listing(listing_id: UUID, conn: psycopg.Connection = Depends(db)):
    listing = repo.get_listing(conn, str(listing_id))
    if listing is None:
        raise HTTPException(404, "listing not found")
    with conn.transaction():
        repo.record_event(conn, str(listing_id), "VIEWED")
    return listing


# ------------------------------------------------------------- buy and pay


@router.post("/listings/{listing_id}/buy", response_model=s.ReservationOut)
def buy(listing_id: UUID, body: s.BuyIn, conn: psycopg.Connection = Depends(db)):
    """BUY. One live reservation per listing is enforced by a partial unique
    index, not this handler — two concurrent calls race the database, and
    exactly one gets a 201."""
    try:
        with conn.transaction():
            reservation = repo.reserve_listing(conn, str(listing_id),
                                              buyer_contact=body.buyer_contact, as_of=_now())
    except LookupError as e:
        raise HTTPException(404, str(e))
    except repo.AlreadyReserved as e:
        raise HTTPException(409, str(e))
    return reservation


@router.get("/reservations/{reservation_id}", response_model=s.ReservationWithListingOut)
def get_reservation(reservation_id: UUID, conn: psycopg.Connection = Depends(db)):
    reservation = repo.get_reservation(conn, str(reservation_id))
    if reservation is None:
        raise HTTPException(404, "reservation not found")
    return reservation


@router.post("/reservations/{reservation_id}/proof-of-payment", response_model=s.ReservationOut)
def proof_of_payment(reservation_id: UUID, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            return repo.submit_proof_of_payment(conn, str(reservation_id), as_of=_now())
    except LookupError as e:
        raise HTTPException(404, str(e))


@operator_router.post("/payments", response_model=s.PaymentOut)
def record_payment(body: s.PaymentIn, conn: psycopg.Connection = Depends(db)):
    """An operator entering what they saw land. Payment matching is manual in
    drop one (v3's build order puts automation in drops two to five); nothing
    ships on an unmatched payment either way."""
    with conn.transaction():
        return repo.record_payment(conn, reference=body.reference, amount=body.amount,
                                   currency=body.currency, received_at=body.received_at)


@operator_router.post("/reservations/expire-overdue", response_model=list[str])
def expire_overdue(conn: psycopg.Connection = Depends(db)):
    """No scheduler exists yet; an operator (or an external cron hitting this
    with a service credential) sweeps overdue holds back to LISTED."""
    with conn.transaction():
        return repo.expire_overdue_reservations(conn, as_of=_now())


# ----------------------------------------------------------------- analytics


@operator_router.get("/analytics/sell-through", response_model=list[s.SellThroughRowOut])
def sell_through(conn: psycopg.Connection = Depends(db)):
    return repo.sell_through_report(conn)
