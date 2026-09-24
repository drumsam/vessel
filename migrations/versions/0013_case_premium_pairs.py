"""Record every wine met in two pack sizes, so the case premium can be measured.

Decision 0016, revised 24 September when the premium was measured at parity
(median 1.0000, n=27, Bordeaux Index). 27 pairs from one merchant is not enough
to settle a constant that moves prices, so the collection step now records every
pair it meets while the traffic is happening anyway.

Revision ID: 0013_case_premium_pairs
Revises: 0012_vintage_tier_register
Create Date: 2026-09-24
"""
from alembic import op

revision = "0013_case_premium_pairs"
down_revision = "0012_vintage_tier_register"
branch_labels = None
depends_on = None

SCHEMA = """
CREATE TABLE case_premium_pair (
    pair_id        bigserial PRIMARY KEY,
    snapshot_id    uuid NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    merchant_id    text NOT NULL REFERENCES merchant(merchant_id),
    wine_id        uuid NOT NULL REFERENCES wine(wine_id) ON DELETE CASCADE,
    vintage        integer NOT NULL,
    bottle_ml      integer NOT NULL CHECK (bottle_ml > 0),
    duty_status    text NOT NULL,
    captured_at    timestamptz NOT NULL,

    smaller_pack   integer NOT NULL CHECK (smaller_pack >= 1),
    smaller_price  numeric(14,2) NOT NULL CHECK (smaller_price > 0),
    larger_pack    integer NOT NULL CHECK (larger_pack > 1),
    larger_price   numeric(14,2) NOT NULL CHECK (larger_price > 0),
    ratio          numeric(10,6) NOT NULL CHECK (ratio > 0),

    is_loose_pair  boolean NOT NULL GENERATED ALWAYS AS (smaller_pack = 1) STORED,

    CONSTRAINT case_premium_pair_order CHECK (larger_pack > smaller_pack),
    UNIQUE (snapshot_id, wine_id, vintage, bottle_ml, duty_status, smaller_pack, larger_pack)
);

CREATE INDEX case_premium_pair_measure ON case_premium_pair (bottle_ml, captured_at)
    WHERE is_loose_pair;
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP TABLE case_premium_pair")
