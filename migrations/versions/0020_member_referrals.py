"""Buyer referrals, the smallest version that works: one invite at a time,
first touch permanent, reward on completed purchase only, access not cash.

Decision 0025. Doug overrode his own "stand down" instruction because
growing the buyer list is the one thing left before deal one — but
everything from the parked growth/club document (waitlist positions,
status tiers, membership caps, cash credits, buyer ranking) stays parked;
building any of it now would be exactly the "out of tidiness" mistake
Doug named directly.

`member` is new: VESSEL's buyers have never had an account (decision
0020's own admission). This migration gives buyers who go through the
referral loop a lightweight one, phone-identified, no password — the same
"no login beyond an unguessable link" discipline the rest of VESSEL
already uses, extended only as far as a referral programme needs it to go.

Revision ID: 0020_member_referrals
Revises: 0019_auction_evidence
Create Date: 2026-10-07
"""
from alembic import op

revision = "0020_member_referrals"
down_revision = "0019_auction_evidence"
branch_labels = None
depends_on = None

SCHEMA = """
-- E.164: '+' then 7-15 digits, first digit 1-9. Checked here and in every
-- place a phone is written, never trusted from the caller alone.
CREATE TABLE member (
    member_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone              text NOT NULL UNIQUE CHECK (phone ~ '^\\+[1-9][0-9]{6,14}$'),
    display_name       text,
    city               text,
    -- "How do you store wine?" - a lead for the NEXT seller, not a service
    -- VESSEL offers this member. Free text, operator-read only.
    storage_note       text,
    invite_available   boolean NOT NULL DEFAULT false,
    -- Not in Doug's five-field schema, added because rule 1 ("flips true
    -- when a member's first purchase confirms") needs a place to record
    -- THIS fact for every member, not only one who arrived by referral -
    -- invite.first_purchase_at (below) answers a different question: did
    -- the person THIS INVITE brought in buy, which is what pays the
    -- inviter's reward.
    first_purchase_at  timestamptz,
    -- The reward (decision 0025, rule 5): access, never money. Both sides
    -- of a completed referral get it; so does a member on their own first
    -- purchase being the one who unlocks their own next invite - whether
    -- early_access_until is also granted there is Doug's call, not
    -- assumed here, so this migration only ever sets it from a referral
    -- completing (see app/member/repo.py).
    early_access_until timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- Never stored long-term, never logged in the clear: request_login_code
-- overwrites the one row for a phone, verify_login_code deletes it on a
-- correct match or a used-up attempt. Proves the phone at invite
-- acceptance; nothing here is a persistent session.
CREATE TABLE member_login_code (
    phone       text PRIMARY KEY CHECK (phone ~ '^\\+[1-9][0-9]{6,14}$'),
    code_hash   text NOT NULL,
    expires_at  timestamptz NOT NULL,
    attempts    int NOT NULL DEFAULT 0
);

CREATE TABLE invite (
    code               text PRIMARY KEY,
    inviter_id         uuid NOT NULL REFERENCES member(member_id),
    invitee_phone      text UNIQUE CHECK (
                          invitee_phone IS NULL OR invitee_phone ~ '^\\+[1-9][0-9]{6,14}$'),
    accepted_at        timestamptz,
    first_purchase_at  timestamptz,
    created_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT invite_first_purchase_needs_acceptance CHECK (
        first_purchase_at IS NULL OR accepted_at IS NOT NULL),
    CONSTRAINT invite_first_purchase_needs_invitee CHECK (
        first_purchase_at IS NULL OR invitee_phone IS NOT NULL)
);

-- "A member can never hold two open invites" (rule 1) - a database
-- constraint, not application logic, same discipline as VESSEL's own
-- one-live-reservation-per-listing index.
CREATE UNIQUE INDEX invite_one_open_per_inviter
    ON invite (inviter_id) WHERE accepted_at IS NULL;

-- The seller introduction (decision 0025): captured on the introducer's
-- own mandate, at approval time. Doug makes the approach, so there is no
-- automatic path from a lead to a future mandate - resulting_mandate_id
-- is set by hand, later, only if and when the lead becomes a seller.
-- Paying the 1% is then a manual step reading this table; nothing here
-- computes or schedules a payment.
CREATE TABLE seller_introduction (
    introduction_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_on_mandate_id uuid NOT NULL REFERENCES vessel_mandate(mandate_id),
    lead_name             text NOT NULL,
    lead_phone            text NOT NULL,
    commission_rate       numeric(5,4) NOT NULL DEFAULT 0.01,
    resulting_mandate_id  uuid REFERENCES vessel_mandate(mandate_id),
    paid_at               timestamptz,
    created_at            timestamptz NOT NULL DEFAULT now()
);

-- "Ask every seller which warehouse they use" - one field, no logic, a
-- term of the mandate exactly like settlement_mode already is.
ALTER TABLE vessel_mandate ADD COLUMN storage_facility text;
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("ALTER TABLE vessel_mandate DROP COLUMN storage_facility")
    op.execute("DROP TABLE seller_introduction")
    op.execute("DROP INDEX invite_one_open_per_inviter")
    op.execute("DROP TABLE invite")
    op.execute("DROP TABLE member_login_code")
    op.execute("DROP TABLE member")
