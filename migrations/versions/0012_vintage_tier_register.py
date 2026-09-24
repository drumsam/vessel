"""The vintage register is a file, not a screen.

Decision 0015 as revised 24 September. `vintage_tier` now carries the register's
own columns (tier_label, sources, note) and is loaded from
docs/research/vintage-tiers.csv by scripts/load_vintage_tiers.py. Nobody types
into it, so `set_by` becomes the file and its revision rather than an operator.

`region` carries the colour — 2014 Burgundy is tier 3 red and tier 1 white — so
a colour-blind register would produce nonsense bands.

Revision ID: 0012_vintage_tier_register
Revises: 0011_vintage_band
Create Date: 2026-09-24
"""
from alembic import op

revision = "0012_vintage_tier_register"
down_revision = "0011_vintage_band"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The table has never been populated: it was added yesterday and only the
    # loader writes to it. Rebuilt rather than migrated row by row.
    op.execute("DELETE FROM vintage_tier")
    op.execute("ALTER TABLE vintage_tier DROP CONSTRAINT vintage_tier_set_by_fkey")
    op.execute("ALTER TABLE vintage_tier ALTER COLUMN set_by TYPE text USING set_by::text")
    op.execute("ALTER TABLE vintage_tier RENAME COLUMN source TO sources")
    op.execute("ALTER TABLE vintage_tier ADD COLUMN tier_label text NOT NULL")
    op.execute("ALTER TABLE vintage_tier ADD COLUMN note text")


def downgrade() -> None:
    op.execute("DELETE FROM vintage_tier")
    op.execute("ALTER TABLE vintage_tier DROP COLUMN note")
    op.execute("ALTER TABLE vintage_tier DROP COLUMN tier_label")
    op.execute("ALTER TABLE vintage_tier RENAME COLUMN sources TO source")
    op.execute("ALTER TABLE vintage_tier ALTER COLUMN set_by TYPE uuid USING set_by::uuid")
    op.execute("""ALTER TABLE vintage_tier ADD CONSTRAINT vintage_tier_set_by_fkey
                  FOREIGN KEY (set_by) REFERENCES operator(operator_id)""")
