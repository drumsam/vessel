"""The client want list, as identity rules and a listing-side gate
(decision 0038). House style as in test_traps.py: name the producer and
the confusion the rule prevents. Built from
docs/research/want-list-producer-rules.md, verbatim.

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    python -m pytest -q tests/test_want_list.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.identity.want_list import WANT_LIST_RULES, is_want_list_producer, match_want_list

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")
AS_OF = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _names(text):
    return {m.producer for m in match_want_list(text)}


# ---------------------------------------------------------------- DRC


def test_drc_matches_on_the_adjacent_pair_or_the_shorthand():
    assert _names("Domaine de la Romanée-Conti, Richebourg 2015") == \
        {"Domaine de la Romanée-Conti"}
    assert _names("DRC Echezeaux 2010") == {"Domaine de la Romanée-Conti"}


def test_a_cuvee_name_never_implies_drc():
    """Richebourg, Romanée-St-Vivant, Échézeaux, Corton and Montrachet are
    all made by others too — the cuvée alone must match nothing here."""
    for cuvee in ("Richebourg 2015", "Romanee-St-Vivant 2012", "Grands-Echezeaux 2011",
                 "Corton 2016", "Montrachet 2014"):
        assert match_want_list(cuvee) == [], cuvee


def test_la_romanee_is_liger_belairs_own_monopole_not_drc():
    """Comte Liger-Belair owns La Romanée; DRC has nothing to do with it.
    Decision 0043 adds Comte Liger-Belair to the want list itself, so this
    text now correctly matches THAT producer — the point of this test is
    DRC's own "liger" exclusion still holding, not that nothing matches."""
    assert _names("Comte Liger-Belair, La Romanée 2014") == {"Comte Liger-Belair"}
    # DRC is still refused even if "Romanée-Conti" is mistyped alongside "Liger".
    assert "Domaine de la Romanée-Conti" not in _names(
        "Romanee-Conti but really Liger-Belair's La Romanee")


# -------------------------------------------------------------- Leroy family


def test_a_bare_leroy_matches_but_always_goes_to_review():
    [m] = [m for m in match_want_list("Leroy Chambertin 2015") if m.producer == "Domaine Leroy"]
    assert m.always_review is True


def test_maison_leroy_is_excluded_outright():
    """The single most expensive confusion in Burgundy: a fraction of the
    price, and it must never be read as the domaine."""
    assert _names("Maison Leroy Bourgogne Rouge 2018") == set()


def test_auvenay_alongside_leroy_still_matches_auvenay_not_leroy():
    """'leroy' appearing alongside d'Auvenay is expected (same owner) and
    must not block the Auvenay match, and must not itself match Leroy."""
    names = _names("Domaine d'Auvenay (Lalou Bize-Leroy) Meursault Les Narvaux")
    assert names == {"Domaine d'Auvenay"}


def test_domaine_auvenay_matches_cleanly_with_no_mandatory_review():
    [m] = match_want_list("Domaine d'Auvenay Criots-Batard-Montrachet 2013")
    assert m.producer == "Domaine d'Auvenay"
    assert m.always_review is False


# --------------------------------------------------------------------- Bizot


def test_bizot_does_not_match_the_unrelated_coche_bizouard():
    assert _names("Jean-Yves Bizot Echezeaux 2017") == {"Domaine Jean-Yves Bizot"}
    assert _names("Coche-Bizouard Meursault 2019") == set()


# ------------------------------------------------------------------- Roumier


def test_georges_or_christophe_roumier_matches_a_bare_roumier_does_not():
    assert _names("Domaine Georges Roumier Bonnes-Mares 2016") == {"Domaine Georges Roumier"}
    assert _names("Christophe Roumier Musigny 2015") == {"Domaine Georges Roumier"}
    assert match_want_list("Roumier Bonnes-Mares 2016") == []


def test_herve_and_laurent_roumier_are_different_domaines():
    assert _names("Herve Roumier Chambolle-Musigny 2018") == set()
    assert _names("Laurent Roumier Chambolle-Musigny 2018") == set()


# -------------------------------------------------------------- Comtes Lafon


def test_comte_alone_does_not_identify_comtes_lafon():
    """Héritiers du Comte Lafon is the family's Mâcon estate — the
    exclusion list is required, not optional."""
    assert _names("Comtes Lafon Meursault Perrieres 2016") == {"Domaine des Comtes Lafon"}
    assert _names("Heritiers du Comte Lafon Macon 2018") == set()


def test_dominique_lafon_negoce_label_is_excluded():
    assert _names("Dominique Lafon Comte Bourgogne 2017") == set()


# --------------------------------------------------------------- Coche-Dury


def test_coche_alone_is_unpriceable_and_matches_nothing():
    assert match_want_list("Coche Meursault 2015") == []


def test_coche_dury_matches_fabien_coche_does_not():
    assert _names("Coche-Dury Corton-Charlemagne 2014") == {"Coche-Dury"}
    assert _names("Fabien Coche Meursault 2019") == set()


# -------------------------------------------------------------------- PYCM


def test_morey_is_not_used_as_a_standalone_token_so_marc_colin_does_not_match():
    """The exact trap named in the spec: without the exclusion, the
    adjacent pair alone would match "Marc Colin, Morey-St-Denis" because
    punctuation-stripping brings "colin" and "morey" together."""
    assert match_want_list("Marc Colin, Morey-St-Denis 2016") == []


def test_pycm_matches_by_full_name_initials_or_shorthand():
    assert _names("Pierre-Yves Colin-Morey Chassagne Caillerets 2015") == \
        {"Pierre-Yves Colin-Morey"}
    assert _names("PYCM Saint-Aubin 2018") == {"Pierre-Yves Colin-Morey"}


def test_the_other_colin_siblings_are_excluded():
    for name in ("Philippe Colin Chassagne 2017", "Bruno Colin Santenay 2018",
                 "Joseph Colin Chassagne 2016", "Simon Colin Saint-Aubin 2019",
                 "Colin-Deleger Chassagne 2010"):
        assert _names(name) == set(), name


# ---------------------------------------------------------------- Leflaive


def test_leflaive_matches_olivier_leflaive_is_excluded():
    assert _names("Domaine Leflaive Batard-Montrachet 2016") == {"Domaine Leflaive"}
    assert _names("Olivier Leflaive Puligny 1er Cru 2018") == set()


# --------------------------------------------------------------- Rousseau


def test_armand_rousseau_requires_both_tokens_a_bare_rousseau_goes_nowhere():
    assert _names("Domaine Armand Rousseau Chambertin 2015") == {"Domaine Armand Rousseau"}
    assert match_want_list("Rousseau Gevrey-Chambertin 2015") == []


# ============================================= decision 0043: the ten new rules


def test_comte_liger_belair_matches_thibault_liger_belair_is_excluded():
    """Two different people, two different estates: Comte Liger-Belair
    owns La Romanée (Vosne-Romanée); Thibault Liger-Belair is based in
    Nuits-St-Georges and makes Richebourg. Doug's own instruction: default
    to Comte on a bare match, but it still always goes to review."""
    [m] = [m for m in match_want_list("Liger-Belair La Romanee 2018")
          if m.producer == "Comte Liger-Belair"]
    assert m.always_review is True
    assert _names("Thibault Liger-Belair Richebourg 2018") == set()


def test_prieure_roch_requires_both_tokens_jacques_prieur_is_excluded():
    """Domaine Prieuré-Roch (Henry-Frédéric Roch) and Domaine Jacques
    Prieur are unrelated domaines — live in the WFS cellar's own data as
    a real Jacques Prieur Chambertin, so this collision is not
    hypothetical."""
    assert _names("Domaine Prieure-Roch Clos de Beze 2017") == {"Domaine Prieuré-Roch"}
    assert _names("Domaine Jacques Prieur Chambertin 2015") == set()
    assert match_want_list("Prieur Meursault 2018") == []


def test_dujac_matches_but_always_goes_to_review_fils_et_pere_is_excluded():
    """Same shape as Leroy/Maison Leroy: Dujac Fils & Père is the
    family's own négoce arm, materially cheaper."""
    [m] = [m for m in match_want_list("Dujac Clos de la Roche 2016")
          if m.producer == "Domaine Dujac"]
    assert m.always_review is True
    assert _names("Dujac Fils et Pere Bourgogne 2019") == set()


def test_arnaud_ente_requires_both_tokens_benoit_ente_is_excluded():
    """Brothers, separate domaines, separate prices."""
    assert _names("Arnaud Ente Meursault Les Petits Charrons 2017") == {"Arnaud Ente"}
    assert _names("Benoit Ente Meursault 2018") == set()
    assert match_want_list("Ente Meursault 2017") == []


def test_groffier_de_vogue_and_raveneau_match_on_their_own_name():
    assert _names("Domaine Robert Groffier Clos de Beze 2015") == {"Domaine Robert Groffier"}
    assert _names("Comte Georges de Vogue Musigny 2016") == {"Comte Georges de Vogüé"}
    assert _names("Francois Raveneau Chablis Les Clos 2018") == {"François Raveneau"}


def test_krug_jacques_selosse_and_dom_perignon_match_on_their_own_name():
    """Edition numbers (Krug), Plénitude release codes (Dom Pérignon) and
    disgorgement dates (Selosse) are all resolver/cuvée questions, not
    producer-matching ambiguities — this module only ever answers "which
    producer"."""
    assert _names("Krug Grande Cuvee 173eme Edition") == {"Krug"}
    assert _names("Krug Rose 24eme Edition") == {"Krug"}
    assert _names("Jacques Selosse Substance") == {"Jacques Selosse"}
    assert _names("Anselme Selosse Initial") == {"Jacques Selosse"}
    assert _names("Dom Perignon Vintage P2 2002") == {"Dom Pérignon"}


# ------------------------------------------------------- is_want_list_producer


def test_is_want_list_producer_is_an_exact_normalised_match_not_a_fuzzy_one():
    for canonical in ("Domaine Leroy", "domaine leroy", "DOMAINE LEROY",
                      "Domaine d'Auvenay", "Pierre-Yves Colin-Morey"):
        assert is_want_list_producer(canonical)
    for not_on_the_list in ("Maison Leroy", "Olivier Leflaive", "Marc Colin",
                            "Domaine Georges Mugneret-Gibourg"):
        assert not is_want_list_producer(not_on_the_list)


def test_there_are_exactly_twenty_rules():
    """Ten original (decision 0038) plus ten added by decision 0043."""
    assert len(WANT_LIST_RULES) == 20
    assert len({r.producer for r in WANT_LIST_RULES}) == 20


# ============================================================= Postgres: the gate


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


def _deal_with_line(conn, operator_id, *, producer, cuvee="Chambertin", quantity=6) -> tuple[str, str, str]:
    from app.db import repo as db

    wine = db.create_wine(conn, producer=producer, cuvee=cuvee, region="Burgundy",
                          colour="Red", lwin7=None)
    deal = db.create_deal(
        conn, {"name": "Want list test", "seller": None, "source_file": None,
              "currency": "GBP", "target_margin": None, "created_by": operator_id},
        [{"row_index": 0, "raw_description": f"{producer} {cuvee}", "raw_row": {"A": "x"},
          "quantity": quantity, "cost": None, "cost_currency": None,
          "target_margin": None, "target_discount": None, "manual_price": None}])
    [line] = db.deal_lines(conn, str(deal["deal_id"]))
    db.set_line_identity(conn, str(line["line_id"]), wine_id=str(wine["wine_id"]), vintage=2015,
                         bottle_ml=750, pack_size=1, flags=[], source="operator",
                         approved_by=operator_id)
    return str(deal["deal_id"]), str(line["line_id"]), str(wine["wine_id"])


def _seed_run_and_price(conn, line_id, *, comps: list[Decimal]) -> None:
    """Two merchants agreeing — READY, nothing pricing-side to gate on, so
    only the want-list check (if any) stands between this line and export."""
    prices = sorted(comps)
    floor, reference = prices[0], (prices[0] if len(prices) == 1 else prices[1])
    median = prices[len(prices) // 2]
    run = conn.execute(
        """INSERT INTO benchmark_run (line_id, as_of, uk_floor, uk_reference, uk_median,
                                      comp_count, flags, state)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (line_id, AS_OF, floor, reference, median, len(prices), [], "READY")).fetchone()
    for i, price in enumerate(prices):
        snapshot = {"offer_id": f"merchant-{i}:x", "merchant_id": f"merchant-{i}",
                   "merchant": f"Merchant {i}", "merchant_offer_id": f"mo-{i}",
                   "vintage": 2015, "bottle_ml": 750, "pack_size": 1, "price": str(price),
                   "currency": "GBP", "duty_status": "IB", "price_kind": "ASK",
                   "is_buyable": True, "offered_units": None, "stock_type": "WAREHOUSE",
                   "stock_type_basis": "confirmed", "condition_flags": [],
                   "condition_notes": None, "source_url": None, "captured_at": AS_OF.isoformat()}
        conn.execute(
            """INSERT INTO benchmark_comp (run_id, offer_pk, role, reject_reason, offer_snapshot)
               VALUES (%s, NULL, 'merchant_best', NULL, %s)""",
            (run["run_id"], psycopg.types.json.Jsonb(snapshot)))
    from app.db import repo as db
    db.save_pricing(conn, line_id=line_id, run=run, priced=_priced_line(reference),
                    priced_by=_operator(conn), cost=None, cost_currency=None, fx_rate=None)


def _priced_line(reference: Decimal):
    from app.pricing.pricer import price_line
    return price_line(uk_reference=reference, cost=None, cost_currency=None)


@pg
def test_create_wine_sets_want_list_from_the_producer_alone(conn):
    from app.db import repo as db

    leroy = db.create_wine(conn, producer="Domaine Leroy", cuvee="Chambertin",
                           region="Burgundy", colour="Red", lwin7=None)
    assert leroy["want_list"] is True
    maison = db.create_wine(conn, producer="Maison Leroy", cuvee="Bourgogne Rouge",
                            region="Burgundy", colour="Red", lwin7=None)
    assert maison["want_list"] is False


@pg
def test_acknowledge_want_list_refuses_a_non_want_list_line(conn):
    from app.db import repo as db

    operator_id = _operator(conn)
    _, line_id, _ = _deal_with_line(conn, operator_id, producer="Domaine Not-On-The-List")
    with pytest.raises(db.Conflict):
        db.acknowledge_want_list(conn, line_id, acknowledged_by=operator_id)


@pg
def test_acknowledge_want_list_is_tied_to_the_line_not_a_pricing_run(conn):
    """"ONCE even when identity resolves cleanly and even when two
    merchants agree" -- acknowledging survives a reprice because it is
    not stored on pricing_result at all."""
    from app.db import repo as db

    operator_id = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, operator_id, producer="Domaine Leroy")
    acked = db.acknowledge_want_list(conn, line_id, acknowledged_by=operator_id)
    assert str(acked["want_list_ack_by"]) == operator_id
    assert acked["want_list_ack_at"] is not None

    _seed_run_and_price(conn, line_id, comps=[Decimal("1000.00"), Decimal("1050.00")])
    still = db.get_line(conn, line_id)
    assert still["want_list_ack_at"] is not None   # unchanged by the reprice


@pg
def test_a_want_list_line_cannot_be_issued_unacknowledged_even_when_ready(conn):
    """Two merchants agreeing is not enough on this list -- the exact
    asymmetry Doug named: Leroy is confused with Maison Leroy at a
    5-20x error. The refusal names the wine, never a UUID or a flag."""
    from app.db import repo as db

    operator_id = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, operator_id, producer="Domaine Leroy",
                                          cuvee="Chambertin")
    _seed_run_and_price(conn, line_id, comps=[Decimal("1000.00"), Decimal("1050.00")])
    assert db.latest_pricing(conn, line_id)["requires_acknowledgement"] is False  # READY

    # LineNotReady is raised internally by _offer_line and collected by
    # create_buyer_offer into a single, batched Conflict (decision 0037) —
    # that outer Conflict is what a caller of create_buyer_offer sees.
    with pytest.raises(db.Conflict) as exc:
        db.create_buyer_offer(conn, deal_id=deal_id, client="A Merchant", currency="GBP",
                              terms=None, issued_by=operator_id, asks=[{"line_id": line_id}])
    assert "Domaine Leroy" in str(exc.value) or "Chambertin" in str(exc.value)
    assert "want list" in str(exc.value)
    assert line_id not in str(exc.value)

    db.acknowledge_want_list(conn, line_id, acknowledged_by=operator_id)
    offer = db.create_buyer_offer(conn, deal_id=deal_id, client="A Merchant", currency="GBP",
                                  terms=None, issued_by=operator_id, asks=[{"line_id": line_id}])
    assert offer["buyer_offer_id"]


@pg
def test_the_shared_offer_link_gates_on_the_want_list_too(conn):
    """Decision 0037 made the share link the ONE route to a buyer -- the
    want-list gate has to live there, not only in the legacy
    create_buyer_offer path this link was built to replace."""
    from app.db import repo as db
    from app.offerlink import repo as link_repo

    operator_id = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, operator_id, producer="Domaine d'Auvenay",
                                          cuvee="Meursault Les Narvaux")
    _seed_run_and_price(conn, line_id, comps=[Decimal("2000.00"), Decimal("2100.00")])

    with pytest.raises(link_repo.LineNotSendable) as exc:
        link_repo.create_link(conn, deal_id=deal_id, line_ids=[line_id], kind="buyer",
                              fx_rate=None, created_by=operator_id)
    assert "want list" in str(exc.value)
    assert line_id not in str(exc.value)

    db.acknowledge_want_list(conn, line_id, acknowledged_by=operator_id)
    link = link_repo.create_link(conn, deal_id=deal_id, line_ids=[line_id], kind="buyer",
                                 fx_rate=None, created_by=operator_id)
    assert link["token"]
