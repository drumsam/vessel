"""FastAPI service.  uvicorn app.api.main:app

The API records operator input and enqueues work. It never computes a price:
benchmarks are produced by the worker calling `app.core.benchmark` and are read
back here exactly as persisted.
"""
from __future__ import annotations

from typing import Iterator, Optional
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job

from app.api import schemas as s
from app.db import repo
from app.db.connection import transaction
from app.worker.queue import get_queue

app = FastAPI(title="UK Fine Wine Deal Pricer")

JOB_TIMEOUT = 60 * 30


def db() -> Iterator[psycopg.Connection]:
    """One transaction per request; rolled back if the handler raises."""
    with transaction() as conn:
        yield conn


def queue() -> Queue:
    return get_queue()


def _translate(e: Exception) -> HTTPException:
    if isinstance(e, repo.AmbiguousProducer):
        return HTTPException(409, {"error": str(e), "candidates": e.candidates})
    if isinstance(e, repo.Conflict):
        return HTTPException(409, str(e))
    if isinstance(e, psycopg.errors.UniqueViolation):
        return HTTPException(409, e.diag.message_detail or str(e))
    if isinstance(e, psycopg.errors.ForeignKeyViolation):
        return HTTPException(422, e.diag.message_detail or str(e))
    raise e


# ----------------------------------------------------------------- health


@app.get("/health")
def health(conn: psycopg.Connection = Depends(db), q: Queue = Depends(queue)) -> dict:
    conn.execute("SELECT 1")
    q.connection.ping()
    return {"database": "ok", "redis": "ok"}


# -------------------------------------------------------------- merchants


@app.get("/merchants", response_model=list[s.MerchantOut])
def list_merchants(conn: psycopg.Connection = Depends(db)):
    return repo.list_merchants(conn)


# ------------------------------------------------------------------ wines


@app.post("/wines", response_model=s.WineOut, status_code=201)
def create_wine(body: s.WineIn, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            return repo.create_wine(conn, **body.model_dump())
    except psycopg.Error as e:
        raise _translate(e)


@app.get("/wines", response_model=list[s.WineOut])
def list_wines(conn: psycopg.Connection = Depends(db)):
    return repo.list_wines(conn)


@app.get("/aliases", response_model=list[s.AliasOut])
def list_aliases(producer_only: Optional[bool] = None,
                 conn: psycopg.Connection = Depends(db)):
    """`producer_only=true` is the audit view: every alias with no cuvee."""
    return repo.list_aliases(conn, producer_only=producer_only)


@app.get("/alias-suggestions", response_model=list[s.AliasSuggestionOut])
def alias_suggestions(min_occurrences: int = 2, conn: psycopg.Connection = Depends(db)):
    return repo.alias_suggestions(conn, min_occurrences=min_occurrences)


@app.post("/wines/{wine_id}/aliases", response_model=s.AliasOut, status_code=201)
def create_alias(wine_id: UUID, body: s.AliasIn, conn: psycopg.Connection = Depends(db)):
    payload = body.model_dump()
    payload["confirm_target"] = str(body.confirm_target) if body.confirm_target else None
    try:
        with conn.transaction():
            return repo.create_alias(conn, wine_id=str(wine_id), **payload)
    except LookupError:
        raise HTTPException(404, "wine not found")
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)


# ------------------------------------------------------------ deals, lines


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
    out = s.LineOut.model_validate({**row, "line_state": _line_state(row, run)})
    out.benchmark = s.RunSummary.model_validate(run) if run else None
    out.pricing = s.PricingOut.model_validate(pricing) if pricing else None
    return out


def _deal_out(conn: psycopg.Connection, deal: dict) -> s.DealOut:
    lines = [_line_out(conn, r) for r in repo.deal_lines(conn, deal["deal_id"])]
    return s.DealOut.model_validate({**deal, "lines": lines})


@app.post("/deals", response_model=s.DealOut, status_code=201)
def create_deal(body: s.DealIn, conn: psycopg.Connection = Depends(db)):
    deal = body.model_dump(exclude={"lines"})
    try:
        with conn.transaction():
            row = repo.create_deal(conn, deal, [ln.model_dump() for ln in body.lines])
    except psycopg.Error as e:
        raise _translate(e)
    return _deal_out(conn, row)


@app.get("/deals/{deal_id}", response_model=s.DealOut)
def get_deal(deal_id: UUID, conn: psycopg.Connection = Depends(db)):
    deal = repo.get_deal(conn, str(deal_id))
    if deal is None:
        raise HTTPException(404, "deal not found")
    return _deal_out(conn, deal)


@app.put("/lines/{line_id}/identity", response_model=s.LineOut)
def set_line_identity(line_id: UUID, body: s.IdentityIn,
                      conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            row = repo.set_line_identity(conn, str(line_id), wine_id=str(body.wine_id),
                                         vintage=body.vintage, bottle_ml=body.bottle_ml,
                                         pack_size=body.pack_size, flags=list(body.flags),
                                         source=body.source, approved_by=body.approved_by)
    except psycopg.Error as e:
        raise _translate(e)
    if row is None:
        raise HTTPException(404, "line not found")
    return _line_out(conn, row)


@app.get("/lines/{line_id}/identity-history", response_model=list[s.IdentityHistoryOut])
def get_identity_history(line_id: UUID, conn: psycopg.Connection = Depends(db)):
    if repo.get_line(conn, str(line_id)) is None:
        raise HTTPException(404, "line not found")
    return repo.identity_history(conn, str(line_id))


@app.get("/lines/{line_id}/benchmark", response_model=s.RunOut)
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
        {**run, "sources": repo.run_sources(conn, run["run_id"]), "comps": comps})


@app.post("/lines/{line_id}/pricing/acknowledge", response_model=s.PricingOut)
def acknowledge_pricing(line_id: UUID, body: s.AcknowledgementIn,
                        conn: psycopg.Connection = Depends(db)):
    """A named operator accepting a price that is below cost, or above the UK
    market the client document quotes it against. Without this the line cannot
    reach a buyer offer at all."""
    pricing = repo.latest_pricing(conn, str(line_id))
    if pricing is None:
        raise HTTPException(404, "line has not been priced")
    try:
        with conn.transaction():
            repo.acknowledge_pricing(conn, pricing["pricing_id"],
                                     acknowledged_by=body.acknowledged_by, note=body.note)
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)
    return repo.latest_pricing(conn, str(line_id))


@app.get("/lines/{line_id}/pricing", response_model=s.PricingOut)
def get_line_pricing(line_id: UUID, conn: psycopg.Connection = Depends(db)):
    pricing = repo.latest_pricing(conn, str(line_id))
    if pricing is None:
        raise HTTPException(404, "line has not been priced")
    return pricing


# ------------------------------------------------------------ LWIN conflicts


@app.get("/lwin-conflicts", response_model=list[s.LwinConflictOut])
def list_lwin_conflicts(unresolved_only: bool = True, conn: psycopg.Connection = Depends(db)):
    return repo.list_lwin_conflicts(conn, unresolved_only=unresolved_only)


@app.post("/lwin-conflicts/{conflict_id}/resolve", response_model=s.LwinConflictOut)
def resolve_lwin_conflict(conflict_id: UUID, body: s.LwinConflictResolution,
                          conn: psycopg.Connection = Depends(db)):
    """The operator decides what the collision was, and the decision is acted on
    in one transaction: aliases for one wine under two names, or an exclusion
    plus an untrusted LWIN for two wines under one."""
    row = repo.get_lwin_conflict(conn, str(conflict_id))
    if row is None:
        raise HTTPException(404, "conflict not found")
    if row["resolution"] is not None:
        raise HTTPException(409, f"already resolved as {row['resolution']}")
    try:
        with conn.transaction():
            if body.resolution == "same_wine":
                for a in body.aliases:
                    repo.create_alias(conn, wine_id=str(a.wine_id), producer_text=a.producer_text,
                                      cuvee_text=a.cuvee_text, source="operator",
                                      approved_by=body.resolved_by,
                                      note=f"LWIN-7 {row['lwin7']} conflict: same wine")
            else:
                repo.create_exclusion(conn, str(body.exclude[0]), str(body.exclude[1]),
                                      reason=f"{row['merchant_id']} LWIN-7 {row['lwin7']}: "
                                             f"{'; '.join(row['names'])}")
                repo.mark_lwin_untrusted(
                    conn, row["merchant_id"], row["lwin7"], marked_by=body.resolved_by,
                    reason=f"used for different wines: {'; '.join(row['names'])}")
            return repo.close_lwin_conflict(conn, str(conflict_id), resolution=body.resolution,
                                            resolved_by=body.resolved_by, note=body.note)
    except LookupError:
        raise HTTPException(404, "wine not found")
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)


# ------------------------------------------------------ snapshots and jobs


@app.post("/snapshots", response_model=s.JobOut, status_code=202)
def collect_snapshot(body: s.SnapshotIn, q: Queue = Depends(queue)):
    job = q.enqueue_call(func="app.worker.jobs.collect_snapshot",
                         kwargs=body.model_dump(), timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@app.post("/snapshots/targeted", response_model=s.JobOut, status_code=202)
def collect_targeted(body: s.TargetedSnapshotIn, q: Queue = Depends(queue)):
    kwargs = body.model_dump()
    kwargs["wine_id"] = str(body.wine_id)
    job = q.enqueue_call(func="app.worker.jobs.collect_targeted",
                         kwargs=kwargs, timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@app.get("/snapshots/{snapshot_id}", response_model=s.SnapshotOut)
def get_snapshot(snapshot_id: UUID, conn: psycopg.Connection = Depends(db)):
    row = repo.get_snapshot(conn, str(snapshot_id))
    if row is None:
        raise HTTPException(404, "snapshot not found")
    return row


@app.post("/deals/{deal_id}/benchmark", response_model=s.JobOut, status_code=202)
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


@app.post("/deals/{deal_id}/pricing", response_model=s.JobOut, status_code=202)
def price_deal(deal_id: UUID, body: s.PricingIn,
               conn: psycopg.Connection = Depends(db), q: Queue = Depends(queue)):
    if repo.get_deal(conn, str(deal_id)) is None:
        raise HTTPException(404, "deal not found")
    threshold = body.deep_discount_threshold
    job = q.enqueue_call(func="app.worker.jobs.price_deal",
                         kwargs={"deal_id": str(deal_id), "priced_by": body.priced_by,
                                 "fx_rates": body.fx_rates,
                                 "deep_discount_threshold":
                                     str(threshold) if threshold is not None else None},
                         timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@app.post("/snapshots/prune", response_model=s.JobOut, status_code=202)
def prune_snapshots(keep: Optional[int] = None, q: Queue = Depends(queue)):
    """Drop snapshots no merchant still needs. Retention is per merchant, so a
    merchant's latest capture is never pruned."""
    job = q.enqueue_call(func="app.worker.jobs.prune_snapshots",
                         kwargs={"keep": keep}, timeout=JOB_TIMEOUT)
    return s.JobOut(job_id=job.id, status=job.get_status())


@app.get("/jobs/{job_id}", response_model=s.JobOut)
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
