"""Shareable public offer links (decision 0035): the machinery (Postgres)
and the API surface. House style as in test_traps.py: name the rule and
the size of the error the test prevents.

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    TEST_REDIS_URL=redis://localhost:6379/15 python -m pytest -q tests/test_offerlink.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import fakeredis
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from rq import Queue, SimpleWorker

from app.offerlink import repo as offerlink_repo

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
TEST_REDIS = os.environ.get("TEST_REDIS_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

AS_OF = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


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


OPERATOR = {"username": "op", "display_name": "The Operator", "password": "correct horse"}


def _sign_in(client, **overrides) -> dict:
    body = {**{k: OPERATOR[k] for k in ("username", "password")}, **overrides}
    return client.post("/session", json=body)


@pytest.fixture
def operator(conn):
    from app.api import auth
    return auth.create_operator(OPERATOR["username"], OPERATOR["display_name"],
                                OPERATOR["password"])


@pytest.fixture
def client(conn, operator):
    from app.api import main as api

    if TEST_REDIS:
        from redis import Redis
        q_conn = Redis.from_url(TEST_REDIS)
    else:
        q_conn = fakeredis.FakeRedis()
    q = Queue(f"test-{uuid4().hex}", connection=q_conn)
    api.app.dependency_overrides[api.queue] = lambda: q
    c = TestClient(api.app, base_url="https://testserver")
    c.queue = q
    c.operator = operator
    assert _sign_in(c).status_code == 200
    yield c
    api.app.dependency_overrides.clear()


def _work(q: Queue) -> None:
    SimpleWorker([q], connection=q.connection).work(burst=True)


def _deal_with_lines(conn, operator_id, specs: list[dict]) -> tuple[str, list[str]]:
    """One deal, one approved-identity seller_line per spec. Mirrors
    tests/test_vessel.py's own helper of the same shape."""
    from app.db import repo as db

    tag = uuid4().hex[:8]
    wines = [db.create_wine(conn, producer=sp.get("producer", f"Domaine Test {tag}"),
                            cuvee=sp.get("cuvee", f"Cuvee {tag}-{i}"), region="Champagne",
                            colour="White", lwin7=None)
             for i, sp in enumerate(specs)]
    deal = db.create_deal(
        conn, {"name": "WFS Cellar", "seller": "A Private Seller", "source_file": None,
              "currency": "GBP", "target_margin": None, "created_by": operator_id},
        [{"row_index": i, "raw_description": f"line {i}", "raw_row": {"A": "x"},
          "quantity": sp.get("quantity", 6), "cost": None, "cost_currency": None,
          "target_margin": None, "target_discount": None, "manual_price": None}
         for i, sp in enumerate(specs)])
    lines = db.deal_lines(conn, str(deal["deal_id"]))
    for line, wine, sp in zip(lines, wines, specs):
        db.set_line_identity(conn, str(line["line_id"]), wine_id=str(wine["wine_id"]),
                             vintage=sp.get("vintage", 2015), bottle_ml=750,
                             pack_size=1, flags=[], source="operator",
                             approved_by=operator_id)
    return str(deal["deal_id"]), [str(l["line_id"]) for l in lines]


def _seed_run(conn, line_id, *, comps: list[Decimal], as_of=AS_OF) -> str:
    """A plausible benchmark_run + one benchmark_comp per comp price --
    direct SQL, same discipline as test_vessel.py's own _seed_run: the rest
    of the benchmark machinery is exercised elsewhere."""
    prices = sorted(comps)
    floor, reference = prices[0], (prices[0] if len(prices) == 1 else prices[1])
    median = prices[len(prices) // 2]
    flags = ["ONE_COMP"] if len(prices) == 1 else []
    state = "REVIEW" if flags else "READY"
    run = conn.execute(
        """INSERT INTO benchmark_run (line_id, as_of, uk_floor, uk_reference, uk_median,
                                      comp_count, flags, state)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
        (line_id, as_of, floor, reference, median, len(prices), flags, state),
    ).fetchone()
    for i, price in enumerate(prices):
        snapshot = {"offer_id": f"merchant-{i}:x", "merchant_id": f"merchant-{i}",
                   "merchant": f"Merchant {i}", "merchant_offer_id": f"mo-{i}",
                   "vintage": 2015, "bottle_ml": 750, "pack_size": 1, "price": str(price),
                   "currency": "GBP", "duty_status": "IB", "price_kind": "ASK",
                   "is_buyable": True, "offered_units": None, "stock_type": "WAREHOUSE",
                   "stock_type_basis": "confirmed", "condition_flags": [],
                   "condition_notes": None, "source_url": None, "captured_at": as_of.isoformat()}
        conn.execute(
            """INSERT INTO benchmark_comp (run_id, offer_pk, role, reject_reason, offer_snapshot)
               VALUES (%s, NULL, 'merchant_best', NULL, %s)""",
            (run["run_id"], psycopg.types.json.Jsonb(snapshot)))
    return str(run["run_id"])


def _price(client, deal_id) -> None:
    r = client.post(f"/deals/{deal_id}/pricing", json={})
    assert r.status_code == 202, r.text
    _work(client.queue)


# ============================================================= Postgres: repo


@pg
def test_create_link_refuses_a_line_still_gated(conn, operator):
    operator_id = str(operator["operator_id"])
    deal_id, [line_id] = _deal_with_lines(conn, operator_id, [{}])
    _seed_run(conn, line_id, comps=[Decimal("150.00")])   # ONE_COMP -> REVIEW, ungated
    with pytest.raises(offerlink_repo.LineNotSendable):
        offerlink_repo.create_link(conn, deal_id=deal_id, line_ids=[line_id], kind="buyer",
                                   fx_rate=None, created_by=operator_id)


@pg
def test_create_link_refuses_a_line_outside_the_deal(conn, operator):
    operator_id = str(operator["operator_id"])
    deal_id, _ = _deal_with_lines(conn, operator_id, [{}])
    other_deal_id, [other_line_id] = _deal_with_lines(conn, operator_id, [{}])
    with pytest.raises(offerlink_repo.LineNotInDeal):
        offerlink_repo.create_link(conn, deal_id=deal_id, line_ids=[other_line_id],
                                   kind="buyer", fx_rate=None, created_by=operator_id)


@pg
def test_token_round_trips_and_is_long_and_url_safe(conn, operator, client):
    operator_id = str(operator["operator_id"])
    deal_id, [line_id] = _deal_with_lines(conn, operator_id, [{}])
    _seed_run(conn, line_id, comps=[Decimal("150.00"), Decimal("152.00")])
    _price(client, deal_id)

    link = offerlink_repo.create_link(conn, deal_id=deal_id, line_ids=[line_id], kind="buyer",
                                      fx_rate=Decimal("10.37"), created_by=operator_id)
    assert len(link["token"]) >= 32
    assert all(c.isalnum() or c in "-_" for c in link["token"])

    fetched = offerlink_repo.get_valid_link(conn, link["token"])
    assert fetched is not None and fetched["deal_id"] == uuid_or_str(deal_id)
    assert offerlink_repo.get_valid_link(conn, "not-a-real-token") is None


def uuid_or_str(v):
    from uuid import UUID
    return UUID(v) if isinstance(v, str) else v


@pg
def test_expired_link_reads_as_not_found(conn, operator, client):
    operator_id = str(operator["operator_id"])
    deal_id, [line_id] = _deal_with_lines(conn, operator_id, [{}])
    _seed_run(conn, line_id, comps=[Decimal("150.00"), Decimal("152.00")])
    _price(client, deal_id)

    link = offerlink_repo.create_link(conn, deal_id=deal_id, line_ids=[line_id], kind="buyer",
                                      fx_rate=None, created_by=operator_id, ttl_days=-1)
    assert offerlink_repo.get_valid_link(conn, link["token"]) is None


@pg
def test_buyer_payload_never_carries_seller_price_or_commission(conn, operator, client):
    """Structural absence, not a null value: the dict build_public_payload
    returns for a buyer-kind link never gains the key at all."""
    operator_id = str(operator["operator_id"])
    deal_id, [line_id] = _deal_with_lines(conn, operator_id, [{}])
    _seed_run(conn, line_id, comps=[Decimal("150.00"), Decimal("152.00")])
    _price(client, deal_id)

    link = offerlink_repo.create_link(conn, deal_id=deal_id, line_ids=[line_id], kind="buyer",
                                      fx_rate=None, created_by=operator_id)
    payload = offerlink_repo.build_public_payload(conn, link)
    [line] = payload["lines"]
    assert "seller_price_gbp" not in line
    assert "commission_gbp" not in line
    # And no field anywhere names the deal or the seller.
    assert "WFS Cellar" not in str(payload) and "A Private Seller" not in str(payload)


@pg
def test_seller_payload_carries_commission(conn, operator, client):
    operator_id = str(operator["operator_id"])
    deal_id, [line_id] = _deal_with_lines(conn, operator_id, [{}])
    _seed_run(conn, line_id, comps=[Decimal("150.00"), Decimal("152.00")])
    _price(client, deal_id)

    link = offerlink_repo.create_link(conn, deal_id=deal_id, line_ids=[line_id], kind="seller",
                                      fx_rate=None, created_by=operator_id)
    payload = offerlink_repo.build_public_payload(conn, link)
    [line] = payload["lines"]
    pricing = conn.execute(
        "SELECT * FROM pricing_result WHERE line_id = %s", (line_id,)).fetchone()
    assert line["seller_price_gbp"] == pricing["seller_price_gbp"]
    assert line["commission_gbp"] == pricing["gp"]


# ================================================================= API surface


@pg
def test_api_creates_a_link_and_the_public_endpoint_needs_no_session(conn, operator, client):
    from app.api import main as api

    operator_id = str(operator["operator_id"])
    deal_id, [line_id] = _deal_with_lines(conn, operator_id, [{}])
    _seed_run(conn, line_id, comps=[Decimal("150.00"), Decimal("152.00")])
    _price(client, deal_id)

    r = client.post(f"/deals/{deal_id}/offer-links",
                    json={"line_ids": [line_id], "kind": "buyer", "fx_rate": "10.37"})
    assert r.status_code == 201, r.text
    token = r.json()["token"]

    anon = TestClient(api.app, base_url="https://testserver")   # no sign-in, no cookie
    pub = anon.get(f"/public/offer-links/{token}")
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert body["kind"] == "buyer"
    [line] = body["lines"]
    assert "seller_price_gbp" not in line and "commission_gbp" not in line


@pg
def test_api_refuses_a_gated_line_with_422(conn, operator, client):
    operator_id = str(operator["operator_id"])
    deal_id, [line_id] = _deal_with_lines(conn, operator_id, [{}])
    _seed_run(conn, line_id, comps=[Decimal("150.00")])   # ONE_COMP, never priced/accepted
    _price(client, deal_id)

    r = client.post(f"/deals/{deal_id}/offer-links",
                    json={"line_ids": [line_id], "kind": "buyer", "fx_rate": None})
    assert r.status_code == 422, r.text


@pg
def test_api_unknown_token_is_404(client):
    r = client.get("/public/offer-links/does-not-exist")
    assert r.status_code == 404
