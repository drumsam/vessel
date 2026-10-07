"""Register Bordeaux Index LiveTrade — step 6 of "Adding a merchant adapter".

An exception to migration 0002's own stated rule ("The ids must equal each
adapter's `id` attribute, because offers are written with
`merchant_id = adapter.id`"), made deliberately and explained here rather
than quietly: `bordeaux-index-livetrade` is registered so collection,
politeness and LWIN-conflict tracking can address LiveTrade on its own —
but every `Offer` the adapter produces is published under
`merchant_id = 'bordeaux-index'`, the SAME row the sibling adapter already
uses. LiveTrade and the regular fine-wine listing pages are one company
publishing two different views of its own book; registering a second row
and letting offers carry it would double-count that one company as two
merchants the moment both pages happen to have a price on the same day
(invariant 4: a merchant never becomes its own second comp). See
docs/decisions/0027 and app/adapters/bordeaux_index_livetrade.py.

Revision ID: 0022_bordeaux_index_livetrade
Revises: 0021_bid_last_trade
Create Date: 2026-10-08
"""
from alembic import op

revision = "0022_bordeaux_index_livetrade"
down_revision = "0021_bid_last_trade"
branch_labels = None
depends_on = None

MERCHANT_ID = "bordeaux-index-livetrade"
NAME = "Bordeaux Index LiveTrade"
NOTES = ("Server-rendered JSON embedded in the search page markup (data-item "
        "attributes), no scraping of display text. Verified live 2026-10-08. "
        "Offers are published under merchant_id bordeaux-index (see this "
        "migration docstring), not this id.")


def upgrade() -> None:
    op.execute(
        "INSERT INTO merchant (merchant_id, name, approved, notes) "
        f"VALUES ('{MERCHANT_ID}', '{NAME}', true, '{NOTES}')"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM merchant WHERE merchant_id = '{MERCHANT_ID}'")
