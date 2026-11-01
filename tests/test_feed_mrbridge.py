"""MrBridge Wine-Searcher dataset → generic market-evidence batch (decision
0049), against the four REAL rows collected on 1 November 2026
(tests/fixtures/mrbridge/dataset_2026-11-01.json) and the four wines' real
register names (docs/research/want-list-wines.csv).

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    python -m pytest -q tests/test_feed_mrbridge.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from app.feed import importer, mrbridge

ROOT = Path(__file__).resolve().parents[1]
ROWS = json.loads((ROOT / "tests/fixtures/mrbridge/dataset_2026-11-01.json").read_text())
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

REGISTER = [("Comte Liger-Belair", "La Romanée"), ("Domaine Armand Rousseau", "Chambertin"),
            ("Domaine Armand Rousseau", "Chambertin Clos de Bèze"),
            ("Domaine Leroy", "Clos de Vougeot"), ("Domaine de la Romanée-Conti", "La Tâche")]


def _row(fragment):
    return next(r for r in ROWS if fragment in r["inputValue"])


# ----------------------------------------------------------------- pure mapping


def test_names_split_into_wine_searchers_winery_and_a_register_shaped_cuvee():
    assert mrbridge.split_name(_row("Rousseau")["wineName"], "Domaine Armand Rousseau", 2023) == (
        "Domaine Armand Rousseau", "chambertin")
    assert mrbridge.split_name(_row("La Tache")["wineName"], "Domaine de la Romanee-Conti", 1996) == (
        "Domaine de la Romanee-Conti", "la tache")
    assert mrbridge.split_name(_row("Leroy")["wineName"], "Domaine Leroy", 2001) == (
        "Domaine Leroy", "clos de vougeot")
    # Wine-Searcher's winery spelling mapped onto the register's producer
    assert mrbridge.split_name(_row("Liger")["wineName"], "Domaine du Comte Liger-Belair", None) == (
        "Comte Liger-Belair", "la romanee")


def test_clos_de_beze_never_collapses_into_plain_chambertin():
    """The resolver's producer-less substring mode would match 'chambertin'
    inside '...Chambertin Clos de Beze' — the producer is always passed."""
    _, cuvee = mrbridge.split_name("2015 Domaine Armand Rousseau Pere et Fils Chambertin "
                                   "Clos de Beze Grand Cru", "Domaine Armand Rousseau", 2015)
    assert cuvee == "chambertin clos de beze"


def test_the_converter_passes_on_only_what_a_row_states():
    batch, skipped = mrbridge.to_batch(ROWS)
    assert batch["source"] == "wine-searcher-via-mrbridge" and skipped == []
    by_input = {o["raw"]["inputValue"]: o for o in batch["observations"]}
    rousseau = by_input["2023 Chambertin Grand Cru Rousseau 2023"]
    # No URL states a size, so every row is a 75cl EQUIVALENT, never a listing
    assert (rousseau["kind"], rousseau["price"], rousseau["currency"]) == (
        "EQUIVALENT_75CL", "1695.00", "GBP")
    assert rousseau["merchant"]["name"] == "Mann Fine Wine"
    assert rousseau["bottle_ml"] is None and rousseau["duty_status"] == "UNKNOWN"   # never stated
    assert rousseau["raw"]["offersCount"] == 6 and rousseau["raw"]["bottlesPerUnit"] == 1
    assert rousseau["raw"]["format_stated"] is False
    assert rousseau["observed_at"] == "2026-11-01T04:36:26.828Z"
    # Leroy: 3333.33 per 75cl from a 6-bottle listing — never multiplied back
    leroy = by_input["2001 Clos Vougeot, Leroy"]
    assert (leroy["kind"], leroy["price"]) == ("EQUIVALENT_75CL", "3333.33")
    assert leroy["raw"]["bottlesPerUnit"] == 6 and leroy["raw"]["bottle_equivalent_of"] == 6
    # La Romanée: a generic page, no vintage — kept as null, never guessed
    assert by_input["La Romanée Grand Cru Comte Liger-Belair"]["vintage"] is None


def test_only_a_url_confirmed_750ml_single_bottle_becomes_a_listing():
    row = {**_row("Rousseau"), "wineSearcherUrl": _row("Rousseau")["wineSearcherUrl"] + "?Xbottle_size=750"}
    obs = mrbridge.to_batch([row])[0]["observations"][0]
    assert (obs["kind"], obs["bottle_ml"]) == ("CURRENT_LISTING", 750)
    case = {**_row("Leroy"), "wineSearcherUrl": _row("Leroy")["wineSearcherUrl"] + "?Xbottle_size=750"}
    obs = mrbridge.to_batch([case])[0]["observations"][0]
    assert (obs["kind"], obs["bottle_ml"]) == ("EQUIVALENT_75CL", None)     # 6-btl: still an equivalent


def test_750ml_only_when_the_wine_searcher_url_states_it():
    base = "https://www.wine-searcher.com/find/2023+Chambertin+Grand+Cru+Rousseau+2023"
    assert mrbridge.bottle_ml_from_url(f"{base}?Xbottle_size=750") == 750
    assert mrbridge.bottle_ml_from_url(f"{base}?xbottle_size=750ml") == 750
    assert mrbridge.bottle_ml_from_url(base) is None                       # normalised ≠ stated
    assert mrbridge.bottle_ml_from_url(f"{base}?Xbottle_size=1500") is None
    assert mrbridge.bottle_ml_from_url(f"{base}?Xbottle_size=all") is None
    assert mrbridge.bottle_ml_from_url(None) is None


def test_a_row_the_actor_failed_is_handed_back_not_converted():
    batch, skipped = mrbridge.to_batch([{**ROWS[0], "status": "error"}])
    assert batch["observations"] == [] and skipped[0]["reason"] == "status 'error'"


# ------------------------------------------------- through the unchanged importer


@pytest.fixture
def conn(monkeypatch):
    with psycopg.connect(TEST_DB, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
                   env={**os.environ, "DATABASE_URL": TEST_DB}, check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, row_factory=dict_row, autocommit=True,
                         prepare_threshold=None) as c:
        from app.db import repo
        for producer, cuvee in REGISTER:
            repo.create_wine(c, producer=producer, cuvee=cuvee, region="Burgundy",
                             colour="red", lwin7=None)
        yield c


@pg
def test_real_rows_resolve_where_the_names_agree_and_fail_closed_where_they_do_not(conn):
    """Identity is VESSEL's: all four resolve by exact key to the register —
    Liger-Belair through the converter's winery equivalence."""
    from app.db import repo
    registry = repo.load_registry(conn)
    batch, _ = mrbridge.to_batch(ROWS)
    resolved = {o["raw"]["inputValue"]: registry.resolve_candidate(o["wine"]["producer"],
                                                                   o["wine"]["name"])
                for o in batch["observations"]}
    names = {str(w["wine_id"]): f"{w['producer']} / {w['cuvee']}"
             for w in conn.execute("SELECT wine_id, producer, cuvee FROM wine").fetchall()}
    assert names[resolved["2023 Chambertin Grand Cru Rousseau 2023"]] == "Domaine Armand Rousseau / Chambertin"
    assert names[resolved["1996 La Tache, DRC"]] == "Domaine de la Romanée-Conti / La Tâche"
    assert names[resolved["2001 Clos Vougeot, Leroy"]] == "Domaine Leroy / Clos de Vougeot"
    assert names[resolved["La Romanée Grand Cru Comte Liger-Belair"]] == "Comte Liger-Belair / La Romanée"


SIZED = [{**r, "wineSearcherUrl": r["wineSearcherUrl"] + "?Xbottle_size=750"} for r in ROWS]


def _wine_id(conn, producer, cuvee):
    return str(conn.execute("SELECT wine_id FROM wine WHERE producer = %s AND cuvee = %s",
                            (producer, cuvee)).fetchone()["wine_id"])



def _when():
    from datetime import datetime, timezone
    return datetime(2026, 11, 2, tzinfo=timezone.utc)


@pg
def test_the_real_export_gives_75cl_eq_steers_and_never_an_offer_the_core_can_read(conn):
    """Doug's real four-row export, no URL filtering: Rousseau 2023, DRC La Tache
    1996 and Leroy Clos de Vougeot 2001 each give a /75cl eq steer; La Romanee
    (no vintage) gives none. Not one row becomes an offer, so Floor cannot move."""
    summary = importer.import_batch(conn, mrbridge.to_batch(ROWS)[0])
    assert (summary["written"], summary["rejected"]) == (0, 4)
    assert summary["rejected_by_reason"] == {"EQUIVALENT_ONLY": 3, "VINTAGE": 1}
    assert conn.execute("SELECT count(*) AS n FROM offer").fetchone()["n"] == 0
    assert conn.execute("SELECT count(*) AS n FROM snapshot_merchant").fetchone()["n"] == 0

    rousseau = _wine_id(conn, "Domaine Armand Rousseau", "Chambertin")
    s = mrbridge.steer(conn, wine_id=rousseau, vintage=2023, bottle_ml=750, as_of=_when())
    assert (s["source"], s["merchant"], str(s["price"]), s["unit"], s["currency"],
            s["offers_count"], s["bottle_equivalent_of"]) == (
        "Wine-Searcher", "Mann Fine Wine", "1695.00", "75cl eq", "GBP", 6, None)
    drc = _wine_id(conn, "Domaine de la Romanée-Conti", "La Tâche")
    s = mrbridge.steer(conn, wine_id=drc, vintage=1996, bottle_ml=750, as_of=_when())
    assert (str(s["price"]), s["unit"]) == ("4600.00", "75cl eq")
    leroy = _wine_id(conn, "Domaine Leroy", "Clos de Vougeot")
    s = mrbridge.steer(conn, wine_id=leroy, vintage=2001, bottle_ml=750, as_of=_when())
    assert (str(s["price"]), s["unit"], s["bottle_equivalent_of"]) == ("3333.33", "75cl eq", 6)
    romanee = _wine_id(conn, "Comte Liger-Belair", "La Romanée")
    for vintage in (2019, 2020, 2023):
        assert mrbridge.steer(conn, wine_id=romanee, vintage=vintage, bottle_ml=750, as_of=_when()) is None


@pg
def test_an_equivalent_is_never_recorded_as_a_750ml_bottle(conn):
    importer.import_batch(conn, mrbridge.to_batch(ROWS)[0])
    raws = [r["raw"] for r in conn.execute(
        "SELECT raw FROM offer_reject WHERE reason = 'EQUIVALENT_ONLY'").fetchall()]
    assert len(raws) == 3
    assert all(r["observation"]["bottle_ml"] is None for r in raws)            # no size claimed
    assert all(r["acquisition_source"] == "wine-searcher-via-mrbridge" for r in raws)
    assert sorted(r["observation"]["raw"]["bottlesPerUnit"] for r in raws) == [1, 1, 6]


@pg
def test_a_steer_is_exactly_this_wine_and_vintage_and_goes_stale(conn):
    from datetime import datetime, timezone
    importer.import_batch(conn, mrbridge.to_batch(ROWS)[0])
    rousseau = _wine_id(conn, "Domaine Armand Rousseau", "Chambertin")
    beze = _wine_id(conn, "Domaine Armand Rousseau", "Chambertin Clos de Bèze")
    assert mrbridge.steer(conn, wine_id=rousseau, vintage=2022, bottle_ml=750, as_of=_when()) is None
    assert mrbridge.steer(conn, wine_id=beze, vintage=2023, bottle_ml=750, as_of=_when()) is None
    stale = datetime(2026, 11, 20, tzinfo=timezone.utc)                  # > 14 days after the scrape
    assert mrbridge.steer(conn, wine_id=rousseau, vintage=2023, bottle_ml=750, as_of=stale) is None


@pg
def test_a_url_confirmed_750ml_bottle_is_a_listing_shown_per_btl_that_still_sets_no_floor(conn):
    summary = importer.import_batch(conn, mrbridge.to_batch(SIZED)[0])
    assert summary["written"] == 2                     # Rousseau + DRC: single bottles, 750 confirmed
    assert summary["rejected_by_reason"] == {"EQUIVALENT_ONLY": 1, "VINTAGE": 1}   # Leroy 6-btl
    kinds = {(r["price_kind"], r["duty_status"], r["bottle_ml"]) for r in conn.execute(
        "SELECT price_kind, duty_status, bottle_ml FROM offer")}
    assert kinds == {("ASK", "UNKNOWN", 750)}
    assert conn.execute("SELECT count(*) AS n FROM snapshot_merchant").fetchone()["n"] == 0
    rousseau = _wine_id(conn, "Domaine Armand Rousseau", "Chambertin")
    s = mrbridge.steer(conn, wine_id=rousseau, vintage=2023, bottle_ml=750, as_of=_when())
    assert (str(s["price"]), s["unit"]) == ("1695.00", "btl")
    assert mrbridge.steer(conn, wine_id=rousseau, vintage=2023, bottle_ml=1500, as_of=_when()) is None


@pg
def test_a_feed_row_that_cannot_count_never_hides_a_merchants_own_in_bond_price(conn):
    """Wine-Searcher's cheapest is sometimes a merchant we also collect directly.
    A capture claims coverage only when it carries something that could set
    Floor, so Farr's own In Bond ask still counts."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.core.enums import DutyStatus, PriceKind
    from app.core.models import Offer
    from app.db import repo
    rousseau = _wine_id(conn, "Domaine Armand Rousseau", "Chambertin")
    earlier = datetime(2026, 10, 31, tzinfo=timezone.utc)
    snap = repo.create_snapshot(conn, captured_at=earlier, schema_version="2", is_demo=False)
    repo.write_offer(conn, snap, Offer(
        offer_id="farr:1", merchant_id="farr", merchant="Farr", wine_id=rousseau, vintage=2023,
        bottle_ml=750, pack_size=1, price=Decimal("1500.00"), currency="GBP",
        duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK, is_buyable=True,
        offered_units=1, captured_at=earlier))
    repo.write_snapshot_merchant(conn, snap, "farr", captured_at=earlier, written=1)
    farr_name = conn.execute("SELECT name FROM merchant WHERE merchant_id = 'farr'").fetchone()["name"]
    row = {**SIZED[2], "cheapestPriceMerchant": farr_name}                 # Rousseau, cheapest = Farr
    importer.import_batch(conn, mrbridge.to_batch([row])[0])
    res = repo.resolve_offers(conn, wine_id=rousseau, vintage=2023, as_of=_when())
    farr = [o for o in res.offers if o.merchant_id == "farr"]
    assert [(o.duty_status, str(o.price)) for o in farr] == [(DutyStatus.IN_BOND, "1500.00")]


def test_the_post_script_chunks_and_never_needs_the_token_for_a_dry_run(monkeypatch, capsys):
    import runpy
    monkeypatch.delenv("MARKET_FEED_TOKEN", raising=False)
    script = runpy.run_path(str(ROOT / "scripts/post_mrbridge_batch.py"))
    assert [len(c) for c in script["chunks"](list(range(650)), 300)] == [300, 300, 50]
    lines = script["overview"](mrbridge.to_batch(ROWS)[0]["observations"])
    assert len(lines) == 4 and "Mann Fine Wine" in lines[2] and "size not stated" in lines[2]
