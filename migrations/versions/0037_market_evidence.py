"""Pocket cache fingerprint and auditable auction imports; no new tables."""

from alembic import op

revision = "0037_market_evidence"
down_revision = "0036_confirmed_commercial"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE benchmark_run ADD COLUMN evidence_key text")
    op.execute(
        "ALTER TABLE auction_evidence ADD COLUMN raw_evidence jsonb NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute("ALTER TABLE auction_evidence ADD COLUMN import_key text")
    op.execute(
        "CREATE UNIQUE INDEX auction_evidence_import_active ON auction_evidence (import_key) WHERE import_key IS NOT NULL AND retracted_at IS NULL"
    )


def downgrade():
    op.execute("DROP INDEX auction_evidence_import_active")
    op.execute("ALTER TABLE auction_evidence DROP COLUMN import_key")
    op.execute("ALTER TABLE auction_evidence DROP COLUMN raw_evidence")
    op.execute("ALTER TABLE benchmark_run DROP COLUMN evidence_key")
