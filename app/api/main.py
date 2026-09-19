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


@app.post("/wines/{wine_id}/aliases", response_model=s.AliasOut, status_code=201)
def create_alias(wine_id: UUID, body: s.AliasIn, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            return repo.create_alias(conn, wine_id=str(wine_id), **body.model_dump())
    except LookupError:
        raise HTTPException(404, "wine not found")
    except (repo.Conflict, psycopg.Error) as e:
        raise _translate(e)


# ------------------------------------------------------------ deals, lines


def _line_out(conn: psycopg.Connection, row: dict) -> s.LineOut:
    out = s.LineOut.model_validate(row)
    run = repo.latest_run(conn, row["line_id"])
    out.benchmark = s.RunSummary.model_validate(run) if run else None
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
