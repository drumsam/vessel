"""inbound_offer -- VESSEL Pocket, decision pending (build brief, Phase 1b
step 2): the capture table for Screen 1 (NEW) and Screen 2 (CANDIDATE).

The raw record is sacred, same discipline as `seller_line.raw_row`:
`raw_body`/`raw_media` are stored VERBATIM, before any AI call is ever
made, and are never rewritten by a re-parse -- only `parse_state`,
`parse_error` and `parsed_at` move. A bad parse is re-parsed, never
reconstructed, so no structured proposal field is persisted here; the
AI's output is shown once, in the response to the call that produced it,
and re-derived on retry.

`category` ('wine'|'whisky'|'unknown') is the one proposal fact that IS
persisted, because `buy-side-margin-test.md` needs it to survive past
the single request that produced it: a whisky offer is captured exactly
like a wine one and flagged `UNPRICEABLE_CATEGORY` at identity
resolution, never silently dropped for being the wrong category.

`confirmed_wine_id` and `identity_confirmed_by`/`_at` are the operator's
own confirmed identity (Screen 2's actual job: "confirm/correct
identity") -- not the AI's proposal, which is never authoritative and
never stored, and not free text either: this points at a real, already-
approved row in `wine` (the same register decision 0043 seeded), reusing
the identity the rest of the system already trusts rather than inventing
a second, looser one. This is also the photo gate's technical
enforcement point: `wine.want_list` is already a persisted fact on that
row (decision 0038), so `app.api.inbound.confirm_identity` can check it
directly and refuse to set these columns for a want-list wine without an
explicit acknowledgement -- invariant 14, who did something is the
server's answer, never invented.

`created_by` records who captured it, same invariant. `deal_id` stays
null through Screens 1-2; it is set once this becomes a real deal with
a real `seller_line`, which is Screen 3's job, not this one's.

Revision ID: 0034_inbound_offer
Revises: 0033_want_list_wine_fields
Create Date: 2026-10-28
"""
from alembic import op

revision = "0034_inbound_offer"
down_revision = "0033_want_list_wine_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE inbound_offer (
            inbound_offer_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            received_at         timestamptz NOT NULL DEFAULT now(),
            channel             text NOT NULL
                                 CHECK (channel IN ('paste', 'photo', 'upload')),
            raw_body            text,
            raw_media           bytea,
            media_mime          text,
            parsed_at           timestamptz,
            parse_state         text NOT NULL DEFAULT 'pending'
                                 CHECK (parse_state IN ('pending', 'parsed', 'unparseable')),
            parse_error         text,
            category            text
                                 CHECK (category IN ('wine', 'whisky', 'unknown')),
            confirmed_wine_id   uuid REFERENCES wine(wine_id),
            confirmed_vintage   integer,
            confirmed_bottle_ml integer,
            confirmed_pack_size integer,
            identity_confirmed_by uuid REFERENCES operator(operator_id),
            identity_confirmed_at timestamptz,
            deal_id             uuid REFERENCES deal(deal_id),
            created_by          uuid NOT NULL REFERENCES operator(operator_id),
            CONSTRAINT inbound_offer_has_raw_input CHECK (
                raw_body IS NOT NULL OR raw_media IS NOT NULL),
            CONSTRAINT inbound_offer_confirmation_is_attributed CHECK (
                (identity_confirmed_by IS NULL) = (identity_confirmed_at IS NULL))
        )
    """)
    op.execute("CREATE INDEX inbound_offer_parse_state_idx ON inbound_offer (parse_state)")


def downgrade() -> None:
    op.execute("DROP TABLE inbound_offer")
