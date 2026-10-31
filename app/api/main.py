"""FastAPI service.  uvicorn app.api.main:app

The API records operator input and enqueues work. It never computes a price:
benchmarks are produced by the worker calling `app.core.benchmark` and are read
back here exactly as persisted.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Iterator, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.api import auth, schemas as s
from app.api.deps import current_operator, db, queue
from app.api.deps import translate as _translate
from app.api.vessel import operator_router as vessel_operator_router
from app.api.vessel import router as vessel_router
from app.api.member import router as member_router
from app.api.inbound import router as inbound_router
from app.api.feed import router as feed_router
from app.auction import repo as auction_repo
from app.auction.evidence import InvalidAuctionEvidence
from app.core.enums import StockType
from app.core.flags import claims_a_saving
from app.db import repo
from app.evaluate import repo as evaluate_repo
from app.identity.want_list import match_want_list
from app.offerlink import repo as offerlink_repo
from app.market.parcel import SAME_PRICE_AS_ANOTHER_MERCHANT
from app.db.connection import EXPECTED_HEAD_REVISION, transaction
from app.worker import jobs
from app.worker.queue import get_queue

#: Vercel sets this on every deployment, preview and production alike, so
#: it also covers preview once Deployment Protection is off there too
#: (decision pending, VESSEL Pocket hosting). scripts/desk.sh never sets
#: it, so local development keeps Swagger UI. Schema disclosure -- route
#: paths, field names, the session cookie's own name -- is reconnaissance,
#: not data, but it still has no business being public.
_ON_VERCEL = bool(os.environ.get("VERCEL"))

app = FastAPI(
    title="UK Fine Wine Deal Pricer",
    docs_url=None if _ON_VERCEL else "/docs",
    redoc_url=None if _ON_VERCEL else "/redoc",
    openapi_url=None if _ON_VERCEL else "/openapi.json",
)

#: The browser app sends its session cookie, so the allowed origins are explicit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("FRONTEND_ORIGINS", "").split(",") if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOB_TIMEOUT = 60 * 30

#: Every route below is signed-in only. /health, /session and VESSEL's
#: public (seller- and buyer-facing) routes are not — see app/api/vessel.py.
protected = APIRouter(dependencies=[Depends(current_operator)])


# ----------------------------------------------------------------- health


@app.get("/health")
def health(conn: psycopg.Connection = Depends(db)) -> dict:
    """Never 500s on a missing worker: no REDIS_URL (scripts/desk.sh runs
    none on purpose) and an unreachable Redis both read as a plain
    "unavailable" here, not a crash — the frontend uses this to decide
    whether Collect/Benchmark/Price can be pressed at all, and a dependency
    failure before this body even ran would give it nothing to read.

    "database" is never just "can I connect" — a reachable Postgres with no
    tables, or with an older schema than this code expects, connects fine
    and would otherwise read as "ok" (the exact 0040 fail-open shape: a
    real connection standing in for a real answer). So this reads the
    applied Alembic revision and compares it to EXPECTED_HEAD_REVISION;
    green means usable, not merely reachable."""
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        revision = row["version_num"] if row else None
    except psycopg.errors.UndefinedTable:
        revision = None
    if revision == EXPECTED_HEAD_REVISION:
        database_status = "ok"
    elif revision is None:
        database_status = "unmigrated"
    else:
        database_status = f"schema_mismatch: at {revision}, expected {EXPECTED_HEAD_REVISION}"
    try:
        get_queue().connection.ping()
        redis_status = "ok"
    except Exception:
        redis_status = "unavailable"
    return {"database": database_status, "redis": redis_status}


# -------------------------------------------------------------- merchants


@protected.get("/merchants", response_model=list[s.MerchantOut])
def list_merchants(conn: psycopg.Connection = Depends(db)):
    return repo.list_merchants(conn)


# ------------------------------------------------------------------ wines


@protected.post("/wines", response_model=s.WineOut, status_code=201)
def create_wine(body: s.WineIn, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            return repo.create_wine(conn, **body.model_dump())
    except psycopg.Error as e:
        raise _translate(e)


@protected.get("/wines", response_model=list[s.WineOut])
def list_wines(conn: psycopg.Connection = Depends(db)):
    return repo.list_wines(conn)


@protected.get("/aliases", response_model=list[s.AliasOut])
def list_aliases(producer_only: Optional[bool] = None,
                 conn: psycopg.Connection = Depends(db)):
    """`producer_only=true` is the audit view: every alias with no cuvee."""
    return _ops(conn, repo.list_aliases(conn, producer_only=producer_only), "approved_by")


@protected.get("/alias-suggestions", response_model=list[s.AliasSuggestionOut])
def alias_suggestions(min_occurrences: int = 2, conn: psycopg.Connection = Depends(db)):
    out = []
    for g in repo.alias_suggestions(conn, min_occurrences=min_occurrences):
        refs = repo.operator_refs(conn, g["changed_by"])
        out.append({**g, "changed_by": [refs[str(i)] for i in g["changed_by"] if str(i) in refs]})
    return out


@protected.post("/wines/{wine_id}/aliases", response_model=s.AliasOut, status_code=201)
def create_alias(wine_id: UUID, body: s.AliasIn, conn: psycopg.Connection = Depends(db),
                 q: Queue = Depends(queue), operator: dict = Depends(current_operator)):
    payload = body.model_dump()
    payload["approved_by"] = operator["operator_id"]
    payload["confirm_target"] = str(body.confirm_target) if body.confirm_target else None
    try:
        with conn.transaction():
            out = _op(conn, repo.create_alias(conn, wine_id=str(wine_id), **payload),
                      "approved_by")
    except LookupError:
        raise HTTPException(404, "wine not found")
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)
    # Decision 0029: this alias may make an already-rejected offer resolvable
    # right now, and nothing goes back for it on its own — recover what it
    # can, from what is already on disk, no network.
    q.enqueue_call(func="app.worker.jobs.reresolve_rejects", timeout=JOB_TIMEOUT)
    return out


# ------------------------------------------------------------ deals, lines


def _ops(conn: psycopg.Connection, rows: list[dict], *fields: str) -> list[dict]:
    """Replace stored operator ids with who they are, for display."""
    refs = repo.operator_refs(conn, [r[f] for r in rows for f in fields])
    return [{**r, **{f: refs.get(str(r[f])) if r[f] else None for f in fields}} for r in rows]


def _op(conn: psycopg.Connection, row: dict, *fields: str) -> dict:
    return _ops(conn, [row], *fields)[0]


def _line_state(row: dict, run: Optional[dict]) -> str:
    """NOT_SEARCHED is not NO_MARKET. NO_MARKET means every approved merchant
    was searched and none of them offers this wine; NOT_SEARCHED means nobody
    has looked yet, so there is nothing to price or to send a buyer."""
    if row["wine_id"] is None:
        return "IDENTITY_NOT_APPROVED"
    if run is None:
        return "NOT_SEARCHED"
    return run["state"]


def _line_out(conn: psycopg.Connection, row: dict) -> s.LineOut:
    run = repo.latest_run(conn, row["line_id"])
    pricing = repo.latest_pricing(conn, row["line_id"])
    wine = repo.get_wine(conn, str(row["wine_id"])) if row["wine_id"] else None
    resolved = _op(conn, row, "wine_id_approved_by", "want_list_ack_by")
    out = s.LineOut.model_validate({
        **resolved, "line_state": _line_state(row, run),
        "want_list": bool(wine and wine["want_list"]),
        "want_list_acknowledged_by": resolved["want_list_ack_by"],
        "want_list_acknowledged_at": row["want_list_ack_at"],
    })
    out.benchmark = s.RunSummary.model_validate(run) if run else None
    out.pricing = s.PricingOut.model_validate(_pricing_out(conn, pricing)) if pricing else None
    return out


def _pricing_out(conn: psycopg.Connection, pricing: dict) -> dict:
    ack = pricing.get("acknowledgement")
    uk_floor = Decimal(str(pricing["uk_floor"])) if pricing.get("uk_floor") is not None else None
    sell_price = Decimal(str(pricing["sell_price"])) if pricing.get("sell_price") is not None else None
    saving = claims_a_saving(sell_price, uk_floor) if sell_price is not None else None
    return {**_op(conn, pricing, "priced_by"),
            "acknowledgement": _op(conn, ack, "acknowledged_by") if ack else None,
            "floor_saving_claim": saving}


def _deal_out(conn: psycopg.Connection, deal: dict) -> s.DealOut:
    lines = [_line_out(conn, r) for r in repo.deal_lines(conn, deal["deal_id"])]
    return s.DealOut.model_validate({**_op(conn, deal, "created_by"), "lines": lines})


@protected.post("/deals", response_model=s.DealOut, status_code=201)
def create_deal(body: s.DealIn, conn: psycopg.Connection = Depends(db),
                operator: dict = Depends(current_operator)):
    deal = {**body.model_dump(exclude={"lines"}), "created_by": operator["operator_id"]}
    try:
        with conn.transaction():
            row = repo.create_deal(conn, deal, [ln.model_dump() for ln in body.lines])
    except psycopg.Error as e:
        raise _translate(e)
    return _deal_out(conn, row)


@protected.get("/deals", response_model=list[s.DealSummaryOut])
def list_deals(conn: psycopg.Connection = Depends(db)):
    return _ops(conn, repo.list_deals(conn), "created_by")


@protected.get("/review-queue", response_model=list[s.ReviewQueueOut])
def review_queue(conn: psycopg.Connection = Depends(db)):
    """Everything waiting on a person, across deals: unapproved identities,
    lines nobody has searched, lines in REVIEW, and prices that need accepting."""
    rows = repo.review_queue(conn)
    return [{**r, "line_state": _line_state(r, {"state": r["state"]} if r["state"] else None),
             "benchmark_flags": r["benchmark_flags"] or [],
             "pricing_flags": r["pricing_flags"] or [],
             "requires_acknowledgement": bool(r["requires_acknowledgement"]),
             "acknowledged": bool(r["acknowledged"])} for r in rows]


@protected.get("/deals/{deal_id}", response_model=s.DealOut)
def get_deal(deal_id: UUID, conn: psycopg.Connection = Depends(db)):
    deal = repo.get_deal(conn, str(deal_id))
    if deal is None:
        raise HTTPException(404, "deal not found")
    return _deal_out(conn, deal)


@protected.post("/deals/{deal_id}/offer-links", response_model=s.OfferLinkOut, status_code=201)
def create_offer_link(deal_id: UUID, body: s.OfferLinkIn, conn: psycopg.Connection = Depends(db),
                      operator: dict = Depends(current_operator)):
    """A signed, unguessable, read-only public link for a chosen set of a
    deal's lines (decision 0035) — never for a line still gated under
    invariant 12, whatever the caller asks for."""
    try:
        with conn.transaction():
            link = offerlink_repo.create_link(
                conn, deal_id=str(deal_id), line_ids=[str(i) for i in body.line_ids],
                kind=body.kind, fx_rate=body.fx_rate, created_by=operator["operator_id"])
    except (offerlink_repo.LineNotInDeal, offerlink_repo.LineNotSendable) as e:
        raise HTTPException(422, str(e))
    return link


@app.get("/public/offer-links/{token}", response_model=s.PublicOfferOut,
         response_model_exclude_none=True)
def get_public_offer(token: str, conn: psycopg.Connection = Depends(db)):
    """No session, by design — this is the one screen in the whole app a
    buyer or a seller can open directly. An unknown or an expired token
    reads identically, a plain 404: a stale link should never confirm to
    whoever is holding it that it once worked."""
    link = offerlink_repo.get_valid_link(conn, token)
    if link is None:
        raise HTTPException(404, "link not found or expired")
    return offerlink_repo.build_public_payload(conn, link)


@protected.put("/lines/{line_id}/identity", response_model=s.LineOut)
def set_line_identity(line_id: UUID, body: s.IdentityIn,
                      conn: psycopg.Connection = Depends(db),
                      operator: dict = Depends(current_operator)):
    try:
        with conn.transaction():
            row = repo.set_line_identity(conn, str(line_id), wine_id=str(body.wine_id),
                                         vintage=body.vintage, bottle_ml=body.bottle_ml,
                                         pack_size=body.pack_size, flags=list(body.flags),
                                         source=body.source,
                                         approved_by=operator["operator_id"])
    except psycopg.Error as e:
        raise _translate(e)
    if row is None:
        raise HTTPException(404, "line not found")
    return _line_out(conn, row)


@protected.get("/lines/{line_id}/identity-history", response_model=list[s.IdentityHistoryOut])
def get_identity_history(line_id: UUID, conn: psycopg.Connection = Depends(db)):
    if repo.get_line(conn, str(line_id)) is None:
        raise HTTPException(404, "line not found")
    return _ops(conn, repo.identity_history(conn, str(line_id)), "changed_by")


@protected.get("/lines/{line_id}/benchmark", response_model=s.RunOut)
def get_line_benchmark(line_id: UUID, conn: psycopg.Connection = Depends(db)):
    run = repo.latest_run(conn, str(line_id))
    if run is None:
        raise HTTPException(404, "line has not been benchmarked")
    # Everything below is read from the run itself, so it is unchanged after
    # the snapshots it drew on have been pruned.
    comps = [s.CompOut.model_validate({**c["offer_snapshot"], "role": c["role"],
                                       "reject_reason": c["reject_reason"],
                                       "offer_pk": c["offer_pk"]})
             for c in repo.run_comps(conn, run["run_id"])]
    return s.RunOut.model_validate(
        {**run, "sources": repo.run_sources(conn, run["run_id"]), "comps": comps,
         "vintage_band": _band_out(conn, run["run_id"]),
         "same_price_notes": _same_price_notes(comps)})


def _same_price_notes(comps: list[s.CompOut]) -> list[dict]:
    """Two merchants at one price, to the penny — possibly one parcel seen
    twice. Read from the run's own merchant-bests, so it is still right after
    the snapshots behind it have been pruned (decision 0014)."""
    bests: dict[Decimal, list[s.CompOut]] = {}
    for c in comps:
        if c.role == "merchant_best":
            bests.setdefault(c.price, []).append(c)
    out = []
    for price, group in sorted(bests.items()):
        if len({c.merchant_id for c in group}) < 2:
            continue
        merchants = sorted(c.merchant for c in group)
        out.append({
            "price": price, "merchants": merchants,
            "any_brokered": any(c.stock_type == StockType.BROKERED.value for c in group),
            "flag": SAME_PRICE_AS_ANOTHER_MERCHANT,
            "note": (f"same price as another merchant ({', '.join(merchants)} at {price}) "
                     "— may be the same parcel")})
    return out


def _band_out(conn: psycopg.Connection, run_id) -> Optional[dict]:
    """The band for a run, with its exclusions. None for runs computed before
    the check existed — absent, not an empty band that claims it was checked."""
    band = repo.run_band(conn, str(run_id))
    if band is None:
        return None
    exclusions = []
    for x in repo.run_exclusions(conn, str(run_id)):
        snapshot = x["offer_snapshot"]
        exclusions.append(_op(conn, {**x, "merchant": snapshot["merchant"],
                                     "price": snapshot["price"]}, "reinstated_by"))
    return {**band, "excluded": exclusions}


@protected.post("/comp-exclusions/{exclusion_id}/reinstate", response_model=s.RunOut)
def reinstate_comp(exclusion_id: UUID, body: s.ReinstateIn,
                   conn: psycopg.Connection = Depends(db),
                   operator: dict = Depends(current_operator)):
    """Put an automatically excluded comp back: the one click in spec 5.

    The original run is not edited. A new run is computed with the comp
    restored, and the exclusion row records who asked and why.
    """
    try:
        done = jobs.reinstate_comp(str(exclusion_id), str(operator["operator_id"]), body.reason)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)
    return get_line_benchmark(UUID(done["line_id"]), conn)


@protected.post("/lines/{line_id}/pricing/acknowledge", response_model=s.PricingOut)
def acknowledge_pricing(line_id: UUID, body: s.AcknowledgementIn,
                        conn: psycopg.Connection = Depends(db),
                        operator: dict = Depends(current_operator)):
    """A named operator accepting a price that is below cost, or above the UK
    market the client document quotes it against. Without this the line cannot
    reach a buyer offer at all."""
    pricing = repo.latest_pricing(conn, str(line_id))
    if pricing is None:
        raise HTTPException(404, "line has not been priced")
    try:
        with conn.transaction():
            repo.acknowledge_pricing(conn, pricing["pricing_id"],
                                     acknowledged_by=operator["operator_id"], note=body.note)
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)
    return _pricing_out(conn, repo.latest_pricing(conn, str(line_id)))


@protected.get("/lines/{line_id}/pricing", response_model=s.PricingOut)
def get_line_pricing(line_id: UUID, conn: psycopg.Connection = Depends(db)):
    pricing = repo.latest_pricing(conn, str(line_id))
    if pricing is None:
        raise HTTPException(404, "line has not been priced")
    return _pricing_out(conn, pricing)


@protected.post("/lines/{line_id}/want-list/acknowledge", response_model=s.LineOut)
def acknowledge_want_list(line_id: UUID, conn: psycopg.Connection = Depends(db),
                          operator: dict = Depends(current_operator)):
    """A named operator confirming, once, that this line really is one of
    the ten want-list producers and not its cheaper namesake (decision
    0038) — tied to the line's own identity, never to a single pricing
    run, so it survives a reprice."""
    try:
        with conn.transaction():
            repo.acknowledge_want_list(conn, str(line_id), acknowledged_by=operator["operator_id"])
    except LookupError as e:
        raise HTTPException(404, str(e))
    except repo.Conflict as e:
        raise HTTPException(409, str(e))
    return _line_out(conn, repo.get_line(conn, str(line_id)))


# --------------------------------------------------------------- auction evidence


@protected.post("/lines/{line_id}/auction-evidence", response_model=s.AuctionEvidenceOut)
def add_auction_evidence(line_id: UUID, body: s.AuctionEvidenceIn,
                         conn: psycopg.Connection = Depends(db),
                         operator: dict = Depends(current_operator)):
    """A person reading a public results page and typing in six facts, with
    a mandatory source URL — never a scraper. wine_id/vintage/bottle_ml come
    from the line's own approved identity, never from the request body."""
    line = repo.get_line(conn, str(line_id))
    if line is None:
        raise HTTPException(404, "line not found")
    if line["wine_id"] is None:
        raise HTTPException(422, "line has no approved identity yet")
    try:
        with conn.transaction():
            row = auction_repo.record_auction_evidence(
                conn, wine_id=str(line["wine_id"]), vintage=line["vintage"],
                bottle_ml=line["bottle_ml"], bottles_in_lot=body.bottles_in_lot,
                auction_house=body.auction_house, sale_date=body.sale_date,
                lot_ref=body.lot_ref, source_url=body.source_url, currency=body.currency,
                amount=body.amount, amount_basis=body.amount_basis,
                premium_rate=body.premium_rate, fx_rate=body.fx_rate, fx_source=body.fx_source,
                is_mixed_lot=body.is_mixed_lot, condition_notes=body.condition_notes,
                condition_flagged=body.condition_flagged,
                entered_by=operator["operator_id"])
    except InvalidAuctionEvidence as e:
        raise HTTPException(422, str(e))
    except psycopg.Error as e:
        raise _translate(e)
    return _op(conn, row, "entered_by", "retracted_by")


@protected.get("/lines/{line_id}/auction-evidence", response_model=list[s.AuctionEvidenceOut])
def get_line_auction_evidence(line_id: UUID, include_retracted: bool = False,
                              conn: psycopg.Connection = Depends(db)):
    line = repo.get_line(conn, str(line_id))
    if line is None:
        raise HTTPException(404, "line not found")
    if line["wine_id"] is None:
        return []
    rows = auction_repo.evidence_for_wine(conn, str(line["wine_id"]), line["vintage"],
                                          line["bottle_ml"], include_retracted=include_retracted)
    return _ops(conn, rows, "entered_by", "retracted_by")


@protected.post("/auction-evidence/{auction_evidence_id}/retract",
                response_model=s.AuctionEvidenceOut)
def retract_auction_evidence(auction_evidence_id: UUID, body: s.AuctionRetractIn,
                             conn: psycopg.Connection = Depends(db),
                             operator: dict = Depends(current_operator)):
    try:
        with conn.transaction():
            row = auction_repo.retract_auction_evidence(
                conn, str(auction_evidence_id), retracted_by=operator["operator_id"],
                reason=body.reason)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except InvalidAuctionEvidence as e:
        raise HTTPException(422, str(e))
    return _op(conn, row, "entered_by", "retracted_by")


@protected.get("/lines/{line_id}/auction-health", response_model=s.AuctionHealthOut)
def get_line_auction_health(line_id: UUID, conn: psycopg.Connection = Depends(db)):
    """Opened from a line in the review queue. Works for a NO_MARKET line
    too — the note says plainly that auction evidence is not a price."""
    run = repo.latest_run(conn, str(line_id))
    uk_reference_per_bottle = Decimal(str(run["uk_reference"])) if run and run["uk_reference"] else None
    try:
        health = auction_repo.line_auction_health(
            conn, str(line_id), uk_reference_per_bottle=uk_reference_per_bottle)
    except LookupError as e:
        raise HTTPException(422, str(e))
    return health


# ------------------------------------------------- buy-side evaluation (0039)


@protected.post("/identity/want-list-match", response_model=list[s.WantListMatchOut])
def want_list_match(body: s.WantListMatchIn):
    """A suggestion only (decision 0038) — never sets a wine_id, never
    bypasses the operator picking the exact wine by hand."""
    return [{"producer": m.producer, "always_review": m.always_review,
            "fork_with": list(m.fork_with)} for m in match_want_list(body.text)]


@protected.post("/evaluate", response_model=s.LineOut, status_code=201)
def evaluate_offer(body: s.EvaluateOfferIn, conn: psycopg.Connection = Depends(db),
                   operator: dict = Depends(current_operator)):
    """The single box (decision 0039): what Doug was offered, and the
    market prices he found for it, each source named. Every comp becomes
    a real `offer` row and goes through the real benchmark, synchronously
    — one line, not a job queue."""
    try:
        with conn.transaction():
            result = evaluate_repo.evaluate_offer(
                conn, raw_description=body.raw_description, wine_id=str(body.wine_id),
                vintage=body.vintage, bottle_ml=body.bottle_ml, pack_size=body.pack_size,
                quantity=body.quantity, asking_price=body.asking_price,
                asking_currency=body.asking_currency,
                comps=[c.model_dump() for c in body.comps],
                evaluated_by=operator["operator_id"])
    except evaluate_repo.InvalidEvaluation as e:
        raise HTTPException(422, str(e))
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)
    return _line_out(conn, repo.get_line(conn, result["line_id"]))


# ------------------------------------------------------------ LWIN conflicts


@protected.get("/lwin-conflicts", response_model=list[s.LwinConflictOut])
def list_lwin_conflicts(unresolved_only: bool = True, conn: psycopg.Connection = Depends(db)):
    return _ops(conn, repo.list_lwin_conflicts(conn, unresolved_only=unresolved_only),
                "resolved_by")


@protected.post("/lwin-conflicts/{conflict_id}/resolve", response_model=s.LwinConflictOut)
def resolve_lwin_conflict(conflict_id: UUID, body: s.LwinConflictResolution,
                          conn: psycopg.Connection = Depends(db), q: Queue = Depends(queue),
                          operator: dict = Depends(current_operator)):
    """The operator decides what the collision was, and the decision is acted on
    in one transaction: aliases for one wine under two names, or an exclusion
    plus an untrusted LWIN for two wines under one."""
    row = repo.get_lwin_conflict(conn, str(conflict_id))
    if row is None:
        raise HTTPException(404, "conflict not found")
    if row["resolution"] is not None:
        resolved_as = "one wine under two names" if row["resolution"] == "same_wine" \
            else "two different wines"
        raise HTTPException(409, f"this conflict was already resolved as {resolved_as}")
    try:
        with conn.transaction():
            if body.resolution == "same_wine":
                for a in body.aliases:
                    repo.create_alias(conn, wine_id=str(a.wine_id), producer_text=a.producer_text,
                                      cuvee_text=a.cuvee_text, source="operator",
                                      approved_by=operator["operator_id"],
                                      confirm_target=str(a.wine_id),
                                      note=f"LWIN-7 {row['lwin7']} conflict: same wine")
            else:
                repo.create_exclusion(conn, str(body.exclude[0]), str(body.exclude[1]),
                                      reason=f"{row['merchant_id']} LWIN-7 {row['lwin7']}: "
                                             f"{'; '.join(row['names'])}")
                repo.mark_lwin_untrusted(
                    conn, row["merchant_id"], row["lwin7"], marked_by=operator["operator_id"],
                    reason=f"used for different wines: {'; '.join(row['names'])}")
            out = _op(conn, repo.close_lwin_conflict(
                conn, str(conflict_id), resolution=body.resolution,
                resolved_by=operator["operator_id"], note=body.note), "resolved_by")
    except LookupError:
        raise HTTPException(404, "wine not found")
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)
    if body.resolution == "same_wine":
        # Decision 0029: a "same wine" resolution is also a new alias.
        q.enqueue_call(func="app.worker.jobs.reresolve_rejects", timeout=JOB_TIMEOUT)
    return out


# ------------------------------------------------------------ buyer offers


@protected.post("/deals/{deal_id}/buyer-offers", response_model=s.BuyerOfferOut, status_code=201)
def create_buyer_offer(deal_id: UUID, body: s.BuyerOfferIn,
                       conn: psycopg.Connection = Depends(db),
                       operator: dict = Depends(current_operator)):
    """Issue the offer. A line with no price, or with a price that needed an
    operator's acknowledgement and has not had one, stops the whole document."""
    if repo.get_deal(conn, str(deal_id)) is None:
        raise HTTPException(404, "deal not found")
    try:
        with conn.transaction():
            offer = repo.create_buyer_offer(
                conn, deal_id=str(deal_id), client=body.client, currency=body.currency,
                terms=body.terms, issued_by=operator["operator_id"],
                asks=[ln.model_dump() for ln in body.lines])
    except LookupError as e:
        raise HTTPException(404, str(e))
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)
    return _op(conn, offer, "issued_by")


@protected.get("/deals/{deal_id}/buyer-offers", response_model=list[s.BuyerOfferOut])
def list_buyer_offers(deal_id: UUID, conn: psycopg.Connection = Depends(db)):
    return _ops(conn, repo.deal_buyer_offers(conn, str(deal_id)), "issued_by")


@protected.get("/buyer-offers/{buyer_offer_id}", response_model=s.BuyerOfferOut)
def get_buyer_offer(buyer_offer_id: UUID, conn: psycopg.Connection = Depends(db)):
    offer = repo.get_buyer_offer(conn, str(buyer_offer_id))
    if offer is None:
        raise HTTPException(404, "buyer offer not found")
    return _op(conn, offer, "issued_by")


# ------------------------------------------------------ snapshots and jobs


@protected.post("/snapshots", response_model=s.JobOut, status_code=202)
def collect_snapshot(body: s.SnapshotIn, q: Queue = Depends(queue)):
    job = q.enqueue_call(func="app.worker.jobs.collect_snapshot",
                         kwargs=body.model_dump(), timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@protected.get("/merchants/{merchant_id}/search-keys", response_model=list[s.SearchKeyOut])
def list_search_keys(merchant_id: str, conn: psycopg.Connection = Depends(db)):
    return _ops(conn, repo.list_search_keys(conn, merchant_id), "set_by")


@protected.put("/merchants/{merchant_id}/search-keys", response_model=s.SearchKeyOut)
def set_search_key(merchant_id: str, body: s.SearchKeyIn,
                   conn: psycopg.Connection = Depends(db),
                   operator: dict = Depends(current_operator)):
    try:
        with conn.transaction():
            row = repo.set_search_key(conn, merchant_id=merchant_id,
                                      producer_key=body.producer_key, params=body.params,
                                      source="operator", set_by=operator["operator_id"],
                                      note=body.note)
    except psycopg.Error as e:
        raise _translate(e)
    return _op(conn, row, "set_by")


@protected.post("/merchants/{merchant_id}/search-keys/learn", response_model=s.JobOut,
                status_code=202)
def learn_search_keys(merchant_id: str, q: Queue = Depends(queue),
                      operator: dict = Depends(current_operator)):
    """Read the merchant's own producer index into merchant_search_key."""
    job = q.enqueue_call(func="app.worker.jobs.learn_search_keys",
                         kwargs={"merchant_id": merchant_id,
                                 "set_by": str(operator["operator_id"])},
                         timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@protected.post("/deals/{deal_id}/deep-search", response_model=s.JobOut, status_code=202)
def deep_search(deal_id: UUID, body: Optional[s.DeepSearchIn] = None,
                conn: psycopg.Connection = Depends(db), q: Queue = Depends(queue)):
    """DEEP MERCHANT SEARCH: ask the search-only merchants about the lines the
    sweep left thin, and nothing else."""
    if repo.get_deal(conn, str(deal_id)) is None:
        raise HTTPException(404, "deal not found")
    body = body or s.DeepSearchIn()
    job = q.enqueue_call(func="app.worker.jobs.deep_search",
                         kwargs={"deal_id": str(deal_id), "min_comps": body.min_comps,
                                 "merchant_ids": body.merchant_ids}, timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@protected.post("/snapshots/targeted", response_model=s.JobOut, status_code=202)
def collect_targeted(body: s.TargetedSnapshotIn, q: Queue = Depends(queue)):
    kwargs = body.model_dump()
    kwargs["wine_id"] = str(body.wine_id)
    job = q.enqueue_call(func="app.worker.jobs.collect_targeted",
                         kwargs=kwargs, timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@protected.get("/snapshots/{snapshot_id}", response_model=s.SnapshotOut)
def get_snapshot(snapshot_id: UUID, conn: psycopg.Connection = Depends(db)):
    row = repo.get_snapshot(conn, str(snapshot_id))
    if row is None:
        raise HTTPException(404, "snapshot not found")
    return row


@protected.post("/deals/{deal_id}/benchmark", response_model=s.JobOut, status_code=202)
def benchmark_deal(deal_id: UUID, body: Optional[s.BenchmarkIn] = None,
                   conn: psycopg.Connection = Depends(db), q: Queue = Depends(queue)):
    if repo.get_deal(conn, str(deal_id)) is None:
        raise HTTPException(404, "deal not found")
    as_of = body.as_of if body else None
    job = q.enqueue_call(func="app.worker.jobs.benchmark_deal",
                         kwargs={"deal_id": str(deal_id),
                                 "as_of": as_of.isoformat() if as_of else None},
                         timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@protected.post("/deals/{deal_id}/pricing", response_model=s.JobOut, status_code=202)
def price_deal(deal_id: UUID, body: s.PricingIn,
               conn: psycopg.Connection = Depends(db), q: Queue = Depends(queue),
               operator: dict = Depends(current_operator)):
    if repo.get_deal(conn, str(deal_id)) is None:
        raise HTTPException(404, "deal not found")
    threshold = body.deep_discount_threshold
    job = q.enqueue_call(func="app.worker.jobs.price_deal",
                         kwargs={"deal_id": str(deal_id),
                                 "priced_by": str(operator["operator_id"]),
                                 "fx_rates": body.fx_rates,
                                 "deep_discount_threshold":
                                     str(threshold) if threshold is not None else None},
                         timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@protected.post("/snapshots/prune", response_model=s.JobOut, status_code=202)
def prune_snapshots(keep: Optional[int] = None, q: Queue = Depends(queue)):
    """Drop snapshots no merchant still needs. Retention is per merchant, so a
    merchant's latest capture is never pruned."""
    job = q.enqueue_call(func="app.worker.jobs.prune_snapshots",
                         kwargs={"keep": keep}, timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@protected.get("/jobs/{job_id}", response_model=s.JobOut)
def get_job(job_id: str, q: Queue = Depends(queue)):
    try:
        job = Job.fetch(job_id, connection=q.connection)
    except NoSuchJobError:
        raise HTTPException(404, "job not found")
    status = job.get_status()
    latest = job.latest_result()
    error = latest.exc_string if latest is not None and latest.exc_string else None
    return s.JobOut(job_id=job.id, status=status,
                    result=job.return_value() if status == "finished" else None,
                    error=error)


# ---------------------------------------------------------------- the session


@app.post("/session", response_model=s.OperatorOut)
def sign_in(body: s.SignIn, response: Response, conn: psycopg.Connection = Depends(db)):
    operator = auth.authenticate(conn, body.username, body.password)
    if operator is None:
        raise HTTPException(401, "unknown operator, wrong password, or access revoked")
    auth.start_session(conn, operator["operator_id"], response)
    return operator


@app.get("/session", response_model=s.OperatorOut)
def whoami(operator: dict = Depends(current_operator)):
    return operator


@app.delete("/session", status_code=204)
def sign_out(response: Response, pricer_session: Optional[str] = Cookie(default=None),
             conn: psycopg.Connection = Depends(db)):
    auth.end_session(conn, pricer_session, response)


app.include_router(protected)
app.include_router(vessel_router)
app.include_router(vessel_operator_router)
app.include_router(member_router)
app.include_router(inbound_router)
app.include_router(feed_router)
