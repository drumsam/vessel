"""Buyer referral routes (decision 0025). All public: a member has no
password and no persistent session, the same "no login beyond an
unguessable link" discipline VESSEL's own public routes already use.
"""
from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.api import member_schemas as s
from app.api.deps import db
from app.member import repo
from app.member.engine import AlreadyClaimed, InvalidPhone, SelfReferral
from app.notify.provider import send_sms

router = APIRouter(tags=["members"])


def _member_out(row: dict, *, open_invite: dict | None) -> s.MemberOut:
    return s.MemberOut(**{**row, "open_invite_code": open_invite["code"] if open_invite else None})


@router.post("/members/request-code", status_code=204)
def request_code(body: s.RequestCodeIn, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            code = repo.request_login_code(conn, body.phone)
    except InvalidPhone as e:
        raise HTTPException(422, str(e))
    send_sms(body.phone, f"Your VESSEL code is {code}. It expires in 10 minutes.")


@router.get("/invites/{code}", response_model=s.InviteLandingOut)
def get_invite_landing(code: str, conn: psycopg.Connection = Depends(db)):
    invite = repo.get_invite(conn, code)
    if invite is None:
        raise HTTPException(404, "invite not found")
    cellar = repo.current_cellar_summary(conn)
    return s.InviteLandingOut(
        inviter_first_name=(invite["inviter_display_name"] or "A VESSEL member").split()[0],
        already_accepted=invite["accepted_at"] is not None,
        cellar=cellar, recent_sales=repo.recent_sales(conn))


@router.post("/invites/{code}/accept", response_model=s.AcceptInviteOut)
def accept_invite(code: str, body: s.AcceptInviteIn, conn: psycopg.Connection = Depends(db)):
    try:
        with conn.transaction():
            result = repo.accept_invite(
                conn, code, phone=body.phone, name=body.name, city=body.city,
                storage_note=body.storage_note, otp_code=body.otp_code)
    except repo.InviteNotFound as e:
        raise HTTPException(404, str(e))
    except (repo.InviteAlreadyAccepted, SelfReferral, AlreadyClaimed) as e:
        raise HTTPException(409, str(e))
    except (repo.InvalidOtp, InvalidPhone) as e:
        raise HTTPException(422, str(e))
    except psycopg.errors.UniqueViolation as e:
        raise HTTPException(409, e.diag.message_detail or str(e))
    member = result["member"]
    return s.AcceptInviteOut(member=_member_out(member, open_invite=None))


@router.get("/members/{member_id}", response_model=s.MemberOut)
def get_member(member_id: UUID, conn: psycopg.Connection = Depends(db)):
    member = repo.get_member(conn, str(member_id))
    if member is None:
        raise HTTPException(404, "member not found")
    open_invite = repo.member_open_invite(conn, str(member_id)) if member["invite_available"] else None
    return _member_out(member, open_invite=open_invite)
