"""The operator Workbench, the Trades list, and the offer actions Delete and
Duplicate (decision 0050). Read models over existing tables — no pricing
logic here: status and next action are derived from what each offer already
records, never stored."""
from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.api import schemas as s
from app.api.deps import current_operator, db
from app.db import repo
from app.inbound import repo as inbound_repo
from app.pricing import pricer

router = APIRouter(tags=["workbench"], dependencies=[Depends(current_operator)])

#: What the operator does next, in their words — never a system state
#: (decision 0050). The flow is INCOMING → IDENTITY → PRICE → OFFER →
#: CONFIRMED → OPS → COMPLETE.
NEXT_ACTION = {
    "UNREADABLE": "Read again",
    "NEEDS_IDENTITY": "Review identity",
    "WHISKY": "No action — kept for the record",
    "READY_TO_PRICE": "Set price",
    "OFFER_OUT": "Await client",
    "CONFIRMED": "Arrange ops",
    "COMPLETE": "Done",
}


def _next_action(status: str, r: dict) -> str:
    """READY_TO_PRICE splits by what is actually missing: a supplier price,
    then a market check, then the price itself."""
    if status == "READY_TO_PRICE":
        if r["asking_price"] is None or not r["asking_currency"]:
            return "Complete details"
        if r["deal_id"] is None:
            return "Check market"
    return NEXT_ACTION[status]


def _status(r: dict) -> str:
    if r["category"] == "whisky":
        return "WHISKY"
    if r["parse_state"] != "parsed":
        return "UNREADABLE"
    if r["identity_confirmed_at"] is None:
        return "NEEDS_IDENTITY"
    if r["fulfilment_state"] == "COMPLETE":
        return "COMPLETE"
    if r["fulfilment_state"] == "OPEN":
        return "CONFIRMED"
    if r["vessel_sell"] is not None:
        return "OFFER_OUT"
    return "READY_TO_PRICE"


def _item(r: dict) -> s.TradeItemOut:
    status = _status(r)
    confirmed = r["identity_confirmed_at"] is not None and r["producer"]
    title = (repo.wine_display_name({"vintage": r["vintage"], "raw_description": ""},
                                    {"producer": r["producer"], "cuvee": r["cuvee"]})
             if confirmed else ("Photo" if r["has_media"] and not r["raw_snippet"] else
                                (r["raw_snippet"] or "Upload").splitlines()[0][:60]))
    return s.TradeItemOut(
        inbound_offer_id=r["inbound_offer_id"], status=status, title=title,
        snippet=None if confirmed else (r["raw_snippet"] or None),
        supplier_id=r["supplier_id"], supplier_name=r["supplier_name"],
        client_id=r["client_id"], buyer_name=r["client_name"] or r["buyer_name"],
        vessel_sell=r["vessel_sell"],
        quote_unit=(pricer.quote_unit(r["asking_basis"], r["pack_size"]) if r["pack_size"] else None),
        pack_size=r["pack_size"], quantity=r["quantity"], bottle_ml=r["bottle_ml"],
        next_action=_next_action(status, r),
        when=max(t for t in (r["received_at"], r["priced_at"], r["confirmed_at"]) if t))


def _cellar(d: dict) -> s.CellarItemOut:
    if d["identity_not_approved"]:
        action = "Review identity"
    elif d["not_searched"]:
        action = "Check market"
    elif d["review"]:
        action = "Review prices"
    elif d["ready"]:
        action = "Make an offer"
    else:
        action = "No action"
    return s.CellarItemOut(deal_id=d["deal_id"], name=d["name"], seller=d["seller"],
                           lines=d["lines"], ready=d["ready"], review=d["review"],
                           no_market=d["no_market"],
                           waiting=d["identity_not_approved"] + d["not_searched"],
                           next_action=action, when=d["created_at"])


@router.get("/workbench", response_model=s.WorkbenchOut)
def workbench(conn: psycopg.Connection = Depends(db)):
    rows = inbound_repo.pocket_offers(conn)
    items = [_item(r) for r in rows]
    by = lambda *statuses: [i for i in items if i.status in statuses]  # noqa: E731
    pocket_deals = inbound_repo.pocket_deal_ids(conn)
    cellar_lines = sum(1 for r in repo.review_queue(conn) if str(r["deal_id"]) not in pocket_deals)
    recent = []
    for r, i in zip(rows, items):
        for when, text in ((r["received_at"], "Captured"),
                           (r["identity_confirmed_at"], "Wine confirmed"),
                           (r["priced_at"], "Offer created"),
                           (r["confirmed_at"], f"Confirmed with {i.buyer_name}" if i.buyer_name else None)):
            if when and text:
                recent.append(s.ActivityOut(inbound_offer_id=r["inbound_offer_id"],
                                            text=f"{text} · {i.title}", when=when))
    # One line per offer — what last happened to it — so a busy offer does
    # not push everything else off the list.
    recent.sort(key=lambda a: a.when, reverse=True)
    seen: set = set()
    recent = [a for a in recent if not (a.inbound_offer_id in seen or seen.add(a.inbound_offer_id))]
    return s.WorkbenchOut(
        to_review=by("UNREADABLE", "NEEDS_IDENTITY"),
        review_counts=s.ReviewCountsOut(
            cellar_lines=cellar_lines,
            lwin_conflicts=len(repo.list_lwin_conflicts(conn, unresolved_only=True)),
            alias_suggestions=len(repo.alias_suggestions(conn, min_occurrences=2))),
        ready_to_price=by("READY_TO_PRICE"), offers_out=by("OFFER_OUT"),
        confirmed=by("CONFIRMED"), recent=recent[:10])


@router.get("/trades", response_model=s.TradesOut)
def trades(conn: psycopg.Connection = Depends(db)):
    return s.TradesOut(pocket=[_item(r) for r in inbound_repo.pocket_offers(conn)],
                       cellars=[_cellar(d) for d in inbound_repo.cellar_deals(conn)])


@router.post("/inbound-offers/{inbound_offer_id}/discard", response_model=s.InboundOfferOut)
def discard(inbound_offer_id: UUID, conn: psycopg.Connection = Depends(db),
            operator: dict = Depends(current_operator)):
    """Delete, as a soft delete (decision 0050): hidden everywhere, never
    destroyed; a confirmed trade can't be deleted."""
    try:
        with conn.transaction():
            row = inbound_repo.discard_offer(conn, str(inbound_offer_id),
                                             discarded_by=operator["operator_id"])
    except inbound_repo.NotDiscardable as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    return s.InboundOfferOut.model_validate({**row, "identity_confirmed_by": None,
                                             "has_media": row["raw_media"] is not None})


@router.post("/inbound-offers/{inbound_offer_id}/duplicate", response_model=s.InboundOfferOut,
             status_code=201)
def duplicate(inbound_offer_id: UUID, conn: psycopg.Connection = Depends(db),
              operator: dict = Depends(current_operator)):
    """A new, unconfirmed draft from the same message — confirmed afresh."""
    try:
        with conn.transaction():
            row = inbound_repo.duplicate_offer(conn, str(inbound_offer_id),
                                               created_by=operator["operator_id"])
    except LookupError as e:
        raise HTTPException(404, str(e))
    return s.InboundOfferOut.model_validate({**row, "identity_confirmed_by": None,
                                             "has_media": row["raw_media"] is not None})
