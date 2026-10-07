"""Request and response shapes for buyer referrals (decision 0025). Public
routes only — members have no password and no persistent session; the OTP
proves a phone at the moment of accepting an invite and nothing more.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import Field

from app.api.schemas import Money, _In, _Out


class RequestCodeIn(_In):
    phone: str = Field(min_length=8)


class AcceptInviteIn(_In):
    phone: str = Field(min_length=8)
    otp_code: str = Field(min_length=4, max_length=8)
    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    storage_note: Optional[str] = None


class MemberOut(_Out):
    member_id: UUID
    display_name: Optional[str]
    city: Optional[str]
    invite_available: bool
    first_purchase_at: Optional[datetime]
    early_access_until: Optional[datetime]
    #: Present only when invite_available is true — absent, not null, when
    #: there is nothing to share yet (invariant 15's own discipline, applied
    #: here: no claim without the thing behind it). The frontend builds the
    #: wa.me link and its own share text client-side; the backend does not
    #: know its own public domain.
    open_invite_code: Optional[str] = None


class AcceptInviteOut(_Out):
    member: MemberOut


class CellarSummaryOut(_Out):
    region: Optional[str]
    listing_count: int
    price_from: Optional[Money]
    currency: Optional[str]


class RecentSaleOut(_Out):
    display_producer: str
    display_wine: str
    vintage: int
    days_to_sell: Optional[int]


class InviteLandingOut(_Out):
    inviter_first_name: str
    already_accepted: bool
    cellar: Optional[CellarSummaryOut]
    recent_sales: list[RecentSaleOut]


class SellerIntroductionIn(_In):
    introducer_name: str = Field(min_length=1)
    lead_name: str = Field(min_length=1)
    lead_phone: str = Field(min_length=8)


class SellerIntroductionOut(_Out):
    introduction_id: UUID
    captured_on_mandate_id: UUID
    lead_name: str
    lead_phone: str
    commission_rate: Decimal
    resulting_mandate_id: Optional[UUID]
    paid_at: Optional[datetime]
    created_at: datetime


class ReferralFunnelOut(_Out):
    invitations_sent: int
    invitations_accepted: int
    accepted_who_bought_within_60_days: int
    acceptance_rate: Optional[Decimal]
    purchase_rate_of_accepted: Optional[Decimal]
