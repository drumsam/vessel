"""Service layer: API, migrations, RQ worker.

Offline tests always run. Tests marked `pg` need a disposable Postgres and run
only when TEST_DATABASE_URL is set; they DROP the public schema of that database.

    TEST_DATABASE_URL=postgresql://... python -m pytest -q
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from rq import Queue, SimpleWorker

from app.api import main as api
from app.api.schemas import LineIn
from app.worker import jobs
from app.worker.queue import QUEUE_NAME

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = (ROOT / "app/db/schema.sql").read_text()
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


# ============================================================ offline: money


@pytest.mark.parametrize("cost", [2353.1, 2353.10, 1e3])
def test_json_number_money_is_refused_not_converted(cost):
    """A JSON number is a binary float before we see it. £2,353.10 must arrive
    as the string "2353.10" or not at all."""
    with pytest.raises(ValidationError, match="never a JSON number"):
        LineIn(row_index=0, raw_description="x", raw_row={}, quantity=1,
               cost=cost, cost_currency="GBP")


def test_money_string_is_exact_and_third_decimal_is_refused():
    ok = LineIn(row_index=0, raw_description="x", raw_row={}, quantity=1,
                cost="2353.10", cost_currency="GBP")
    assert ok.cost == Decimal("2353.10") and str(ok.cost) == "2353.10"
    # numeric(14,2) would silently round this to 2353.11 on insert.
    with pytest.raises(ValidationError):
        LineIn(row_index=0, raw_description="x", raw_row={}, quantity=1,
               cost="2353.105", cost_currency="GBP")


def test_api_rejects_float_money_with_422():
    api.app.dependency_overrides[api.db] = lambda: None
    try:
        r = TestClient(api.app).post("/deals", json={
            "name": "d", "created_by": "op",
            "lines": [{"row_index": 0, "raw_description": "x", "raw_row": {},
                       "quantity": 1, "cost": 2353.1, "cost_currency": "GBP"}]})
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 422
    assert "never a JSON number" in r.text


def test_schema_has_no_float_column_types():
    body = re.sub(r"--[^\n]*", "", SCHEMA_SQL).lower()
    assert not re.search(r"\b(float\d*|real|double\s+precision|money)\b", body)


# ======================================================= offline: migrations


def test_offline_migration_sql_renders_the_whole_schema():
    env = {**os.environ, "DATABASE_URL": "postgresql://offline/none"}
    out = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
                         cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
    for table in ("wine", "wine_alias", "offer", "offer_reject", "seller_line",
                  "benchmark_run", "benchmark_comp", "ai_decision"):
        assert f"CREATE TABLE {table} (" in out
    assert "INSERT INTO merchant" in out


# ============================================================ offline: queue


def test_snapshot_request_enqueues_the_collection_job():
    q = Queue(QUEUE_NAME, connection=fakeredis.FakeRedis())
    api.app.dependency_overrides[api.queue] = lambda: q
    try:
        r = TestClient(api.app).post("/snapshots", json={"merchant_ids": ["farr"]})
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 202
    job = q.fetch_job(r.json()["job_id"])
    assert job.func_name == "app.worker.jobs.collect_snapshot"
    assert job.kwargs == {"merchant_ids": ["farr"], "is_demo": False}


# ================================================================ Postgres


def _reset(url: str) -> None:
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT,
                   env={**os.environ, "DATABASE_URL": TEST_DB}, check=True,
                   capture_output=True)


def _catalog(url: str) -> dict:
    import psycopg
    with psycopg.connect(url) as c:
        cols = c.execute("""
            SELECT table_name, column_name, data_type, udt_name, character_maximum_length,
                   numeric_precision, numeric_scale, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name <> 'alembic_version'
             ORDER BY 1, 2""").fetchall()
        cons = c.execute("""
            SELECT t.relname, con.conname, pg_get_constraintdef(con.oid)
              FROM pg_constraint con JOIN pg_class t ON t.oid = con.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'public' AND t.relname <> 'alembic_version'
             ORDER BY 1, 2""").fetchall()
        idx = c.execute("""
            SELECT indexname, indexdef FROM pg_indexes
             WHERE schemaname = 'public' AND tablename <> 'alembic_version'
             ORDER BY 1""").fetchall()
    return {"columns": cols, "constraints": cons, "indexes": idx}


@pytest.fixture
def db(monkeypatch):
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    monkeypatch.setenv("DATABASE_URL", TEST_DB)

    # Server-side prepared statements off: a single-session test server such as
    # PGlite shares one backend between connections, so psycopg's statement
    # names collide. Real Postgres does not need this.
    from app.db import connection
    real_connect = connection.connect

    def connect(url=None):
        conn = real_connect(url)
        conn.prepare_threshold = None
        return conn

    monkeypatch.setattr(connection, "connect", connect)
    yield TEST_DB


@pytest.fixture
def client(db):
    q = Queue(QUEUE_NAME, connection=fakeredis.FakeRedis())
    api.app.dependency_overrides[api.queue] = lambda: q
    c = TestClient(api.app)
    c.queue = q
    yield c
    api.app.dependency_overrides.clear()


def _work(q: Queue) -> None:
    SimpleWorker([q], connection=q.connection).work(burst=True)


def _job(client: TestClient, job_id: str) -> dict:
    return client.get(f"/jobs/{job_id}").json()


@pg
def test_migrations_reproduce_schema_sql_exactly():
    """schema.sql is the head schema. If a migration and schema.sql disagree on
    any column, type, default, constraint or index, this fails."""
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    migrated = _catalog(TEST_DB)
    _reset(TEST_DB)
    import psycopg
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute(SCHEMA_SQL)
    assert migrated == _catalog(TEST_DB)
    assert any(col[1] == "price" and col[5:7] == (14, 2) for col in migrated["columns"])


@pg
def test_downgrade_to_base_removes_every_table():
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")
    assert _catalog(TEST_DB) == {"columns": [], "constraints": [], "indexes": []}


# --- live-shaped Farr records ----------------------------------------------

R = "Domaine Armand Rousseau"


def farr(wine_id, wine, vintage, size, price, per, units, variation=None):
    return {"WineId": wine_id, "Wine": wine, "Vintage": vintage, "Size": size,
            "SellGBP": price, "Per": per, "Units": units, "Variation": variation,
            "Url": f"https://www.farrvintners.com/wine.php?wine={wine_id}"}


FARR_BOOK = [
    # Charmes 2011: one loose bottle at £610, and a 6x75cl case — the Bordeaux
    # Index / Farr pair from decision 0001, reduced to Farr only.
    farr(1, "Charmes-Chambertin, Domaine Armand Rousseau", "2011", "1×75cl", "610.00", 1, 1,
         "Not in original carton"),
    farr(2, "Charmes-Chambertin, Domaine Armand Rousseau", "2011", "6×75cl", "4428.00", 6, 1),
    # Mazoyères is a structural exclusion from Charmes. No alias exists for it.
    farr(3, "Mazoyeres-Chambertin, Domaine Armand Rousseau", "2011", "1×75cl", "300.00", 1, 4),
    farr(4, "Mixed case of Rousseau, Domaine Armand Rousseau", "2011", "6×75cl", "3000.00", 6, 1),
]


def _seed_wine(client, producer=R, cuvee="Charmes-Chambertin") -> str:
    r = client.post("/wines", json={"producer": producer, "cuvee": cuvee})
    assert r.status_code == 201, r.text
    return r.json()["wine_id"]


def _collect(client, book=FARR_BOOK) -> str:
    """Enqueue through the API, run the real job in-process with the network
    replaced: fetch returns the captured book and robots.txt allows."""
    jid = client.post("/snapshots", json={"merchant_ids": ["farr"]}).json()["job_id"]
    orig = jobs.collect_snapshot

    def offline(merchant_ids=None, is_demo=False):
        return orig(merchant_ids, is_demo=is_demo,
                    fetch=lambda a: book if a.id == "farr" else [], robots=lambda url: None)

    jobs.collect_snapshot = offline
    try:
        _work(client.queue)
    finally:
        jobs.collect_snapshot = orig
    j = _job(client, jid)
    assert j["status"] == "finished", j
    return j["result"]


def _deal(client, wine_id, quantity=6, pack=1) -> tuple[str, str]:
    r = client.post("/deals", json={
        "name": "Rousseau parcel", "created_by": "op", "currency": "GBP",
        "lines": [{"row_index": 0, "raw_description": "Rousseau Charmes 2011 x6 loose",
                   "raw_row": {"A": "Rousseau Charmes 2011", "B": "6", "C": "£480"},
                   "quantity": quantity, "cost": "480.00", "cost_currency": "GBP"}]})
    assert r.status_code == 201, r.text
    deal = r.json()
    line_id = deal["lines"][0]["line_id"]
    r = client.put(f"/lines/{line_id}/identity", json={
        "wine_id": wine_id, "vintage": 2011, "bottle_ml": 750, "pack_size": pack})
    assert r.status_code == 200, r.text
    return deal["deal_id"], line_id


def _benchmark(client, deal_id) -> dict:
    jid = client.post(f"/deals/{deal_id}/benchmark").json()["job_id"]
    _work(client.queue)
    return _job(client, jid)


@pg
def test_every_raw_record_ends_as_one_offer_or_one_reject(client):
    _seed_wine(client)
    sid = _collect(client)
    snap = client.get(f"/snapshots/{sid}").json()
    assert (snap["offers_written"], snap["offers_rejected"]) == (2, 2)
    import psycopg
    with psycopg.connect(TEST_DB) as c:
        rejects = dict(c.execute("SELECT reason, detail FROM offer_reject").fetchall())
    assert set(rejects) == {"MIXED_LOT", "UNRESOLVED_IDENTITY"}
    assert "Mazoyeres" in rejects["UNRESOLVED_IDENTITY"]


@pg
def test_one_farr_bottle_is_review_not_ready_and_case_is_visible_not_priced(client):
    """Farr Charmes 2011: one loose bottle at £610 must price as ONE_COMP /
    REVIEW, and the 6x75cl case (£738/btl pro rata) must be shown, not used."""
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    assert _benchmark(client, deal_id)["status"] == "finished"

    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["state"] == "REVIEW"
    assert set(run["flags"]) == {"ONE_COMP", "QUANTITY_SHORTFALL"}
    assert (run["uk_floor"], run["uk_reference"], run["uk_median"]) == ("610.00",) * 3
    roles = {(c["role"], c["price"]) for c in run["comps"]}
    assert ("merchant_best", "610.00") in roles
    assert ("cross_unit", "4428.00") in roles
    assert ("rejected", "4428.00") in roles
    xu = next(c for c in run["comps"] if c["role"] == "cross_unit")
    assert Decimal(xu["per_bottle"]) == Decimal("738")
    assert next(c for c in run["comps"] if c["role"] == "merchant_best")[
        "condition_notes"] == "Not in original carton"


@pg
def test_api_never_emits_a_float_for_money(client):
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)

    def walk(v, path=""):
        if isinstance(v, float):
            raise AssertionError(f"float at {path}: {v!r}")
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}")
        if isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")

    walk(client.get(f"/deals/{deal_id}").json())
    walk(client.get(f"/lines/{line_id}/benchmark").json())


@pg
def test_half_penny_median_is_rounded_explicitly_and_floor_reference_stay_exact(client):
    """Two merchants at £610.01 and £610.02: the median is £610.015. uk_median
    is numeric(14,2), so it is banker's-rounded in code, not by Postgres.
    Floor and Reference are real offer prices and are never rounded."""
    wid = _seed_wine(client)
    sid = _collect(client, [farr(1, "Charmes-Chambertin, Domaine Armand Rousseau",
                                 "2011", "1×75cl", "610.01", 1, 6)])
    import psycopg
    from dataclasses import replace
    from app.db import repo
    with psycopg.connect(TEST_DB, row_factory=psycopg.rows.dict_row) as c:
        o = repo.offer_from_row(c.execute(
            "SELECT o.*, m.name AS merchant_name FROM offer o JOIN merchant m USING (merchant_id)"
        ).fetchone())
        repo.write_offer(c, sid, replace(o, offer_id="goedhuis:X", merchant_id="goedhuis",
                                         price=Decimal("610.02"), wine_id=wid))
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["state"] == "READY" and run["comp_count"] == 2
    assert (run["uk_floor"], run["uk_reference"], run["uk_median"]) == (
        "610.01", "610.02", "610.02")


@pg
def test_unapproved_merchant_is_outside_the_universe(client):
    wid = _seed_wine(client)
    _collect(client)
    import psycopg
    with psycopg.connect(TEST_DB) as c:
        c.execute("UPDATE merchant SET approved = false WHERE merchant_id = 'farr'")
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    assert client.get(f"/lines/{line_id}/benchmark").json()["state"] == "NO_MARKET"


@pg
def test_benchmark_with_no_snapshot_fails_closed_instead_of_no_market(client):
    wid = _seed_wine(client)
    deal_id, line_id = _deal(client, wid)
    j = _benchmark(client, deal_id)
    assert j["status"] == "failed" and "NoSnapshot" in j["error"]
    assert client.get(f"/lines/{line_id}/benchmark").status_code == 404


@pg
def test_line_without_approved_identity_is_not_benchmarked(client):
    _seed_wine(client)
    _collect(client)
    r = client.post("/deals", json={"name": "d", "created_by": "op", "lines": [
        {"row_index": 0, "raw_description": "Rousseau ?", "raw_row": {}, "quantity": 1}]})
    deal_id = r.json()["deal_id"]
    j = _benchmark(client, deal_id)
    assert j["result"]["runs"] == {} and len(j["result"]["unapproved_identity"]) == 1


@pg
def test_setting_identity_never_touches_the_original_seller_text(client):
    wid = _seed_wine(client)
    deal_id, _ = _deal(client, wid)
    line = client.get(f"/deals/{deal_id}").json()["lines"][0]
    assert line["raw_description"] == "Rousseau Charmes 2011 x6 loose"
    assert line["raw_row"] == {"A": "Rousseau Charmes 2011", "B": "6", "C": "£480"}
    assert line["wine_id"] == wid


@pg
def test_alias_may_not_bridge_charmes_and_mazoyeres(client):
    """STRUCTURAL_EXCLUSIONS: an operator alias that pointed Mazoyères at
    Charmes would price one grand cru off the other."""
    charmes = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    r = client.post(f"/wines/{charmes}/aliases", json={
        "producer_text": R, "cuvee_text": "Mazoyeres-Chambertin Grand Cru",
        "source": "operator", "approved_by": "op"})
    assert r.status_code == 409


@pg
def test_alias_may_not_steal_another_wines_canonical_key(client):
    a = _seed_wine(client, cuvee="Chambertin")
    b = _seed_wine(client, cuvee="Chambertin Clos de Beze")
    r = client.post(f"/wines/{a}/aliases", json={
        "producer_text": R, "cuvee_text": "Chambertin Clos de Beze",
        "source": "operator", "approved_by": "op"})
    assert r.status_code == 409 and b in r.text


@pg
def test_approved_alias_resolves_merchant_spelling_on_next_collection(client):
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    assert _collect_written(client) == 0
    r = client.post(f"/wines/{wid}/aliases", json={
        "producer_text": R, "cuvee_text": "Charmes-Chambertin",
        "source": "operator", "approved_by": "op", "note": "Farr omits 'Grand Cru'"})
    assert r.status_code == 201
    assert _collect_written(client) == 2


def _collect_written(client) -> int:
    return client.get(f"/snapshots/{_collect(client)}").json()["offers_written"]


@pg
def test_targeted_only_merchant_is_a_recorded_failure_not_a_silent_gap(db):
    sid = jobs.collect_snapshot(["farr", "bordeaux-index"],
                                fetch=lambda a: [], robots=lambda url: None)
    import psycopg
    with psycopg.connect(TEST_DB) as c:
        failures, ok = c.execute(
            "SELECT failures, adapters_succeeded FROM snapshot WHERE snapshot_id = %s",
            (sid,)).fetchone()
    assert ok == 1
    assert [f["merchant_id"] for f in failures] == ["bordeaux-index"]


@pg
def test_robots_disallow_is_a_recorded_failure(db):
    from app.worker.politeness import RobotsDisallowed

    def deny(url):
        raise RobotsDisallowed(f"robots.txt disallows {url}")

    sid = jobs.collect_snapshot(["farr"], fetch=lambda a: FARR_BOOK, robots=deny)
    import psycopg
    with psycopg.connect(TEST_DB) as c:
        failures, written = c.execute(
            "SELECT failures, offers_written FROM snapshot WHERE snapshot_id = %s",
            (sid,)).fetchone()
    assert written == 0 and "RobotsDisallowed" in failures[0]["error"]
