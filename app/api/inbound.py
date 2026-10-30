"""VESSEL Pocket, build brief Phase 1b step 2: Screen 1 (NEW) and Screen 2
(CANDIDATE). Operator-only — `router` carries the same session dependency
every other internal route uses; there is no public, seller/buyer-facing
side to this feature the way VESSEL Private Sale has one.

Decision 0040 applies to the provider call itself, not only to the
frontend: a provider outage or a malformed response is a distinct,
loud failure (502, `parse_state` left 'pending') from the AI running
fine and concluding there is nothing to find (200, `parse_state` =
'unparseable') — the two must never collapse into the same shape, and
neither may look like a clean parse.
"""
from __future__ import annotations

import base64
from typing import Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response

from app.ai.provider import AIProvider, InboundOfferProposal, get_provider
from app.api import schemas as s
from app.api.deps import current_operator, db, translate
from app.db import repo
from app.db.connection import transaction
from app.identity.want_list import match_want_list
from app.inbound import repo as inbound_repo
from app.worker import jobs

router = APIRouter(tags=["inbound"], dependencies=[Depends(current_operator)])


def _offer_out(conn: psycopg.Connection, row: dict) -> s.InboundOfferOut:
    ref = None
    if row["identity_confirmed_by"]:
        refs = repo.operator_refs(conn, [row["identity_confirmed_by"]])
        ref = refs.get(str(row["identity_confirmed_by"]))
    return s.InboundOfferOut.model_validate(
        {**row, "identity_confirmed_by": ref, "has_media": row["raw_media"] is not None})


def _proposal_out(proposal: InboundOfferProposal) -> s.InboundOfferProposalOut:
    hint = [m.producer for m in
           match_want_list(f"{proposal.producer or ''} {proposal.cuvee or ''}".strip())]
    return s.InboundOfferProposalOut(
        category=proposal.category, producer=proposal.producer, cuvee=proposal.cuvee,
        vintage=proposal.vintage, bottle_ml=proposal.bottle_ml, pack_size=proposal.pack_size,
        quantity=proposal.quantity, total_bottles=proposal.total_bottles,
        bond_status=proposal.bond_status, stock_location=proposal.stock_location,
        packaging=proposal.packaging, asking_price=proposal.asking_price,
        asking_currency=proposal.asking_currency, asking_basis=proposal.asking_basis,
        reasoning=proposal.reasoning, want_list_hint=hint)


def _parse(row: dict) -> tuple[dict, s.InboundOfferProposalOut]:
    """Calls the provider OUTSIDE any transaction that could roll the raw
    capture back, and never lets a provider exception reach the caller
    as anything but a 502 — never a 200 carrying a half-built candidate."""
    try:
        provider: AIProvider = get_provider()
        proposal = provider.propose_inbound_offer(
            row["raw_body"], row["raw_media"], row["media_mime"])
    except Exception as e:
        with transaction() as conn:
            inbound_repo.mark_parse_attempt_failed(
                conn, str(row["inbound_offer_id"]), error=str(e))
        # The raw capture survived (see above) but the caller has no id to
        # retry against unless this failure carries one — on a first create
        # call, this is the only response the client will ever see for this
        # row. Structured detail, not a plain string, exactly so the one
        # field that matters survives a 502.
        raise HTTPException(502, {"error": "couldn't read this — try again",
                                  "inbound_offer_id": str(row["inbound_offer_id"])}) from e

    with transaction() as conn:
        if proposal.category == "unknown":
            updated = inbound_repo.mark_unparseable(
                conn, str(row["inbound_offer_id"]), reason=proposal.reasoning)
        else:
            updated = inbound_repo.mark_parsed(
                conn, str(row["inbound_offer_id"]), category=proposal.category)
    return updated, _proposal_out(proposal)


@router.post("/inbound-offers", response_model=s.InboundOfferWithProposalOut, status_code=201)
def create_inbound_offer(body: s.InboundOfferIn, operator: dict = Depends(current_operator)):
    raw_media = base64.b64decode(body.raw_media_base64) if body.raw_media_base64 else None
    with transaction() as conn:
        row = inbound_repo.create_inbound_offer(
            conn, channel=body.channel, raw_body=body.raw_body, raw_media=raw_media,
            media_mime=body.media_mime, created_by=operator["operator_id"])
    # Committed and durable now — whatever the parse step does next, the
    # raw capture this call exists to protect has already survived it.
    updated, proposal = _parse(row)
    with transaction() as conn:
        # Deterministic pre-highlight (supplier-attribution-spec.md): the
        # model never sees this and never proposes a supplier — matched
        # against raw_body directly, read fresh off the row just created.
        matched = inbound_repo.match_supplier_aliases(conn, row["raw_body"])
        return s.InboundOfferWithProposalOut(offer=_offer_out(conn, updated), proposal=proposal,
                                             matched_supplier_ids=matched)


@router.get("/inbound-offers/candidate-wines", response_model=list[s.CandidateWineGroupOut])
def candidate_wines(producer: Optional[str] = None, cuvee: Optional[str] = None,
                    conn: psycopg.Connection = Depends(db)):
    """Screen 2's own filtered confirm-identity list. `producer`/`cuvee`
    are whatever the proposal (or the operator's own correction) names —
    never trusted as an identity, only used to narrow which real wines
    are worth showing.

    Declared BEFORE the dynamic /inbound-offers/{inbound_offer_id} route
    below on purpose: Starlette matches routes by string pattern first,
    type-converts the path parameter second, so a route registered after
    that one would have "candidate-wines" swallowed as an attempted UUID
    and 422 before ever reaching here."""
    return inbound_repo.candidate_wine_groups(conn, producer=producer, cuvee=cuvee)


@router.get("/inbound-offers/{inbound_offer_id}", response_model=s.InboundOfferOut)
def get_inbound_offer(inbound_offer_id: UUID, conn: psycopg.Connection = Depends(db)):
    row = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
    if row is None:
        raise HTTPException(404, "inbound offer not found")
    return _offer_out(conn, row)


@router.post("/inbound-offers/{inbound_offer_id}/reparse",
            response_model=s.InboundOfferWithProposalOut)
def reparse_inbound_offer(inbound_offer_id: UUID, conn: psycopg.Connection = Depends(db)):
    """A bad parse is re-parsed, never reconstructed — this reads the same
    raw_body/raw_media stored on create and calls the provider again."""
    row = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
    if row is None:
        raise HTTPException(404, "inbound offer not found")
    updated, proposal = _parse(row)
    with transaction() as conn2:
        matched = inbound_repo.match_supplier_aliases(conn2, row["raw_body"])
        return s.InboundOfferWithProposalOut(offer=_offer_out(conn2, updated), proposal=proposal,
                                             matched_supplier_ids=matched)


@router.get("/inbound-offers/{inbound_offer_id}/media")
def get_inbound_offer_media(inbound_offer_id: UUID, conn: psycopg.Connection = Depends(db)):
    """Screen 2's own rule: show the photo next to the proposed identity,
    so Doug confirms against the label, not against the AI's prose."""
    row = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
    if row is None or row["raw_media"] is None:
        raise HTTPException(404, "no media on this offer")
    return Response(content=bytes(row["raw_media"]), media_type=row["media_mime"] or "application/octet-stream")


@router.post("/inbound-offers/{inbound_offer_id}/confirm-identity", response_model=s.InboundOfferOut)
def confirm_identity(inbound_offer_id: UUID, body: s.ConfirmIdentityIn,
                     conn: psycopg.Connection = Depends(db),
                     operator: dict = Depends(current_operator)):
    """THE PHOTO GATE, technically enforced: a want-list wine (checked
    against wine.want_list, never against anything the caller claims)
    refuses this call outright without want_list_ack=true. No confidence
    score anywhere in this path can override that — there is no field
    for one to override."""
    wine = repo.get_wine(conn, str(body.wine_id))
    if wine is None:
        raise HTTPException(404, "wine not found")
    if wine["want_list"] and not body.want_list_ack:
        raise HTTPException(
            422, f"{wine['producer']} is a want-list producer — confirming this identity "
                f"requires explicit acknowledgement (want_list_ack), every time, regardless "
                f"of how the identity was proposed")
    # supplier-attribution-spec.md point 1: capture is never blocked, but
    # confirmation always is without a real supplier -- same enforcement
    # shape as want_list_ack just above, one check down.
    supplier = inbound_repo.get_supplier(conn, str(body.supplier_id))
    if supplier is None:
        raise HTTPException(404, "supplier not found")
    # A price with no stated unit is ambiguous by exactly the multiple
    # pack_size would convert it by -- blocking, not a detail, on any
    # line that is more than one bottle. A single bottle (pack_size=1,
    # quantity=1) has no such ambiguity: per_bottle, per_case and total
    # are numerically identical there.
    if (body.asking_price is not None and body.asking_basis is None
            and body.pack_size * body.quantity > 1):
        raise HTTPException(
            422, "a price was given with no basis (per bottle, per case, or total) on a "
                "line of more than one bottle -- that is ambiguous by exactly the multiple "
                "the commercial unit would convert it by; set asking_basis before confirming")
    try:
        with conn.transaction():
            row = inbound_repo.confirm_identity(
                conn, str(inbound_offer_id), wine_id=str(body.wine_id), vintage=body.vintage,
                bottle_ml=body.bottle_ml, pack_size=body.pack_size, quantity=body.quantity,
                packaging=body.packaging, bond_status=body.bond_status,
                stock_location=body.stock_location, asking_price=body.asking_price,
                asking_currency=body.asking_currency, asking_basis=body.asking_basis,
                supplier_id=str(body.supplier_id), confirmed_by=operator["operator_id"])
    except inbound_repo.NotConfirmable as e:
        raise HTTPException(422, str(e))
    except psycopg.Error as e:
        raise translate(e)
    return _offer_out(conn, row)


@router.post("/suppliers", response_model=s.SupplierOut, status_code=201)
def create_supplier(body: s.SupplierIn, conn: psycopg.Connection = Depends(db),
                    operator: dict = Depends(current_operator)):
    try:
        with conn.transaction():
            row = inbound_repo.create_supplier(conn, name=body.name, phone=body.phone,
                                               created_by=operator["operator_id"])
    except psycopg.Error as e:
        raise translate(e)
    return {**row, "last_used_at": None}


@router.get("/suppliers", response_model=list[s.SupplierOut])
def list_suppliers(conn: psycopg.Connection = Depends(db)):
    return inbound_repo.list_suppliers(conn)


def _evaluate(conn: psycopg.Connection, inbound_offer_id: UUID, operator: dict, *, force=False) -> s.EvaluateOut:
    from app.market.reference import market_reference
    from app.auction.repo import transaction_summary
    with conn.transaction():
        # Serialize line creation/cache updates and reconfirmation for this inbound record.
        conn.execute("SELECT inbound_offer_id FROM inbound_offer WHERE inbound_offer_id=%s FOR UPDATE",
                     (inbound_offer_id,)).fetchone()
        offer = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
        if offer is None:
            raise HTTPException(404, "inbound offer not found")
        try:
            deal_id, line_id = inbound_repo.ensure_evaluation_line(conn, offer, created_by=operator['operator_id'])
        except inbound_repo.NotReadyToEvaluate as exc:
            raise HTTPException(422, str(exc))
        line = repo.get_line(conn, line_id)
        expected = (str(offer['confirmed_wine_id']), offer['confirmed_vintage'],
                    offer['confirmed_bottle_ml'], offer['confirmed_pack_size'])
        actual = (str(line['wine_id']), line['vintage'], line['bottle_ml'], line['pack_size'])
        if actual != expected:
            raise HTTPException(422, 'Identity changed since confirmation; reconfirm this offer')
        facts = market_reference(conn, line, force=force)
        identity_flags = set(line['flags'] or []) & {'NAME_REVIEW', 'FORMAT_REVIEW'}
        ask = None
        if offer['confirmed_asking_price'] is not None:
            ask = s.SellerAskOut(amount=offer['confirmed_asking_price'],
                currency=offer['confirmed_asking_currency'], basis=offer['confirmed_asking_basis'],
                pack_size=offer['confirmed_pack_size'], quantity=offer['confirmed_quantity'])
        return s.EvaluateOut(deal_id=deal_id, line_id=line_id, **facts, ask=ask,
            transactions=transaction_summary(conn, line_id), blocks_create_offer=bool(identity_flags),
            block_reason='identity/format needs confirmation' if identity_flags else None)


@router.post("/inbound-offers/{inbound_offer_id}/evaluate", response_model=s.EvaluateOut)
def evaluate_inbound_offer(inbound_offer_id: UUID, conn: psycopg.Connection = Depends(db),
                           operator: dict = Depends(current_operator)):
    return _evaluate(conn, inbound_offer_id, operator)


@router.post("/inbound-offers/{inbound_offer_id}/collect-now",
            response_model=s.CollectNowOut)
def collect_now_for_offer(inbound_offer_id: UUID, conn: psycopg.Connection = Depends(db),
                          operator: dict = Depends(current_operator)):
    """speed-and-cost-plan.md's own first slice, deliberately small:
    one wine, synchronous, every targeted adapter with a search key for
    its producer -- never the whole-book sweep, never a queued job.
    Writes real snapshot_merchant rows (decision 0004 already
    distinguishes looked-and-empty from couldn't-look; no schema
    change here), then re-runs the exact same evaluation /evaluate
    itself would, so the screen shows one consistent result either
    way."""
    offer = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
    if offer is None:
        raise HTTPException(404, "inbound offer not found")
    if offer["confirmed_wine_id"] is None:
        raise HTTPException(422, "identity has not been confirmed yet")
    collected = jobs.collect_now(str(offer["confirmed_wine_id"]), offer["confirmed_vintage"])
    evaluation = _evaluate(conn, inbound_offer_id, operator, force=True)
    return s.CollectNowOut(collected=collected["results"], evaluation=evaluation)


@router.post("/auction-imports")
def import_auction_file(body: s.AuctionImportIn, conn: psycopg.Connection = Depends(db),
                        operator: dict = Depends(current_operator)):
    from app.auction.importer import import_file
    import binascii
    from zipfile import BadZipFile
    try:
        content = base64.b64decode(body.content_base64, validate=True)
        with conn.transaction():
            result = import_file(conn, filename=body.filename, content=content,
                                 operator_id=operator['operator_id'])
        return result
    except (ValueError, binascii.Error, KeyError, TypeError, BadZipFile) as exc:
        raise HTTPException(422, 'Invalid CSV/XLSX import: ' + str(exc)) from exc
