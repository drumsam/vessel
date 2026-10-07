"""Buyer referrals — the pure rules. No clock, no network, no database.

Decision 0025. The smallest version that works, at roughly twenty buyers
and two to three cellars a year: one open invite per member, first touch
permanent, reward on a completed purchase only, access not cash. Nothing
here is a waitlist position, a status tier, a membership cap, a cash
credit or a buyer ranking — all five need volume this business does not
have, and were named explicitly as not to be built.
"""
from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

#: E.164: '+' then 7-15 digits, first digit 1-9.
PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{6,14}$")

#: Random, URL-safe, ~8 characters — long enough that guessing a live code
#: is not a realistic path in, short enough to read aloud or paste by hand.
INVITE_CODE_ALPHABET = string.ascii_lowercase + string.digits
INVITE_CODE_LENGTH = 8

#: Six digits, ten minutes, three attempts — a phone-ownership check at the
#: moment of accepting an invite, never a persistent session.
OTP_LENGTH = 6
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 3

#: The reward (rule 5): access, never money. 48 hours first look at the
#: next cellar, for both sides of a completed referral.
EARLY_ACCESS_WINDOW = timedelta(hours=48)

#: Captured on an introducer's own mandate (decision 0025's seller
#: introduction); paid manually when the lead's own cellar, if any, raises
#: its own commission invoice.
INTRODUCTION_COMMISSION_RATE = "0.01"


class InvalidPhone(Exception):
    """Not E.164. Checked here and by the database CHECK behind it — the
    same house pattern as every other guarded write in this codebase."""


class SelfReferral(Exception):
    """Same phone as the inviter. The reward is withheld and the invite is
    refused outright — simpler than, and equivalent in effect to, "accept
    but withhold the reward": no path exists for a self-referral to ever
    produce one."""


class AlreadyClaimed(Exception):
    """First touch, permanent (rule 3): this phone already accepted a
    different invite. This one is refused and stays open, unused, for its
    own inviter — the phone being already spoken for is not their fault."""


def normalise_phone(phone: str) -> str:
    phone = phone.strip()
    if not PHONE_PATTERN.match(phone):
        raise InvalidPhone(f"{phone!r} is not E.164 (+ then 7-15 digits)")
    return phone


def new_invite_code() -> str:
    return "".join(secrets.choice(INVITE_CODE_ALPHABET) for _ in range(INVITE_CODE_LENGTH))


def new_otp() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(OTP_LENGTH))


def check_self_referral(inviter_phone: str, invitee_phone: str) -> None:
    if inviter_phone == invitee_phone:
        raise SelfReferral(f"{invitee_phone} is the inviter's own number")


def share_text(inviter_first_name: str, invite_url: str) -> str:
    """The one WhatsApp share button's pre-filled text. No integration, no
    API: this is urlencoded into a wa.me link client-side, never sent on
    anyone's behalf."""
    return (f"{inviter_first_name} here — I buy fine wine through VESSEL, "
           f"a private sale. Thought you'd want a look: {invite_url}")


@dataclass(frozen=True)
class CellarSummary:
    """What's in the current or next cellar (landing page, part 2): region,
    count, price from — never fabricated, omitted entirely when there is
    nothing real to show."""
    region: Optional[str]
    listing_count: int
    price_from: Optional[object]       # Decimal, lot total, lowest currency shown
    currency: Optional[str]


@dataclass(frozen=True)
class RecentSale:
    """A real SOLD listing (landing page, part 3) — never fabricated, never
    a placeholder. Omit the whole section if there are none."""
    display_producer: str
    display_wine: str
    vintage: int
    days_to_sell: Optional[int]
