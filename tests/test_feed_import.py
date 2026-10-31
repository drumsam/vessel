"""Source-agnostic market-evidence import (app/feed/importer.py) — the proof:
external JSON -> validation -> merchant mapping -> offer rows -> benchmark ->
MARKET (Floor). No production data; a synthetic provider batch.

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    python -m pytest -q tests/test_feed_import.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.feed import importer

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def conn(monkeypatch):
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                   env={**os.environ, "DATABASE_URL": TEST_DB}, check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, row_factory=dict_row, autocommit=True,
                         prepare_threshold=None) as c:
        yield c


def _wine(conn, producer, cuvee, *, region="Burgundy", colour="red"):
    from app.db import repo
    return str(repo.create_wine(conn, producer=producer, cuvee=cuvee, region=region,
                                colour=colour, lwin7=None)["wine_id"])


def _obs(merchant, price, *, producer="Domaine Armand Rousseau", name="Chambertin",
         vintage=2015, bottle_ml=750, pack_size=6, currency="GBP", duty="IN_BOND", **kw):
    return {"wine": {"producer": producer, "name": name}, "vintage": vintage,
            "bottle_ml": bottle_ml, "pack_size": pack_size, "merchant": {"name": merchant},
            "price": price, "currency": currency, "duty_status": duty,
            "availability": "IN_STOCK", "observed_at": NOW.isoformat(),
            "url": f"https://provider.example/{merchant}", **kw}


def _floor(conn, wine_id, vintage=2015, pack_size=6):
    """The existing benchmark, run exactly as EVALUATE runs it, on a one-line deal."""
    from app.db import repo
    from app.worker import jobs
    op = conn.execute("INSERT INTO operator (username, display_name, password_hash) "
                      "VALUES ('op', 'Op', 'x') ON CONFLICT DO NOTHING RETURNING operator_id").fetchone()
    op = op or conn.execute("SELECT operator_id FROM operator LIMIT 1").fetchone()
    deal = repo.create_deal(conn, {"name": f"t-{wine_id}", "seller": None, "city": None,
                                   "source_file": None, "currency": None, "target_margin": None,
                                   "buyer_discount": None, "margin_on_sale": None,
                                   "created_by": op["operator_id"]}, [])
    line = conn.execute("INSERT INTO seller_line (deal_id, row_index, raw_description, raw_row, "
                        "quantity) VALUES (%s, 0, 'x', '{}', 1) RETURNING line_id",
                        (deal["deal_id"],)).fetchone()
    repo.set_line_identity(conn, str(line["line_id"]), wine_id=wine_id, vintage=vintage,
                           bottle_ml=750, pack_size=pack_size, flags=[], source="operator",
                           approved_by=op["operator_id"])
    row = repo.get_line(conn, str(line["line_id"]))
    res = repo.resolve_offers(conn, wine_id=wine_id, vintage=vintage, as_of=NOW + timedelta(minutes=1))
    jobs.benchmark_with_band(conn, repo.seller_line_for_benchmark(row), res, NOW + timedelta(minutes=1))
    return repo.latest_run(conn, str(line["line_id"]))


@pg
def test_external_json_becomes_offers_and_sets_market_through_the_existing_floor(conn):
    chambertin = _wine(conn, "Domaine Armand Rousseau", "Chambertin")
    farr_name = conn.execute("SELECT name FROM merchant WHERE merchant_id = 'farr'").fetchone()["name"]
    jb_name = conn.execute("SELECT name FROM merchant WHERE merchant_id = 'justerini-brooks'").fetchone()["name"]
    batch = {"source": "external-feed-test", "observed_at": NOW.isoformat(), "observations": [
        _obs(f"{farr_name} Ltd", "24500.00"),                            # maps to farr; lowest valid
        _obs(jb_name, "25800.00"),                                       # maps to justerini-brooks
        _obs(farr_name, "26000.00", duty="DUTY_PAID"),                   # stored, excluded (DUTY)
        _obs("Cru Wine Traders", "21000.00"),                            # new, unapproved: no Floor
        _obs(jb_name, "48000.00", bottle_ml=1500, pack_size=3),          # magnum: excluded (SIZE)
        _obs(jb_name, "23000.00", vintage=2014),                         # other vintage: excluded
        _obs(jb_name, "19000.00", currency="EUR"),                       # EUR: excluded (CURRENCY)
        _obs(jb_name, "22000.00", producer="Maison Leroy", name="Chambertin"),  # unresolved
        _obs(jb_name, 24000.0),                                          # JSON number: refused
        _obs(jb_name, "24000.00", kind="HISTORIC_PRICE"),                # kept, not an ask
    ]}
    summary = importer.import_batch(conn, batch)

    assert (summary["observations"], summary["written"], summary["rejected"]) == (10, 7, 3)
    assert summary["rejected_by_reason"] == {"KIND": 1, "ROW_UNREADABLE": 1, "UNRESOLVED_IDENTITY": 1}
    assert summary["unapproved_merchants"] == ["cru-wine-traders"]
    assert summary["written_to_unapproved_merchants"] == 1
    assert summary["merchants_mapped"][f"{farr_name} Ltd"] == "farr"       # never a second Farr
    assert summary["merchants_mapped"][jb_name] == "justerini-brooks"
    assert summary["merchants_created"] == ["cru-wine-traders"]
    assert conn.execute("SELECT approved FROM merchant WHERE merchant_id = 'cru-wine-traders'"
                        ).fetchone()["approved"] is False
    assert conn.execute("SELECT count(*) AS n FROM merchant WHERE name ILIKE 'farr%'").fetchone()["n"] == 1

    rejects = {r["reason"] for r in conn.execute("SELECT reason FROM offer_reject").fetchall()}
    assert {"UNRESOLVED_IDENTITY", "ROW_UNREADABLE", "KIND"} <= rejects
    raw = conn.execute("SELECT raw FROM offer WHERE merchant_id = 'farr' AND price = 24500.00").fetchone()["raw"]
    assert raw["acquisition_source"] == "external-feed-test"

    run = _floor(conn, chambertin)
    assert run["state"] in ("READY", "REVIEW")
    assert run["uk_floor"] == Decimal("24500.00")     # lowest TRUSTED UK IB GBP 6x75cl ask
    assert run["comp_count"] == 2                     # farr + justerini-brooks, not the new one


@pg
def test_a_batch_without_a_source_or_list_writes_nothing(conn):
    with pytest.raises(importer.InvalidBatch):
        importer.import_batch(conn, {"observations": []})
    assert conn.execute("SELECT count(*) AS n FROM snapshot").fetchone()["n"] == 0


@pg
def test_a_feed_capture_never_masks_a_sibling_wine_from_a_fuller_capture(conn):
    """Decision 0048. A capture's scope used to be producer + vintage only —
    right for a merchant search (it returns every wine of the producer),
    wrong for a feed that reports only the wine it was asked about: Farr's
    feed row for Rousseau Chambertin 2015 became Farr's latest capture for
    ALL Rousseau 2015, and Farr's whole-book Clos de Beze 2015 stopped
    counting (proved before the fix). scope_wine_id narrows it to one wine."""
    from app.core.enums import DutyStatus, PriceKind
    from app.core.models import Offer
    from app.db import repo
    chambertin = _wine(conn, "Domaine Armand Rousseau", "Chambertin")
    beze = _wine(conn, "Domaine Armand Rousseau", "Chambertin Clos de Beze")
    earlier = NOW - timedelta(days=1)
    snap = repo.create_snapshot(conn, captured_at=earlier, schema_version="2", is_demo=False)
    repo.write_offer(conn, snap, Offer(
        offer_id="wb:beze", merchant_id="farr", merchant="Farr", wine_id=beze, vintage=2015,
        bottle_ml=750, pack_size=6, price=Decimal("23000.00"), currency="GBP",
        duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK, is_buyable=True,
        offered_units=1, captured_at=earlier))
    repo.write_snapshot_merchant(conn, snap, "farr", captured_at=earlier, written=1)  # whole book
    assert _floor(conn, beze)["comp_count"] == 1

    farr_name = conn.execute("SELECT name FROM merchant WHERE merchant_id = 'farr'").fetchone()["name"]
    importer.import_batch(conn, {"source": "external-feed-test", "observations": [
        _obs(farr_name, "24500.00")]})                                       # Chambertin only
    assert _floor(conn, beze)["comp_count"] == 1                              # sibling still counts
    assert _floor(conn, beze)["uk_floor"] == Decimal("23000.00")
    assert _floor(conn, chambertin)["uk_floor"] == Decimal("24500.00")        # and the feed wine too


@pg
def test_an_existing_unapproved_merchant_stays_unapproved_and_sets_no_floor(conn):
    """Decision 0048's hybrid rule: an existing approved merchant counts at once;
    an existing unapproved one keeps its state; only a genuinely new one is
    created — unapproved."""
    chambertin = _wine(conn, "Domaine Armand Rousseau", "Chambertin")
    conn.execute("UPDATE merchant SET approved = false WHERE merchant_id = 'justerini-brooks'")
    jb_name = conn.execute("SELECT name FROM merchant WHERE merchant_id = 'justerini-brooks'").fetchone()["name"]
    summary = importer.import_batch(conn, {"source": "t", "observations": [
        _obs(jb_name, "20000.00"), _obs("Brand New Cellars", "19000.00")]})
    assert summary["merchants_created"] == ["brand-new-cellars"]
    assert summary["unapproved_merchants"] == ["brand-new-cellars", "justerini-brooks"]
    assert conn.execute("SELECT approved FROM merchant WHERE merchant_id = 'justerini-brooks'"
                        ).fetchone()["approved"] is False
    assert conn.execute("SELECT count(*) AS n FROM offer").fetchone()["n"] == 2   # both kept
    run = _floor(conn, chambertin)
    assert run["state"] == "NO_MARKET" and run["uk_floor"] is None              # neither sets Floor


@pg
def test_an_observation_with_no_merchant_is_handed_back_not_stored(conn):
    _wine(conn, "Domaine Armand Rousseau", "Chambertin")
    obs = _obs("x", "1.00")
    obs["merchant"] = {}
    summary = importer.import_batch(conn, {"source": "t", "observations": [obs]})
    assert summary["unattributed_observations"] == [0]
    assert conn.execute("SELECT count(*) AS n FROM offer_reject").fetchone()["n"] == 0


# ------------------------------------------------- POST /market-evidence/batches

TOKEN = "t" * 40


@pytest.fixture
def api(conn, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import main
    monkeypatch.setenv("MARKET_FEED_TOKEN", TOKEN)
    return TestClient(main.app, base_url="https://testserver")


@pg
def test_the_feed_route_needs_the_feed_token(api, monkeypatch):
    body = {"source": "t", "observations": []}
    assert api.post("/market-evidence/batches", json=body).status_code == 401
    assert api.post("/market-evidence/batches", json=body,
                    headers={"Authorization": "Bearer wrong"}).status_code == 401
    monkeypatch.setenv("MARKET_FEED_TOKEN", "short")
    assert api.post("/market-evidence/batches", json=body,
                    headers={"Authorization": "Bearer short"}).status_code == 503


@pg
def test_the_feed_route_imports_and_returns_the_summary(api, conn):
    _wine(conn, "Domaine Armand Rousseau", "Chambertin")
    farr_name = conn.execute("SELECT name FROM merchant WHERE merchant_id = 'farr'").fetchone()["name"]
    r = api.post("/market-evidence/batches", headers={"Authorization": f"Bearer {TOKEN}"},
                 json={"source": "provider-x", "observations": [_obs(farr_name, "24500.00"),
                                                                _obs(farr_name, 1.0)]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["written"], body["rejected"], body["merchants_mapped"]) == (
        1, 1, {farr_name: "farr"})
    assert body["rejected_by_reason"] == {"ROW_UNREADABLE": 1}


@pg
def test_a_malformed_batch_is_refused_whole(api, conn):
    r = api.post("/market-evidence/batches", headers={"Authorization": f"Bearer {TOKEN}"},
                 json={"observations": []})
    assert r.status_code == 422
    assert conn.execute("SELECT count(*) AS n FROM snapshot").fetchone()["n"] == 0
    too_many = {"source": "t", "observations": [{}] * (importer.MAX_OBSERVATIONS + 1)}
    r = api.post("/market-evidence/batches", headers={"Authorization": f"Bearer {TOKEN}"},
                 json=too_many)
    assert r.status_code == 422 and "split the batch" in r.json()["detail"]
