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
    assert (rousseau["price"], rousseau["currency"], rousseau["pack_size"]) == ("1695.00", "GBP", 1)
    assert rousseau["merchant"]["name"] == "Mann Fine Wine"
    assert rousseau["bottle_ml"] is None and rousseau["duty_status"] == "UNKNOWN"   # never stated
    assert rousseau["kind"] == "CURRENT_LISTING"
    assert rousseau["raw"]["offersCount"] == 6                                      # context kept
    assert rousseau["observed_at"] == "2026-11-01T04:36:26.828Z"
    # Leroy: 3333.33 per 75cl from a 6-bottle listing — a bottle-equivalent,
    # never multiplied back into a case price nobody printed
    leroy = by_input["2001 Clos Vougeot, Leroy"]
    assert (leroy["kind"], leroy["price"], leroy["pack_size"]) == ("BOTTLE_EQUIVALENT", "3333.33", 1)
    assert leroy["raw"]["bottle_equivalent_of"] == 6
    # La Romanée: a generic page, no vintage — kept as null, never guessed
    assert by_input["La Romanée Grand Cru Comte Liger-Belair"]["vintage"] is None


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


@pg
def test_under_todays_rules_no_row_sets_market_and_every_row_is_kept(conn):
    """The data states no bottle size and no duty status, so the existing
    screens keep all four out of Floor — stored, with their reasons, and the
    merchants created unapproved. Nothing here changes the pricing core."""
    batch, _ = mrbridge.to_batch(ROWS)
    summary = importer.import_batch(conn, batch)
    assert (summary["written"], summary["rejected"]) == (0, 4)
    assert summary["rejected_by_reason"] == {"SIZE": 3, "VINTAGE": 1}
    assert sorted(summary["merchants_created"]) == [
        "farthinghoe-fine-wine", "mann-fine-wine", "turville-valley-wines", "wilkinson-vintners"]
    raws = [r["raw"] for r in conn.execute("SELECT raw FROM offer_reject").fetchall()]
    assert all(r["observation"]["raw"]["offersCount"] == 6 for r in raws)
    assert all(r["observation"]["raw"]["inputValue"] for r in raws)


SIZED = [{**r, "wineSearcherUrl": r["wineSearcherUrl"] + "?Xbottle_size=750"} for r in ROWS]


def _wine_id(conn, producer, cuvee):
    return str(conn.execute("SELECT wine_id FROM wine WHERE producer = %s AND cuvee = %s",
                            (producer, cuvee)).fetchone()["wine_id"])


@pg
def test_with_size_stated_the_rows_store_as_evidence_that_can_never_set_floor(conn):
    batch, _ = mrbridge.to_batch(SIZED)
    summary = importer.import_batch(conn, batch)
    assert (summary["written"], summary["rejected"]) == (3, 1)
    assert summary["rejected_by_reason"] == {"VINTAGE": 1}          # La Romanée, no vintage
    kinds = {r["merchant_id"]: (r["price_kind"], r["duty_status"], r["pack_size"])
             for r in conn.execute("SELECT merchant_id, price_kind, duty_status, pack_size FROM offer")}
    assert kinds["mann-fine-wine"] == ("ASK", "UNKNOWN", 1)
    assert kinds["farthinghoe-fine-wine"] == ("INDICATION", "UNKNOWN", 1)   # bottle-equivalent
    # nothing that cannot set Floor claims a capture, so nothing is masked
    assert conn.execute("SELECT count(*) AS n FROM snapshot_merchant").fetchone()["n"] == 0


@pg
def test_the_steer_shows_for_exactly_this_wine_vintage_and_size_from_any_merchant(conn):
    from datetime import datetime, timezone
    importer.import_batch(conn, mrbridge.to_batch(SIZED)[0])
    rousseau = _wine_id(conn, "Domaine Armand Rousseau", "Chambertin")
    leroy = _wine_id(conn, "Domaine Leroy", "Clos de Vougeot")
    when = datetime(2026, 11, 2, tzinfo=timezone.utc)
    s = mrbridge.steer(conn, wine_id=rousseau, vintage=2023, bottle_ml=750, as_of=when)
    assert (s["source"], s["merchant"], str(s["price_per_bottle"]), s["currency"],
            s["offers_count"], s["bottle_equivalent_of"]) == (
        "Wine-Searcher", "Mann Fine Wine", "1695.00", "GBP", 6, None)     # unapproved, still shown
    s = mrbridge.steer(conn, wine_id=leroy, vintage=2001, bottle_ml=750, as_of=when)
    assert (str(s["price_per_bottle"]), s["bottle_equivalent_of"]) == ("3333.33", 6)
    assert mrbridge.steer(conn, wine_id=rousseau, vintage=2022, bottle_ml=750, as_of=when) is None
    assert mrbridge.steer(conn, wine_id=rousseau, vintage=2023, bottle_ml=1500, as_of=when) is None
    stale = datetime(2026, 11, 20, tzinfo=timezone.utc)                  # > 14 days after the scrape
    assert mrbridge.steer(conn, wine_id=rousseau, vintage=2023, bottle_ml=750, as_of=stale) is None


@pg
def test_a_feed_row_that_cannot_count_never_hides_a_merchants_own_in_bond_price(conn):
    """Wine-Searcher's cheapest is sometimes a merchant we also collect directly.
    A feed capture used to supersede that merchant's capture of the same wine —
    Farr's own In Bond ask hidden behind a duty-unknown feed row, the Floor
    lifted to the next merchant. A capture now claims coverage only when it
    carries something that could set Floor."""
    from datetime import datetime, timedelta, timezone
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
    res = repo.resolve_offers(conn, wine_id=rousseau, vintage=2023,
                              as_of=datetime(2026, 11, 2, tzinfo=timezone.utc))
    farr = [o for o in res.offers if o.merchant_id == "farr"]
    assert [(o.duty_status, str(o.price)) for o in farr] == [(DutyStatus.IN_BOND, "1500.00")]


def test_the_post_script_chunks_and_never_needs_the_token_for_a_dry_run(monkeypatch, capsys):
    import runpy
    monkeypatch.delenv("MARKET_FEED_TOKEN", raising=False)
    script = runpy.run_path(str(ROOT / "scripts/post_mrbridge_batch.py"))
    assert [len(c) for c in script["chunks"](list(range(650)), 300)] == [300, 300, 50]
    lines = script["overview"](mrbridge.to_batch(ROWS)[0]["observations"])
    assert len(lines) == 4 and "Mann Fine Wine" in lines[2] and "size not stated" in lines[2]
