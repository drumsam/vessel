"""VESSEL Private Sale: the pricing rules (pure) and the machinery (Postgres).

Offline tests (no marker) always run. Tests marked `pg` need a disposable
Postgres, same convention as tests/test_service.py:

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    python -m pytest -q tests/test_vessel.py

House style as in test_traps.py: name the rule and the size of the error the
test prevents.
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

from app.vessel import engine

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

AS_OF = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


# ================================================================ offline: engine
#
# Pure functions, no clock, no network, no database — the arithmetic the
# whole machinery leans on.


def test_price_listing_matches_the_published_mockup():
    """Rousseau Clos St Jacques 2010, 6 bottles: market HK$84,000, a 17%
    discount within NORMAL. VESSEL price rounds to HK$69,500 — not
    HK$69,473 — and the seller net is exactly 92% of THAT clean figure, not
    of the raw 84,000: HK$63,940, matching v3/v4's own worked example."""
    p = engine.price_listing(Decimal("84000"), band="NORMAL", currency="HKD",
                             discount=Decimal("0.17"))
    assert p.vessel_price == Decimal("69500")
    assert p.seller_net == Decimal("63940.00")


def test_seller_net_is_eight_percent_below_vessel_price():
    for market, band, discount in [("1000", "STRONG", "0.10"), ("50000", "NORMAL", "0.18"),
                                   ("777", "CLEARANCE", "0.30")]:
        p = engine.price_listing(Decimal(market), band=band, currency="GBP",
                                 discount=Decimal(discount))
        assert p.seller_net == (p.vessel_price * Decimal("0.92")).quantize(Decimal("0.01"))


def test_round_to_clean_figure_nearest_not_down():
    """v3 said 'rounded down'; v4 and the brief just say 'a clean figure'.
    Always-down would favour VESSEL over the seller for no stated reason, so
    this is nearest, half-even — not floor."""
    assert engine.round_to_clean_figure(Decimal("69473"), "HKD") == Decimal("69500")
    assert engine.round_to_clean_figure(Decimal("69249"), "HKD") == Decimal("69000")
    assert engine.round_to_clean_figure(Decimal("432"), "GBP") == Decimal("450")
    assert engine.round_to_clean_figure(Decimal("424"), "GBP") == Decimal("400")


@pytest.mark.parametrize("band,discount,ok", [
    ("STRONG", "0.10", True), ("STRONG", "0.149", True), ("STRONG", "0.15", False),
    ("NORMAL", "0.15", True), ("NORMAL", "0.199", True), ("NORMAL", "0.20", False),
    ("CLEARANCE", "0.20", True), ("CLEARANCE", "0.40", True), ("CLEARANCE", "0.19", False),
])
def test_resolve_discount_enforces_its_own_band(band, discount, ok):
    if ok:
        assert engine.resolve_discount(band, Decimal(discount)) == Decimal(discount)
    else:
        with pytest.raises(engine.CannotList):
            engine.resolve_discount(band, Decimal(discount))


def test_no_percentage_claim_on_single_source_listing():
    """One offer, sanity check passed: an indicative reference and NO
    percentage claim — the percentage is the strongest thing VESSEL says,
    and it only appears when two independent merchants agree."""
    claim = engine.evidence_claim(1, vintage_band_passed=True,
                                  market_reference=Decimal("84000"),
                                  vessel_price=Decimal("69500"))
    assert claim.can_list is True
    assert claim.reference_label == "Indicative reference"
    assert claim.percentage_claim_pct is None


def test_single_source_failing_vintage_band_cannot_be_listed():
    """Bordeaux Index listed 2020 Mugneret-Gibourg Vosne-Romanee at £2,070 a
    case against Lea & Sandeman's £1,200 - a 72% error (0015's own worked
    case). One source, no sanity check behind it: not listed, at any price."""
    claim = engine.evidence_claim(1, vintage_band_passed=False)
    assert claim.can_list is False
    assert "thin evidence" in claim.reason

    zero = engine.evidence_claim(0, vintage_band_passed=False)
    assert zero.can_list is False and "no market" in zero.reason

    two = engine.evidence_claim(2, vintage_band_passed=False,
                               market_reference=Decimal("1000"), vessel_price=Decimal("800"))
    assert two.can_list is True and two.percentage_claim_pct == Decimal("0.2000")


def test_hk_retail_single_source_is_refused_with_no_sanity_check():
    """No HK-equivalent of the UK vintage-band check exists yet, so a single
    Hong Kong retail source never lists, no matter how it would have fared
    against a band — refusing rather than guessing (0020 revision)."""
    claim = engine.evidence_claim(1, vintage_band_passed=True, market="HK_RETAIL")
    assert claim.can_list is False
    assert "HK_RETAIL" not in claim.reason   # names it in English, not the enum
    assert "Hong Kong retail" in claim.reason


def test_hk_retail_two_sources_names_the_market():
    """"34% below the best Hong Kong retail offer we can find" — the page
    claim the request asked for, composed once, server-side."""
    claim = engine.evidence_claim(2, vintage_band_passed=False, market="HK_RETAIL",
                                  market_reference=Decimal("100000"),
                                  vessel_price=Decimal("66000"))
    assert claim.can_list is True
    assert claim.reference_label == "Hong Kong retail reference"
    assert claim.percentage_claim_pct == Decimal("0.3400")
    assert (engine.market_claim_sentence("HK_RETAIL", claim.percentage_claim_pct)
            == "34% below the best Hong Kong retail offer we can find")


def test_uk_in_bond_label_and_claim_are_unchanged_by_naming_the_market():
    """Naming the market does not reword what UK In Bond already said —
    every listing built before this revision used exactly this text."""
    assert engine.reference_label("UK_IN_BOND", 2) == "Market reference"
    assert engine.reference_label("UK_IN_BOND", 1) == "Indicative reference"
    assert (engine.market_claim_sentence("UK_IN_BOND", Decimal("0.1700"))
            == "17% below the best UK In Bond offer we can find")
    assert engine.market_claim_sentence("UK_IN_BOND", None) is None


def test_listing_below_minimum_value_is_refused():
    """GBP 400 equivalent, configurable. A GBP 350 listing fails the default;
    a HKD listing below the GBP-equivalent threshold fails through the FX
    rate, not a hardcoded HKD number."""
    assert engine.meets_minimum_value(Decimal("500"), "GBP", None) is True
    assert engine.meets_minimum_value(Decimal("350"), "GBP", None) is False
    assert engine.meets_minimum_value(Decimal("350"), "GBP", None, minimum_gbp=Decimal("300")) is True
    # HKD 3,000 at 9.7 HKD/GBP is about GBP 309 - above 300, below the 400 default.
    assert engine.meets_minimum_value(Decimal("3000"), "HKD", Decimal("9.7")) is False
    assert engine.meets_minimum_value(Decimal("3000"), "HKD", Decimal("9.7"),
                                      minimum_gbp=Decimal("300")) is True


def test_hold_duration_is_thirty_minutes_under_fifty_thousand_hkd():
    assert engine.hold_duration(Decimal("49999"), "HKD", None) == timedelta(minutes=30)
    assert engine.hold_duration(Decimal("50000"), "HKD", None) == timedelta(hours=2)
    # A GBP listing is converted through its own fx_hkd_per_gbp before the threshold
    # is applied - never a separate, unstated GBP threshold. GBP 5,200 at 9.7
    # is HK$50,440; GBP 4,000 is HK$38,800.
    assert engine.hold_duration(Decimal("5200"), "GBP", Decimal("9.7")) == timedelta(hours=2)
    assert engine.hold_duration(Decimal("4000"), "GBP", Decimal("9.7")) == timedelta(minutes=30)


# ================================================================== Postgres
#
# The machinery: concurrency, immutability, state, and the evidence rule as
# the database itself enforces it.


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


def _deal_with_lines(conn, operator_id, specs: list[dict]) -> tuple[str, list[str], list[str]]:
    """One deal, one approved-identity seller_line per spec.
    Returns (deal_id, [line_id, ...], [wine_id, ...]), in spec order."""
    from app.db import repo as db

    wines = [db.create_wine(conn, producer=sp.get("producer", "Domaine Test"),
                            cuvee=sp.get("cuvee", "Test Wine"), region=sp.get("region", "Burgundy"),
                            colour=sp.get("colour", "Red"), lwin7=None)
             for sp in specs]
    deal = db.create_deal(
        conn, {"name": "Test cellar", "seller": None, "source_file": None,
              "currency": "GBP", "target_margin": None, "created_by": operator_id},
        [{"row_index": i, "raw_description": f"line {i}", "raw_row": {"A": "x"},
          "quantity": sp.get("quantity", 6), "cost": None, "cost_currency": None,
          "target_margin": None, "target_discount": None, "manual_price": None}
         for i, sp in enumerate(specs)])
    lines = db.deal_lines(conn, str(deal["deal_id"]))
    for line, wine, sp in zip(lines, wines, specs):
        db.set_line_identity(conn, str(line["line_id"]), wine_id=str(wine["wine_id"]),
                             vintage=sp.get("vintage", 2015), bottle_ml=sp.get("bottle_ml", 750),
                             pack_size=sp.get("pack_size", 1), flags=[], source="operator",
                             approved_by=operator_id)
    return (str(deal["deal_id"]), [str(l["line_id"]) for l in lines],
           [str(w["wine_id"]) for w in wines])


def _deal_with_line(conn, operator_id, **spec) -> tuple[str, str, str]:
    """The single-line case of _deal_with_lines, for tests that only need one."""
    deal_id, line_ids, wine_ids = _deal_with_lines(conn, operator_id, [spec])
    return deal_id, line_ids[0], wine_ids[0]


def _seed_run(conn, line_id, *, uk_reference, comp_count, state="READY",
             band_low=None, band_high=None, as_of=AS_OF) -> str:
    """A plausible benchmark_run + vintage_band_check, written directly:
    VESSEL only ever reads these two tables, so the rest of the benchmark
    machinery (offers, merchants, snapshots) is out of scope for these tests
    and is exercised elsewhere, in tests/test_service.py."""
    run = conn.execute(
        """INSERT INTO benchmark_run (line_id, as_of, uk_floor, uk_reference, uk_median,
                                      comp_count, state)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING run_id""",
        (line_id, as_of, uk_reference, uk_reference, uk_reference, comp_count, state),
    ).fetchone()
    conn.execute(
        """INSERT INTO vintage_band_check (run_id, unit, band_low, band_high, tiers_available)
           VALUES (%s, %s, %s, %s, %s)""",
        (run["run_id"], "1x750", band_low, band_high, band_low is not None))
    return str(run["run_id"])


def _priced_listing(conn, *, source_count=3, uk_reference=Decimal("1443.30"), quantity=6,
                    band_low=Decimal("1200"), band_high=Decimal("1600"),
                    producer="Domaine Test") -> dict:
    """RECOMMENDED, in HKD at a NORMAL-band 17% discount. uk_reference is per
    bottle, GBP, as the benchmark always stores it; the default (times 6
    bottles, times the 9.7 fx_hkd_per_gbp below) lands the lot at the published
    mockup's own HK$84,000 — a coincidence worth keeping, not relied on by
    anything that reads this fixture."""
    from app.vessel import repo as vrepo

    operator_id = _operator(conn)
    deal_id, line_id, wine_id = _deal_with_line(conn, operator_id, quantity=quantity,
                                                producer=producer)
    _seed_run(conn, line_id, uk_reference=uk_reference, comp_count=source_count,
             band_low=band_low, band_high=band_high)
    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="HKD", fx_hkd_per_gbp=Decimal("9.7"), fx_source="XE",
        fx_rate_date=AS_OF.date(), stock_location="HK_BOND",
        line_choices={line_id: {"band": "NORMAL", "discount": Decimal("0.17")}})
    assert not excluded, excluded
    return listings[0]


def _listed_listing(conn, **kwargs) -> dict:
    """APPROVED, then LISTED in a drop — the state BUY requires."""
    from app.vessel import repo as vrepo

    listing = _priced_listing(conn, **kwargs)
    operator_id = _operator(conn)
    mandate = vrepo.approve_mandate(conn, listing["deal_id"], move_line_ids=[listing["line_id"]],
                                    keep_line_ids=[], approved_by_name="A Seller", as_of=AS_OF)
    drop = vrepo.create_drop(conn, label="Drop one", drop_date=AS_OF.date(),
                             created_by=operator_id)
    vrepo.add_to_drop(conn, str(drop["drop_id"]), [str(listing["listing_id"])], as_of=AS_OF)
    return vrepo.get_listing(conn, str(listing["listing_id"]))


@pg
def test_one_live_reservation_per_listing(conn):
    """Two concurrent BUYs on the same listing: the partial unique index
    decides, not application logic. A second psycopg connection stands in
    for the second buyer's own request."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    first = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com",
                                  as_of=AS_OF)
    assert first["state"] == "HELD"

    with psycopg.connect(TEST_DB, row_factory=dict_row, autocommit=True) as conn2:
        with pytest.raises(vrepo.AlreadyReserved):
            vrepo.reserve_listing(conn2, str(listing["listing_id"]), buyer_contact="b@x.com",
                                  as_of=AS_OF)

    # Exactly one HELD reservation exists, and the listing shows RESERVED, not
    # some half-applied state from the losing attempt.
    held = conn.execute(
        "SELECT count(*) AS n FROM vessel_reservation WHERE listing_id = %s AND state = 'HELD'",
        (listing["listing_id"],)).fetchone()["n"]
    assert held == 1
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "RESERVED"


@pg
def test_reservation_timeout_returns_listing_to_pool(conn):
    """as_of is an argument, never the clock: the timeout is tested without
    waiting for one."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    reservation = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com",
                                        as_of=AS_OF)
    still_live = vrepo.expire_overdue_reservations(conn, as_of=AS_OF + timedelta(minutes=10))
    assert still_live == []
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "RESERVED"

    expired = vrepo.expire_overdue_reservations(conn, as_of=AS_OF + timedelta(hours=3))
    assert expired == [str(reservation["reservation_id"])]
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "LISTED"
    assert conn.execute(
        "SELECT state FROM vessel_reservation WHERE reservation_id = %s",
        (reservation["reservation_id"],)).fetchone()["state"] == "EXPIRED"

    # And a fresh BUY can now take it - the pool, not a dead end.
    second = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="c@x.com",
                                   as_of=AS_OF + timedelta(hours=3))
    assert second["state"] == "HELD"


@pg
def test_proof_of_payment_extends_hold(conn):
    """Nobody loses a wine to reconciliation lag: submitting proof moves the
    deadline forward, automatically, by exactly one fixed 2-hour extension —
    never the original hold_duration() again."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    reservation = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com",
                                        as_of=AS_OF)
    original_deadline = reservation["expires_at"]

    submitted_at = AS_OF + timedelta(minutes=25)
    extended = vrepo.submit_proof_of_payment(conn, str(reservation["reservation_id"]),
                                             as_of=submitted_at)
    assert extended["expires_at"] == submitted_at + engine.PROOF_OF_PAYMENT_EXTENSION
    assert extended["expires_at"] > original_deadline
    assert extended["proof_submitted_at"] is not None

    # The old deadline has already passed; without the extension this would
    # have expired.
    assert vrepo.expire_overdue_reservations(conn, as_of=original_deadline + timedelta(seconds=1)) == []
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "RESERVED"


@pg
def test_proof_of_payment_extension_is_capped_at_one(conn):
    """Capped in code: a reservation that already used its one extension
    cannot be granted a second — an operator resolves it from here, never
    another timer."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    reservation = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com",
                                        as_of=AS_OF)
    vrepo.submit_proof_of_payment(conn, str(reservation["reservation_id"]),
                                  as_of=AS_OF + timedelta(minutes=25))

    with pytest.raises(vrepo.AlreadyExtended):
        vrepo.submit_proof_of_payment(conn, str(reservation["reservation_id"]),
                                      as_of=AS_OF + timedelta(minutes=40))


@pg
def test_expire_overdue_skips_a_reservation_with_proof_submitted(conn):
    """A reservation past even its extended deadline is NOT auto-expired once
    proof has been submitted — it waits for an operator, not a sweep."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    reservation = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com",
                                        as_of=AS_OF)
    vrepo.submit_proof_of_payment(conn, str(reservation["reservation_id"]),
                                  as_of=AS_OF + timedelta(minutes=25))

    long_after = AS_OF + timedelta(hours=10)
    assert vrepo.expire_overdue_reservations(conn, as_of=long_after) == []
    assert conn.execute(
        "SELECT state FROM vessel_reservation WHERE reservation_id = %s",
        (reservation["reservation_id"],)).fetchone()["state"] == "HELD"


@pg
def test_reservations_needing_confirmation_lists_only_the_stuck_ones(conn):
    """The operator's queue: HELD, past its one extension, unresolved either
    way. A fresh HELD reservation (no proof yet) and one safely inside its
    window do not belong on it."""
    from app.vessel import repo as vrepo

    stuck_listing = _listed_listing(conn)
    stuck = vrepo.reserve_listing(conn, str(stuck_listing["listing_id"]), buyer_contact="a@x.com",
                                  as_of=AS_OF)
    extended = vrepo.submit_proof_of_payment(conn, str(stuck["reservation_id"]),
                                             as_of=AS_OF + timedelta(minutes=25))

    fresh_listing = _listed_listing(conn, producer="Domaine Autre")
    vrepo.reserve_listing(conn, str(fresh_listing["listing_id"]), buyer_contact="b@x.com", as_of=AS_OF)

    due = vrepo.reservations_needing_confirmation(conn, as_of=extended["expires_at"] + timedelta(seconds=1))
    assert [r["reservation_id"] for r in due] == [stuck["reservation_id"]]

    not_yet_due = vrepo.reservations_needing_confirmation(conn, as_of=extended["expires_at"] - timedelta(seconds=1))
    assert not_yet_due == []


@pg
def test_cancel_reservation_releases_the_listing(conn):
    """The operator's confirmation that payment did not, in fact, arrive:
    CANCELLED, and the listing goes back to LISTED for a fresh buyer."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    reservation = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com",
                                        as_of=AS_OF)
    vrepo.submit_proof_of_payment(conn, str(reservation["reservation_id"]),
                                  as_of=AS_OF + timedelta(minutes=25))

    cancelled = vrepo.cancel_reservation(conn, str(reservation["reservation_id"]),
                                         as_of=AS_OF + timedelta(hours=3))
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["cancelled_at"] is not None
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "LISTED"

    second = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="c@x.com",
                                   as_of=AS_OF + timedelta(hours=3))
    assert second["state"] == "HELD"


@pg
def test_no_percentage_claim_on_single_source_listing_pg(conn):
    """The CHECK constraint, not just the Python function: a single-source
    listing is written with no percentage_claim_pct, enforced in the model."""
    listing = _priced_listing(conn, source_count=1, band_low=Decimal("12000"),
                              band_high=Decimal("16000"))
    assert listing["source_count"] == 1
    assert listing["percentage_claim_pct"] is None
    assert listing["vintage_band_passed"] is True

    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "UPDATE vessel_listing SET percentage_claim_pct = 0.1700 WHERE listing_id = %s",
            (listing["listing_id"],))


@pg
def test_single_source_failing_vintage_band_cannot_be_listed_pg(conn):
    """No band row (no quality-matched neighbours at all) means the single
    source does not pass, and recommend_lines excludes it as thin evidence —
    never creates a listing row for it."""
    from app.vessel import repo as vrepo

    operator_id = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, operator_id)
    _seed_run(conn, line_id, uk_reference=Decimal("14000"), comp_count=1,
             band_low=None, band_high=None)             # the band never ran
    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="HKD", fx_hkd_per_gbp=Decimal("9.7"), fx_source="XE",
        fx_rate_date=AS_OF.date(), stock_location="HK_BOND")
    assert listings == []
    [one] = excluded
    assert one.reason == vrepo.THIN_EVIDENCE
    assert conn.execute("SELECT count(*) AS n FROM vessel_listing").fetchone()["n"] == 0


@pg
def test_seller_net_is_eight_percent_below_vessel_price_pg(conn):
    """The relationship end to end, through recommend_lines and the real
    table — not just the pure function tested above."""
    listing = _priced_listing(conn)
    assert listing["seller_net"] == (Decimal(listing["vessel_price"]) * Decimal("0.92")
                                     ).quantize(Decimal("0.01"))


@pg
def test_listing_below_minimum_value_is_refused_pg(conn):
    """6 bottles at GBP 50/bottle is a GBP 300 lot even before the VESSEL
    discount - below the GBP 400 floor, and never recommended."""
    from app.vessel import repo as vrepo

    operator_id = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, operator_id, quantity=6)
    _seed_run(conn, line_id, uk_reference=Decimal("50"), comp_count=3)
    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="GBP", fx_hkd_per_gbp=None, fx_source=None, fx_rate_date=None,
        stock_location="UK_BOND")
    assert listings == []
    [one] = excluded
    assert one.reason == vrepo.BELOW_MINIMUM_VALUE


@pg
def test_unmatched_payment_does_not_confirm_a_sale(conn):
    """A reference nobody is holding ships nothing: no title moves before
    cleared funds, no exceptions."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com", as_of=AS_OF)

    payment = vrepo.record_payment(conn, reference="NOT-A-REAL-REF", amount=Decimal("69500.00"),
                                   currency="HKD", received_at=AS_OF)
    assert payment["state"] == "UNMATCHED"
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "RESERVED"

    # The right reference but the wrong amount is equally unmatched - never
    # waved through because the reference alone looked right.
    held = conn.execute(
        "SELECT payment_reference FROM vessel_reservation WHERE listing_id = %s AND state = 'HELD'",
        (listing["listing_id"],)).fetchone()
    short = vrepo.record_payment(conn, reference=held["payment_reference"],
                                 amount=Decimal("1.00"), currency="HKD", received_at=AS_OF)
    assert short["state"] == "UNMATCHED"
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "RESERVED"

    # The right reference and the right amount DOES confirm.
    paid = vrepo.record_payment(conn, reference=held["payment_reference"],
                                amount=Decimal(listing["vessel_price"]), currency="HKD",
                                received_at=AS_OF)
    assert paid["state"] == "MATCHED"
    assert vrepo.get_listing(conn, str(listing["listing_id"]))["state"] == "PAID"


@pg
def test_sold_listing_stays_visible_in_drop(conn):
    """SOLD stays on the page, greyed, for the life of the drop - not
    removed, not hidden."""
    from app.vessel import repo as vrepo

    listing = _listed_listing(conn)
    drop_id = listing["drop_id"]
    reservation = vrepo.reserve_listing(conn, str(listing["listing_id"]), buyer_contact="a@x.com",
                                        as_of=AS_OF)
    vrepo.record_payment(conn, reference=reservation["payment_reference"],
                         amount=Decimal(listing["vessel_price"]), currency="HKD",
                         received_at=AS_OF + timedelta(minutes=11))

    rows = vrepo.drop_listings(conn, str(drop_id))
    [row] = [r for r in rows if str(r["listing_id"]) == str(listing["listing_id"])]
    assert row["state"] == "PAID"
    assert row["sold_at"] is not None
    assert row["sold_at"] - row["listed_at"] >= timedelta(minutes=11)


@pg
def test_mandate_record_is_immutable_once_approved(conn):
    """No UPDATE, no DELETE, ever - a trigger, not a convention. And the
    listing's own commercial figures freeze the moment it has a mandate."""
    from app.vessel import repo as vrepo

    listing = _priced_listing(conn)
    mandate = vrepo.approve_mandate(conn, listing["deal_id"], move_line_ids=[listing["line_id"]],
                                    keep_line_ids=[], approved_by_name="A Seller")

    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE vessel_mandate SET approved_by_name = 'Someone Else' "
                     "WHERE mandate_id = %s", (mandate["mandate_id"],))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM vessel_mandate WHERE mandate_id = %s", (mandate["mandate_id"],))

    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE vessel_listing SET vessel_price = 1.00 WHERE listing_id = %s",
                     (listing["listing_id"],))

    still_there = conn.execute("SELECT * FROM vessel_mandate WHERE mandate_id = %s",
                               (mandate["mandate_id"],)).fetchone()
    assert still_there["approved_by_name"] == "A Seller"


@pg
def test_mandate_covers_only_the_approved_lines_and_declines_the_rest(conn):
    """Two states per line: MOVE or KEEP. Declining is the floor - no
    editable field, and a kept line is DECLINED, not left RECOMMENDED. Both
    lines are in the SAME mandate's deal; only one is ticked."""
    from app.vessel import repo as vrepo

    op = _operator(conn)
    deal_id, (move_line, keep_line), _ = _deal_with_lines(conn, op, [
        {"cuvee": "Moved Wine"}, {"cuvee": "Kept Wine"}])
    for line_id in (move_line, keep_line):
        _seed_run(conn, line_id, uk_reference=Decimal("14000"), comp_count=3,
                 band_low=Decimal("12000"), band_high=Decimal("16000"))
    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="HKD", fx_hkd_per_gbp=Decimal("9.7"), fx_source="XE",
        fx_rate_date=AS_OF.date(), stock_location="HK_BOND")
    assert not excluded and len(listings) == 2

    vrepo.approve_mandate(conn, deal_id, move_line_ids=[move_line], keep_line_ids=[keep_line],
                          approved_by_name="A Seller")
    by_line = {str(l["line_id"]): l for l in
              conn.execute("SELECT * FROM vessel_listing WHERE deal_id = %s",
                          (deal_id,)).fetchall()}
    assert by_line[move_line]["state"] == "APPROVED"
    assert by_line[move_line]["mandate_id"] is not None
    assert by_line[keep_line]["state"] == "DECLINED"
    assert by_line[keep_line]["mandate_id"] is None     # declined: no mandate at all


@pg
def test_why_not_recommended_counts_by_reason(conn):
    """'319 no UK market * 147 thin evidence * 53 better held' - the seller
    sees counts, per the reasons the spec names."""
    from app.vessel import repo as vrepo

    op = _operator(conn)
    deal_id, (no_market_line, thin_line), _ = _deal_with_lines(conn, op, [
        {"cuvee": "No Market Wine"}, {"cuvee": "Thin Wine"}])
    _seed_run(conn, thin_line, uk_reference=Decimal("1000"), comp_count=1,
             band_low=None, band_high=None)
    # no_market_line gets no run at all - never searched, no evidence.

    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="GBP", fx_hkd_per_gbp=None, fx_source=None, fx_rate_date=None,
        stock_location="UK_BOND")
    assert listings == []
    counts = vrepo.why_not_recommended(excluded)
    assert counts == {vrepo.NO_MARKET: 1, vrepo.THIN_EVIDENCE: 1}

    # And the same counts are readable later, by anyone revisiting the
    # approval screen — not only in this call's own return value.
    assert vrepo.excluded_summary(conn, deal_id) == {vrepo.NO_MARKET: 1, vrepo.THIN_EVIDENCE: 1}

    # A line that later qualifies drops out of the summary, not just gains a
    # listing: the stale exclusion is removed, not left to contradict it.
    _seed_run(conn, no_market_line, uk_reference=Decimal("500"), comp_count=2)
    listings2, _ = vrepo.recommend_lines(
        conn, deal_id, currency="GBP", fx_hkd_per_gbp=None, fx_source=None, fx_rate_date=None,
        stock_location="UK_BOND")
    assert len(listings2) == 1
    assert vrepo.excluded_summary(conn, deal_id) == {vrepo.THIN_EVIDENCE: 1}


# ======================================================== multi-market reference


@pg
def test_hk_retail_listing_is_priced_from_the_operator_entered_figure(conn):
    """No UK benchmark run at all - HK_RETAIL prices entirely from the
    manually entered reference, named on the listing and captured as its
    own vessel_reference row for provenance."""
    from app.vessel import repo as vrepo

    op = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, op, quantity=6)
    # Deliberately no _seed_run: HK_RETAIL does not need a UK benchmark run.

    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="HKD", fx_hkd_per_gbp=Decimal("9.7"), fx_source="XE",
        fx_rate_date=AS_OF.date(), stock_location="HK_BOND",
        line_choices={line_id: {
            "band": "NORMAL", "discount": Decimal("0.17"),
            "reference_market": "HK_RETAIL",
            "hk_reference_price": Decimal("100000.00"), "hk_source_count": 2,
            "hk_evidence": ["https://example.hk/listing-a", "https://example.hk/listing-b"]}})
    assert not excluded, excluded
    [listing] = listings
    assert listing["reference_market"] == "HK_RETAIL"
    assert listing["market_reference"] == Decimal("100000.00")
    assert listing["source_count"] == 2
    assert listing["reference_id"] is not None

    reference = conn.execute("SELECT * FROM vessel_reference WHERE reference_id = %s",
                             (listing["reference_id"],)).fetchone()
    assert reference["market"] == "HK_RETAIL"
    assert str(reference["line_id"]) == line_id
    assert reference["evidence"] == ["https://example.hk/listing-a", "https://example.hk/listing-b"]


@pg
def test_hk_retail_without_a_manual_price_is_excluded_not_guessed(conn):
    """"A listing needs a named reference market" cuts both ways: naming
    HK_RETAIL without supplying what it needs excludes the line, same as
    any other missing evidence - never a silent fall-back to UK."""
    from app.vessel import repo as vrepo

    op = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, op)

    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="HKD", fx_hkd_per_gbp=Decimal("9.7"), fx_source="XE",
        fx_rate_date=AS_OF.date(), stock_location="HK_BOND",
        line_choices={line_id: {"reference_market": "HK_RETAIL"}})
    assert listings == []
    [one] = excluded
    assert one.reason == vrepo.NO_MARKET


@pg
def test_hk_retail_single_source_is_excluded_at_the_database_too(conn):
    """The Python gate (evidence_claim) refuses this before a row is ever
    built, but the CHECK constraint is the one that cannot be bypassed by a
    future code path that forgets evidence_claim exists - direct SQL proves
    it, same discipline as test_no_percentage_claim_on_single_source_listing_pg."""
    listing = _priced_listing(conn, source_count=2)   # any valid UK_IN_BOND row to clone from
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            """UPDATE vessel_listing
                  SET reference_market = 'HK_RETAIL', source_count = 1, vintage_band_passed = true
                WHERE listing_id = %s""",
            (listing["listing_id"],))


@pg
def test_a_line_can_carry_both_a_uk_and_an_hk_reference(conn):
    """"Allow more than one reference per line" - the same line gets a
    UK_IN_BOND listing recommended once; a second, independent HK_RETAIL
    vessel_reference capture for the same line is not blocked by it (the
    uniqueness VESSEL enforces is one LISTING per line, never one reference
    per line)."""
    from app.vessel import repo as vrepo

    op = _operator(conn)
    deal_id, line_id, _ = _deal_with_line(conn, op, quantity=6)
    _seed_run(conn, line_id, uk_reference=Decimal("1443.30"), comp_count=3,
             band_low=Decimal("1200"), band_high=Decimal("1600"))

    listings, excluded = vrepo.recommend_lines(
        conn, deal_id, currency="HKD", fx_hkd_per_gbp=Decimal("9.7"), fx_source="XE",
        fx_rate_date=AS_OF.date(), stock_location="HK_BOND",
        line_choices={line_id: {"band": "NORMAL", "discount": Decimal("0.17")}})
    assert not excluded, excluded
    [listing] = listings
    assert listing["reference_market"] == "UK_IN_BOND"

    # An independent HK capture for the SAME line, recorded after the fact -
    # carried as its own row, not merged into or replacing the UK one.
    hk_reference = conn.execute(
        """INSERT INTO vessel_reference (line_id, market, reference_price, currency,
                                         source_count, evidence)
           VALUES (%s, 'HK_RETAIL', 100000.00, 'HKD', 2, '["https://example.hk/x"]')
           RETURNING *""", (line_id,)).fetchone()
    assert hk_reference["market"] == "HK_RETAIL"

    both = conn.execute("SELECT market FROM vessel_reference WHERE line_id = %s ORDER BY market",
                        (line_id,)).fetchall()
    assert {r["market"] for r in both} == {"UK_IN_BOND", "HK_RETAIL"}


@pg
def test_vessel_reference_is_append_only(conn):
    """No UPDATE, no DELETE, ever - mirrors vessel_mandate's own
    immutability trigger: a changed price is a new captured row."""
    listing = _priced_listing(conn)
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE vessel_reference SET reference_price = 1.00 WHERE reference_id = %s",
                     (listing["reference_id"],))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM vessel_reference WHERE reference_id = %s",
                     (listing["reference_id"],))
