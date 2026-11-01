"""Minimal merchant review (decision 0051).

A merchant a market feed introduced arrives unapproved (decision 0048). An
operator either approves it or keeps it unapproved; both are recorded with who
and when, so a kept merchant leaves the review list instead of returning to
it. Approval is never automatic.

Revision ID: 0041_merchant_review
Revises: 0040_counterparties
Create Date: 2026-11-01
"""
from alembic import op

revision = "0041_merchant_review"
down_revision = "0040_counterparties"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE merchant ADD COLUMN reviewed_by uuid REFERENCES operator(operator_id)")
    op.execute("ALTER TABLE merchant ADD COLUMN reviewed_at timestamptz")
    op.execute("""ALTER TABLE merchant ADD CONSTRAINT merchant_review_attributed
                  CHECK ((reviewed_at IS NULL) = (reviewed_by IS NULL))""")


def downgrade() -> None:
    op.execute("ALTER TABLE merchant DROP CONSTRAINT merchant_review_attributed")
    op.execute("ALTER TABLE merchant DROP COLUMN reviewed_at")
    op.execute("ALTER TABLE merchant DROP COLUMN reviewed_by")
