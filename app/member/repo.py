"""Buyer referrals — persistence. Every write goes through here.

Decision 0025. Reads VESSEL's own tables for the landing page's real
content (the current drop, real SOLD listings) but writes nothing to
them — `confirm_first_purchase` is called from the VESSEL API route that
already confirms a sale (`app/api/vessel.py`), never from inside
`app/vessel/` itself, so that package stays exactly as VESSEL left it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import psycopg

from app.api.auth import hash_password, verify_password
from app.member.engine import (
    EARLY_ACCESS_WINDOW,
    OTP_MAX_ATTEMPTS,
    OTP_TTL,
    AlreadyClaimed,
    InvalidPhone,
    SelfReferral,
    check_self_referral,
    new_invite_code,
    new_otp,
    normalise_phone,
)


class InvalidOtp(Exception):
    """Wrong code, expired, or no code was ever requested."""


class InviteNotFound(Exception):
    pass


class InviteAlreadyAccepted(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -------------------------------------------------------------------- login


def request_login_code(conn: psycopg.Connection, phone: str, *,
                       as_of: Optional[datetime] = None) -> str:
    """Returns the raw code — the caller (the API route) sends it via
    app.notify.provider.send_sms. Never stored or logged in the clear."""
    phone = normalise_phone(phone)
    as_of = as_of or _now()
    code = new_otp()
    conn.execute(
        """INSERT INTO member_login_code (phone, code_hash, expires_at, attempts)
           VALUES (%s, %s, %s, 0)
           ON CONFLICT (phone) DO UPDATE
              SET code_hash = EXCLUDED.code_hash, expires_at = EXCLUDED.expires_at, attempts = 0""",
        (phone, hash_password(code), as_of + OTP_TTL))
    return code


def verify_login_code(conn: psycopg.Connection, phone: str, code: str, *,
                      as_of: Optional[datetime] = None) -> bool:
    """Single-use: deletes the row on a correct match. A row that has
    already used up its attempts is deleted too, so a guessed-at code
    cannot be retried past the limit by racing the expiry."""
    phone = normalise_phone(phone)
    as_of = as_of or _now()
    row = conn.execute("SELECT * FROM member_login_code WHERE phone = %s", (phone,)).fetchone()
    if row is None or row["expires_at"] <= as_of or row["attempts"] >= OTP_MAX_ATTEMPTS:
        if row is not None:
            conn.execute("DELETE FROM member_login_code WHERE phone = %s", (phone,))
        return False
    if verify_password(row["code_hash"], code):
        conn.execute("DELETE FROM member_login_code WHERE phone = %s", (phone,))
        return True
    if row["attempts"] + 1 >= OTP_MAX_ATTEMPTS:
        conn.execute("DELETE FROM member_login_code WHERE phone = %s", (phone,))
    else:
        conn.execute("UPDATE member_login_code SET attempts = attempts + 1 WHERE phone = %s", (phone,))
    return False


# ------------------------------------------------------------------ invites


def _grant_next_invite(conn: psycopg.Connection, member_id: str, *, as_of: datetime) -> None:
    """"A member can never hold two open invites": idempotent. Flips
    invite_available and creates the one open row together, so the two
    facts the schema holds about this never disagree."""
    conn.execute("UPDATE member SET invite_available = true WHERE member_id = %s", (member_id,))
    existing = conn.execute(
        "SELECT 1 FROM invite WHERE inviter_id = %s AND accepted_at IS NULL", (member_id,)
    ).fetchone()
    if existing is None:
        conn.execute("INSERT INTO invite (code, inviter_id, created_at) VALUES (%s, %s, %s)",
                     (new_invite_code(), member_id, as_of))


def member_open_invite(conn: psycopg.Connection, member_id: str) -> Optional[dict]:
    return conn.execute(
        "SELECT * FROM invite WHERE inviter_id = %s AND accepted_at IS NULL", (member_id,)
    ).fetchone()


def accept_invite(conn: psycopg.Connection, code: str, *, phone: str, name: str, city: str,
                  storage_note: Optional[str], otp_code: str,
                  as_of: Optional[datetime] = None) -> dict:
    """"Four fields, sixty seconds." The OTP proves the phone is theirs;
    first-touch-permanent and self-referral are both checked before
    anything is written, so an invite that fails either check is left
    exactly as it was — never consumed, never half-accepted."""
    as_of = as_of or _now()
    phone = normalise_phone(phone)
    invite = conn.execute(
        """SELECT i.*, m.phone AS inviter_phone FROM invite i
             JOIN member m ON m.member_id = i.inviter_id
            WHERE i.code = %s""", (code,)).fetchone()
    if invite is None:
        raise InviteNotFound(f"no invite {code}")
    if invite["accepted_at"] is not None:
        raise InviteAlreadyAccepted(f"invite {code} was already accepted")
    check_self_referral(invite["inviter_phone"], phone)          # SelfReferral, uncaught here
    if not verify_login_code(conn, phone, otp_code, as_of=as_of):
        raise InvalidOtp(f"wrong or expired code for {phone}")
    claimed = conn.execute(
        "SELECT 1 FROM member WHERE phone = %s UNION SELECT 1 FROM invite WHERE invitee_phone = %s",
        (phone, phone)).fetchone()
    if claimed is not None:
        raise AlreadyClaimed(f"{phone} already accepted an earlier invite")
    member = conn.execute(
        """INSERT INTO member (phone, display_name, city, storage_note)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (phone, name, city, storage_note)).fetchone()
    accepted = conn.execute(
        """UPDATE invite SET invitee_phone = %s, accepted_at = %s
            WHERE code = %s RETURNING *""",
        (phone, as_of, code)).fetchone()
    return {"member": member, "invite": accepted}


def confirm_first_purchase(conn: psycopg.Connection, buyer_contact: str, *,
                           as_of: Optional[datetime] = None) -> Optional[dict]:
    """Called once, from the one place a VESSEL sale actually confirms
    (`app/api/vessel.py`'s confirm-seller-receipt route) — never from
    inside app/vessel/ itself. `buyer_contact` is VESSEL's own free-text
    field; most values are not phone numbers and that is fine; nothing
    here applies to a buyer who was never a member in the first place.

    Reward on completed purchase, never on signup (rule 4): if this phone
    is a member on their OWN first purchase, they earn their own next
    invite. If this phone is also the invitee on a still-open referral,
    that referral completes: both sides get early_access_until, and the
    inviter earns their next invite.
    """
    as_of = as_of or _now()
    try:
        phone = normalise_phone(buyer_contact)
    except InvalidPhone:
        return None
    member = conn.execute("SELECT * FROM member WHERE phone = %s", (phone,)).fetchone()
    if member is None:
        return None

    if member["first_purchase_at"] is None:
        conn.execute("UPDATE member SET first_purchase_at = %s WHERE member_id = %s",
                     (as_of, member["member_id"]))
        _grant_next_invite(conn, str(member["member_id"]), as_of=as_of)

    referral = conn.execute(
        """SELECT * FROM invite
            WHERE invitee_phone = %s AND accepted_at IS NOT NULL AND first_purchase_at IS NULL""",
        (phone,)).fetchone()
    if referral is not None:
        conn.execute("UPDATE invite SET first_purchase_at = %s WHERE code = %s",
                     (as_of, referral["code"]))
        until = as_of + EARLY_ACCESS_WINDOW
        conn.execute(
            "UPDATE member SET early_access_until = %s WHERE member_id IN (%s, %s)",
            (until, referral["inviter_id"], member["member_id"]))
        _grant_next_invite(conn, str(referral["inviter_id"]), as_of=as_of)

    return conn.execute("SELECT * FROM member WHERE member_id = %s",
                        (member["member_id"],)).fetchone()


# -------------------------------------------------------------------- reads


def get_member(conn: psycopg.Connection, member_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM member WHERE member_id = %s", (member_id,)).fetchone()


def get_invite(conn: psycopg.Connection, code: str) -> Optional[dict]:
    return conn.execute(
        """SELECT i.*, m.display_name AS inviter_display_name
             FROM invite i JOIN member m ON m.member_id = i.inviter_id
            WHERE i.code = %s""", (code,)).fetchone()


def current_cellar_summary(conn: psycopg.Connection) -> Optional[dict]:
    """The landing page's part 2: region, count, price from — from the most
    recent drop's own listings, joined back to the wine for region. None
    when there is nothing live to show (omit the section, never invent one)."""
    drop = conn.execute("SELECT drop_id FROM vessel_drop ORDER BY drop_date DESC LIMIT 1").fetchone()
    if drop is None:
        return None
    rows = conn.execute(
        """SELECT w.region, l.currency, l.vessel_price
             FROM vessel_listing l
             JOIN seller_line sl ON sl.line_id = l.line_id
             JOIN wine w ON w.wine_id = sl.wine_id
            WHERE l.drop_id = %s AND l.state NOT IN ('DECLINED')""",
        (drop["drop_id"],)).fetchall()
    if not rows:
        return None
    regions = sorted({r["region"] for r in rows if r["region"]})
    currency = rows[0]["currency"]
    cheapest = min((r["vessel_price"] for r in rows if r["currency"] == currency), default=None)
    return {"region": ", ".join(regions) or None, "listing_count": len(rows),
           "price_from": cheapest, "currency": currency}


def recent_sales(conn: psycopg.Connection, *, limit: int = 3) -> list[dict]:
    """The landing page's part 3: real SOLD listings only, with how many
    days from listed to sold. Never fabricated — an empty list means the
    section is omitted, not filled with a placeholder."""
    rows = conn.execute(
        """SELECT l.display_producer, l.display_wine, l.vintage, l.listed_at,
                  (SELECT min(r.fulfilled_at) FROM vessel_reservation r
                    WHERE r.listing_id = l.listing_id AND r.state = 'FULFILLED') AS sold_at
             FROM vessel_listing l
            WHERE l.state IN ('PAID','TRANSFERRING','SETTLED')
            ORDER BY l.listed_at DESC LIMIT %s""", (limit,)).fetchall()
    out = []
    for r in rows:
        days = (r["sold_at"] - r["listed_at"]).days if r["sold_at"] and r["listed_at"] else None
        out.append({"display_producer": r["display_producer"], "display_wine": r["display_wine"],
                    "vintage": r["vintage"], "days_to_sell": days})
    return out


# -------------------------------------------------------- seller introduction


def create_seller_introduction(conn: psycopg.Connection, mandate_id: str, *, introducer_name: str,
                               lead_name: str, lead_phone: str,
                               as_of: Optional[datetime] = None) -> dict:
    """Captures a name and a phone number and nothing else — Doug makes the
    approach, the referrer never has to sell to a friend. Paying the 1% is
    a manual step once (if) resulting_mandate_id is set by hand; nothing
    here computes or schedules that payment."""
    as_of = as_of or _now()
    return conn.execute(
        """INSERT INTO seller_introduction
               (captured_on_mandate_id, lead_name, lead_phone, created_at)
           VALUES (%s, %s, %s, %s) RETURNING *""",
        (mandate_id, lead_name, lead_phone, as_of)).fetchone()


# -------------------------------------------------------------------- report


def referral_funnel(conn: psycopg.Connection) -> dict:
    """"Invitations sent; share accepted; share of accepted who buy within
    60 days." One read-only query, same shape as the acknowledgement
    report — no dashboard, no analytics tables."""
    row = conn.execute(
        """SELECT count(*) AS sent,
                  count(accepted_at) AS accepted,
                  count(*) FILTER (WHERE accepted_at IS NOT NULL
                                     AND first_purchase_at IS NOT NULL
                                     AND first_purchase_at <= accepted_at + interval '60 days')
                      AS bought_within_60_days
             FROM invite""").fetchone()
    accepted = row["accepted"] or 0
    return {
        "invitations_sent": row["sent"],
        "invitations_accepted": accepted,
        "accepted_who_bought_within_60_days": row["bought_within_60_days"],
        "acceptance_rate": (accepted / row["sent"]) if row["sent"] else None,
        "purchase_rate_of_accepted": (row["bought_within_60_days"] / accepted) if accepted else None,
    }
