"""Buyer referrals (decision 0025): the pure rules (offline) and the
machinery (Postgres). House style as in test_vessel.py: name the rule and
the size of the error the test prevents.
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

from app.member import engine

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")

AS_OF = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


# ================================================================ offline: engine


def test_phone_must_be_e164():
    assert engine.normalise_phone("+447700900123") == "+447700900123"
    for bad in ("07700900123", "+0123456", "not-a-phone", "+1"):
        with pytest.raises(engine.InvalidPhone):
            engine.normalise_phone(bad)


def test_invite_code_is_url_safe_and_eight_characters():
    code = engine.new_invite_code()
    assert len(code) == engine.INVITE_CODE_LENGTH == 8
    assert all(c in engine.INVITE_CODE_ALPHABET for c in code)


def test_otp_is_six_digits():
    code = engine.new_otp()
    assert len(code) == 6 and code.isdigit()


def test_self_referral_is_refused():
    with pytest.raises(engine.SelfReferral):
        engine.check_self_referral("+447700900123", "+447700900123")
    engine.check_self_referral("+447700900123", "+447700900456")   # does not raise


def test_early_access_window_is_forty_eight_hours():
    """"Both sides get first look at the next cellar - 48 hours before the
    main list." Not a flag, a concrete window."""
    assert engine.EARLY_ACCESS_WINDOW == timedelta(hours=48)


def test_share_text_names_the_inviter_and_carries_the_link():
    text = engine.share_text("Maria", "https://vssl.co/i/ab12cd34")
    assert "Maria" in text and "https://vssl.co/i/ab12cd34" in text


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


def _member(conn, phone: str, **kw) -> dict:
    from app.member import repo as mrepo
    return conn.execute(
        "INSERT INTO member (phone, display_name, city) VALUES (%s, %s, %s) RETURNING *",
        (phone, kw.get("display_name", "Test Buyer"), kw.get("city", "London"))).fetchone()


@pg
def test_login_code_round_trip_is_single_use(conn):
    from app.member import repo as mrepo

    phone = "+447700900001"
    code = mrepo.request_login_code(conn, phone, as_of=AS_OF)
    assert mrepo.verify_login_code(conn, phone, code, as_of=AS_OF) is True
    # Single use: the same code does not verify twice.
    assert mrepo.verify_login_code(conn, phone, code, as_of=AS_OF) is False


@pg
def test_wrong_code_does_not_verify_and_locks_out_after_three(conn):
    from app.member import repo as mrepo

    phone = "+447700900002"
    mrepo.request_login_code(conn, phone, as_of=AS_OF)
    for _ in range(engine.OTP_MAX_ATTEMPTS):
        assert mrepo.verify_login_code(conn, phone, "000000", as_of=AS_OF) is False
    # A fresh, never-requested code would also fail now - the row is burned.
    assert conn.execute("SELECT * FROM member_login_code WHERE phone = %s",
                        (phone,)).fetchone() is None


@pg
def test_expired_code_does_not_verify(conn):
    from app.member import repo as mrepo

    phone = "+447700900003"
    code = mrepo.request_login_code(conn, phone, as_of=AS_OF)
    later = AS_OF + engine.OTP_TTL + timedelta(seconds=1)
    assert mrepo.verify_login_code(conn, phone, code, as_of=later) is False


@pg
def test_accept_invite_creates_a_member_and_consumes_the_code(conn):
    from app.member import repo as mrepo

    inviter = _member(conn, "+447700900010")
    code = engine.new_invite_code()
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)",
                (code, inviter["member_id"]))

    invitee_phone = "+447700900011"
    otp = mrepo.request_login_code(conn, invitee_phone, as_of=AS_OF)
    result = mrepo.accept_invite(conn, code, phone=invitee_phone, name="A Buyer",
                                 city="Bristol", storage_note="own cellar, 200 bottles",
                                 otp_code=otp, as_of=AS_OF)
    assert result["member"]["phone"] == invitee_phone
    assert result["invite"]["accepted_at"] == AS_OF
    assert result["invite"]["invitee_phone"] == invitee_phone


@pg
def test_accept_invite_refuses_a_second_acceptance(conn):
    from app.member import repo as mrepo

    inviter = _member(conn, "+447700900020")
    code = engine.new_invite_code()
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)",
                (code, inviter["member_id"]))
    otp = mrepo.request_login_code(conn, "+447700900021", as_of=AS_OF)
    mrepo.accept_invite(conn, code, phone="+447700900021", name="A", city="B",
                        storage_note=None, otp_code=otp, as_of=AS_OF)

    otp2 = mrepo.request_login_code(conn, "+447700900022", as_of=AS_OF)
    with pytest.raises(mrepo.InviteAlreadyAccepted):
        mrepo.accept_invite(conn, code, phone="+447700900022", name="C", city="D",
                           storage_note=None, otp_code=otp2, as_of=AS_OF)


@pg
def test_self_referral_is_refused_and_the_invite_stays_open(conn):
    """Rule 6: same phone as the inviter, reward withheld, and — since this
    is refused outright — nothing about the invite changes at all."""
    from app.member import repo as mrepo

    inviter_phone = "+447700900030"
    inviter = _member(conn, inviter_phone)
    code = engine.new_invite_code()
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)",
                (code, inviter["member_id"]))
    otp = mrepo.request_login_code(conn, inviter_phone, as_of=AS_OF)

    with pytest.raises(engine.SelfReferral):
        mrepo.accept_invite(conn, code, phone=inviter_phone, name="Me", city="Here",
                           storage_note=None, otp_code=otp, as_of=AS_OF)

    unchanged = conn.execute("SELECT * FROM invite WHERE code = %s", (code,)).fetchone()
    assert unchanged["accepted_at"] is None and unchanged["invitee_phone"] is None


@pg
def test_first_touch_permanent_a_second_link_to_the_same_phone_is_refused_unused(conn):
    """Rule 3: the first accepted link wins, for life. A second inviter's
    code reaching the same phone is refused — and stays open, unused, for
    that second inviter, not consumed by the attempt."""
    from app.member import repo as mrepo

    phone = "+447700900040"
    inviter_a = _member(conn, "+447700900041")
    code_a = engine.new_invite_code()
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)", (code_a, inviter_a["member_id"]))
    otp_a = mrepo.request_login_code(conn, phone, as_of=AS_OF)
    mrepo.accept_invite(conn, code_a, phone=phone, name="First", city="Here",
                       storage_note=None, otp_code=otp_a, as_of=AS_OF)

    inviter_b = _member(conn, "+447700900042")
    code_b = engine.new_invite_code()
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)", (code_b, inviter_b["member_id"]))
    otp_b = mrepo.request_login_code(conn, phone, as_of=AS_OF)
    with pytest.raises(engine.AlreadyClaimed):
        mrepo.accept_invite(conn, code_b, phone=phone, name="Second try", city="There",
                           storage_note=None, otp_code=otp_b, as_of=AS_OF)

    still_open = conn.execute("SELECT * FROM invite WHERE code = %s", (code_b,)).fetchone()
    assert still_open["accepted_at"] is None and still_open["invitee_phone"] is None


@pg
def test_one_open_invite_per_inviter_is_a_database_constraint(conn):
    """"A member can never hold two open invites" - a partial unique
    index, not application logic. Direct SQL, bypassing the repo
    entirely, still cannot create a second open row."""
    inviter = _member(conn, "+447700900050")
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)",
                (engine.new_invite_code(), inviter["member_id"]))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)",
                     (engine.new_invite_code(), inviter["member_id"]))


@pg
def test_confirm_first_purchase_grants_the_members_own_first_invite(conn):
    from app.member import repo as mrepo

    phone = "+447700900060"
    member = _member(conn, phone)
    assert member["invite_available"] is False

    updated = mrepo.confirm_first_purchase(conn, phone, as_of=AS_OF)
    assert updated["first_purchase_at"] == AS_OF
    assert updated["invite_available"] is True
    [invite] = conn.execute("SELECT * FROM invite WHERE inviter_id = %s",
                            (member["member_id"],)).fetchall()
    assert invite["accepted_at"] is None

    # A second purchase does not touch first_purchase_at again or grant a
    # second open invite (the partial unique index would refuse it anyway).
    again = mrepo.confirm_first_purchase(conn, phone, as_of=AS_OF + timedelta(days=30))
    assert again["first_purchase_at"] == AS_OF
    assert conn.execute("SELECT count(*) AS n FROM invite WHERE inviter_id = %s",
                        (member["member_id"],)).fetchone()["n"] == 1


@pg
def test_confirm_first_purchase_completes_a_referral_and_rewards_both_sides(conn):
    """Rule 4 (reward on completed purchase, never on signup) and rule 5
    (the reward is access, for both sides): the inviter earns their next
    invite and early_access_until; so does the invitee who just bought."""
    from app.member import repo as mrepo

    inviter = _member(conn, "+447700900070")
    invitee_phone = "+447700900071"
    code = engine.new_invite_code()
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)",
                (code, inviter["member_id"]))
    otp = mrepo.request_login_code(conn, invitee_phone, as_of=AS_OF)
    mrepo.accept_invite(conn, code, phone=invitee_phone, name="Invitee", city="Leeds",
                       storage_note=None, otp_code=otp, as_of=AS_OF)

    purchased_at = AS_OF + timedelta(days=5)
    mrepo.confirm_first_purchase(conn, invitee_phone, as_of=purchased_at)

    referral = conn.execute("SELECT * FROM invite WHERE code = %s", (code,)).fetchone()
    assert referral["first_purchase_at"] == purchased_at

    inviter_row = conn.execute("SELECT * FROM member WHERE member_id = %s",
                               (inviter["member_id"],)).fetchone()
    assert inviter_row["early_access_until"] == purchased_at + engine.EARLY_ACCESS_WINDOW
    assert inviter_row["invite_available"] is True
    [inviter_next] = conn.execute("SELECT * FROM invite WHERE inviter_id = %s AND accepted_at IS NULL",
                                  (inviter["member_id"],)).fetchall()
    assert inviter_next["code"] != code

    invitee_row = conn.execute("SELECT * FROM member WHERE phone = %s", (invitee_phone,)).fetchone()
    assert invitee_row["early_access_until"] == purchased_at + engine.EARLY_ACCESS_WINDOW


@pg
def test_confirm_first_purchase_ignores_a_buyer_contact_that_is_not_a_phone(conn):
    """Most VESSEL buyers are not members at all - an email address, or a
    phone nobody ever became a member with, is a quiet no-op, never a
    crash and never an invented member."""
    from app.member import repo as mrepo

    assert mrepo.confirm_first_purchase(conn, "someone@example.com", as_of=AS_OF) is None
    assert mrepo.confirm_first_purchase(conn, "+447700900099", as_of=AS_OF) is None   # valid phone, no member row
    assert conn.execute("SELECT count(*) AS n FROM member").fetchone()["n"] == 0


@pg
def test_seller_introduction_is_captured_against_the_mandate(conn):
    from app.member import repo as mrepo
    from app.vessel import repo as vrepo
    from app.api.auth import hash_password
    from app.db import repo as db

    operator = conn.execute(
        "INSERT INTO operator (username, display_name, password_hash) VALUES (%s, %s, %s) "
        "RETURNING operator_id", (f"op-{uuid4().hex[:8]}", "Op", hash_password("x" * 12))
    ).fetchone()
    wine = db.create_wine(conn, producer="Domaine Test", cuvee="Test Wine", region="Burgundy",
                          colour="Red", lwin7=None)
    deal = db.create_deal(
        conn, {"name": "Test cellar", "seller": None, "source_file": None, "currency": "GBP",
              "target_margin": None, "created_by": operator["operator_id"]},
        [{"row_index": 0, "raw_description": "line 0", "raw_row": {"A": "x"}, "quantity": 6,
          "cost": None, "cost_currency": None, "target_margin": None, "target_discount": None,
          "manual_price": None}])
    [line] = db.deal_lines(conn, str(deal["deal_id"]))
    db.set_line_identity(conn, str(line["line_id"]), wine_id=str(wine["wine_id"]), vintage=2015,
                         bottle_ml=750, pack_size=1, flags=[], source="operator",
                         approved_by=operator["operator_id"])
    run = conn.execute(
        """INSERT INTO benchmark_run (line_id, as_of, uk_floor, uk_reference, uk_median,
                                      comp_count, state)
           VALUES (%s, %s, %s, %s, %s, %s, 'READY') RETURNING run_id""",
        (line["line_id"], AS_OF, Decimal("1443.30"), Decimal("1443.30"), Decimal("1443.30"), 3),
    ).fetchone()
    conn.execute(
        """INSERT INTO vintage_band_check (run_id, unit, band_low, band_high, tiers_available)
           VALUES (%s, %s, %s, %s, true)""",
        (run["run_id"], "1x750", Decimal("1200"), Decimal("1600")))
    listings, excluded = vrepo.recommend_lines(
        conn, str(deal["deal_id"]), currency="HKD", fx_hkd_per_gbp=Decimal("9.7"), fx_source="XE",
        fx_rate_date=AS_OF.date(), stock_location="HK_BOND")
    assert not excluded, excluded
    mandate = vrepo.approve_mandate(conn, str(deal["deal_id"]), move_line_ids=[str(line["line_id"])],
                                    keep_line_ids=[], approved_by_name="A Seller")

    intro = mrepo.create_seller_introduction(
        conn, str(mandate["mandate_id"]), introducer_name="A Seller",
        lead_name="A Friend", lead_phone="+447700900080", as_of=AS_OF)
    assert intro["captured_on_mandate_id"] == mandate["mandate_id"]
    assert intro["commission_rate"] == Decimal("0.0100")
    assert intro["resulting_mandate_id"] is None and intro["paid_at"] is None


@pg
def test_referral_funnel_counts_sent_accepted_and_bought(conn):
    """One accepted invite, its own first purchase confirmed within 60
    days. confirm_first_purchase also grants two FRESH, unaccepted invites
    (the invitee's own, and the inviter's referral reward) — real rows,
    correctly counted as sent but not yet accepted."""
    from app.member import repo as mrepo

    inviter = _member(conn, "+447700900090")
    code = engine.new_invite_code()
    conn.execute("INSERT INTO invite (code, inviter_id) VALUES (%s, %s)",
                (code, inviter["member_id"]))
    otp = mrepo.request_login_code(conn, "+447700900091", as_of=AS_OF)
    mrepo.accept_invite(conn, code, phone="+447700900091", name="Buyer", city="York",
                       storage_note=None, otp_code=otp, as_of=AS_OF)
    mrepo.confirm_first_purchase(conn, "+447700900091", as_of=AS_OF + timedelta(days=10))

    report = mrepo.referral_funnel(conn)
    assert report["invitations_sent"] == 3        # original + invitee's own + inviter's reward
    assert report["invitations_accepted"] == 1     # only the original was ever accepted
    assert report["accepted_who_bought_within_60_days"] == 1
