"""The vintage-neighbour sanity check: tiers, the band on a run, and exclusions.

docs/research/vintage-neighbour-check-spec.md. The check runs after the
benchmark, on its result, and excludes only a DEAR comp — automatically
dropping a cheap one would push the Reference up and let us overprice a client.
Every automatic exclusion is recorded like a manual correction and can be put
back, which computes a new run.

Nothing here is read by pricing and nothing here reaches a buyer document.

Revision ID: 0011_vintage_band
Revises: 0010_ls_and_lw_trading
Create Date: 2026-09-24
"""
from alembic import op

revision = "0011_vintage_band"
down_revision = "0010_ls_and_lw_trading"
branch_labels = None
depends_on = None

SCHEMA = """
-- ================================================ vintage-neighbour sanity check

-- docs/research/vintage-neighbour-check-spec.md. A band is a sanity check on
-- comps we already hold, never a price: nothing in these three tables is read
-- by pricing, and nothing in them reaches a client document.

-- Operator-maintained, not a critic feed. One tier per region and vintage,
-- 1 = greatest. Rows missing means the band is not widened, which is the
-- conservative direction: the check speaks more often, not less.
CREATE TABLE vintage_tier (
    region      text     NOT NULL,              -- 'BURGUNDY_RED', 'BURGUNDY_WHITE', ...
    vintage     integer  NOT NULL,
    tier        smallint NOT NULL CHECK (tier BETWEEN 1 AND 5),
    source      text     NOT NULL,              -- who says so, in words
    set_by      uuid     NOT NULL REFERENCES operator(operator_id),
    set_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region, vintage)
);

-- The band as it stood for one run. Attached to the run, never to the
-- benchmark figures. band_low/band_high are NULL together when there were
-- fewer than two neighbouring vintages: silence, not a guess.
CREATE TABLE vintage_band_check (
    run_id          uuid PRIMARY KEY REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    unit            text NOT NULL,              -- '6x750', display only
    band_low        numeric(14,2),
    band_high       numeric(14,2),
    neighbours      jsonb NOT NULL DEFAULT '[]',   -- vintage, median, merchants, as_of, stale
    low_outliers    jsonb NOT NULL DEFAULT '[]',   -- flagged, never excluded (spec 5)
    format_incoherent jsonb NOT NULL DEFAULT '[]', -- per-bottle figures live here and nowhere else
    tiers_available boolean NOT NULL,
    note            text,
    CONSTRAINT vintage_band_edges_together CHECK ((band_low IS NULL) = (band_high IS NULL)),
    CONSTRAINT vintage_band_ordered CHECK (band_low IS NULL OR band_low <= band_high)
);

-- A comp the band excluded automatically, recorded exactly like a manual
-- correction: the offer, the edge it failed, the multiple, and who put it back.
-- Only a DEAR comp is ever excluded automatically (spec 5), so the flag is
-- constrained to one value: an automatic rule must never be able to delete a
-- cheap comp, which would push the Reference up and let us overprice a client.
CREATE TABLE benchmark_comp_exclusion (
    exclusion_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          uuid NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
    offer_pk        uuid REFERENCES offer(offer_pk) ON DELETE SET NULL,
    offer_snapshot  jsonb NOT NULL,             -- the offer as the run saw it; money is a string
    flag            text NOT NULL CHECK (flag = 'COMP_EXCLUDED_VINTAGE_BAND'),
    band_edge       numeric(14,2) NOT NULL,     -- band_high x HIGH_MULTIPLE, after widening
    band_multiple   numeric(6,4) NOT NULL,      -- price / edge, for the operator to see
    excluded_at     timestamptz NOT NULL DEFAULT now(),

    -- "Put it back": a new run computed with this comp restored, and who asked.
    reinstated_at   timestamptz,
    reinstated_by   uuid REFERENCES operator(operator_id),
    reinstated_reason text,
    replacement_run_id uuid REFERENCES benchmark_run(run_id),
    UNIQUE (run_id, offer_pk),
    CONSTRAINT comp_exclusion_reinstatement_complete CHECK (
        (reinstated_at IS NULL AND reinstated_by IS NULL AND reinstated_reason IS NULL
         AND replacement_run_id IS NULL)
        OR (reinstated_at IS NOT NULL AND reinstated_by IS NOT NULL
            AND reinstated_reason IS NOT NULL AND replacement_run_id IS NOT NULL))
);

CREATE INDEX comp_exclusion_open ON benchmark_comp_exclusion (run_id)
    WHERE reinstated_at IS NULL;
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP TABLE benchmark_comp_exclusion")
    op.execute("DROP TABLE vintage_band_check")
    op.execute("DROP TABLE vintage_tier")
