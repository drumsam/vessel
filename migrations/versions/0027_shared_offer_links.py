"""Shareable public offer links (decision 0035).

A buyer or a seller cannot open /deals/{id}/offer -- it sits behind the
operator session, same as every other screen in this app. This migration
adds the one table a signed, unguessable, read-only, time-boxed public
link needs: a random token, the deal and the exact set of lines it was
cut for, which of the two safe views it shows (buyer never sees cost or
commission; seller may see commission but never the wider cellar), the
display rate it was generated at, who made it and when, and when it
stops working. No open-receipt or analytics column exists on purpose --
Doug asked for none.

Revision ID: 0027_shared_offer_links
Revises: 0026_sell_at_or_above_floor
Create Date: 2026-10-20
"""
from alembic import op

revision = "0027_shared_offer_links"
down_revision = "0026_sell_at_or_above_floor"
branch_labels = None
depends_on = None

SCHEMA = """
CREATE TABLE shared_offer_link (
    link_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- secrets.token_urlsafe(32): 256 bits, the public URL's own path
    -- segment. Not guessable by iterating an id; not shortened for looks.
    token        text NOT NULL UNIQUE,
    deal_id      uuid NOT NULL REFERENCES deal(deal_id) ON DELETE CASCADE,
    -- Not individually FK'd -- same discipline as the flags arrays
    -- elsewhere in this schema -- but every element is checked against
    -- the deal's own lines at creation time (app/offerlink/repo.py).
    line_ids     uuid[] NOT NULL CHECK (array_length(line_ids, 1) > 0),
    kind         text NOT NULL CHECK (kind IN ('buyer', 'seller')),
    fx_rate      numeric(10,4),
    created_by   uuid NOT NULL REFERENCES operator(operator_id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL
);
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP TABLE shared_offer_link")
