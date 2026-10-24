"""Buy-side, single-line evaluation (decision 0039). House style as in
test_traps.py: name the rule and the size of the error the test
prevents.

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    python -m pytest -q tests/test_evaluate.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import fakeredis
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from rq import Queue

from app.api import main as api
from app.evaluate import repo as evaluate_repo

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


def _reset(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT,
                   env={**os.environ, "DATABASE_URL": TEST_DB}, check=True, capture_output=True)


@pytest.fixture
def conn(monkeypatch):
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, row_factory=dict_row, autocommit=True,
                         prepare_threshold=None) as c:
        yield c


def _operator(conn) -> str:
    from app.api.auth import hash_password
    row = conn.execute(
        "INSERT INTO operator (username, display_name, password_hash) VALUES (%s, %s, %s) "
        "RETURNING operator_id",
        (f"op-{uuid4().hex[:8]}", "Test Operator", hash_password("x" * 12))).fetchone()
    return str(row["operator_id"])


OPERATOR = {"username": "op", "display_name": "The Operator", "password": "correct horse"}


@pytest.fixture
def client(conn):
    from app.api import auth

    auth.create_operator(OPERATOR["username"], OPERATOR["display_name"], OPERATOR["password"])
    q = Queue(f"test-{uuid4().hex}", connection=fakeredis.FakeRedis())
    api.app.dependency_overrides[api.queue] = lambda: q
    c = TestClient(api.app, base_url="https://testserver")
    assert c.post("/session", json={"username": OPERATOR["username"],
                                    "password": OPERATOR["password"]}).status_code == 200
    yield c
    api.app.dependency_overrides.clear()


def _comp(merchant="Wine-Searcher: Millesima", price="9800.00", bottle_ml=750, pack_size=1,
          **kw) -> dict:
    return {"merchant": merchant, "price": price, "currency": "GBP", "bottle_ml": bottle_ml,
           "pack_size": pack_size, "duty_status": "IB", "price_kind": "ASK",
           "is_buyable": True, "offered_units": None, "source_url": None,
           "captured_at": None, **kw}


@pg
def test_ensure_manual_merchant_reuses_the_same_row_by_name(conn):
    from app.db import repo as db

    first = evaluate_repo.ensure_manual_merchant(conn, "Wine-Searcher: Millesima")
    second = evaluate_repo.ensure_manual_merchant(conn, "Wine-Searcher: Millesima")
    assert first == second
    matches = [m for m in db.list_merchants(conn) if m["name"] == "Wine-Searcher: Millesima"]
    assert len(matches) == 1 and matches[0]["approved"] is True


@pg
def test_a_non_whole_pence_comp_is_refused_not_rounded(conn):
    from app.db import repo as db

    operator_id = _operator(conn)
    wine = db.create_wine(conn, producer="Domaine Leroy", cuvee="Chambertin",
                          region="Burgundy", colour="Red", lwin7=None)
    with pytest.raises(evaluate_repo.InvalidEvaluation, match="whole number of pence"):
        evaluate_repo.evaluate_offer(
            conn, raw_description="Leroy Chambertin 2015 x3", wine_id=str(wine["wine_id"]),
            vintage=2015, bottle_ml=750, pack_size=1, quantity=3,
            asking_price=Decimal("9500.00"), asking_currency="GBP",
            comps=[_comp(price="9800.129")], evaluated_by=operator_id)


@pg
def test_evaluate_offer_runs_the_real_benchmark_and_lands_in_one_persistent_deal(conn):
    """"Doug does this often" -- a second evaluation lands in the SAME
    deal, not a fresh one, so the history accumulates rather than
    scattering across one-line deals."""
    from app.db import repo as db

    operator_id = _operator(conn)
    wine = db.create_wine(conn, producer="Domaine Leroy", cuvee="Chambertin",
                          region="Burgundy", colour="Red", lwin7=None)
    result = evaluate_repo.evaluate_offer(
        conn, raw_description="Leroy Chambertin 2015 x3", wine_id=str(wine["wine_id"]),
        vintage=2015, bottle_ml=750, pack_size=1, quantity=3,
        asking_price=Decimal("9500.00"), asking_currency="GBP",
        comps=[_comp(merchant="Wine-Searcher: Millesima", price="9800.00"),
              _comp(merchant="Wine-Searcher: Uncorked", price="10150.00")],
        evaluated_by=operator_id)
    assert result["run_id"] is not None
    run = db.latest_run(conn, result["line_id"])
    assert (run["uk_floor"], run["uk_reference"], run["comp_count"]) == \
        (Decimal("9800.00"), Decimal("10150.00"), 2)
    assert run["state"] == "READY"

    wine2 = db.create_wine(conn, producer="Domaine d'Auvenay", cuvee="Meursault",
                           region="Burgundy", colour="White", lwin7=None)
    second = evaluate_repo.evaluate_offer(
        conn, raw_description="Auvenay Meursault 2016 x1", wine_id=str(wine2["wine_id"]),
        vintage=2016, bottle_ml=750, pack_size=1, quantity=1,
        asking_price=Decimal("3000.00"), asking_currency="GBP",
        comps=[_comp(merchant="Wine-Searcher: Millesima", price="3200.00"),
              _comp(merchant="Wine-Searcher: Uncorked", price="3300.00")],
        evaluated_by=operator_id)
    assert second["deal_id"] == result["deal_id"]
    deal = db.get_deal(conn, second["deal_id"])
    assert deal["name"] == "Buy-side evaluations"
    assert len(db.deal_lines(conn, second["deal_id"])) == 2


@pg
def test_a_one_merchant_evaluation_is_one_comp_and_review(conn):
    """The same ONE_COMP rule applies here as anywhere else — no bypass."""
    from app.db import repo as db

    operator_id = _operator(conn)
    wine = db.create_wine(conn, producer="Coche-Dury", cuvee="Corton-Charlemagne",
                          region="Burgundy", colour="White", lwin7=None)
    result = evaluate_repo.evaluate_offer(
        conn, raw_description="Coche-Dury Corton-Charlemagne 2018 x1",
        wine_id=str(wine["wine_id"]), vintage=2018, bottle_ml=750, pack_size=1, quantity=1,
        asking_price=Decimal("2500.00"), asking_currency="GBP",
        comps=[_comp(merchant="Wine-Searcher: Millesima", price="2700.00")],
        evaluated_by=operator_id)
    run = db.latest_run(conn, result["line_id"])
    assert run["comp_count"] == 1 and run["state"] == "REVIEW"
    assert "ONE_COMP" in run["flags"]


@pg
def test_the_asking_price_is_the_lines_own_cost_readable_like_any_other_line(conn):
    """No new pricing concept: the asking price is seller_line.cost, the
    same field sell-side lines already use -- a screen compares it
    against uk_floor/uk_reference, it does not invent a new figure."""
    from app.db import repo as db

    operator_id = _operator(conn)
    wine = db.create_wine(conn, producer="Domaine Armand Rousseau", cuvee="Chambertin",
                          region="Burgundy", colour="Red", lwin7=None)
    result = evaluate_repo.evaluate_offer(
        conn, raw_description="Rousseau Chambertin 2017 x2", wine_id=str(wine["wine_id"]),
        vintage=2017, bottle_ml=750, pack_size=1, quantity=2,
        asking_price=Decimal("4200.00"), asking_currency="GBP",
        comps=[_comp(price="4500.00"), _comp(merchant="Wine-Searcher: Uncorked",
                                              price="4600.00")],
        evaluated_by=operator_id)
    line = db.get_line(conn, result["line_id"])
    assert line["cost"] == Decimal("4200.00") and line["cost_currency"] == "GBP"


# --------------------------------------------------------------------- API


@pg
def test_want_list_match_endpoint_is_a_suggestion_never_a_resolution(client):
    r = client.post("/identity/want-list-match", json={"text": "Leroy Chambertin 2015"})
    assert r.status_code == 200
    [match] = r.json()
    assert match == {"producer": "Domaine Leroy", "always_review": True}


@pg
def test_want_list_match_endpoint_returns_empty_for_no_match(client):
    r = client.post("/identity/want-list-match", json={"text": "Chateau Margaux 2015"})
    assert r.status_code == 200 and r.json() == []


@pg
def test_evaluate_endpoint_runs_the_real_benchmark_end_to_end(client):
    wine = client.post("/wines", json={
        "producer": "Domaine d'Auvenay", "cuvee": "Meursault Narvaux",
        "region": "Burgundy", "colour": "White"}).json()
    r = client.post("/evaluate", json={
        "raw_description": "Auvenay Meursault Narvaux 2016 x2 offered by a supplier",
        "wine_id": wine["wine_id"], "vintage": 2016, "bottle_ml": 750, "pack_size": 1,
        "quantity": 2, "asking_price": "2800.00", "asking_currency": "GBP",
        "comps": [
            {"merchant": "Wine-Searcher: Millesima", "price": "3100.00", "currency": "GBP",
             "bottle_ml": 750, "pack_size": 1},
            {"merchant": "Wine-Searcher: Uncorked", "price": "3250.00", "currency": "GBP",
             "bottle_ml": 750, "pack_size": 1},
        ]})
    assert r.status_code == 201, r.text
    line = r.json()
    assert line["benchmark"]["uk_floor"] == "3100.00"
    assert line["benchmark"]["uk_reference"] == "3250.00"
    assert line["benchmark"]["comp_count"] == 2


@pg
def test_evaluate_endpoint_refuses_a_non_whole_pence_comp_with_422(client):
    wine = client.post("/wines", json={
        "producer": "Domaine Leflaive", "cuvee": "Puligny-Montrachet",
        "region": "Burgundy", "colour": "White"}).json()
    r = client.post("/evaluate", json={
        "raw_description": "Leflaive Puligny 2018 x1", "wine_id": wine["wine_id"],
        "vintage": 2018, "bottle_ml": 750, "pack_size": 1, "quantity": 1,
        "asking_price": "900.00", "asking_currency": "GBP",
        "comps": [{"merchant": "Wine-Searcher: Millesima", "price": "950.129",
                  "currency": "GBP", "bottle_ml": 750, "pack_size": 1}]})
    assert r.status_code == 422
