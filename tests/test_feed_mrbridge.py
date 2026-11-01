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
    assert mrbridge.split_name(_row("Liger")["wineName"], "Domaine du Comte Liger-Belair", None) == (
        "Domaine du Comte Liger-Belair", "la romanee")


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
    assert rousseau["raw"]["offersCount"] == 6                                      # context kept
    assert rousseau["observed_at"] == "2026-11-01T04:36:26.828Z"
    # Leroy: 3333.33 per 75cl from a 6-bottle listing — never multiplied back
    assert by_input["2001 Clos Vougeot, Leroy"]["price"] is None
    assert by_input["2001 Clos Vougeot, Leroy"]["pack_size"] == 6
    # La Romanée: a generic page, no vintage — kept as null, never guessed
    assert by_input["La Romanée Grand Cru Comte Liger-Belair"]["vintage"] is None


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
    """Identity is VESSEL's: three of the four resolve by exact key to the
    register; Liger-Belair does not ('Domaine du Comte Liger-Belair' is not
    the register's 'Comte Liger-Belair') and goes to the alias queue."""
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
    assert resolved["La Romanée Grand Cru Comte Liger-Belair"] is None


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
