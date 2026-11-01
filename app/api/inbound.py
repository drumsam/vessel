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
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response

from app.ai.provider import AIProvider, InboundOfferProposal, get_provider
from app.api import schemas as s
from app.api.deps import current_operator, db, translate
from app.auction import repo as auction_repo
from app.core.flags import MIN_TRADE_MARGIN, REVIEW_FLAGS
from app.db import repo
from app.db.connection import transaction
from app.evaluate import walkaway
from app.counterparty import repo as cp
from app.feed import mrbridge
from app.identity.want_list import match_want_list
from app.inbound import repo as inbound_repo
from app.pricing import pricer
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
    if inbound_repo.get_fulfilment(conn, str(inbound_offer_id)):
        raise HTTPException(409, "this trade is already confirmed — what was agreed can't change")
    current = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
    if current is not None and current["discarded_at"] is not None:
        raise HTTPException(409, "this offer was deleted")
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
def list_suppliers(all: bool = False, conn: psycopg.Connection = Depends(db)):
    """The active chip-row list, most recently used first; `all=true` is the
    register view, inactive suppliers included (decision 0050)."""
    return cp.all_suppliers(conn) if all else inbound_repo.list_suppliers(conn)


def _round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _dec(v) -> Optional[Decimal]:
    return Decimal(str(v)) if v is not None else None


def _ask_unit(offer: dict, line_row: dict) -> Optional[Decimal]:
    if offer["confirmed_asking_price"] is None:
        return None
    return walkaway.ask_per_unit(Decimal(str(offer["confirmed_asking_price"])),
                                 offer["confirmed_asking_basis"], line_row["pack_size"],
                                 line_row["quantity"])


def _market(conn: psycopg.Connection, run: dict, pack_size: int) -> Optional[s.MarketOut]:
    if run is None or run["uk_floor"] is None:
        return None
    comps = []
    for c in repo.run_comps(conn, run["run_id"]):
        if c["role"] != "merchant_best":
            continue
        o = c["offer_snapshot"]
        per_bottle = (Decimal(o["per_bottle"]) if o.get("per_bottle")
                      else Decimal(o["price"]) / o["pack_size"])
        comps.append(s.MarketCompOut(merchant=o["merchant"], per_bottle=_round2(per_bottle),
                                     captured_at=o.get("captured_at"), source_url=o.get("source_url")))
    comps.sort(key=lambda c: c.per_bottle)
    floor = Decimal(str(run["uk_floor"]))
    return s.MarketOut(floor_per_unit=floor, floor_per_bottle=_round2(floor / pack_size),
                       comp_count=run["comp_count"],
                       checked_at=max((c.captured_at for c in comps if c.captured_at), default=None),
                       comps=comps)


def _market_note(run: Optional[dict]) -> Optional[str]:
    if run is None:
        return "has not been checked against the market"
    if run["state"] not in ("REVIEW", "NO_MARKET"):
        return None
    return repo.gate_reason_phrase({"flags": run["flags"] or [], "comp_count": run["comp_count"],
                                    "state": run["state"]})


def _committed(conn: psycopg.Connection, line_id: str) -> Optional[s.CommittedOfferOut]:
    p = repo.latest_pricing(conn, line_id)
    if p is None or p["price_basis"] != "parcel_trade":
        return None
    return s.CommittedOfferOut(
        pricing_id=p["pricing_id"], priced_at=p["priced_at"], vessel_sell=p["sell_price"],
        supplier_price=p["cost_gbp"], gp=p["gp"],
        requires_acknowledgement=p["requires_acknowledgement"],
        accepted=p["acknowledgement"] is not None)


def _pocket_facts(conn: psycopg.Connection, offer: dict, line_row: dict,
                  run: Optional[dict]) -> dict:
    """Everything the four-price screen shows beyond the benchmark itself.
    Read, never computed here: the Floor is the engine's, the auction figure
    is app/auction's own health rule, the default sell is the pricer's."""
    wine = repo.get_wine(conn, str(line_row["wine_id"]))
    pack_size = line_row["pack_size"]
    facts = dict(
        producer=wine["producer"], cuvee=wine["cuvee"], vintage=line_row["vintage"],
        bottle_ml=line_row["bottle_ml"], pack_size=pack_size, quantity=line_row["quantity"],
        packaging=offer["confirmed_packaging"], bond_status=offer["confirmed_bond_status"],
        stock_location=offer["confirmed_stock_location"], availability=offer["availability"],
        supplier_currency=offer["confirmed_asking_currency"], min_trade_margin=MIN_TRADE_MARGIN,
        market=_market(conn, run, pack_size), market_note=_market_note(run),
        market_steer=mrbridge.steer(conn, wine_id=str(line_row["wine_id"]),
                                    vintage=line_row["vintage"], bottle_ml=line_row["bottle_ml"]),
        committed=_committed(conn, str(line_row["line_id"])))
    supplier = inbound_repo.get_supplier(conn, str(offer["supplier_id"])) if offer["supplier_id"] else None
    facts["supplier_id"] = offer["supplier_id"]
    facts["supplier_name"] = supplier["name"] if supplier else None
    unit = pricer.quote_unit(offer["confirmed_asking_basis"], pack_size)
    facts["quote_unit"] = unit
    ask_unit = _ask_unit(offer, line_row)
    if ask_unit is not None:
        facts["ask"] = s.AskOut(per_unit=ask_unit, per_bottle=_round2(ask_unit / pack_size),
                                total=_round2(ask_unit * line_row["quantity"]))
        supplier_quote = pricer.per_quote(ask_unit, unit, pack_size)
        facts["supplier_quote"] = _round2(supplier_quote)
        default_quote = pricer.default_vessel_sell(supplier_quote)
        facts["default_vessel_sell"] = default_quote * (1 if unit == "case" else pack_size)
    ref = _dec(run["uk_reference"]) if run else None
    health = auction_repo.line_auction_health(
        conn, str(line_row["line_id"]),
        uk_reference_per_bottle=_round2(ref / pack_size) if ref is not None else None)
    if health.lot_count:
        facts["auction"] = s.AuctionOut(median_per_bottle=health.median_per_bottle_gbp,
                                        lot_count=health.lot_count,
                                        latest_sale_date=health.latest_sale_date)
    f = inbound_repo.get_fulfilment(conn, str(offer["inbound_offer_id"]))
    if f is not None:
        facts["fulfilment"] = s.FulfilmentOut.model_validate(
            {**f, "quote_unit": pricer.quote_unit(offer["confirmed_asking_basis"], f["pack_size"])})
    return facts


def _evaluate(conn: psycopg.Connection, inbound_offer_id: UUID, operator: dict) -> s.EvaluateOut:
    """Screen 3, EVALUATE: facts only, the walk-away price (buy-side-
    margin-test.md). Reuses the same engine every other line in this
    app goes through -- app.core.benchmark via resolve_offers and
    benchmark_with_band, never a second pricing path -- and synchronous,
    no RQ job, the same discipline decision 0039 already established
    for one line at a time.

    NO_MARKET is the PRIMARY state this builds for, not an error path:
    merchant evidence on these 20 want-list producers is measurably
    thin to absent, so that is the common case here, not the edge
    case. `checked_merchants` names exactly what was consulted and
    found nothing -- a screen that looks broken when it is working
    correctly will not get trusted.

    Shared by both /evaluate and /collect-now: a fresh collection ends
    in exactly the same re-benchmark a plain EVALUATE open does, never
    a second response shape for "the same facts, now with more
    evidence." A confirmed trade is never re-benchmarked: what was
    agreed is the record, not today's market."""
    offer = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
    if offer is None:
        raise HTTPException(404, "inbound offer not found")
    if offer["deal_id"] and inbound_repo.get_fulfilment(conn, str(inbound_offer_id)):
        return _view(conn, offer)
    try:
        with conn.transaction():
            deal_id, line_id = inbound_repo.ensure_evaluation_line(
                conn, offer, created_by=operator["operator_id"])
    except inbound_repo.NotReadyToEvaluate as e:
        raise HTTPException(422, str(e))

    when = datetime.now(timezone.utc)
    line_row = repo.get_line(conn, line_id)
    line = repo.seller_line_for_benchmark(line_row)
    res = repo.resolve_offers(conn, wine_id=str(line_row["wine_id"]),
                              vintage=line_row["vintage"], as_of=when)
    if not res.sources:
        # Vanishingly rare: no merchant anywhere has ever had a resolved
        # capture. Not the same fact as NO_MARKET (every approved
        # merchant searched and none offers THIS wine) -- never blurred
        # into it (invariant 10).
        return s.EvaluateOut(
            deal_id=UUID(deal_id), line_id=UUID(line_id), state="NOT_SEARCHED",
            blocks_create_offer=True,
            block_reason="nothing in this system has ever been collected yet",
            **_pocket_facts(conn, offer, line_row, None))
    with conn.transaction():
        jobs.benchmark_with_band(conn, line, res, when)
    return _view(conn, inbound_repo.get_inbound_offer(conn, str(inbound_offer_id)))


def _view(conn: psycopg.Connection, offer: dict) -> s.EvaluateOut:
    """The screen's facts from the line's LATEST run, without running a new
    one — shared by EVALUATE (just after benchmarking), CREATE OFFER and
    CONFIRM, so all three answer in exactly one shape."""
    line_row = repo.deal_lines(conn, str(offer["deal_id"]))[0]
    line_id = str(line_row["line_id"])
    run = repo.latest_run(conn, line_id)
    facts = _pocket_facts(conn, offer, line_row, run)
    base = dict(deal_id=offer["deal_id"], line_id=line_row["line_id"])
    if run is None:
        return s.EvaluateOut(**base, state="NOT_SEARCHED", blocks_create_offer=True,
                             block_reason="nothing in this system has ever been collected yet",
                             **facts)

    if run["state"] == "NO_MARKET":
        checked = sorted(m["name"] for m in repo.list_merchants(conn))
        return s.EvaluateOut(
            **base, state="NO_MARKET", as_of=run["as_of"],
            comp_count=0, flags=run["flags"] or [], checked_merchants=checked,
            blocks_create_offer=True,
            block_reason="no Floor — none of the merchants checked offer this wine", **facts)

    out = s.EvaluateOut(**base, state=run["state"], as_of=run["as_of"],
                        comp_count=run["comp_count"], flags=run["flags"] or [], **facts)

    uk_floor = Decimal(str(run["uk_floor"]))
    w = walkaway.compute(uk_floor)
    pack_size = line_row["pack_size"]
    out.walk_away = s.WalkAwayOut(
        uk_floor=w.uk_floor, uk_floor_per_bottle=_round2(w.uk_floor / pack_size),
        max_sell=w.max_sell, walk_away=w.walk_away,
        walk_away_per_bottle=_round2(w.walk_away / pack_size))

    # Review flags come first (buy-side-margin-test.md): a REVIEW line
    # blocks the offer regardless of what the ask comparison below says.
    needs_review = bool(set(run["flags"] or []) & REVIEW_FLAGS)
    if needs_review:
        out.blocks_create_offer = True
        out.block_reason = "this line needs review before an offer can be made"
    else:
        out.blocks_create_offer = False

    if out.ask is not None:
        ask_unit = out.ask.per_unit
        out.headroom = w.walk_away - ask_unit
        out.headroom_per_bottle = _round2(out.headroom / pack_size)
        out.margin_at_ask_pct = (walkaway.margin_at_ask(w.max_sell, ask_unit)
                                 * Decimal("100"))
        if ask_unit > w.walk_away:
            required = walkaway.required_sell_for_margin(ask_unit)
            out.required_sell_for_margin = required
            out.exceeds_floor = required > uk_floor
            if not needs_review:
                out.blocks_create_offer = True
                above_or_within = "above" if out.exceeds_floor else "within"
                out.block_reason = (
                    f"this ask is above walk-away — {int(walkaway.MIN_TRADE_MARGIN * 100)}% "
                    f"on it needs a sell of {required}, {above_or_within} the UK Floor")
    return out


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
    evaluation = _evaluate(conn, inbound_offer_id, operator)
    return s.CollectNowOut(collected=collected["results"], evaluation=evaluation)


# ------------------------------------------------- CREATE OFFER and CONFIRM


class _NeedsAccept(Exception):
    pass


def _trade_context(conn: psycopg.Connection, inbound_offer_id: UUID) -> tuple[dict, dict, dict]:
    """The offer, its Pocket line and wine — refusing, in plain English,
    anything that cannot be traded yet or any more."""
    offer = inbound_repo.get_inbound_offer(conn, str(inbound_offer_id))
    if offer is None:
        raise HTTPException(404, "inbound offer not found")
    if inbound_repo.get_fulfilment(conn, str(inbound_offer_id)):
        raise HTTPException(409, "this trade is already confirmed — what was agreed can't change")
    if offer["discarded_at"] is not None:
        raise HTTPException(409, "this offer was deleted")
    if offer["confirmed_wine_id"] is None or offer["deal_id"] is None:
        raise HTTPException(422, "check the market for this wine first")
    line_row = repo.deal_lines(conn, str(offer["deal_id"]))[0]
    wine = repo.get_wine(conn, str(line_row["wine_id"]))
    name = repo.wine_display_name(line_row, wine)
    # decision 0038, the listing-side check the share link applies too.
    if wine["want_list"] and line_row["want_list_ack_at"] is None:
        raise HTTPException(409, f"{name} is on the client want list and needs a one-time "
                                 "identity check")
    return offer, line_row, wine


@router.post("/inbound-offers/{inbound_offer_id}/offer", response_model=s.EvaluateOut)
def create_offer(inbound_offer_id: UUID, body: s.CreatePocketOfferIn,
                 conn: psycopg.Connection = Depends(db),
                 operator: dict = Depends(current_operator)):
    """CREATE OFFER: commits Doug's VESSEL sell price as one parcel_trade
    pricing_result on the Pocket line, against the market the screen just
    showed. The export gates are the database's own (requires_acknowledgement);
    when one applies and Doug has not accepted it, nothing is written and the
    reason comes back for a one-tap accept."""
    offer, line_row, wine = _trade_context(conn, inbound_offer_id)
    line_id = str(line_row["line_id"])
    name = repo.wine_display_name(line_row, wine)
    run = repo.latest_run(conn, line_id)
    if run is None:
        # Decision 0046: never searched is not the same fact as searched and
        # found nothing, and it stays its own state -- but a parcel trade's
        # price is Doug's, so it may proceed behind an explicit accept. Only
        # while there is still nothing to search against: once any capture
        # exists, EVALUATE benchmarks and this line must be checked first.
        if repo.resolve_offers(conn, wine_id=str(line_row["wine_id"]), vintage=line_row["vintage"],
                               as_of=datetime.now(timezone.utc)).sources:
            raise HTTPException(422, "check the market again before creating the offer")
        run = {"run_id": None, "uk_floor": None, "uk_reference": None, "uk_median": None,
               "comp_count": 0, "flags": [], "state": "NOT_SEARCHED"}
    elif run["computed_at"] < offer["identity_confirmed_at"]:
        raise HTTPException(422, "check the market again — the wine's details changed since")
    ask_unit = _ask_unit(offer, line_row)
    if ask_unit is None:
        raise HTTPException(422, "no supplier price was recorded for this offer")
    currency = offer["confirmed_asking_currency"]
    if not currency:
        raise HTTPException(422, "the supplier price has no currency")
    if currency != "GBP":
        raise HTTPException(422, f"the supplier price is in {currency} — Pocket can only price "
                                 "a GBP supplier price for now")
    pack_size = line_row["pack_size"]
    unit = pricer.quote_unit(offer["confirmed_asking_basis"], pack_size)
    if not pricer.is_quotable(body.vessel_sell, unit, pack_size):
        label = "/btl" if unit == "bottle" else f"/cs of {pack_size}"
        raise HTTPException(422, f"the VESSEL sell price must be a whole multiple of "
                                 f"{currency} {pricer.QUOTE_STEP} {label}")
    try:
        priced = pricer.price_parcel_trade(
            vessel_sell=body.vessel_sell, supplier_price=ask_unit, supplier_currency=currency,
            uk_reference=_dec(run["uk_reference"]), uk_floor=_dec(run["uk_floor"]))
    except pricer.CannotPrice as e:
        raise HTTPException(422, str(e))

    try:
        with conn.transaction():
            pricing_id = repo.save_pricing(conn, line_id=line_id, run=run, priced=priced,
                                           priced_by=operator["operator_id"], cost=ask_unit,
                                           cost_currency=currency, fx_rate=None)
            pricing = repo.latest_pricing(conn, line_id)
            if pricing["requires_acknowledgement"]:
                if not body.accept:
                    raise _NeedsAccept(f"{name} {repo.gate_reason_phrase(pricing)}")
                repo.acknowledge_pricing(conn, str(pricing_id),
                                         acknowledged_by=operator["operator_id"],
                                         note="accepted in Pocket at CREATE OFFER")
            inbound_repo.set_availability(conn, str(inbound_offer_id),
                                          (body.availability or "").strip() or None)
    except _NeedsAccept as e:
        raise HTTPException(409, {"error": f"{e} — accept to continue", "needs_accept": True})
    return _view(conn, inbound_repo.get_inbound_offer(conn, str(inbound_offer_id)))


@router.post("/inbound-offers/{inbound_offer_id}/confirm", response_model=s.EvaluateOut)
def confirm_trade(inbound_offer_id: UUID, body: s.ConfirmTradeIn,
                  conn: psycopg.Connection = Depends(db),
                  operator: dict = Depends(current_operator)):
    """CONFIRM: the buyer said yes. Freezes the committed offer into one
    fulfilment row — copied, never joined — and nothing about it can change
    afterwards (the table's own trigger)."""
    client = None
    if body.client_id is not None:
        client = cp.get_client(conn, str(body.client_id))
        if client is None:
            raise HTTPException(404, "client not found")
    buyer = client["name"] if client else (body.buyer_name or "").strip()
    if not buyer:
        raise HTTPException(422, "name the buyer")
    offer, line_row, wine = _trade_context(conn, inbound_offer_id)
    pricing = repo.latest_pricing(conn, str(line_row["line_id"]))
    if pricing is None or pricing["price_basis"] != "parcel_trade":
        raise HTTPException(422, "create the offer first")
    if pricing["priced_at"] < offer["identity_confirmed_at"]:
        raise HTTPException(409, "the wine's details changed after this offer was created — "
                                 "create the offer again")
    if pricing["requires_acknowledgement"] and pricing["acknowledgement"] is None:
        raise HTTPException(409, f"{repo.wine_display_name(line_row, wine)} "
                                 f"{repo.gate_reason_phrase(pricing)} and hasn't been accepted")
    supplier_price = Decimal(str(pricing["cost_gbp"]))
    sell = Decimal(str(pricing["sell_price"]))
    quantity = line_row["quantity"]
    try:
        with conn.transaction():
            inbound_repo.create_fulfilment(
                conn, inbound_offer_id=str(inbound_offer_id), line_id=str(line_row["line_id"]),
                pricing_id=str(pricing["pricing_id"]),
                pricing_requires_ack=pricing["requires_acknowledgement"],
                ack_id=(str(pricing["acknowledgement"]["ack_id"])
                        if pricing["acknowledgement"] else None),
                supplier_id=str(offer["supplier_id"]), buyer_name=buyer,
                wine_id=str(line_row["wine_id"]),
                wine_name=repo.wine_display_name(line_row, wine), vintage=line_row["vintage"],
                bottle_ml=line_row["bottle_ml"], pack_size=line_row["pack_size"],
                quantity=quantity, packaging=offer["confirmed_packaging"],
                bond_status=offer["confirmed_bond_status"],
                stock_location=offer["confirmed_stock_location"],
                availability=offer["availability"], currency=pricing["sell_currency"],
                supplier_price=supplier_price, vessel_sell_price=sell,
                gross_total=(sell - supplier_price) * quantity,
                confirmed_by=operator["operator_id"],
                client_id=str(client["client_id"]) if client else None)
    except psycopg.Error as e:
        raise translate(e)
    return _view(conn, offer)


@router.post("/fulfilments/{fulfilment_id}/complete", response_model=s.FulfilmentOut)
def complete_fulfilment(fulfilment_id: UUID, conn: psycopg.Connection = Depends(db),
                        operator: dict = Depends(current_operator)):
    with conn.transaction():
        row = inbound_repo.complete_fulfilment(conn, str(fulfilment_id),
                                               completed_by=operator["operator_id"])
    if row is None:
        raise HTTPException(409, "this trade is not open")
    return row


@router.get("/pocket/trades", response_model=list[s.PocketTradeOut])
def pocket_trades(conn: psycopg.Connection = Depends(db)):
    out = []
    for r in inbound_repo.list_trades(conn):
        state = {"OPEN": "CONFIRMED", "COMPLETE": "COMPLETE"}.get(r["fulfilment_state"], "OFFERED")
        name = repo.wine_display_name(r, {"producer": r["producer"], "cuvee": r["cuvee"]})
        out.append(s.PocketTradeOut(**r, wine_name=name, state=state,
                                    quote_unit=pricer.quote_unit(r["asking_basis"], r["pack_size"])))
    return out
