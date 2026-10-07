"""Operator-entered auction evidence: the pure derivation (offline) and the
machinery (Postgres). Spec: docs/research/auction-evidence-form-spec.md.
Decision 0024.

House style as in test_traps.py and test_vessel.py: name the rule and the
size of the error the test prevents.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.auction import evidence as engine

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


# ================================================================ offline: engine


def test_inclusive_price_without_rate_is_refused():
    """A 25% premium read as hammer is a 25% error; the CHECK this mirrors
    in Python prevents it before any database round trip."""
    with pytest.raises(engine.InvalidAuctionEvidence):
        engine.derive_hammer_gbp(amount=Decimal("1000"), currency="GBP",
                                 amount_basis="BUYER_PREMIUM_INCLUSIVE",
                                 premium_rate=None, fx_rate=None)


def test_inclusive_price_with_rate_divides_it_out():
    """£1,250 including a 25% premium is a £1,000 hammer — the one
    documented rounding point here, half-even to the penny."""
    hammer = engine.derive_hammer_gbp(amount=Decimal("1250.00"), currency="GBP",
                                      amount_basis="BUYER_PREMIUM_INCLUSIVE",
                                      premium_rate=Decimal("0.25"), fx_rate=None)
    assert hammer == Decimal("1000.00")


def test_non_gbp_without_fx_rate_is_absent_not_estimated():
    """No FX source for the date -> store nothing converted, never a guess."""
    hammer_gbp = engine.derive_hammer_gbp(amount=Decimal("1000"), currency="USD",
                                          amount_basis="HAMMER", premium_rate=None,
                                          fx_rate=None)
    assert hammer_gbp is None


def test_non_gbp_with_fx_rate_converts():
    hammer_gbp = engine.derive_hammer_gbp(amount=Decimal("1000"), currency="USD",
                                          amount_basis="HAMMER", premium_rate=None,
                                          fx_rate=Decimal("0.79"))
    assert hammer_gbp == Decimal("790.00")


def test_per_bottle_hammer_is_a_read_time_figure_only():
    """A 6-bottle lot at £3,000 hammer shows as £500/btl — this function's
    only caller is a display path; nothing stores its result."""
    assert engine.per_bottle_hammer_gbp(Decimal("3000.00"), 6) == Decimal("500.00")


def test_auction_below_reference_is_not_a_review_flag():
    """REVIEW_FLAGS, the single definition of what forces review, is
    untouched by this module — AUCTION_BELOW_REFERENCE is a different,
    informational flag that this file owns, not app.core.flags."""
    from app.core.flags import REVIEW_FLAGS
    assert engine.AUCTION_BELOW_REFERENCE not in REVIEW_FLAGS
    assert "AUCTION_BELOW_REFERENCE" not in {f.value for f in REVIEW_FLAGS}


def test_auction_health_flags_a_median_well_below_the_uk_reference():
    lots = [
        {"hammer_gbp": Decimal("400.00"), "bottles_in_lot": 1,
         "sale_date": date(2026, 1, 1), "source_url": "https://example.com/a"},
        {"hammer_gbp": Decimal("420.00"), "bottles_in_lot": 1,
         "sale_date": date(2026, 2, 1), "source_url": "https://example.com/b"},
    ]
    health = engine.auction_health(lots, uk_reference_per_bottle=Decimal("600.00"))
    assert health.lot_count == 2
    assert health.median_per_bottle_gbp == Decimal("410.00")
    assert health.flag == engine.AUCTION_BELOW_REFERENCE
    assert health.note is None


def test_auction_health_with_no_uk_reference_says_so_plainly():
    """"No UK market. Auction evidence is not a price." — shown even when
    there are lots, and even when there are none."""
    no_lots = engine.auction_health([], uk_reference_per_bottle=None)
    assert no_lots.note == "No UK market. Auction evidence is not a price."
    assert no_lots.flag is None

    with_lots = engine.auction_health(
        [{"hammer_gbp": Decimal("400.00"), "bottles_in_lot": 1,
          "sale_date": date(2026, 1, 1), "source_url": "https://example.com/a"}],
        uk_reference_per_bottle=None)
    assert with_lots.note == "No UK market. Auction evidence is not a price."
    assert with_lots.flag is None


def test_auction_health_counts_an_fx_unavailable_lot_without_pricing_it():
    """A lot with no FX rate is still real evidence (lot_count includes it)
    but cannot contribute to the median."""
    lots = [
        {"hammer_gbp": Decimal("500.00"), "bottles_in_lot": 1,
         "sale_date": date(2026, 1, 1), "source_url": "https://example.com/a"},
        {"hammer_gbp": None, "bottles_in_lot": 1,
         "sale_date": date(2026, 1, 2), "source_url": "https://example.com/b"},
    ]
    health = engine.auction_health(lots, uk_reference_per_bottle=Decimal("500.00"))
    assert health.lot_count == 2
    assert health.median_per_bottle_gbp == Decimal("500.00")


def test_auction_evidence_never_reaches_benchmark():
    """Static check: nothing under app/core/ or app/pricing/ imports
    app.auction. A health check must never be one import away from a price."""
    for root in (ROOT / "app" / "core", ROOT / "app" / "pricing"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [n.name for n in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                else:
                    continue
                assert not any(n and n.startswith("app.auction") for n in names), (
                    f"{path} imports app.auction — a health check must never reach the core")


# ============================================================= Postgres: repo


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


def _wine(conn) -> str:
    from app.db import repo as db
    wine = db.create_wine(conn, producer="Domaine Test", cuvee="Test Wine",
                          region="Burgundy", colour="Red", lwin7=None)
    return str(wine["wine_id"])


def _lot(conn, operator_id, wine_id, **kwargs):
    from app.auction import repo as auction_repo
    defaults = dict(
        wine_id=wine_id, vintage=2015, bottle_ml=750, bottles_in_lot=6,
        auction_house="BONHAMS", sale_date=date(2026, 1, 1), lot_ref="Lot 1",
        source_url="https://bonhams.com/lot/1", currency="GBP", amount=Decimal("3000.00"),
        amount_basis="HAMMER", entered_by=operator_id)
    defaults.update(kwargs)
    return auction_repo.record_auction_evidence(conn, **defaults)


@pg
def test_auction_evidence_requires_source_url(conn):
    """Insert without a URL fails at the database, not only in the form —
    the CHECK is the one that cannot be bypassed by a future code path."""
    operator_id = _operator(conn)
    wine_id = _wine(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """INSERT INTO auction_evidence
                   (wine_id, vintage, bottle_ml, bottles_in_lot, auction_house, sale_date,
                    lot_ref, source_url, currency, amount, amount_basis, entered_by)
               VALUES (%s, 2015, 750, 6, 'BONHAMS', %s, 'Lot 1', 'not-a-url', 'GBP', 1000.00,
                       'HAMMER', %s)""",
            (wine_id, date(2026, 1, 1), operator_id))


@pg
def test_inclusive_price_without_rate_is_refused_at_the_database(conn):
    """The Python guard (tested offline) refuses this first; the CHECK is
    the backstop for any path that bypasses record_auction_evidence."""
    operator_id = _operator(conn)
    wine_id = _wine(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """INSERT INTO auction_evidence
                   (wine_id, vintage, bottle_ml, bottles_in_lot, auction_house, sale_date,
                    lot_ref, source_url, currency, amount, amount_basis, entered_by)
               VALUES (%s, 2015, 750, 6, 'BONHAMS', %s, 'Lot 1', 'https://bonhams.com/1',
                       'GBP', 1000.00, 'BUYER_PREMIUM_INCLUSIVE', %s)""",
            (wine_id, date(2026, 1, 1), operator_id))


@pg
def test_mixed_lot_is_quarantined(conn):
    """The generated column is true, and the health check ignores it."""
    from app.auction import repo as auction_repo

    operator_id = _operator(conn)
    wine_id = _wine(conn)
    row = _lot(conn, operator_id, wine_id, is_mixed_lot=True)
    assert row["quarantined"] is True

    cutoff = date(2020, 1, 1)
    lots = conn.execute(
        """SELECT * FROM auction_evidence WHERE wine_id = %s AND NOT quarantined
             AND sale_date >= %s""", (wine_id, cutoff)).fetchall()
    assert lots == []


@pg
def test_per_bottle_figure_is_not_persisted_or_exported(conn):
    """No per-bottle column exists on the table at all — the API response
    shape is the export surface, and it has no field for one either."""
    operator_id = _operator(conn)
    wine_id = _wine(conn)
    row = _lot(conn, operator_id, wine_id)
    assert "per_bottle_hammer_gbp" not in row
    assert set(row.keys()) <= {
        "auction_evidence_id", "wine_id", "vintage", "bottle_ml", "bottles_in_lot",
        "auction_house", "sale_date", "lot_ref", "source_url", "currency", "amount",
        "amount_basis", "premium_rate", "hammer_gbp", "fx_rate", "fx_source",
        "is_mixed_lot", "condition_notes", "condition_flagged", "quarantined",
        "entered_by", "entered_at", "retracted_at", "retracted_by", "retraction_reason"}


@pg
def test_retracted_evidence_is_ignored_but_kept(conn):
    from app.auction import repo as auction_repo

    operator_id = _operator(conn)
    wine_id = _wine(conn)
    row = _lot(conn, operator_id, wine_id)

    retracted = auction_repo.retract_auction_evidence(
        conn, str(row["auction_evidence_id"]), retracted_by=operator_id,
        reason="wrong lot entirely")
    assert retracted["retracted_at"] is not None
    assert str(retracted["retracted_by"]) == operator_id
    assert retracted["retraction_reason"] == "wrong lot entirely"

    live = auction_repo.evidence_for_wine(conn, wine_id, 2015, 750)
    assert live == []
    everything = auction_repo.evidence_for_wine(conn, wine_id, 2015, 750, include_retracted=True)
    assert len(everything) == 1

    # Retracted, not deleted, not editable again.
    with pytest.raises(LookupError):
        auction_repo.retract_auction_evidence(conn, str(row["auction_evidence_id"]),
                                              retracted_by=operator_id, reason="again")
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE auction_evidence SET lot_ref = 'changed' WHERE auction_evidence_id = %s",
                     (row["auction_evidence_id"],))


@pg
def test_house_not_in_allowed_list_is_refused(conn):
    """SOTHEBYS is rejected in Python, with the decision this is governed by
    named in the error, before any INSERT is attempted."""
    from app.auction.evidence import InvalidAuctionEvidence
    operator_id = _operator(conn)
    wine_id = _wine(conn)
    with pytest.raises(InvalidAuctionEvidence, match="0024"):
        _lot(conn, operator_id, wine_id, auction_house="SOTHEBYS")

    # And the database agrees, for any path that skips the Python guard.
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """INSERT INTO auction_evidence
                   (wine_id, vintage, bottle_ml, bottles_in_lot, auction_house, sale_date,
                    lot_ref, source_url, currency, amount, amount_basis, entered_by)
               VALUES (%s, 2015, 750, 6, 'SOTHEBYS', %s, 'Lot 1', 'https://sothebys.com/1',
                       'GBP', 1000.00, 'HAMMER', %s)""",
            (wine_id, date(2026, 1, 1), operator_id))


@pg
def test_heritage_and_zachys_are_allowed_hand_entry_only(conn):
    """Decision 0024: added over their own personal/non-commercial terms, on
    Doug's explicit instruction. This proves they are allowed in the one
    mechanism that exists — hand entry — and nothing else; there is no
    scraper anywhere in this codebase for either house."""
    operator_id = _operator(conn)
    wine_id = _wine(conn)
    for house in ("HERITAGE", "ZACHYS"):
        row = _lot(conn, operator_id, wine_id, auction_house=house,
                  source_url=f"https://{house.lower()}.com/lot/1")
        assert row["auction_house"] == house


@pg
def test_line_auction_health_reads_from_the_lines_own_identity(conn):
    """wine_id/vintage/bottle_ml come from the seller_line's approved
    identity, never re-typed — matching a lot entered against the wine, the
    vintage and the bottle size the line was actually approved as."""
    from app.auction import repo as auction_repo
    from app.db import repo as db

    operator_id = _operator(conn)
    wine = db.create_wine(conn, producer="Domaine Test", cuvee="Test Wine",
                          region="Burgundy", colour="Red", lwin7=None)
    deal = db.create_deal(
        conn, {"name": "Test cellar", "seller": None, "source_file": None, "currency": "GBP",
              "target_margin": None, "created_by": operator_id},
        [{"row_index": 0, "raw_description": "line 0", "raw_row": {"A": "x"},
          "quantity": 6, "cost": None, "cost_currency": None, "target_margin": None,
          "target_discount": None, "manual_price": None}])
    [line] = db.deal_lines(conn, str(deal["deal_id"]))
    db.set_line_identity(conn, str(line["line_id"]), wine_id=str(wine["wine_id"]), vintage=2015,
                         bottle_ml=750, pack_size=1, flags=[], source="operator",
                         approved_by=operator_id)

    _lot(conn, operator_id, str(wine["wine_id"]), vintage=2015, bottle_ml=750,
        amount=Decimal("3000.00"), bottles_in_lot=6)

    health = auction_repo.line_auction_health(conn, str(line["line_id"]),
                                               uk_reference_per_bottle=Decimal("600.00"))
    assert health.lot_count == 1
    assert health.median_per_bottle_gbp == Decimal("500.00")   # £3,000 / 6 bottles

    with pytest.raises(LookupError):
        auction_repo.line_auction_health(conn, "00000000-0000-0000-0000-000000000000")
