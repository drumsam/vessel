"""The client want list, as identity rules and a listing-side gate
(decision 0038): wine.want_list, set from the producer alone at creation
time (app/identity/want_list.py::is_want_list_producer), and
seller_line.want_list_ack_by/_at, a one-time operator acknowledgement
tied to the line's own identity -- not to any one pricing run, so it
survives a reprice.

Not a new flag in app/core/ and not folded into requires_acknowledgement:
Doug's own words, "a listing-side requirement, the same way decision
0025's invite gate sits outside the engine."

Revision ID: 0029_want_list
Revises: 0028_deal_city
Create Date: 2026-10-24
"""
from alembic import op

revision = "0029_want_list"
down_revision = "0028_deal_city"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE wine ADD COLUMN want_list boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE seller_line ADD COLUMN want_list_ack_by uuid REFERENCES operator(operator_id)")
    op.execute("ALTER TABLE seller_line ADD COLUMN want_list_ack_at timestamptz")
    op.execute("""ALTER TABLE seller_line ADD CONSTRAINT seller_line_want_list_ack_paired CHECK (
        (want_list_ack_by IS NULL AND want_list_ack_at IS NULL)
     OR (want_list_ack_by IS NOT NULL AND want_list_ack_at IS NOT NULL))""")


def downgrade() -> None:
    op.execute("ALTER TABLE seller_line DROP CONSTRAINT seller_line_want_list_ack_paired")
    op.execute("ALTER TABLE seller_line DROP COLUMN want_list_ack_at")
    op.execute("ALTER TABLE seller_line DROP COLUMN want_list_ack_by")
    op.execute("ALTER TABLE wine DROP COLUMN want_list")
