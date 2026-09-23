"""Service layer: API, migrations, RQ worker.

Offline tests always run and need neither Postgres nor Redis. Tests marked `pg`
need a disposable Postgres and run only when TEST_DATABASE_URL is set; they DROP
the public schema of that database. The queue is fakeredis unless TEST_REDIS_URL
is set, in which case jobs go through that real Redis.

    docker compose up -d
    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    TEST_REDIS_URL=redis://localhost:6379/15 python -m pytest -q
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

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
TEST_REDIS = os.environ.get("TEST_REDIS_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


# ============================================================ offline: money


@pytest.mark.parametrize("cost", [2353.1, 2353.10, 1e3])
def test_json_number_money_is_refused_not_converted(cost):
    """A JSON number is a binary float before we see it. £2,353.10 must arrive
    as the string "2353.10" or not at all."""
    with pytest.raises(ValidationError, match="never a JSON number"):
        LineIn(row_index=0, raw_description="x", raw_row={"A": "as the seller wrote it"}, quantity=1,
               cost=cost, cost_currency="GBP")


def test_money_string_is_exact_and_third_decimal_is_refused():
    ok = LineIn(row_index=0, raw_description="x", raw_row={"A": "as the seller wrote it"}, quantity=1,
                cost="2353.10", cost_currency="GBP")
    assert ok.cost == Decimal("2353.10") and str(ok.cost) == "2353.10"
    # numeric(14,2) would silently round this to 2353.11 on insert.
    with pytest.raises(ValidationError):
        LineIn(row_index=0, raw_description="x", raw_row={"A": "as the seller wrote it"}, quantity=1,
               cost="2353.105", cost_currency="GBP")


#: Offline tests exercise validation, not authentication; the session is stubbed.
SIGNED_IN = {"operator_id": "00000000-0000-0000-0000-000000000001",
             "username": "op", "display_name": "The Operator", "active": True}


def _stub_session() -> None:
    api.app.dependency_overrides[api.db] = lambda: None
    api.app.dependency_overrides[api.queue] = lambda: None
    api.app.dependency_overrides[api.current_operator] = lambda: SIGNED_IN


def test_api_rejects_float_money_with_422():
    _stub_session()
    try:
        r = TestClient(api.app, base_url="https://testserver").post("/deals", json={
            "name": "d",
            "lines": [{"row_index": 0, "raw_description": "x",
                       "raw_row": {"A": "x"}, "quantity": 1,
                       "cost": 2353.1, "cost_currency": "GBP"}]})
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 422
    assert "never a JSON number" in r.text


def test_schema_has_no_float_column_types():
    body = re.sub(r"--[^\n]*", "", SCHEMA_SQL).lower()
    assert not re.search(r"\b(float\d*|real|double\s+precision|money)\b", body)


def test_every_money_column_is_numeric_14_2():
    """One money type in Postgres. fx_rate and target_margin are rates, not money."""
    body = re.sub(r"--[^\n]*", "", SCHEMA_SQL)
    money = (r"(price|cost|cost_gbp|hammer|buyer_paid|uk_floor|uk_reference|uk_median|gp"
             r"|unit_price|line_total|manual_price|sell_price)")
    # Column types are lower case in schema.sql; CHECK keywords (cost IS NULL) are not.
    cols = re.findall(rf"^\s*{money}\s+([a-z][\w(),]*)", body, re.M)
    assert len(cols) >= 15 and all(t.startswith("numeric(14,2)") for _, t in cols), cols


# ======================================================= offline: migrations


def test_offline_migration_sql_renders_the_whole_schema():
    env = {**os.environ, "DATABASE_URL": "postgresql://offline/none"}
    out = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
                         cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout
    for table in ("wine", "wine_alias", "offer", "offer_reject", "seller_line",
                  "benchmark_run", "benchmark_comp", "ai_decision", "snapshot_merchant",
                  "benchmark_run_snapshot", "seller_line_identity_history",
                  "pricing_result", "buyer_offer", "buyer_offer_line"):
        assert f"CREATE TABLE {table} (" in out
    assert "INSERT INTO merchant" in out


# ============================================================ offline: queue


def test_snapshot_request_enqueues_the_collection_job():
    q = Queue(QUEUE_NAME, connection=fakeredis.FakeRedis())
    _stub_session()
    api.app.dependency_overrides[api.queue] = lambda: q
    try:
        r = TestClient(api.app, base_url="https://testserver").post(
            "/snapshots", json={"merchant_ids": ["farr"]})
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 202
    job = q.fetch_job(r.json()["job_id"])
    assert job.func_name == "app.worker.jobs.collect_snapshot"
    assert job.kwargs == {"merchant_ids": ["farr"], "is_demo": False}


def test_benchmark_as_of_in_the_future_is_refused():
    _stub_session()
    try:
        r = TestClient(api.app, base_url="https://testserver").post(
            f"/deals/{uuid4()}/benchmark", json={
            "as_of": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 422 and "future" in r.text


# ============================================ offline: infrastructure contracts


@pytest.mark.parametrize("name", ["anthropic", "openai", "gemini"])
def test_unimplemented_ai_provider_fails_legibly(monkeypatch, name):
    from app.ai.provider import get_provider
    monkeypatch.setenv("AI_PROVIDER", name)
    with pytest.raises(NotImplementedError, match=f"AI_PROVIDER='{name}' is not implemented"):
        get_provider()


def test_no_vendor_sdk_is_imported_outside_app_ai():
    for path in (ROOT / "app").rglob("*.py"):
        if "app/ai/" in path.as_posix():
            continue
        src = path.read_text()
        assert not re.search(r"^\s*(import|from)\s+(anthropic|openai|google)\b", src, re.M), path


def test_user_agent_comes_from_the_environment_only(monkeypatch):
    from app.adapters.http import user_agent
    monkeypatch.delenv("COLLECTOR_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError, match="COLLECTOR_USER_AGENT"):
        user_agent()
    monkeypatch.setenv("COLLECTOR_USER_AGENT", "Pricer/1 (+https://x.example/contact)")
    assert user_agent() == "Pricer/1 (+https://x.example/contact)"
    for path in (ROOT / "app").rglob("*.py"):
        assert not re.search(r"""["']User-Agent["']\s*:\s*["']""", path.read_text()), path


# ================================================================ Postgres


def _reset(url: str) -> None:
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT,
                   env={**os.environ, "DATABASE_URL": TEST_DB}, check=True,
                   capture_output=True)


def _sql(query: str, params=None, *, fetch: bool = True):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(TEST_DB, row_factory=dict_row, prepare_threshold=None) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if fetch and cur.description else None


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


def _apply_schema(sql: str) -> dict:
    _reset(TEST_DB)
    import psycopg
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute(sql)
    return _catalog(TEST_DB)


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


OPERATOR = {"username": "op", "display_name": "The Operator", "password": "correct horse"}


def _sign_in(client, **overrides) -> dict:
    body = {**{k: OPERATOR[k] for k in ("username", "password")}, **overrides}
    return client.post("/session", json=body)


@pytest.fixture
def operator(db):
    """One signed-up operator. Identity is the server's, not the caller's."""
    from app.api import auth
    return auth.create_operator(OPERATOR["username"], OPERATOR["display_name"],
                                OPERATOR["password"])


@pytest.fixture
def client(db, operator):
    if TEST_REDIS:
        from redis import Redis
        conn = Redis.from_url(TEST_REDIS)
    else:
        conn = fakeredis.FakeRedis()
    q = Queue(f"test-{uuid4().hex}", connection=conn)
    api.app.dependency_overrides[api.queue] = lambda: q
    c = TestClient(api.app, base_url="https://testserver")
    c.queue = q
    c.operator = operator
    assert _sign_in(c).status_code == 200
    yield c
    api.app.dependency_overrides.clear()


def _work(q: Queue) -> None:
    SimpleWorker([q], connection=q.connection).work(burst=True)


def _job(client: TestClient, job_id: str) -> dict:
    return client.get(f"/jobs/{job_id}").json()


# --- migrations ---------------------------------------------------------------


@pg
def test_migrations_reproduce_schema_sql_exactly():
    """schema.sql is the head schema. If a migration and schema.sql disagree on
    any column, type, default, constraint or index, this fails."""
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    migrated = _catalog(TEST_DB)
    assert migrated == _apply_schema(SCHEMA_SQL)
    assert any(col[1] == "price" and col[5:7] == (14, 2) for col in migrated["columns"])


@pg
@pytest.mark.parametrize("old,new", [
    ("price            numeric(14,2) NOT NULL", "price            numeric(14,3) NOT NULL"),
    ("CHECK (wine_id_a < wine_id_b)", "CHECK (wine_id_a <> wine_id_b)"),
    ("offer_pk       uuid REFERENCES offer(offer_pk) ON DELETE SET NULL",
     "offer_pk       uuid REFERENCES offer(offer_pk)"),
    ("    WHERE status = 'ok';", "    ;"),
])
def test_equivalence_check_detects_a_one_line_drift(old, new):
    """The deliberate-failure check, kept as a test: the comparator above must
    notice a one-line change in scale, a CHECK, an ON DELETE rule or an index
    predicate. If it cannot, a passing equivalence test means nothing."""
    assert SCHEMA_SQL.count(old) == 1, old
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    migrated = _catalog(TEST_DB)
    assert migrated != _apply_schema(SCHEMA_SQL.replace(old, new))


@pg
def test_downgrade_to_base_removes_every_table():
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")
    assert _catalog(TEST_DB) == {"columns": [], "constraints": [], "indexes": []}


@pg
def test_downgrade_from_head_restores_the_previous_schema_exactly():
    _reset(TEST_DB)
    _alembic("upgrade", "0002_seed_verified_merchants")
    before = _catalog(TEST_DB)
    _alembic("upgrade", "head")
    _alembic("downgrade", "0002_seed_verified_merchants")
    assert _catalog(TEST_DB) == before


@pg
def test_0003_carries_existing_data_forward():
    """Data written under 0002 survives 0003: unresolved offers move to
    offer_reject, reversed exclusions are normalised, old runs gain provenance
    and an offer_snapshot, unaudited identities are marked as such."""
    _reset(TEST_DB)
    _alembic("upgrade", "0002_seed_verified_merchants")
    w = sorted(r["wine_id"] for r in _sql(
        """INSERT INTO wine (producer, cuvee, wine_key) VALUES
           ('P', 'A', 'p|a'), ('P', 'B', 'p|b'), ('P', 'C', 'p|c') RETURNING wine_id"""))
    _sql("INSERT INTO wine_exclusion VALUES (%s, %s, 'reversed'), (%s, %s, 'one way'), "
         "(%s, %s, 'other way')", (w[1], w[0], w[1], w[2], w[2], w[1]), fetch=False)
    sid = _sql("""INSERT INTO snapshot (captured_at, schema_version, failures)
                  VALUES ('2026-09-18T10:00Z', '1',
                          '[{"merchant_id": "bordeaux-index", "error": "targeted"}]')
                  RETURNING snapshot_id""")[0]["snapshot_id"]
    offer_cols = """(snapshot_id, offer_id, merchant_id, wine_id, vintage, bottle_ml, pack_size,
                     price, currency, duty_status, price_kind, is_buyable, captured_at)"""
    resolved = _sql(f"""INSERT INTO offer {offer_cols} VALUES
        (%s, 'farr:1', 'farr', %s, 2011, 750, 1, 610.00, 'GBP', 'IB', 'ASK', true,
         '2026-09-18T10:00Z') RETURNING offer_pk""", (sid, w[0]))[0]["offer_pk"]
    _sql(f"""INSERT INTO offer {offer_cols} VALUES
        (%s, 'farr:2', 'farr', NULL, 2011, 750, 1, 300.00, 'GBP', 'IB', 'ASK', true,
         '2026-09-18T10:00Z')""", (sid,), fetch=False)
    _sql("""INSERT INTO offer_reject (snapshot_id, merchant_id, reason, raw)
            VALUES (%s, 'goedhuis', 'MIXED_LOT', '{}')""", (sid,), fetch=False)
    deal = _sql("INSERT INTO deal (name, created_by) VALUES ('d', 'a name') "
                "RETURNING deal_id")[0]
    line = _sql("""INSERT INTO seller_line (deal_id, row_index, raw_description, raw_row, wine_id,
                   vintage, bottle_ml, pack_size, quantity)
                   VALUES (%s, 0, 'x', '{}', %s, 2011, 750, 1, 1) RETURNING line_id""",
                (deal["deal_id"], w[0]))[0]["line_id"]
    run = _sql("""INSERT INTO benchmark_run (line_id, snapshot_id, computed_at, uk_floor,
                  uk_reference, uk_median, comp_count, flags, state)
                  VALUES (%s, %s, '2026-09-18T11:00Z', 610, 610, 610, 1, '{ONE_COMP}', 'REVIEW')
                  RETURNING run_id""", (line, sid))[0]["run_id"]
    _sql("INSERT INTO benchmark_comp VALUES (%s, %s, 'merchant_best', NULL)",
         (run, resolved), fetch=False)

    _alembic("upgrade", "head")

    assert _sql("SELECT wine_id_a, wine_id_b, reason FROM wine_exclusion ORDER BY 1, 2") == [
        {"wine_id_a": w[0], "wine_id_b": w[1], "reason": "reversed"},
        {"wine_id_a": w[1], "wine_id_b": w[2], "reason": "one way / other way"}]
    sm = {r["merchant_id"]: r for r in _sql("SELECT * FROM snapshot_merchant")}
    assert (sm["farr"]["status"], sm["farr"]["offers_written"], sm["farr"]["offers_rejected"]) \
        == ("ok", 1, 1)
    assert sm["goedhuis"]["status"] == "ok"
    assert (sm["bordeaux-index"]["status"], sm["bordeaux-index"]["error"]) == ("failed", "targeted")
    assert _sql("SELECT count(*) AS n FROM offer")[0]["n"] == 1
    moved = _sql("SELECT * FROM offer_reject WHERE reason = 'UNRESOLVED_IDENTITY'")
    assert len(moved) == 1 and moved[0]["raw"]["offer_id"] == "farr:2"
    ln = _sql("""SELECT l.flags, o.username FROM seller_line l
                   JOIN operator o ON o.operator_id = l.wine_id_approved_by""")[0]
    assert ln["username"].startswith("unrecorded") and ln["flags"] == []
    r = _sql("SELECT * FROM benchmark_run")[0]
    assert r["as_of"] == r["computed_at"]
    assert {x["merchant_id"] for x in _sql("SELECT * FROM benchmark_run_snapshot")} \
        == {"farr", "goedhuis"}
    comp = _sql("SELECT * FROM benchmark_comp")[0]
    assert comp["offer_snapshot"]["price"] == "610.00"
    assert comp["offer_snapshot"]["merchant"] == "Farr Vintners"


# --- schema integrity ---------------------------------------------------------


@pg
@pytest.mark.parametrize("column,value", [
    ("wine_id", None),
    ("stock_type", "WAREHOUSE"),
    ("condition_flags", ["ORIGINAL_CASE", "LOOKS_FINE"]),
])
def test_offer_integrity_constraints(db, column, value):
    import psycopg
    wid = _sql("INSERT INTO wine (producer, cuvee, wine_key) VALUES ('P','C','p|c') "
               "RETURNING wine_id")[0]["wine_id"]
    sid = _sql("INSERT INTO snapshot (captured_at, schema_version) VALUES (now(), '2') "
               "RETURNING snapshot_id")[0]["snapshot_id"]
    row = {"wine_id": wid, "stock_type": "UNKNOWN", "condition_flags": []}
    row[column] = value
    with pytest.raises(psycopg.errors.IntegrityError):
        _sql("""INSERT INTO offer (snapshot_id, offer_id, merchant_id, wine_id, vintage,
                bottle_ml, pack_size, price, currency, duty_status, price_kind, is_buyable,
                captured_at, stock_type, condition_flags)
                VALUES (%s, 'x', 'farr', %s, 2011, 750, 1, 1.00, 'GBP', 'IB', 'ASK', true,
                        now(), %s, %s)""",
             (sid, row["wine_id"], row["stock_type"], row["condition_flags"]), fetch=False)


@pg
def test_exclusion_pair_cannot_be_stored_in_both_orders(db):
    import psycopg
    a, b = sorted(r["wine_id"] for r in _sql(
        "INSERT INTO wine (producer, cuvee, wine_key) VALUES ('P','A','p|a'), ('P','B','p|b') "
        "RETURNING wine_id"))
    _sql("INSERT INTO wine_exclusion VALUES (%s, %s, 'r')", (a, b), fetch=False)
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql("INSERT INTO wine_exclusion VALUES (%s, %s, 'r')", (b, a), fetch=False)


@pg
def test_usd_cost_cannot_be_priced_without_its_fx_rate(client):
    """Without the rate and its date, GP on a USD-cost parcel can never be
    reproduced."""
    import psycopg
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    run_id = client.get(f"/lines/{line_id}/benchmark").json()["run_id"]
    cols = ("(line_id, run_id, priced_by, comp_count, cost, cost_currency, state, "
            "price_basis, deep_discount_threshold")
    values = "%(op)s, 1, 500.00, 'USD', 'REVIEW', 'manual', 0.2500"
    params = {"line": line_id, "run": run_id, "op": client.operator["operator_id"]}
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql(f"INSERT INTO pricing_result {cols}) VALUES (%(line)s, %(run)s, {values})",
             params, fetch=False)
    _sql(f"""INSERT INTO pricing_result {cols}, fx_rate, fx_rate_date, fx_source)
             VALUES (%(line)s, %(run)s, {values}, 0.74120000, '2026-09-19', 'ECB')""",
         params, fetch=False)


# --- live-shaped Farr records ------------------------------------------------

R = "Domaine Armand Rousseau"


def farr(wine_id, wine, vintage, size, price, per, units, variation=None, lwin7=None):
    return {"WineId": wine_id, "Wine": wine, "Vintage": vintage, "Size": size,
            "SellGBP": price, "Per": per, "Units": units, "Variation": variation,
            "LWIN-7": lwin7, "Url": f"https://www.farrvintners.com/wine.php?wine={wine_id}"}


FARR_BOOK = [
    # Charmes 2011: one loose bottle at £610, and a 6x75cl case.
    farr(1, "Charmes-Chambertin, Domaine Armand Rousseau", "2011", "1×75cl", "610.00", 1, 1,
         "Not in original carton"),
    farr(2, "Charmes-Chambertin, Domaine Armand Rousseau", "2011", "6×75cl", "4428.00", 6, 1),
    # Mazoyères is a structural exclusion from Charmes. No alias exists for it.
    farr(3, "Mazoyeres-Chambertin, Domaine Armand Rousseau", "2011", "1×75cl", "300.00", 1, 4),
    farr(4, "Mixed case of Rousseau, Domaine Armand Rousseau", "2011", "6×75cl", "3000.00", 6, 1),
]


def bi_card(price: str, vintage: int = 2011, cuvee: str = "Charmes-Chambertin Grand Cru") -> dict:
    return {"title": f"{vintage} Domaine Armand Rousseau, {cuvee}", "code": "roush-2011",
            "url": "https://bordeauxindex.com/livetrade/roush-2011",
            "offers": [f"Bottle (75cl) CONDITION Original Case STATUS In-Bond ETA In Stock "
                       f"You buy £{price} 2 Bottle(s) Available"]}


def _seed_wine(client, producer=R, cuvee="Charmes-Chambertin", lwin7=None) -> str:
    r = client.post("/wines", json={"producer": producer, "cuvee": cuvee, "lwin7": lwin7})
    assert r.status_code == 201, r.text
    return r.json()["wine_id"]


def _run_patched(client, jid: str, name: str, offline) -> dict:
    orig = getattr(jobs, name)
    setattr(jobs, name, offline(orig))
    try:
        _work(client.queue)
    finally:
        setattr(jobs, name, orig)
    j = _job(client, jid)
    assert j["status"] == "finished", j
    return j


def _collect(client, book=FARR_BOOK, merchant="farr") -> str:
    """Enqueue through the API and run the real job in-process with the network
    replaced: fetch returns the captured book and robots.txt allows."""
    jid = client.post("/snapshots", json={"merchant_ids": [merchant]}).json()["job_id"]
    return _run_patched(client, jid, "collect_snapshot", lambda orig: (
        lambda merchant_ids=None, is_demo=False: orig(
            merchant_ids, is_demo=is_demo, fetch=lambda a: book, robots=lambda url: None)
    ))["result"]


def _collect_bi(client, wine_id, cards, vintage=2011) -> str:
    jid = client.post("/snapshots/targeted", json={
        "merchant_id": "bordeaux-index", "wine_id": wine_id, "vintage": vintage,
        "params": {"producer_slug": "domaine-armand-rousseau"}}).json()["job_id"]
    return _run_patched(client, jid, "collect_targeted", lambda orig: (
        lambda merchant_id, wine_id, vintage, params, is_demo=False: orig(
            merchant_id, wine_id, vintage, params, is_demo=is_demo,
            fetch=lambda a, p, v: cards, robots=lambda url: None)
    ))["result"]


def _deal(client, wine_id, quantity=6, pack=1, flags=()) -> tuple[str, str]:
    r = client.post("/deals", json={
        "name": "Rousseau parcel", "currency": "GBP",
        "lines": [{"row_index": 0, "raw_description": "Rousseau Charmes 2011 x6 loose",
                   "raw_row": {"A": "Rousseau Charmes 2011", "B": "6", "C": "£480"},
                   "quantity": quantity, "cost": "480.00", "cost_currency": "GBP"}]})
    assert r.status_code == 201, r.text
    deal = r.json()
    line_id = deal["lines"][0]["line_id"]
    r = client.put(f"/lines/{line_id}/identity", json={
        "wine_id": wine_id, "vintage": 2011, "bottle_ml": 750, "pack_size": pack,
        "source": "operator", "flags": list(flags)})
    assert r.status_code == 200, r.text
    return deal["deal_id"], line_id


def _benchmark(client, deal_id, as_of: datetime | None = None) -> dict:
    body = {"as_of": as_of.isoformat()} if as_of else None
    jid = client.post(f"/deals/{deal_id}/benchmark", json=body).json()["job_id"]
    _work(client.queue)
    return _job(client, jid)


def _age_capture(snapshot_id: str, days: float) -> None:
    """Make a capture look `days` old: its merchant row and every offer in it."""
    for table in ("snapshot_merchant", "offer"):
        _sql(f"UPDATE {table} SET captured_at = captured_at - %s WHERE snapshot_id = %s",
             (timedelta(days=days), snapshot_id), fetch=False)


# --- collection -------------------------------------------------------------


@pg
def test_every_raw_record_ends_as_one_offer_or_one_reject(client):
    _seed_wine(client)
    sid = _collect(client)
    snap = client.get(f"/snapshots/{sid}").json()
    assert (snap["offers_written"], snap["offers_rejected"]) == (2, 2)
    [m] = snap["merchants"]
    assert (m["merchant_id"], m["status"], m["scope_producer_key"]) == ("farr", "ok", None)
    rejects = {r["reason"]: r["detail"] for r in _sql("SELECT reason, detail FROM offer_reject")}
    assert set(rejects) == {"MIXED_LOT", "UNRESOLVED_IDENTITY"}
    assert "Mazoyeres" in rejects["UNRESOLVED_IDENTITY"]


@pg
def test_one_float32_price_no_longer_aborts_the_whole_farr_capture(client):
    """Farr WineId 230806 publishes SellGBP 308.329986. Before the whole-pence
    screen that one record raised inside ingest and lost every Farr offer."""
    _seed_wine(client)
    book = [*FARR_BOOK, farr(230806, "Barolo Cascina Francia, Giacomo Conterno", "2008",
                             "1×1.5L", 308.329986, 1, 1)]
    snap = client.get(f"/snapshots/{_collect(client, book)}").json()
    assert snap["merchants"][0]["status"] == "ok" and snap["offers_written"] == 2
    [r] = _sql("SELECT * FROM offer_reject WHERE reason = 'NOT_WHOLE_PENCE'")
    assert "308.329986" in r["detail"]


@pg
def test_a_collided_lwin_blocks_the_contradicted_record_while_the_conflict_is_open(client):
    """Using the captured feed: 1038217 names both Jadot Clos Saint Jacques and
    Lavaux Saint Jacques. With only Clos Saint Jacques in the canonical table,
    Lavaux must be UNRESOLVED, not priced as Clos Saint Jacques, and the reject
    must point at the open conflict."""
    _seed_wine(client, "Louis Jadot", "Gevrey Chambertin Clos Saint Jacques", lwin7="1038217")
    _collect(client, _farr_pair({227986, 227984}))
    assert [o["offer_id"] for o in _sql("SELECT offer_id FROM offer")] == ["farr:227986"]
    [rej] = _sql("SELECT detail FROM offer_reject")
    assert "Lavaux" in rej["detail"] and "(conflict open)" in rej["detail"]


@pg
def test_a_merchant_lwin_alone_does_not_resolve_a_name_we_do_not_know(client):
    """Farr's 'Lafite Rothschild' carries LWIN-7 1011872 and nothing else names
    it. The LWIN is the merchant's own mapping, so it waits for an alias."""
    lafite = _farr_pair({237136})
    wid = _seed_wine(client, "Chateau Lafite Rothschild", "Grand Vin", lwin7="1011872")
    assert client.get(f"/snapshots/{_collect(client, lafite)}").json()["offers_written"] == 0
    r = client.post(f"/wines/{wid}/aliases", json={
        "producer_text": "Lafite Rothschild", "cuvee_text": "",
        "source": "operator", "note": "Farr prints no cuvee"})
    assert r.status_code == 201
    assert client.get(f"/snapshots/{_collect(client, lafite)}").json()["offers_written"] == 1


@pg
def test_bordeaux_index_card_with_no_rows_at_all_is_a_reject_not_a_silence(client):
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    _collect_bi(client, wid, [{**bi_card("650.00"), "offers": []}])
    assert [r["reason"] for r in _sql("SELECT reason FROM offer_reject")] == ["NO_OFFER_ROWS"]


@pg
def test_whole_book_collection_refers_targeted_merchants_to_targeted_search(db):
    sid = jobs.collect_snapshot(["farr", "bordeaux-index"],
                                fetch=lambda a: [], robots=lambda url: None)
    [snap] = _sql("SELECT failures, adapters_succeeded FROM snapshot WHERE snapshot_id = %s", (sid,))
    assert snap["adapters_succeeded"] == 1
    assert [f["merchant_id"] for f in snap["failures"]] == ["bordeaux-index"]
    assert "collect_targeted" in snap["failures"][0]["error"]


@pg
def test_robots_disallow_is_a_recorded_failure(db):
    from app.worker.politeness import RobotsDisallowed

    def deny(url):
        raise RobotsDisallowed(f"robots.txt disallows {url}")

    sid = jobs.collect_snapshot(["farr"], fetch=lambda a: FARR_BOOK, robots=deny)
    [m] = _sql("SELECT * FROM snapshot_merchant WHERE snapshot_id = %s", (sid,))
    assert m["status"] == "failed" and "RobotsDisallowed" in m["error"]
    assert _sql("SELECT count(*) AS n FROM offer")[0]["n"] == 0


# --- benchmark: resolution, freshness, self-containment ---------------------


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
    assert {("merchant_best", "610.00"), ("cross_unit", "4428.00"), ("rejected", "4428.00")} <= roles
    xu = next(c for c in run["comps"] if c["role"] == "cross_unit")
    assert Decimal(xu["per_bottle"]) == Decimal("738")
    best = next(c for c in run["comps"] if c["role"] == "merchant_best")
    assert best["condition_notes"] == "Not in original carton"
    assert best["merchant_offer_id"] == "farr:1"
    assert [s["merchant_id"] for s in run["sources"]] == ["farr"]


@pg
def test_bordeaux_index_producer_vintage_search_joins_the_market(client):
    """A targeted BI capture covers Rousseau 2011 and nothing else. With Farr it
    makes two merchants: the line is READY instead of ONE_COMP."""
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    client.post(f"/wines/{wid}/aliases", json={
        "producer_text": R, "cuvee_text": "Charmes-Chambertin", "source": "operator",
        "note": "Farr omits 'Grand Cru'"})
    _collect(client)
    sid = _collect_bi(client, wid, [bi_card("650.00")])
    [m] = client.get(f"/snapshots/{sid}").json()["merchants"]
    assert (m["scope_producer_key"], m["scope_vintage"]) == ("domaine armand rousseau", 2011)

    deal_id, line_id = _deal(client, wid, quantity=1)
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["state"] == "READY" and run["comp_count"] == 2
    assert (run["uk_floor"], run["uk_reference"]) == ("610.00", "650.00")
    assert {s["merchant_id"] for s in run["sources"]} == {"farr", "bordeaux-index"}


@pg
def test_targeted_capture_does_not_cover_another_vintage(client):
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    _collect_bi(client, wid, [bi_card("650.00", vintage=2012)], vintage=2012)
    deal_id, line_id = _deal(client, wid)             # a 2011 line
    j = _benchmark(client, deal_id)
    assert j["result"]["no_coverage"] == [line_id]
    assert client.get(f"/lines/{line_id}/benchmark").status_code == 404


@pg
def test_each_merchant_resolves_its_own_latest_capture(client):
    """Farr captured twice: the later capture no longer lists the bottle. The
    earlier £610 must not come back: a newer look that finds nothing wins."""
    wid = _seed_wine(client)
    first = _collect(client)
    _age_capture(first, 2)
    _collect(client, FARR_BOOK[1:])                     # the bottle has sold
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["state"] == "NO_MARKET"
    assert all(c["price"] != "610.00" for c in run["comps"])


@pg
def test_stale_capture_is_rejected_with_its_reason_and_prices_nothing(client):
    """A Farr capture 20 days old is past MAX_OFFER_AGE_DAYS. The £610 bottle is
    in the run, marked stale, and prices nothing; the stale case is not offered
    as cross-unit evidence either."""
    wid = _seed_wine(client)
    _age_capture(_collect(client), 20)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["state"] == "NO_MARKET" and run["uk_reference"] is None
    stale = [c for c in run["comps"] if c["reject_reason"] == "captured outside the freshness window"]
    assert [c["price"] for c in stale] == ["610.00"]
    assert not [c for c in run["comps"] if c["role"] == "cross_unit"]


@pg
def test_oldest_contributing_comp_age_is_on_the_run(client):
    wid = _seed_wine(client)
    sid = _collect(client)
    _age_capture(sid, 3)
    as_of = _sql("SELECT captured_at FROM snapshot_merchant")[0]["captured_at"] + timedelta(days=3)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id, as_of=as_of)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["oldest_comp_age"] == "P3D"
    assert datetime.fromisoformat(run["as_of"]) == as_of


@pg
def test_pruning_a_snapshot_leaves_the_run_whole(client):
    """Snapshots are a cache. Deleting one must not be blocked by history, and
    the run must read exactly as before, except that it no longer points at
    rows that are gone."""
    wid = _seed_wine(client)
    sid = _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    before = client.get(f"/lines/{line_id}/benchmark").json()

    _sql("DELETE FROM snapshot WHERE snapshot_id = %s", (sid,), fetch=False)
    after = client.get(f"/lines/{line_id}/benchmark").json()

    assert all(c["offer_pk"] is None for c in after["comps"])
    assert [s["snapshot_id"] for s in after["sources"]] == [None]
    before["comps"] = [{**c, "offer_pk": None} for c in before["comps"]]
    before["sources"] = [{**s, "snapshot_id": None} for s in before["sources"]]
    assert before == after


@pg
def test_half_penny_median_is_rounded_by_the_core_and_stored_exactly(client):
    """Two merchants at £610.01 and £610.02: the median is £610.015, rounded to
    £610.02 in app/core/benchmark.py. Floor and Reference are never rounded."""
    wid = _seed_wine(client)
    sid = _collect(client, [farr(1, "Charmes-Chambertin, Domaine Armand Rousseau",
                                 "2011", "1×75cl", "610.01", 1, 6)])
    import psycopg
    from psycopg.rows import dict_row
    from app.db import repo
    with psycopg.connect(TEST_DB, row_factory=dict_row, prepare_threshold=None) as c:
        o = repo.offer_from_row(c.execute(
            "SELECT o.*, m.name AS merchant_name FROM offer o JOIN merchant m USING (merchant_id)"
        ).fetchone())
        repo.write_offer(c, sid, replace(o, offer_id="goedhuis:X", merchant_id="goedhuis",
                                         price=Decimal("610.02"), wine_id=wid))
        repo.write_snapshot_merchant(c, sid, "goedhuis", captured_at=o.captured_at, written=1)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["state"] == "READY" and run["comp_count"] == 2
    assert (run["uk_floor"], run["uk_reference"], run["uk_median"]) == (
        "610.01", "610.02", "610.02")


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
    # offer_snapshot keeps money as strings too, not JSON numbers.
    for c in _sql("SELECT offer_snapshot FROM benchmark_comp"):
        assert isinstance(c["offer_snapshot"]["price"], str)


@pg
def test_unapproved_merchant_is_outside_the_universe(client):
    wid = _seed_wine(client)
    _collect(client)
    _sql("UPDATE merchant SET approved = false WHERE merchant_id = 'farr'", fetch=False)
    deal_id, line_id = _deal(client, wid)
    j = _benchmark(client, deal_id)
    assert j["result"]["no_coverage"] == [line_id]


@pg
def test_no_capture_at_all_is_no_coverage_not_no_market(client):
    """Nobody has looked, so NO_MARKET would be a claim nobody made."""
    wid = _seed_wine(client)
    deal_id, line_id = _deal(client, wid)
    j = _benchmark(client, deal_id)
    assert j["status"] == "finished" and j["result"]["no_coverage"] == [line_id]
    assert client.get(f"/lines/{line_id}/benchmark").status_code == 404


@pg
def test_line_without_approved_identity_is_not_benchmarked(client):
    _seed_wine(client)
    _collect(client)
    r = client.post("/deals", json={"name": "d", "lines": [
        {"row_index": 0, "raw_description": "Rousseau ?", "raw_row": {"A": "as the seller wrote it"}, "quantity": 1}]})
    j = _benchmark(client, r.json()["deal_id"])
    assert j["result"]["runs"] == {} and len(j["result"]["unapproved_identity"]) == 1


# --- identity approval, history, line flags ---------------------------------


@pg
def test_identity_approval_is_recorded_with_its_history(client):
    a = _seed_wine(client, cuvee="Charmes-Chambertin")
    b = _seed_wine(client, cuvee="Mazoyeres-Chambertin")
    _, line_id = _deal(client, a)
    r = client.put(f"/lines/{line_id}/identity", json={
        "wine_id": b, "vintage": 2011, "bottle_ml": 750, "pack_size": 1,
        "source": "ai_reviewed", "flags": ["NAME_REVIEW"]})
    line = r.json()
    assert (line["wine_id"], line["wine_id_source"], line["flags"]) == (
        b, "ai_reviewed", ["NAME_REVIEW"])
    # Who approved it is the session's operator, by id, whatever the body said.
    assert line["wine_id_approved_by"]["operator_id"] == str(client.operator["operator_id"])
    assert line["wine_id_approved_by"]["display_name"] == "The Operator"
    first, second = client.get(f"/lines/{line_id}/identity-history").json()
    assert (first["prev_wine_id"], first["new_wine_id"]) == (None, a)
    assert first["changed_by"]["username"] == "op"
    assert (second["prev_wine_id"], second["new_wine_id"], second["source"]) == (a, b, "ai_reviewed")
    assert (second["prev_flags"], second["new_flags"]) == ([], ["NAME_REVIEW"])


@pg
def test_setting_identity_never_touches_the_original_seller_text(client):
    wid = _seed_wine(client)
    deal_id, _ = _deal(client, wid)
    line = client.get(f"/deals/{deal_id}").json()["lines"][0]
    assert line["raw_description"] == "Rousseau Charmes 2011 x6 loose"
    assert line["raw_row"] == {"A": "Rousseau Charmes 2011", "B": "6", "C": "£480"}
    assert line["wine_id"] == wid


@pg
def test_persisted_name_review_holds_a_ready_market_in_review(client):
    """Two merchants make the market READY. The line carries NAME_REVIEW from
    identity verification, so it must come out REVIEW."""
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    client.post(f"/wines/{wid}/aliases", json={
        "producer_text": R, "cuvee_text": "Charmes-Chambertin", "source": "operator"})
    _collect(client)
    _collect_bi(client, wid, [bi_card("650.00")])
    deal_id, line_id = _deal(client, wid, quantity=1, flags=["NAME_REVIEW"])
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["comp_count"] == 2 and run["state"] == "REVIEW"
    assert "NAME_REVIEW" in run["flags"]


@pg
def test_only_line_flags_can_be_persisted_on_a_line(client):
    wid = _seed_wine(client)
    _, line_id = _deal(client, wid)
    r = client.put(f"/lines/{line_id}/identity", json={
        "wine_id": wid, "vintage": 2011, "bottle_ml": 750, "pack_size": 1,
        "source": "operator", "flags": ["WIDE_SPREAD"]})
    assert r.status_code == 422


# --- aliases ------------------------------------------------------------------


@pg
def test_alias_may_not_bridge_charmes_and_mazoyeres(client):
    """STRUCTURAL_EXCLUSIONS: an operator alias that pointed Mazoyères at
    Charmes would price one grand cru off the other."""
    charmes = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    r = client.post(f"/wines/{charmes}/aliases", json={
        "producer_text": R, "cuvee_text": "Mazoyeres-Chambertin Grand Cru",
        "source": "operator"})
    assert r.status_code == 409


@pg
def test_alias_may_not_steal_another_wines_canonical_key(client):
    a = _seed_wine(client, cuvee="Chambertin")
    b = _seed_wine(client, cuvee="Chambertin Clos de Beze")
    r = client.post(f"/wines/{a}/aliases", json={
        "producer_text": R, "cuvee_text": "Chambertin Clos de Beze",
        "source": "operator"})
    assert r.status_code == 409 and b in r.text


@pg
def test_approved_alias_resolves_merchant_spelling_on_next_collection(client):
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    assert _collect_written(client) == 0
    r = client.post(f"/wines/{wid}/aliases", json={
        "producer_text": R, "cuvee_text": "Charmes-Chambertin",
        "source": "operator", "note": "Farr omits 'Grand Cru'"})
    assert r.status_code == 201
    assert _collect_written(client) == 2


def _collect_written(client) -> int:
    return client.get(f"/snapshots/{_collect(client)}").json()["offers_written"]


# --- line state: searched, never searched, no market ------------------------


@pg
def test_never_searched_and_no_market_are_shown_differently(client):
    """NO_MARKET means every approved merchant was searched and none offers the
    wine. NOT_SEARCHED means nobody looked. A buyer must never be sent a price
    for a line nobody looked at, so the deal view must not blur the two."""
    wid = _seed_wine(client)
    deal_id, line_id = _deal(client, wid)

    line = client.get(f"/deals/{deal_id}").json()["lines"][0]
    assert line["line_state"] == "NOT_SEARCHED" and line["benchmark"] is None

    _collect(client, FARR_BOOK[2:])                 # Farr searched; wine not listed
    _benchmark(client, deal_id)
    line = client.get(f"/deals/{deal_id}").json()["lines"][0]
    assert line["line_state"] == "NO_MARKET"
    assert line["benchmark"]["comp_count"] == 0


@pg
def test_a_line_with_no_approved_identity_says_so(client):
    r = client.post("/deals", json={"name": "d", "lines": [
        {"row_index": 0, "raw_description": "Rousseau ?", "raw_row": {"A": "as the seller wrote it"}, "quantity": 1}]})
    [line] = r.json()["lines"]
    assert line["line_state"] == "IDENTITY_NOT_APPROVED"


@pg
def test_a_never_searched_line_cannot_reach_a_buyer_offer(client):
    """Structural, not a convention: a buyer offer line requires a pricing
    result, which requires a benchmark run, which only exists if we searched."""
    import psycopg
    wid = _seed_wine(client)
    deal_id, line_id = _deal(client, wid)
    assert client.get(f"/deals/{deal_id}").json()["lines"][0]["line_state"] == "NOT_SEARCHED"
    assert _sql("SELECT count(*) AS n FROM benchmark_run")[0]["n"] == 0

    offer_id = _sql("""INSERT INTO buyer_offer (deal_id, client, currency, issued_at, issued_by)
                       VALUES (%s, 'A Buyer', 'GBP', now(), %s) RETURNING buyer_offer_id""",
                    (deal_id, client.operator["operator_id"]))[0]["buyer_offer_id"]
    with pytest.raises(psycopg.errors.NotNullViolation):
        _sql("""INSERT INTO buyer_offer_line (buyer_offer_id, line_no, line_id, pricing_id,
                description, vintage, bottle_ml, pack_size, quantity, unit_price, line_total)
                VALUES (%s, 1, %s, NULL, 'Rousseau Charmes 2011', 2011, 750, 1, 6,
                        800.00, 4800.00)""", (offer_id, line_id), fetch=False)


# --- pricing ------------------------------------------------------------------


def _price(client, deal_id, **body) -> dict:
    jid = client.post(f"/deals/{deal_id}/pricing", json=body).json()["job_id"]
    _work(client.queue)
    return _job(client, jid)


@pg
def test_pricing_persists_the_figures_as_at_the_moment_of_pricing(client):
    """The benchmark figures are copied onto the pricing result, not joined back
    to the run: a sent price stays explicable after the market moves."""
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    r = client.put(f"/lines/{line_id}/identity", json={
        "wine_id": wid, "vintage": 2011, "bottle_ml": 750, "pack_size": 1,
        "source": "operator"})
    assert r.status_code == 200
    _sql("UPDATE seller_line SET target_margin = 0.2500", fetch=False)

    j = _price(client, deal_id)
    assert j["status"] == "finished" and list(j["result"]["priced"]) == [line_id]

    p = client.get(f"/lines/{line_id}/pricing").json()
    assert (p["price_basis"], p["sell_price"]) == ("line_margin", "640.00")  # 480 / 0.75
    assert (p["cost"], p["cost_gbp"], p["gp"], p["gross_margin"]) == (
        "480.00", "480.00", "160.00", "0.2500")
    assert (p["uk_reference"], p["comp_count"]) == ("610.00", 1)
    assert p["deep_discount_threshold"] == "0.2500"
    assert "ONE_COMP" in p["flags"] and p["state"] == "REVIEW"
    assert client.get(f"/deals/{deal_id}").json()["lines"][0]["pricing"]["sell_price"] == "640.00"


@pg
def test_pricing_records_the_fx_rate_that_produced_the_gp(client):
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET cost = 500.00, cost_currency = 'USD', target_margin = 0.2000",
         fetch=False)

    j = _price(client, deal_id, fx_rates={"USD": {"rate": "0.7412", "date": "2026-09-19",
                                                  "source": "ECB"}})
    assert j["status"] == "finished"
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert (p["cost_gbp"], p["sell_price"]) == ("370.60", "463.25")
    assert (p["fx_rate"], p["fx_rate_date"], p["fx_source"]) == ("0.74120000", "2026-09-19", "ECB")


@pg
def test_a_usd_line_with_no_rate_is_skipped_not_guessed(client):
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET cost = 500.00, cost_currency = 'USD', target_margin = 0.2000",
         fetch=False)
    j = _price(client, deal_id)
    assert j["result"]["priced"] == {}
    assert j["result"]["skipped"] == [{"line_id": line_id, "reason": "no FX rate for USD"}]
    assert client.get(f"/lines/{line_id}/pricing").status_code == 404


@pg
def test_an_unbenchmarked_line_is_never_priced(client):
    wid = _seed_wine(client)
    deal_id, line_id = _deal(client, wid)
    _sql("UPDATE seller_line SET target_margin = 0.2500", fetch=False)
    j = _price(client, deal_id)
    assert j["result"]["skipped"] == [{"line_id": line_id, "reason": "not benchmarked"}]


@pg
def test_the_deal_margin_is_the_fallback_for_a_line_with_no_rule(client):
    wid = _seed_wine(client)
    _collect(client)
    r = client.post("/deals", json={
        "name": "d", "currency": "GBP", "target_margin": 0.4,
        "lines": [{"row_index": 0, "raw_description": "Rousseau Charmes 2011",
                   "raw_row": {"A": "as the seller wrote it"}, "quantity": 1, "cost": "300.00", "cost_currency": "GBP"}]})
    deal_id, line_id = r.json()["deal_id"], r.json()["lines"][0]["line_id"]
    client.put(f"/lines/{line_id}/identity", json={
        "wine_id": wid, "vintage": 2011, "bottle_ml": 750, "pack_size": 1,
        "source": "operator"})
    _benchmark(client, deal_id)
    _price(client, deal_id)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert (p["price_basis"], p["sell_price"]) == ("global_margin", "500.00")   # 300 / 0.6
    assert Decimal(p["gross_margin"]) == Decimal("0.4000")


# --- LWIN conflicts -----------------------------------------------------------


def _farr_pair(wine_ids):
    feed = json.loads((ROOT / "tests/fixtures/farr-feed-2026-09-19.json").read_text())["data"]
    return [r for r in feed if r["WineId"] in wine_ids]


@pg
def test_a_collided_lwin_opens_one_operator_review(client):
    """Farr uses 1038217 for Jadot Clos Saint Jacques and Lavaux Saint Jacques.
    Both names, and the merchant, are recorded for the operator."""
    _seed_wine(client, "Louis Jadot", "Gevrey Chambertin Clos Saint Jacques", lwin7="1038217")
    _collect(client, _farr_pair({227986, 227984}))
    [c] = client.get("/lwin-conflicts").json()
    assert (c["merchant_id"], c["lwin7"]) == ("farr", "1038217")
    assert len(c["names"]) == 2 and any("Lavaux" in n for n in c["names"])
    assert c["resolution"] is None


@pg
def test_resolving_a_collision_as_different_wines_excludes_and_untrusts(client):
    """Jadot's two climats: record the exclusion, stop trusting Farr's LWIN, and
    the Lavaux listing then resolves on its name alone at the next collection."""
    csj = _seed_wine(client, "Louis Jadot", "Gevrey Chambertin Clos Saint Jacques",
                     lwin7="1038217")
    lavaux = _seed_wine(client, "Louis Jadot", "Gevrey Chambertin Lavaux Saint Jacques")
    pair = _farr_pair({227986, 227984})
    _collect(client, pair)
    assert _sql("SELECT count(*) AS n FROM offer")[0]["n"] == 1      # Lavaux blocked

    [c] = client.get("/lwin-conflicts").json()
    r = client.post(f"/lwin-conflicts/{c['conflict_id']}/resolve", json={
        "resolution": "different_wines",
        "exclude": [csj, lavaux], "note": "adjacent climats"})
    assert r.status_code == 200 and r.json()["resolution"] == "different_wines"
    assert _sql("SELECT count(*) AS n FROM wine_exclusion")[0]["n"] == 1
    assert _sql("SELECT lwin7 FROM merchant_lwin_untrusted")[0]["lwin7"] == "1038217"

    sid = _collect(client, pair)
    assert _sql("SELECT count(*) AS n FROM offer WHERE snapshot_id = %s",
                (sid,))[0]["n"] == 2                                 # both now resolve
    assert client.get("/lwin-conflicts").json() == []                # not reopened


@pg
def test_resolving_a_collision_as_one_wine_creates_the_alias(client):
    """Gaja's Costa Russi under two appellations is one wine. Approving the
    alias recovers the depth that discarding the LWIN would have lost."""
    wid = _seed_wine(client, "Gaja", "Costa Russi", lwin7="1099722")
    book = [farr(1, "Costa Russi, Gaja", "2016", "6×75cl", "1200.00", 6, 2, lwin7=1099722),
            farr(2, "Barbaresco Costa Russi, Gaja", "2016", "6×75cl", "1150.00", 6, 1,
                 lwin7=1099722)]
    _collect(client, book)
    assert _sql("SELECT count(*) AS n FROM offer")[0]["n"] == 1

    [c] = client.get("/lwin-conflicts").json()
    r = client.post(f"/lwin-conflicts/{c['conflict_id']}/resolve", json={
        "resolution": "same_wine",
        "aliases": [{"wine_id": wid, "producer_text": "Gaja",
                     "cuvee_text": "Barbaresco Costa Russi"}],
        "note": "appellation change, same wine"})
    assert r.status_code == 200
    sid = _collect(client, book)
    assert _sql("SELECT count(*) AS n FROM offer WHERE wine_id = %s AND snapshot_id = %s",
                (wid, sid))[0]["n"] == 2


@pg
def test_an_alias_resolution_still_obeys_the_exclusion_guard_rails(client):
    """The conflict queue is not a way round the identity guard rails."""
    charmes = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru", lwin7="1")
    book = [farr(1, "Charmes-Chambertin Grand Cru, Domaine Armand Rousseau", "2011",
                 "1×75cl", "610.00", 1, 1, lwin7=1),
            farr(2, "Mazoyeres-Chambertin Grand Cru, Domaine Armand Rousseau", "2011",
                 "1×75cl", "300.00", 1, 1, lwin7=1)]
    _collect(client, book)
    [c] = client.get("/lwin-conflicts").json()
    r = client.post(f"/lwin-conflicts/{c['conflict_id']}/resolve", json={
        "resolution": "same_wine",
        "aliases": [{"wine_id": charmes, "producer_text": R,
                     "cuvee_text": "Mazoyeres-Chambertin Grand Cru"}]})
    assert r.status_code == 409
    assert client.get("/lwin-conflicts").json()[0]["resolution"] is None


# --- adapter fixes reaching the database -------------------------------------


@pg
def test_farr_non_vintage_wines_are_ingested_as_1000(client):
    _seed_wine(client, "Veuve Clicquot", "Brut")
    _collect(client, [farr(1, "Brut, Veuve Clicquot", "N.V.", "6×75cl", "290.00", 6, 4)])
    assert _sql("SELECT vintage FROM offer")[0]["vintage"] == 1000


@pg
def test_bordeaux_index_unreadable_rows_are_stored_as_rejections(client):
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    card = {**bi_card("650.00")}
    card["offers"] = ["Case (6 x 75cl) STATUS In-Bond price on application", *card["offers"]]
    _collect_bi(client, wid, [card])
    assert [r["reason"] for r in _sql("SELECT reason FROM offer_reject")] == ["ROW_UNREADABLE"]
    assert _sql("SELECT count(*) AS n FROM offer")[0]["n"] == 1


# --- line_state is derived, never stored -------------------------------------


@pg
def test_line_state_is_derived_on_read_not_stored(client):
    """A stored status would drift out of step with the benchmark it describes.
    line_state exists only in the response: nothing writes it, and re-reading
    the same unchanged line after a new run reports the new state."""
    assert not _sql("""SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'public' AND column_name = 'line_state'""")
    wid = _seed_wine(client)
    deal_id, line_id = _deal(client, wid)
    assert client.get(f"/deals/{deal_id}").json()["lines"][0]["line_state"] == "NOT_SEARCHED"

    before = _sql("SELECT * FROM seller_line WHERE line_id = %s", (line_id,))
    _collect(client)
    _benchmark(client, deal_id)
    assert client.get(f"/deals/{deal_id}").json()["lines"][0]["line_state"] == "REVIEW"
    assert _sql("SELECT * FROM seller_line WHERE line_id = %s", (line_id,)) == before


# --- the export gate ----------------------------------------------------------


def _price_below_cost(client) -> tuple[str, str, str]:
    """A line priced at £400 against a £480 cost: NEGATIVE_GP."""
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 400.00", fetch=False)
    _price(client, deal_id)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert "NEGATIVE_GP" in p["flags"] and p["requires_acknowledgement"] is True
    return deal_id, line_id, p["pricing_id"]


def _issue(client, deal_id, line_id, pricing_id, *, requires_ack, ack_id=None):
    offer_id = _sql("""INSERT INTO buyer_offer (deal_id, client, currency, issued_at, issued_by)
                       VALUES (%s, 'A Buyer', 'GBP', now(), %s) RETURNING buyer_offer_id""",
                    (deal_id, client.operator["operator_id"]))[0]["buyer_offer_id"]
    _sql("""INSERT INTO buyer_offer_line (buyer_offer_id, line_no, line_id, pricing_id,
            description, vintage, bottle_ml, pack_size, quantity, unit_price, line_total,
            pricing_requires_ack, ack_id)
            VALUES (%s, 1, %s, %s, 'Rousseau Charmes 2011', 2011, 750, 1, 6,
                    400.00, 2400.00, %s, %s)""",
         (offer_id, line_id, pricing_id, requires_ack, ack_id), fetch=False)


@pg
def test_a_price_below_cost_cannot_be_exported_unacknowledged(client):
    """NEGATIVE_GP gates the buyer export, structurally: the composite key to
    pricing_result means the export cannot claim the price needs no sign-off."""
    import psycopg
    deal_id, line_id, pricing_id = _price_below_cost(client)

    with pytest.raises(psycopg.errors.CheckViolation):          # honest, unacknowledged
        _issue(client, deal_id, line_id, pricing_id, requires_ack=True)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):     # lying about the gate
        _issue(client, deal_id, line_id, pricing_id, requires_ack=False)

    r = client.post(f"/lines/{line_id}/pricing/acknowledge",
                    json={"note": "clearing old stock"})
    assert r.status_code == 200
    ack = r.json()["acknowledgement"]
    assert ack["acknowledged_by"]["display_name"] == "The Operator"
    assert ack["flags"] == ["NEGATIVE_GP"]
    assert ack["acknowledged_at"] and ack["note"] == "clearing old stock"

    _issue(client, deal_id, line_id, pricing_id, requires_ack=True, ack_id=ack["ack_id"])
    assert _sql("SELECT count(*) AS n FROM buyer_offer_line")[0]["n"] == 1


@pg
def test_selling_above_the_uk_market_gates_because_the_document_says_below(client):
    """The client document reads '% below UK market'. Publishing it while above
    the Reference is a false claim, not a thin margin."""
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 700.00", fetch=False)   # Reference is 610
    _price(client, deal_id)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert p["flags"] and "SELL_ABOVE_UK_REFERENCE" in p["flags"]
    assert p["requires_acknowledgement"] is True


@pg
def test_a_deep_discount_is_the_product_not_a_gate(client):
    """The business sells below market, so gating on DEEP_DISCOUNT would gate
    every line. £400 against a £610 Reference is 34% below, and exports —
    on a READY line, where the state itself is not the thing gating."""
    deal_id, line_id = _priced_deal(client, manual="400.00")
    _sql("UPDATE seller_line SET cost = 300.00", fetch=False)
    _price(client, deal_id)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert (p["state"], p["gp"]) == ("READY", "100.00")
    assert "DEEP_DISCOUNT" in p["flags"]
    assert p["requires_acknowledgement"] is False
    _issue(client, deal_id, line_id, p["pricing_id"], requires_ack=False)


@pg
def test_cost_above_the_reference_is_a_commercial_fact_not_a_gate(client):
    """Buying above market leaves only two ways out, and both gate on their own
    account: sell above market, or sell at a loss. COST_ABOVE_UK_REFERENCE is
    never the reason an export is stopped, and never what gets acknowledged."""
    from app.db.repo import EXPORT_GATE_FLAGS
    assert "COST_ABOVE_UK_REFERENCE" not in EXPORT_GATE_FLAGS
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 620.00, cost = 620.00", fetch=False)
    _price(client, deal_id)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert {"COST_ABOVE_UK_REFERENCE", "SELL_ABOVE_UK_REFERENCE"} <= set(p["flags"])
    r = client.post(f"/lines/{line_id}/pricing/acknowledge", json={})
    assert r.json()["acknowledgement"]["flags"] == ["SELL_ABOVE_UK_REFERENCE"]


@pg
def test_acknowledging_a_price_with_nothing_to_acknowledge_is_refused(client):
    deal_id, line_id = _priced_deal(client)
    assert client.get(f"/lines/{line_id}/pricing").json()["requires_acknowledgement"] is False
    r = client.post(f"/lines/{line_id}/pricing/acknowledge", json={})
    assert r.status_code == 409


@pg
def test_repricing_needs_a_fresh_acknowledgement(client):
    """The acknowledgement is of one price, not of a line."""
    deal_id, line_id, _ = _price_below_cost(client)
    client.post(f"/lines/{line_id}/pricing/acknowledge", json={})
    assert client.get(f"/lines/{line_id}/pricing").json()["acknowledgement"] is not None

    _price(client, deal_id)                                   # priced again
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert p["requires_acknowledgement"] is True and p["acknowledgement"] is None


# --- producer-only aliases ----------------------------------------------------


@pg
def test_producer_only_alias_is_refused_while_the_producer_has_two_wines(client):
    """Farr prints both 'Veuve Clicquot' and 'Veuve Clicquot Rosé'. A careless
    producer-only alias attaches the Rosé listing to the Brut."""
    brut = _seed_wine(client, "Veuve Clicquot", "Brut", lwin7="1083129")
    rose = _seed_wine(client, "Veuve Clicquot", "Rose")
    body = {"producer_text": "Veuve Clicquot", "cuvee_text": "",
            "source": "operator"}
    r = client.post(f"/wines/{brut}/aliases", json=body)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert {c["wine_id"] for c in detail["candidates"]} == {brut, rose}
    assert {c["cuvee"] for c in detail["candidates"]} == {"Brut", "Rose"}

    # Naming the target again, deliberately, is what it takes.
    r = client.post(f"/wines/{brut}/aliases", json={**body, "confirm_target": brut})
    assert r.status_code == 201 and r.json()["is_producer_only"] is True


@pg
def test_producer_only_alias_needs_no_confirmation_for_a_single_wine_producer(client):
    wid = _seed_wine(client, "Chateau Lafite Rothschild", "Grand Vin")
    r = client.post(f"/wines/{wid}/aliases", json={
        "producer_text": "Lafite Rothschild", "cuvee_text": "",
        "source": "operator"})
    assert r.status_code == 201


@pg
@pytest.mark.parametrize("source", ["ai_reviewed", "import"])
def test_a_producer_only_alias_may_never_come_from_an_ai_proposal(client, source):
    wid = _seed_wine(client, "Veuve Clicquot", "Brut")
    r = client.post(f"/wines/{wid}/aliases", json={
        "producer_text": "Veuve Clicquot", "cuvee_text": "",
        "source": source})
    assert r.status_code == 409 and "operator-only" in r.text
    assert _sql("SELECT count(*) AS n FROM wine_alias")[0]["n"] == 0


@pg
def test_producer_only_aliases_can_be_audited_as_a_set(client):
    brut = _seed_wine(client, "Veuve Clicquot", "Brut")
    client.post(f"/wines/{brut}/aliases", json={
        "producer_text": "Veuve Clicquot", "cuvee_text": "",
        "source": "operator"})
    client.post(f"/wines/{brut}/aliases", json={
        "producer_text": "Veuve Clicquot", "cuvee_text": "Yellow Label",
        "source": "operator"})
    assert len(client.get("/aliases").json()) == 2
    [only] = client.get("/aliases", params={"producer_only": True}).json()
    assert only["wine_key"] == "veuve clicquot|" and only["is_producer_only"] is True
    assert client.get("/aliases", params={"producer_only": False}).json()[0][
        "wine_key"] == "veuve clicquot|yellow label"


# --- retention ----------------------------------------------------------------


@pg
def test_pruning_keeps_the_newest_captures_per_merchant(client):
    """Retention is per merchant. Farr is captured three times and Goedhuis
    once, long before; keeping one per merchant must not drop Goedhuis."""
    _seed_wine(client)
    old = _collect(client, FARR_BOOK, merchant="goedhuis")
    _age_capture(old, 30)
    first, second, third = (_collect(client) for _ in range(3))
    _age_capture(first, 2)
    _age_capture(second, 1)

    j = jobs.prune_snapshots(keep=1)
    assert set(j["deleted"]) == {first, second}
    kept = {str(r["snapshot_id"]) for r in _sql("SELECT snapshot_id FROM snapshot")}
    assert kept == {old, third}
    assert {r["merchant_id"] for r in _sql("SELECT merchant_id FROM snapshot_merchant")} \
        == {"farr", "goedhuis"}


@pg
def test_pruning_never_removes_what_a_new_benchmark_would_resolve(client):
    wid = _seed_wine(client)
    _age_capture(_collect(client), 3)
    latest = _collect(client)
    deal_id, line_id = _deal(client, wid)

    jobs.prune_snapshots(keep=1)
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["uk_reference"] == "610.00"
    assert [s["snapshot_id"] for s in run["sources"]] == [latest]


@pg
def test_pruning_leaves_past_runs_readable(client):
    wid = _seed_wine(client)
    sid = _collect(client)
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    before = client.get(f"/lines/{line_id}/benchmark").json()
    _collect(client)                                   # a newer capture

    assert jobs.prune_snapshots(keep=1)["deleted"] == [sid]
    after = client.get(f"/lines/{line_id}/benchmark").json()
    assert [c["price"] for c in after["comps"]] == [c["price"] for c in before["comps"]]
    assert all(c["offer_pk"] is None for c in after["comps"])


# --- alias suggestions --------------------------------------------------------


@pg
def test_repeated_corrections_of_the_same_wording_become_an_alias_suggestion(client):
    """The identity trail is what feeds 'operator corrections become reusable
    aliases': the same seller wording corrected to the same wine, twice."""
    a = _seed_wine(client, cuvee="Charmes-Chambertin")
    b = _seed_wine(client, cuvee="Mazoyeres-Chambertin")
    r = client.post("/deals", json={"name": "d", "lines": [
        {"row_index": i, "raw_description": "Rousseau  CHARMES 2011",
         "raw_row": {"A": "Rousseau  CHARMES 2011"}, "quantity": 1} for i in range(2)]})
    lines = [ln["line_id"] for ln in r.json()["lines"]]
    for line_id in lines:
        client.put(f"/lines/{line_id}/identity", json={
            "wine_id": b, "vintage": 2011, "bottle_ml": 750, "pack_size": 1,
            "source": "ai_reviewed"})
        client.put(f"/lines/{line_id}/identity", json={
            "wine_id": a, "vintage": 2011, "bottle_ml": 750, "pack_size": 1,
            "source": "operator"})

    suggestions = client.get("/alias-suggestions").json()
    charmes = [x for x in suggestions if x["wine_id"] == a]
    assert len(charmes) == 1
    assert charmes[0]["normalised"] == "rousseau charmes 2011"
    assert sorted(charmes[0]["line_ids"]) == sorted(lines)
    assert charmes[0]["corrections"] == 2 and charmes[0]["cuvee"] == "Charmes-Chambertin"
    assert [c["username"] for c in charmes[0]["changed_by"]] == ["op"]
    assert client.get("/alias-suggestions", params={"min_occurrences": 3}).json() == []


# --- operator identity --------------------------------------------------------


@pg
def test_every_route_but_health_and_session_needs_a_session(db):
    """Not a convention: the router itself carries the dependency, so a new
    route cannot be added unauthenticated by forgetting something."""
    api.app.dependency_overrides[api.queue] = lambda: Queue(
        "health", connection=fakeredis.FakeRedis())
    anon = TestClient(api.app, base_url="https://testserver")
    assert anon.get("/health").status_code == 200
    assert anon.get("/session").status_code == 401
    for method, path in [("get", "/merchants"), ("get", "/wines"), ("get", "/deals/" + str(uuid4())),
                         ("get", "/lwin-conflicts"), ("get", "/alias-suggestions"),
                         ("post", "/snapshots"), ("get", "/aliases")]:
        assert getattr(anon, method)(path).status_code == 401, path

    routes = [r for r in api.app.routes
              if getattr(r, "path", "").startswith(("/health", "/session"))]
    assert len(routes) == 4                      # health, and the three session verbs
    api.app.dependency_overrides.clear()


@pg
def test_sign_in_sets_an_httponly_secure_lax_cookie(db, operator):
    client = TestClient(api.app, base_url="https://testserver")
    r = _sign_in(client)
    assert r.status_code == 200 and r.json()["display_name"] == "The Operator"
    cookie = r.headers["set-cookie"]
    assert all(flag in cookie.lower() for flag in ("httponly", "secure", "samesite=lax"))
    assert client.get("/session").json()["username"] == "op"
    # Only the hash is stored: the cookie value itself is not in the database.
    token = client.cookies["pricer_session"]
    assert _sql("SELECT count(*) AS n FROM operator_session WHERE token_hash = %s",
                (token,))[0]["n"] == 0
    assert _sql("SELECT count(*) AS n FROM operator_session")[0]["n"] == 1


@pg
@pytest.mark.parametrize("username,password", [("op", "wrong"), ("nobody", "correct horse")])
def test_a_wrong_password_or_unknown_operator_is_401(db, operator, username, password):
    client = TestClient(api.app, base_url="https://testserver")
    r = _sign_in(client, username=username, password=password)
    assert r.status_code == 401
    assert "pricer_session" not in client.cookies


@pg
def test_the_password_is_not_stored_and_is_hashed_with_argon2id(db, operator):
    stored = _sql("SELECT password_hash FROM operator")[0]["password_hash"]
    assert stored.startswith("$argon2id$")
    assert OPERATOR["password"] not in stored


@pg
def test_a_caller_may_not_name_someone_else(client):
    """The three who-fields come from the session. A body that tries to name a
    different person is refused outright rather than quietly ignored."""
    wid = _seed_wine(client)
    _, line_id = _deal(client, wid)
    for path, body in [
        (f"/wines/{wid}/aliases", {"producer_text": R, "cuvee_text": "X",
                                   "source": "operator", "approved_by": "someone else"}),
        (f"/lines/{line_id}/identity", {"wine_id": wid, "vintage": 2011, "bottle_ml": 750,
                                        "pack_size": 1, "source": "operator",
                                        "approved_by": "someone else"}),
        (f"/lines/{line_id}/pricing/acknowledge", {"acknowledged_by": "someone else"}),
    ]:
        method = client.put if path.endswith("/identity") else client.post
        r = method(path, json=body)
        assert r.status_code == 422, (path, r.text)
        assert "approved_by" in r.text or "acknowledged_by" in r.text


@pg
def test_revoking_an_operator_ends_access_without_touching_history(client):
    """`active` is how access is removed: the audit rows still point at the
    operator, and the display name still resolves."""
    wid = _seed_wine(client)
    deal_id, _ = _deal(client, wid)
    from app.api import auth
    auth.set_active(OPERATOR["username"], False)

    assert client.get("/session").status_code == 401
    assert _sign_in(client).status_code == 401
    assert _sql("SELECT revoked_at FROM operator_session")[0]["revoked_at"] is not None

    signed_in = TestClient(api.app, base_url="https://testserver")
    auth.set_active(OPERATOR["username"], True)
    assert _sign_in(signed_in).status_code == 200
    assert signed_in.get(f"/deals/{deal_id}").json()["created_by"]["username"] == "op"


@pg
def test_renaming_an_operator_does_not_rewrite_the_past(client):
    """Audit rows keep the id, so the name shown follows the operator record."""
    wid = _seed_wine(client)
    deal_id, _ = _deal(client, wid)
    _sql("UPDATE operator SET display_name = 'A. Baker (maternity cover)'", fetch=False)
    deal = client.get(f"/deals/{deal_id}").json()
    assert deal["created_by"]["display_name"] == "A. Baker (maternity cover)"
    assert deal["created_by"]["operator_id"] == str(client.operator["operator_id"])


@pg
def test_signing_out_revokes_the_session(client):
    assert client.delete("/session").status_code == 204
    assert client.get("/session").status_code == 401
    assert _sql("SELECT revoked_at FROM operator_session")[0]["revoked_at"] is not None


@pg
def test_setting_a_password_ends_existing_sessions(client):
    from app.api import auth
    assert client.get("/session").status_code == 200
    auth.set_password(OPERATOR["username"], "a new password")
    assert client.get("/session").status_code == 401
    assert _sign_in(client, password="a new password").status_code == 200


# --- issuing a buyer offer ----------------------------------------------------


def _priced_deal(client, manual="500.00", cuvee="Charmes-Chambertin Grand Cru") -> tuple[str, str]:
    """A deal with a real market behind it: Farr's bottle plus a Bordeaux Index
    search, so the line is READY and only the commercial flags can gate it."""
    wid = _seed_wine(client, cuvee=cuvee)
    client.post(f"/wines/{wid}/aliases", json={
        "producer_text": R, "cuvee_text": cuvee.replace(" Grand Cru", ""),
        "source": "operator"})
    _collect(client)
    _collect_bi(client, wid, [bi_card("650.00", cuvee=cuvee)])
    deal_id, line_id = _deal(client, wid, quantity=1)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = %s", (manual,), fetch=False)
    _price(client, deal_id)
    return deal_id, line_id


@pg
def test_an_issued_offer_copies_the_figures_it_was_priced_from(client):
    deal_id, line_id = _priced_deal(client)
    r = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "currency": "GBP", "terms": "Ex-London City Bond",
        "lines": [{"line_id": line_id}]})
    assert r.status_code == 201, r.text
    offer = r.json()
    assert (offer["client"], offer["total"]) == ("A Merchant Ltd", "500.00")
    assert offer["issued_by"]["username"] == "op"
    [ln] = offer["lines"]
    assert (ln["unit_price"], ln["quantity"], ln["line_total"]) == ("500.00", 1, "500.00")
    assert ln["description"] == "Domaine Armand Rousseau Charmes-Chambertin Grand Cru 2011"
    assert client.get(f"/buyer-offers/{offer['buyer_offer_id']}").json() == offer

    # Re-pricing the line later does not rewrite what was sent.
    _sql("UPDATE seller_line SET manual_price = 900.00", fetch=False)
    _price(client, deal_id)
    assert client.get(f"/buyer-offers/{offer['buyer_offer_id']}").json()["total"] == "500.00"


@pg
def test_an_unacknowledged_flagged_price_stops_the_whole_document(client):
    """One bad line does not get quietly dropped from the offer."""
    deal_id, line_id = _priced_deal(client, manual="400.00")
    _sql("UPDATE seller_line SET cost = 480.00", fetch=False)    # priced below cost
    _price(client, deal_id)
    r = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]})
    assert r.status_code == 409 and "NEGATIVE_GP" in r.text
    assert _sql("SELECT count(*) AS n FROM buyer_offer")[0]["n"] == 0

    client.post(f"/lines/{line_id}/pricing/acknowledge", json={"note": "clearing stock"})
    r = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]})
    assert r.status_code == 201
    assert r.json()["lines"][0]["ack_id"] is not None


@pg
def test_an_unpriced_line_cannot_be_offered(client):
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    r = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]})
    assert r.status_code == 409 and "no price" in r.text


@pg
def test_a_line_from_another_deal_cannot_be_offered(client):
    deal_id, _ = _priced_deal(client)
    _, other_line = _priced_deal(client, cuvee="Clos de la Roche")
    r = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": other_line}]})
    assert r.status_code == 404


# --- overviews the operator screens are built on ------------------------------


@pg
def test_an_empty_raw_row_is_refused(client):
    """The spreadsheet is parsed in the browser, so this is where "never
    destroy the original seller description" is enforced for every caller."""
    r = client.post("/deals", json={"name": "d", "lines": [
        {"row_index": 0, "raw_description": "Rousseau Charmes 2011", "raw_row": {},
         "quantity": 1}]})
    assert r.status_code == 422 and "raw_row" in r.text


@pg
def test_the_deal_list_counts_lines_by_state(client):
    wid = _seed_wine(client)
    _collect(client)
    deal_id, _ = _deal(client, wid)
    client.post("/deals", json={"name": "unapproved", "lines": [
        {"row_index": 0, "raw_description": "?", "raw_row": {"A": "?"}, "quantity": 1}]})
    _benchmark(client, deal_id)

    by_name = {d["name"]: d for d in client.get("/deals").json()}
    assert by_name["Rousseau parcel"]["review"] == 1
    assert by_name["Rousseau parcel"]["not_searched"] == 0
    assert by_name["unapproved"]["identity_not_approved"] == 1
    assert by_name["unapproved"]["created_by"]["username"] == "op"


@pg
def test_the_review_queue_says_what_each_line_is_waiting_for(client):
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid)
    r = client.post("/deals", json={"name": "unapproved", "lines": [
        {"row_index": 0, "raw_description": "Rousseau ?", "raw_row": {"A": "?"}, "quantity": 1}]})
    unapproved_line = r.json()["lines"][0]["line_id"]

    queue = {q["line_id"]: q for q in client.get("/review-queue").json()}
    assert queue[unapproved_line]["line_state"] == "IDENTITY_NOT_APPROVED"
    assert queue[line_id]["line_state"] == "NOT_SEARCHED"

    _benchmark(client, deal_id)
    q = {x["line_id"]: x for x in client.get("/review-queue").json()}[line_id]
    assert (q["line_state"], q["deal_name"]) == ("REVIEW", "Rousseau parcel")
    assert "ONE_COMP" in q["benchmark_flags"] and q["uk_reference"] == "610.00"

    # A price that needs accepting keeps the line in the queue after it is READY.
    _sql("UPDATE seller_line SET manual_price = 400.00 WHERE line_id = %s", (line_id,),
         fetch=False)
    _price(client, deal_id)
    q = {x["line_id"]: x for x in client.get("/review-queue").json()}[line_id]
    assert q["requires_acknowledgement"] is True and q["acknowledged"] is False
    client.post(f"/lines/{line_id}/pricing/acknowledge", json={})
    q = {x["line_id"]: x for x in client.get("/review-queue").json()}[line_id]
    assert q["acknowledged"] is True


# --- the market claim, and the state gate (decision 0010) --------------------


@pg
def test_a_line_with_no_uk_reference_carries_no_market_claim(client):
    """The rule that matters more than the gate: no Reference, no claim. Not a
    blank cell, not zero — no row at all, so a document has nothing to print."""
    wid = _seed_wine(client)
    _collect(client, FARR_BOOK[2:])                  # searched; this wine not listed
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 500.00", fetch=False)
    _price(client, deal_id)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert (p["state"], p["uk_reference"]) == ("NO_MARKET", None)

    client.post(f"/lines/{line_id}/pricing/acknowledge", json={"note": "cost-plus, agreed"})
    r = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]})
    assert r.status_code == 201, r.text
    [line] = r.json()["lines"]
    assert line["market_claim"] is None
    assert _sql("SELECT count(*) AS n FROM buyer_offer_market_claim")[0]["n"] == 0


@pg
def test_a_market_claim_records_the_reference_it_was_made_against(client):
    """With two merchants there is a Reference, so the line may say how far
    below it the price is — and the claim keeps the reference and the run."""
    wid = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    client.post(f"/wines/{wid}/aliases", json={
        "producer_text": R, "cuvee_text": "Charmes-Chambertin", "source": "operator"})
    _collect(client)
    _collect_bi(client, wid, [bi_card("650.00")])
    deal_id, line_id = _deal(client, wid, quantity=1)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 520.00", fetch=False)   # 20% below £650
    _price(client, deal_id)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert (p["state"], p["uk_reference"]) == ("READY", "650.00")
    assert p["requires_acknowledgement"] is False

    offer = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]}).json()
    claim = offer["lines"][0]["market_claim"]
    assert claim["uk_reference"] == "650.00" and claim["comp_count"] == 2
    assert Decimal(claim["below_reference"]) == Decimal("0.2000")
    assert claim["run_id"] == p["run_id"]


@pg
def test_a_market_claim_cannot_be_written_without_a_reference(client):
    """Structural, not a convention: the claim table has no nullable reference,
    so no template or code path can reintroduce a claim we cannot support."""
    import psycopg
    wid = _seed_wine(client)
    _collect(client, FARR_BOOK[2:])
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 500.00", fetch=False)
    _price(client, deal_id)
    client.post(f"/lines/{line_id}/pricing/acknowledge", json={})
    offer = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]}).json()
    run_id = client.get(f"/lines/{line_id}/benchmark").json()["run_id"]
    with pytest.raises(psycopg.errors.NotNullViolation):
        _sql("""INSERT INTO buyer_offer_market_claim
                    (buyer_offer_id, line_no, run_id, as_of, uk_reference, comp_count,
                     below_reference)
                VALUES (%s, 1, %s, now(), NULL, 1, 0.2)""",
             (offer["buyer_offer_id"], run_id), fetch=False)


@pg
@pytest.mark.parametrize("state,gated", [("NO_MARKET", True), ("REVIEW", True), ("READY", False)])
def test_the_benchmark_state_gates_the_export_too(client, state, gated):
    """NO_MARKET and REVIEW are about whether we measured a market at all, so
    they need a named operator before anything reaches a buyer."""
    wid = _seed_wine(client)
    _collect(client)
    deal_id, line_id = _deal(client, wid, quantity=1)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 500.00", fetch=False)
    _price(client, deal_id)
    _sql("UPDATE pricing_result SET state = %s", (state,), fetch=False)
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert p["requires_acknowledgement"] is gated

    r = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]})
    assert (r.status_code == 409) is gated, r.text
    if gated:
        assert state in r.text
        client.post(f"/lines/{line_id}/pricing/acknowledge", json={})
        ack = client.get(f"/lines/{line_id}/pricing").json()["acknowledgement"]
        assert ack["state"] == state
        assert client.post(f"/deals/{deal_id}/buyer-offers", json={
            "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]}).status_code == 201


@pg
def test_the_burgundy_case_needs_sign_off_on_every_line(client):
    """The rehearsal issued 20 NO_MARKET lines with nothing stopping it. Now
    every one of them needs a name against it."""
    wid = _seed_wine(client)
    _collect(client, FARR_BOOK[2:])
    deal_id, line_id = _deal(client, wid)
    _benchmark(client, deal_id)
    _sql("UPDATE seller_line SET manual_price = 500.00", fetch=False)
    _price(client, deal_id)
    queue = {q["line_id"]: q for q in client.get("/review-queue").json()}
    assert queue[line_id]["requires_acknowledgement"] is True
    assert client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]}).status_code == 409


# --- DEEP MERCHANT SEARCH ----------------------------------------------------


@pg
def test_deep_search_asks_only_about_the_thin_lines(client):
    """Bordeaux Index cannot join a sweep, so it is asked afterwards about the
    lines the sweep left thin — and about nothing else."""
    charmes = _seed_wine(client, cuvee="Charmes-Chambertin Grand Cru")
    client.post(f"/wines/{charmes}/aliases", json={
        "producer_text": R, "cuvee_text": "Charmes-Chambertin", "source": "operator"})
    _collect(client)                                   # Farr: one bottle, one comp
    deal_id, line_id = _deal(client, charmes, quantity=1)
    _benchmark(client, deal_id)
    assert client.get(f"/lines/{line_id}/benchmark").json()["comp_count"] == 1

    r = client.put("/merchants/bordeaux-index/search-keys", json={
        "producer_key": "domaine armand rousseau",
        "params": {"producer_slug": "domaine_armand_rousseau"},
        "note": "from the merchant's own index"})
    assert r.status_code == 200 and r.json()["set_by"]["username"] == "op"

    asked = []

    def fetch(adapter, params, vintage):
        asked.append((params["producer_slug"], vintage))
        return [bi_card("650.00", vintage=vintage)]

    result = jobs.deep_search(deal_id, fetch=fetch, robots=lambda url: None)
    assert asked == [("domaine_armand_rousseau", 2011)]
    assert result["targets"] == 1 and len(result["searched"]) == 1

    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["comp_count"] == 2 and run["state"] == "READY"
    assert {s["merchant_id"] for s in run["sources"]} == {"farr", "bordeaux-index"}


@pg
def test_deep_search_never_guesses_a_producer_slug(client):
    """domaine-armand-rousseau is a 404 at Bordeaux Index and
    domaine_armand_rousseau is not. A missing key is a recorded skip."""
    wid = _seed_wine(client)
    deal_id, _ = _deal(client, wid)
    result = jobs.deep_search(deal_id, fetch=lambda *a: [], robots=lambda url: None)
    assert result["searched"] == []
    assert result["skipped"][0]["reason"] == "no search key for this producer"
    assert result["skipped"][0]["producer"] == R


@pg
def test_search_keys_are_read_from_the_merchants_own_index(client, monkeypatch):
    from app.adapters.bordeaux_index import BordeauxIndexAdapter
    monkeypatch.setattr(BordeauxIndexAdapter, "search_keys",
                        lambda self: {"Domaine Armand Rousseau": "domaine_armand_rousseau",
                                      "Château Haut-Brion": "chateau_haut-brion"})
    out = jobs.learn_search_keys("bordeaux-index", str(client.operator["operator_id"]),
                                 robots=lambda url: None)
    assert out["keys"] == 2
    keys = {k["producer_key"]: k for k in
            client.get("/merchants/bordeaux-index/search-keys").json()}
    assert keys["domaine armand rousseau"]["params"] == {
        "producer_slugs": ["domaine_armand_rousseau"]}
    assert keys["chateau haut brion"]["source"] == "merchant_index"


@pg
def test_a_producer_published_under_two_slugs_keeps_both(client, monkeypatch):
    """Searching only one of them would quietly halve that producer's depth."""
    from app.adapters.bordeaux_index import BordeauxIndexAdapter
    monkeypatch.setattr(BordeauxIndexAdapter, "search_keys",
                        lambda self, client=None: {
                            "Chateau Haut-Brion": "chateau_haut-brion",
                            "Chateau  Haut Brion": "haut-brion"})
    out = jobs.learn_search_keys("bordeaux-index", str(client.operator["operator_id"]),
                                 robots=lambda url: None)
    assert (out["keys"], out["slugs"]) == (1, 2)
    [key] = client.get("/merchants/bordeaux-index/search-keys").json()
    assert key["params"] == {"producer_slugs": ["chateau_haut-brion", "haut-brion"]}


@pg
def test_a_price_above_the_market_is_not_a_negative_discount(client):
    """Found in the second rehearsal: a line priced above the Reference printed
    as "-114.2% below UK Market". A price above the market is not a smaller
    discount — it is not a discount, so the line carries no claim at all."""
    import psycopg
    deal_id, line_id = _priced_deal(client, manual="900.00")     # the Reference is £650
    p = client.get(f"/lines/{line_id}/pricing").json()
    assert "SELL_ABOVE_UK_REFERENCE" in p["flags"] and p["uk_reference"] == "650.00"
    client.post(f"/lines/{line_id}/pricing/acknowledge", json={"note": "agreed above market"})

    offer = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]}).json()
    assert offer["lines"][0]["market_claim"] is None
    assert _sql("SELECT count(*) AS n FROM buyer_offer_market_claim")[0]["n"] == 0

    # And no code path can write one: the claim itself refuses to be negative.
    run_id = client.get(f"/lines/{line_id}/benchmark").json()["run_id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        _sql("""INSERT INTO buyer_offer_market_claim
                    (buyer_offer_id, line_no, run_id, as_of, uk_reference, comp_count,
                     below_reference)
                VALUES (%s, 1, %s, now(), 650.00, 2, -1.1420)""",
             (offer["buyer_offer_id"], run_id), fetch=False)


# --- brokerage indications (decision 0013) ------------------------------------


def frw_product(name, cuvee, amount, merchants=3, producer=R):
    """A FINE+RARE product page's pageProps, as the adapter receives them."""
    return {"url": f"https://www.frw.co.uk/product/x/{name.lower().replace(' ', '-')}",
            "product": {"_id": f"id-{name}", "name": name,
                        "parent": {"name": cuvee, "producer": {"name": producer}}},
            "productMarketInfo": {"unitSize": "75", "unit": "cl", "listingCount": merchants + 1,
                                  "merchantCount": merchants,
                                  "unitPrice": {"amount": amount, "currencyCode": "GBP"}}}


def _collect_frw(client, wine_id, products, vintage=2011) -> str:
    jid = client.post("/snapshots/targeted", json={
        "merchant_id": "fine-rare", "wine_id": wine_id, "vintage": vintage,
        "params": {"producer_slug": "domaine-armand-rousseau"}}).json()["job_id"]
    return _run_patched(client, jid, "collect_targeted", lambda orig: (
        lambda merchant_id, wine_id, vintage, params, is_demo=False: orig(
            merchant_id, wine_id, vintage, params, is_demo=is_demo,
            fetch=lambda a, p, v: products, robots=lambda url: None)
    ))["result"]


@pg
def test_an_indication_is_kept_as_corroboration_and_prices_nothing(client):
    """FINE+RARE at £590 beside Farr at £610: the Reference stays Farr's, the
    indication is on the run with its variance, and FINE+RARE is not depth."""
    wid = _seed_wine(client)
    _collect(client)
    _collect_frw(client, wid, [frw_product("2011 Charmes-Chambertin", "Charmes-Chambertin",
                                           590, merchants=8)])
    deal_id, line_id = _deal(client, wid, quantity=1)
    _benchmark(client, deal_id)

    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert (run["uk_reference"], run["comp_count"]) == ("610.00", 1)
    assert "ONE_COMP" in run["flags"]                      # FINE+RARE is not a second merchant
    [ind] = [c for c in run["comps"] if c["role"] == "indication"]
    assert (ind["merchant"], ind["price"]) == ("FINE+RARE", "590.00")
    assert Decimal(ind["variance_vs_reference"]) == Decimal("-0.0328")
    assert ind["merchant_count"] == 8                      # context, not depth
    assert all(c["merchant_id"] != "fine-rare"
               for c in run["comps"] if c["role"] in ("comparable", "merchant_best"))


@pg
def test_an_indication_never_reaches_a_client_document(client):
    """A line whose only evidence is an indication is NO_MARKET, so it gates,
    and it carries no market claim: a brokerage's view is not a UK market."""
    wid = _seed_wine(client)
    _collect(client, FARR_BOOK[2:])                        # Farr searched, wine not listed
    _collect_frw(client, wid, [frw_product("2011 Charmes-Chambertin", "Charmes-Chambertin", 590)])
    deal_id, line_id = _deal(client, wid, quantity=1)
    _benchmark(client, deal_id)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["state"] == "NO_MARKET" and run["uk_reference"] is None
    assert [c["role"] for c in run["comps"] if c["role"] == "indication"] == ["indication"]

    _sql("UPDATE seller_line SET manual_price = 500.00", fetch=False)
    _price(client, deal_id)
    client.post(f"/lines/{line_id}/pricing/acknowledge", json={"note": "cost-plus"})
    offer = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]}).json()
    assert offer["lines"][0]["market_claim"] is None


@pg
def test_an_indication_is_stored_as_what_it_is(client):
    wid = _seed_wine(client)
    _collect_frw(client, wid, [frw_product("2011 Charmes-Chambertin", "Charmes-Chambertin", 590)])
    [row] = _sql("SELECT * FROM offer")
    assert (row["price_kind"], row["duty_status"]) == ("INDICATION", "UNKNOWN")
    assert (row["is_buyable"], row["offered_units"]) == (False, 0)
    assert row["stock_type"] == "BROKERED"
    assert row["raw"]["market"]["merchantCount"] == 3


@pg
def test_fine_and_rare_is_searched_never_swept(client):
    """A brokerage is a deep-search source: it answers per producer and vintage,
    so it can no more join a sweep than Bordeaux Index can."""
    sid = jobs.collect_snapshot(["fine-rare"], fetch=lambda a: [], robots=lambda url: None)
    [snap] = _sql("SELECT failures FROM snapshot WHERE snapshot_id = %s", (sid,))
    assert snap["failures"][0]["merchant_id"] == "fine-rare"
    assert "collect_targeted" in snap["failures"][0]["error"]


# --- the vintage-neighbour sanity check ---------------------------------------
#
# docs/research/vintage-neighbour-check-spec.md, tests 8 and 9. The unit tests
# for the band itself are in tests/test_vintage_band.py; these two are about
# what the pipeline does with it.

MG = "Mugneret-Gibourg"
MG_CUVEE = "Vosne-Romanee"


def mg_card(vintage: int, *prices: str) -> dict:
    """One Bordeaux Index LiveTrade card: a vintage of the 6x75 In Bond, with
    every offer BI shows on it. Two prices for one vintage sit on one card —
    two cards would be two products."""
    return {"title": f"{vintage} Domaine Mugneret-Gibourg, {MG_CUVEE}",
            "code": f"mugneret-{vintage}",
            "url": f"https://bordeauxindex.com/livetrade/mugneret-{vintage}",
            "offers": [f"Case (6 x 75cl) CONDITION Original Case STATUS In-Bond ETA In Stock "
                       f"You buy £{price} 1 Case(s) Available" for price in prices]}


def ls_row(price: str, vintage: int = 2020) -> dict:
    """One Lea & Sandeman In Bond list row, thirteen cells, read by position."""
    return {"cells": ["Burgundy", "Red", str(vintage),
                      f"{MG_CUVEE.upper()}, DOMAINE {MG.upper()}", "51234", "6x75cl", "2",
                      price, "1550.00", "IB", "", "", "ADD TO BASKET"],
            "source_url": "https://www.leaandsandeman.co.uk/fine-wine.html"}


def _collect_ls(client, rows) -> str:
    jid = client.post("/snapshots", json={"merchant_ids": ["lea-sandeman"]}).json()["job_id"]
    return _run_patched(client, jid, "collect_snapshot", lambda orig: (
        lambda merchant_ids=None, is_demo=False: orig(
            merchant_ids, is_demo=is_demo, fetch=lambda a: rows, robots=lambda url: None)
    ))["result"]


def _collect_mg(client, wine_id, cards, vintage=2020) -> str:
    jid = client.post("/snapshots/targeted", json={
        "merchant_id": "bordeaux-index", "wine_id": wine_id, "vintage": vintage,
        "params": {"producer_slug": "domaine-mugneret-gibourg"}}).json()["job_id"]
    return _run_patched(client, jid, "collect_targeted", lambda orig: (
        lambda merchant_id, wine_id, vintage, params, is_demo=False: orig(
            merchant_id, wine_id, vintage, params, is_demo=is_demo,
            fetch=lambda a, p, v: cards, robots=lambda url: None)
    ))["result"]


def _mugneret_line(client):
    """The live L21 case: BI £2,070 and L&S £1,200 for the 2020 6x75 In Bond,
    with BI's own 2017 and 2018 as the neighbouring vintages."""
    wid = _seed_wine(client, producer=f"Domaine {MG}", cuvee=MG_CUVEE)
    _collect_mg(client, wid, [mg_card(2020, "2070.00", "2074.00"),
                              mg_card(2017, "1489.00", "1520.00"),
                              mg_card(2018, "1223.00")])
    _collect_ls(client, [ls_row("1200.00")])
    r = client.post("/deals", json={
        "name": "Vosne parcel", "currency": "GBP", "target_margin": 0.2,
        "lines": [{"row_index": 0, "raw_description": "Mugneret-Gibourg Vosne 2020 6x75 IB",
                   "raw_row": {"A": "Mugneret-Gibourg Vosne 2020", "B": "6"},
                   "quantity": 6, "cost": "900.00", "cost_currency": "GBP"}]})
    deal = r.json()
    line_id = deal["lines"][0]["line_id"]
    assert client.put(f"/lines/{line_id}/identity", json={
        "wine_id": wid, "vintage": 2020, "bottle_ml": 750, "pack_size": 6,
        "source": "operator", "flags": []}).status_code == 200
    _benchmark(client, deal["deal_id"])
    return deal["deal_id"], line_id


@pg
def test_mugneret_gibourg_2020_is_excluded_by_the_band_in_the_pipeline(client):
    """The whole point, end to end: Bordeaux Index £2,070 against Lea & Sandeman
    £1,200, with BI's own 2017 and 2018 at £1,489 and £1,223. Left alone the
    line goes out READY off £2,070, 72% above a live UK ask."""
    _, line_id = _mugneret_line(client)
    run = client.get(f"/lines/{line_id}/benchmark").json()

    assert run["uk_reference"] == "1200.00" and run["comp_count"] == 1
    assert run["state"] == "REVIEW" and "ONE_COMP" in run["flags"]

    band = run["vintage_band"]
    assert (band["band_low"], band["band_high"]) == ("1223.00", "1489.00")
    assert [(n["vintage"], n["median"]) for n in band["neighbours"]] == [
        (2017, "1489.00"), (2018, "1223.00")]
    assert band["tiers_available"] is False and "no vintage tiers recorded" in band["note"]

    # BOTH of Bordeaux Index's listings go, not just its best. Excluding only
    # the cheaper of them would promote the other and the Reference would fall
    # from £2,070 to £2,074: the check would have achieved nothing.
    assert [(x["merchant"], x["price"]) for x in band["excluded"]] == [
        ("Bordeaux Index", "2074.00"), ("Bordeaux Index", "2070.00")]
    assert {x["flag"] for x in band["excluded"]} == {"COMP_EXCLUDED_VINTAGE_BAND"}
    assert {x["band_edge"] for x in band["excluded"]} == {"2010.15"}   # 1489.00 x 1.35
    assert all(x["reinstated_at"] is None for x in band["excluded"])
    assert all(c["merchant_id"] != "bordeaux-index"
               for c in run["comps"] if c["role"] == "merchant_best")


@pg
def test_excluded_comp_is_reinstatable_with_provenance(client):
    """One click puts Bordeaux Index's £2,070 back, and the record says who did
    it and why. The original run is not edited: a new run is computed, the old
    one still reads £1,200, and the band still says the comp is out of band."""
    _, line_id = _mugneret_line(client)
    before = client.get(f"/lines/{line_id}/benchmark").json()
    excluded = [x for x in before["vintage_band"]["excluded"] if x["price"] == "2070.00"][0]

    r = client.post(f"/comp-exclusions/{excluded['exclusion_id']}/reinstate",
                    json={"reason": "BI confirmed the ask by phone"})
    assert r.status_code == 200, r.text
    after = r.json()

    assert after["run_id"] != before["run_id"]
    assert after["uk_reference"] == "2070.00" and after["comp_count"] == 2
    # One comp back, the other still out: putting one back is not a blanket
    # amnesty for every comp the band caught.
    assert [x["price"] for x in after["vintage_band"]["excluded"]] == ["2074.00"]
    # Still out of band, and still said so — it is simply no longer removed.
    assert after["vintage_band"]["band_high"] == "1489.00"

    [row] = _sql("SELECT * FROM benchmark_comp_exclusion WHERE exclusion_id = %s",
                 (excluded["exclusion_id"],))
    assert str(row["reinstated_by"]) == str(client.operator["operator_id"])
    assert row["reinstated_reason"] == "BI confirmed the ask by phone"
    assert str(row["replacement_run_id"]) == after["run_id"]
    assert row["band_multiple"] == Decimal("1.0298")       # 2070.00 / 2010.15

    # The run it was excluded from is untouched.
    [old] = _sql("SELECT uk_reference FROM benchmark_run WHERE run_id = %s",
                 (before["run_id"],))
    assert old["uk_reference"] == Decimal("1200.00")


@pg
def test_export_contains_no_band_fields(client):
    """A band is not a price and never appears on a client document: no band,
    no neighbouring vintage, no per-bottle format figure, nothing."""
    deal_id, line_id = _mugneret_line(client)
    run = client.get(f"/lines/{line_id}/benchmark").json()
    assert run["vintage_band"]["band_high"] == "1489.00"   # it exists on the run

    _price(client, deal_id)
    pricing = client.get(f"/lines/{line_id}/pricing").json()
    client.post(f"/lines/{line_id}/pricing/acknowledge", json={"note": "seen, REVIEW"})
    offer = client.post(f"/deals/{deal_id}/buyer-offers", json={
        "client": "A Merchant Ltd", "lines": [{"line_id": line_id}]})
    assert offer.status_code == 201, offer.text

    printed = json.dumps(offer.json())
    for banned in ("band", "neighbour", "vintage_band", "1489", "1223", "2070",
                   "COMP_EXCLUDED_VINTAGE_BAND", "per_bottle"):
        assert banned not in printed, banned
    assert "market_claim" in printed and json.dumps(pricing) is not None

    # And nothing in the export tables carries one either.
    [claim] = _sql("SELECT * FROM buyer_offer_market_claim")
    assert set(claim) == {"buyer_offer_id", "line_no", "run_id", "as_of",
                          "uk_reference", "comp_count", "below_reference"}
