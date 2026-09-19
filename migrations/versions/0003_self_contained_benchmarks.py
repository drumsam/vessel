"""Self-contained benchmarks, freshness, identity audit, pricing and buyer offers.

Decisions 0003 (offer freshness), 0004 (benchmark self-containment and snapshot
retention) and 0005 (inherited line flags).

* snapshot_merchant: per-merchant capture, scope and outcome within a snapshot.
* benchmark_run: snapshot_id is replaced by as_of and benchmark_run_snapshot
  (one contributing capture per merchant, SET NULL when pruned).
* benchmark_comp: surrogate key, offer_snapshot (the offer as used), offer_pk
  SET NULL when pruned.
* offer.wine_id NOT NULL; unresolved offers move to offer_reject.
* CHECKs on offer.stock_type and offer.condition_flags; wine_exclusion stored
  lower id first.
* seller_line identity approval columns and line flags; identity history.
* pricing_result, buyer_offer, buyer_offer_line.

Constraint names are spelled out so that `upgrade head` reproduces
app/db/schema.sql exactly (tests/test_service.py checks this).

Revision ID: 0003_self_contained_benchmarks
Revises: 0002_seed_verified_merchants
Create Date: 2026-09-19
"""
from alembic import op

revision = "0003_self_contained_benchmarks"
down_revision = "0002_seed_verified_merchants"
branch_labels = None
depends_on = None

STOCK_TYPES = "'MERCHANT_STOCK','CLIENT_STOCK','BROKERED','MARKETPLACE','UNKNOWN'"
CONDITION_FLAGS = ("'ORIGINAL_CASE','REPACK','NO_ORIGINAL_CASE','NON_PRISTINE','LABEL_DAMAGE',"
                   "'LEVEL_ISSUE','LEVEL_NOTED','CAPSULE_OR_CORK','SIGNS_OF_SEEPAGE'")
LINE_FLAGS = "'NAME_REVIEW','FORMAT_REVIEW','DERIVED_FROM_CASE'"
ID_SOURCES = "'lwin','alias','operator','ai_reviewed'"

# Must build the same document as app.db.repo.offer_snapshot().
OFFER_SNAPSHOT_SQL = """
    jsonb_build_object(
        'merchant_id', o.merchant_id, 'merchant', m.name, 'merchant_offer_id', o.offer_id,
        'wine_id', o.wine_id, 'vintage', o.vintage, 'bottle_ml', o.bottle_ml,
        'pack_size', o.pack_size, 'price', o.price::text, 'currency', o.currency,
        'duty_status', o.duty_status, 'price_kind', o.price_kind,
        'is_buyable', o.is_buyable, 'offered_units', o.offered_units,
        'is_mixed_lot', o.is_mixed_lot, 'stock_type', o.stock_type,
        'stock_type_basis', o.stock_type_basis, 'condition_flags', to_jsonb(o.condition_flags),
        'condition_notes', o.condition_notes, 'source_url', o.source_url,
        'captured_at', o.captured_at,
        'per_bottle', CASE WHEN c.role = 'cross_unit' THEN (o.price / o.pack_size)::text END)
"""


def upgrade() -> None:
    # ------------------------------------------------ wine_exclusion ordering
    op.execute("""
        UPDATE wine_exclusion k
           SET reason = k.reason || ' / ' || d.reason
          FROM wine_exclusion d
         WHERE k.wine_id_a < k.wine_id_b
           AND d.wine_id_a = k.wine_id_b AND d.wine_id_b = k.wine_id_a
           AND d.reason <> k.reason""")
    op.execute("""
        DELETE FROM wine_exclusion d
         WHERE d.wine_id_a > d.wine_id_b
           AND EXISTS (SELECT 1 FROM wine_exclusion k
                        WHERE k.wine_id_a = d.wine_id_b AND k.wine_id_b = d.wine_id_a)""")
    op.execute("""
        UPDATE wine_exclusion SET wine_id_a = wine_id_b, wine_id_b = wine_id_a
         WHERE wine_id_a > wine_id_b""")
    op.execute("ALTER TABLE wine_exclusion DROP CONSTRAINT wine_exclusion_check")
    op.execute("ALTER TABLE wine_exclusion ADD CONSTRAINT wine_exclusion_check "
               "CHECK (wine_id_a < wine_id_b)")

    # ------------------------------------------------------ snapshot_merchant
    op.execute("""
        CREATE TABLE snapshot_merchant (
            snapshot_id        uuid NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
            merchant_id        text NOT NULL REFERENCES merchant(merchant_id),
            status             text NOT NULL CHECK (status IN ('ok','failed')),
            captured_at        timestamptz NOT NULL,
            scope_producer_key text,
            scope_vintage      int,
            scope_params       jsonb NOT NULL DEFAULT '{}'::jsonb,
            offers_written     int NOT NULL DEFAULT 0,
            offers_rejected    int NOT NULL DEFAULT 0,
            error              text,
            PRIMARY KEY (snapshot_id, merchant_id),
            CONSTRAINT snapshot_merchant_scope
                CHECK ((scope_producer_key IS NULL) = (scope_vintage IS NULL)),
            CONSTRAINT snapshot_merchant_error CHECK ((status = 'failed') = (error IS NOT NULL))
        )""")
    op.execute("""
        CREATE INDEX snapshot_merchant_latest ON snapshot_merchant (merchant_id, captured_at)
            WHERE status = 'ok'""")
    # Every snapshot before 0003 was a whole-book collection.
    op.execute("""
        INSERT INTO snapshot_merchant (snapshot_id, merchant_id, status, captured_at,
                                       offers_written, offers_rejected)
        SELECT s.snapshot_id, x.merchant_id, 'ok', s.captured_at,
               (SELECT count(*) FROM offer o
                 WHERE o.snapshot_id = s.snapshot_id AND o.merchant_id = x.merchant_id
                   AND o.wine_id IS NOT NULL),
               (SELECT count(*) FROM offer_reject r
                 WHERE r.snapshot_id = s.snapshot_id AND r.merchant_id = x.merchant_id)
             + (SELECT count(*) FROM offer o
                 WHERE o.snapshot_id = s.snapshot_id AND o.merchant_id = x.merchant_id
                   AND o.wine_id IS NULL)       -- moved to offer_reject below
          FROM snapshot s
          JOIN (SELECT snapshot_id, merchant_id FROM offer
                UNION SELECT snapshot_id, merchant_id FROM offer_reject) x
            ON x.snapshot_id = s.snapshot_id""")
    op.execute("""
        INSERT INTO snapshot_merchant (snapshot_id, merchant_id, status, captured_at, error)
        SELECT s.snapshot_id, f->>'merchant_id', 'failed', s.captured_at,
               coalesce(f->>'error', 'unrecorded')
          FROM snapshot s, jsonb_array_elements(s.failures) f
         WHERE f->>'merchant_id' IN (SELECT merchant_id FROM merchant)
           AND NOT EXISTS (SELECT 1 FROM snapshot_merchant sm
                            WHERE sm.snapshot_id = s.snapshot_id
                              AND sm.merchant_id = f->>'merchant_id')""")

    # ------------------------------------------------------------------ offer
    op.execute("""
        INSERT INTO offer_reject (snapshot_id, merchant_id, reason, detail, raw)
        SELECT snapshot_id, merchant_id, 'UNRESOLVED_IDENTITY',
               'moved from offer by migration 0003',
               jsonb_build_object('merchant_record', raw, 'offer_id', offer_id)
          FROM offer WHERE wine_id IS NULL""")
    op.execute("DELETE FROM offer WHERE wine_id IS NULL")
    op.execute("ALTER TABLE offer ALTER COLUMN wine_id SET NOT NULL")
    op.execute(f"ALTER TABLE offer ADD CONSTRAINT offer_stock_type_check "
               f"CHECK (stock_type IN ({STOCK_TYPES}))")
    op.execute(f"ALTER TABLE offer ADD CONSTRAINT offer_condition_flags_check "
               f"CHECK (condition_flags <@ ARRAY[{CONDITION_FLAGS}]::text[])")

    # ------------------------------------------------------------ seller_line
    op.execute("ALTER TABLE seller_line ADD COLUMN wine_id_source text")
    op.execute("ALTER TABLE seller_line ADD COLUMN wine_id_approved_by text")
    op.execute("ALTER TABLE seller_line ADD COLUMN wine_id_approved_at timestamptz")
    op.execute("ALTER TABLE seller_line ADD COLUMN flags text[] NOT NULL DEFAULT '{}'")
    op.execute(f"ALTER TABLE seller_line ADD CONSTRAINT seller_line_wine_id_source_check "
               f"CHECK (wine_id_source IN ({ID_SOURCES}))")
    op.execute(f"ALTER TABLE seller_line ADD CONSTRAINT seller_line_flags_check "
               f"CHECK (flags <@ ARRAY[{LINE_FLAGS}]::text[])")
    # Identities set before 0003 have no recorded approver. Say so, rather than
    # invent one or silently discard the operator's work.
    op.execute("""
        UPDATE seller_line
           SET wine_id_source = 'operator',
               wine_id_approved_by = 'unrecorded: approved before migration 0003',
               wine_id_approved_at = now()
         WHERE wine_id IS NOT NULL""")
    op.execute("""
        ALTER TABLE seller_line ADD CONSTRAINT seller_line_identity_approved CHECK (
            (wine_id IS NULL AND wine_id_source IS NULL
             AND wine_id_approved_by IS NULL AND wine_id_approved_at IS NULL)
         OR (wine_id IS NOT NULL AND wine_id_source IS NOT NULL
             AND wine_id_approved_by IS NOT NULL AND wine_id_approved_at IS NOT NULL))""")
    op.execute(f"""
        CREATE TABLE seller_line_identity_history (
            history_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            line_id         uuid NOT NULL REFERENCES seller_line(line_id) ON DELETE CASCADE,
            prev_wine_id    uuid REFERENCES wine(wine_id),
            prev_vintage    int,
            prev_bottle_ml  int,
            prev_pack_size  int,
            prev_flags      text[] NOT NULL,
            new_wine_id     uuid NOT NULL REFERENCES wine(wine_id),
            new_vintage     int NOT NULL,
            new_bottle_ml   int NOT NULL,
            new_pack_size   int NOT NULL,
            new_flags       text[] NOT NULL,
            source          text NOT NULL CHECK (source IN ({ID_SOURCES})),
            changed_by      text NOT NULL,
            changed_at      timestamptz NOT NULL DEFAULT now()
        )""")

    # ---------------------------------------------------------- benchmark_run
    op.execute("ALTER TABLE benchmark_run ADD COLUMN as_of timestamptz")
    op.execute("UPDATE benchmark_run SET as_of = computed_at")
    op.execute("ALTER TABLE benchmark_run ALTER COLUMN as_of SET NOT NULL")
    op.execute("ALTER TABLE benchmark_run ADD COLUMN oldest_comp_age interval")
    op.execute("""
        CREATE TABLE benchmark_run_snapshot (
            run_id       uuid NOT NULL REFERENCES benchmark_run(run_id) ON DELETE CASCADE,
            merchant_id  text NOT NULL REFERENCES merchant(merchant_id),
            snapshot_id  uuid REFERENCES snapshot(snapshot_id) ON DELETE SET NULL,
            captured_at  timestamptz NOT NULL,
            PRIMARY KEY (run_id, merchant_id)
        )""")
    op.execute("""
        INSERT INTO benchmark_run_snapshot (run_id, merchant_id, snapshot_id, captured_at)
        SELECT r.run_id, sm.merchant_id, r.snapshot_id, sm.captured_at
          FROM benchmark_run r
          JOIN snapshot_merchant sm ON sm.snapshot_id = r.snapshot_id AND sm.status = 'ok'""")
    op.execute("ALTER TABLE benchmark_run DROP COLUMN snapshot_id")

    # --------------------------------------------------------- benchmark_comp
    op.execute("ALTER TABLE benchmark_comp ADD COLUMN comp_id uuid NOT NULL DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE benchmark_comp ADD COLUMN offer_snapshot jsonb")
    op.execute(f"""
        UPDATE benchmark_comp c SET offer_snapshot = {OFFER_SNAPSHOT_SQL}
          FROM offer o JOIN merchant m ON m.merchant_id = o.merchant_id
         WHERE o.offer_pk = c.offer_pk""")
    op.execute("ALTER TABLE benchmark_comp ALTER COLUMN offer_snapshot SET NOT NULL")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_pkey")
    op.execute("ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_pkey PRIMARY KEY (comp_id)")
    op.execute("ALTER TABLE benchmark_comp ALTER COLUMN offer_pk DROP NOT NULL")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_offer_pk_fkey")
    op.execute("""ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_offer_pk_fkey
                  FOREIGN KEY (offer_pk) REFERENCES offer(offer_pk) ON DELETE SET NULL""")
    op.execute("""ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_run_id_offer_pk_role_key
                  UNIQUE (run_id, offer_pk, role)""")
    op.execute("""ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_reason
                  CHECK ((role = 'rejected') = (reject_reason IS NOT NULL))""")

    # ---------------------------------------------------------------- pricing
    op.execute("""
        CREATE TABLE pricing_result (
            pricing_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            line_id           uuid NOT NULL REFERENCES seller_line(line_id) ON DELETE CASCADE,
            run_id            uuid NOT NULL REFERENCES benchmark_run(run_id),
            priced_at         timestamptz NOT NULL DEFAULT now(),
            priced_by         text NOT NULL,
            uk_floor          numeric(14,2),
            uk_reference      numeric(14,2),
            uk_median         numeric(14,2),
            comp_count        int NOT NULL,
            auction_evidence  jsonb NOT NULL DEFAULT '[]'::jsonb,
            cost              numeric(14,2),
            cost_currency     char(3),
            fx_rate           numeric(18,8) CHECK (fx_rate > 0),
            fx_rate_date      date,
            fx_source         text,
            cost_gbp          numeric(14,2),
            target_margin     numeric(6,4),
            sell_price        numeric(14,2),
            sell_currency     char(3) NOT NULL DEFAULT 'GBP',
            gp                numeric(14,2),
            flags             text[] NOT NULL DEFAULT '{}',
            state             text NOT NULL CHECK (state IN ('READY','REVIEW','NO_MARKET')),
            CONSTRAINT pricing_result_cost_currency CHECK ((cost IS NULL) = (cost_currency IS NULL)),
            CONSTRAINT pricing_result_fx_recorded CHECK (
                cost IS NULL OR cost_currency = 'GBP'
                OR (fx_rate IS NOT NULL AND fx_rate_date IS NOT NULL AND fx_source IS NOT NULL))
        )""")

    # ----------------------------------------------------------- buyer offers
    op.execute("""
        CREATE TABLE buyer_offer (
            buyer_offer_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            deal_id        uuid NOT NULL REFERENCES deal(deal_id),
            client         text NOT NULL,
            currency       char(3) NOT NULL,
            issued_at      timestamptz NOT NULL,
            issued_by      text NOT NULL,
            terms          text
        )""")
    op.execute("""
        CREATE TABLE buyer_offer_line (
            buyer_offer_id  uuid NOT NULL REFERENCES buyer_offer(buyer_offer_id) ON DELETE CASCADE,
            line_no         int NOT NULL,
            line_id         uuid NOT NULL REFERENCES seller_line(line_id),
            pricing_id      uuid NOT NULL REFERENCES pricing_result(pricing_id),
            description     text NOT NULL,
            vintage         int NOT NULL,
            bottle_ml       int NOT NULL,
            pack_size       int NOT NULL,
            quantity        int NOT NULL CHECK (quantity > 0),
            unit_price      numeric(14,2) NOT NULL CHECK (unit_price > 0),
            line_total      numeric(14,2) NOT NULL,
            condition_notes text,
            PRIMARY KEY (buyer_offer_id, line_no),
            CONSTRAINT buyer_offer_line_total CHECK (line_total = unit_price * quantity)
        )""")


def downgrade() -> None:
    """Lossy where 0002 cannot represent the data: identity history, pricing,
    buyer offers and per-merchant provenance are dropped; comps whose offer was
    pruned are deleted; a run keeps only one of its snapshots."""
    op.execute("DROP TABLE buyer_offer_line")
    op.execute("DROP TABLE buyer_offer")
    op.execute("DROP TABLE pricing_result")

    op.execute("DELETE FROM benchmark_comp WHERE offer_pk IS NULL")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_reason")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_run_id_offer_pk_role_key")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_pkey")
    op.execute("ALTER TABLE benchmark_comp DROP CONSTRAINT benchmark_comp_offer_pk_fkey")
    op.execute("""ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_offer_pk_fkey
                  FOREIGN KEY (offer_pk) REFERENCES offer(offer_pk)""")
    op.execute("ALTER TABLE benchmark_comp ALTER COLUMN offer_pk SET NOT NULL")
    op.execute("ALTER TABLE benchmark_comp DROP COLUMN comp_id")
    op.execute("ALTER TABLE benchmark_comp DROP COLUMN offer_snapshot")
    op.execute("""ALTER TABLE benchmark_comp ADD CONSTRAINT benchmark_comp_pkey
                  PRIMARY KEY (run_id, offer_pk, role)""")

    op.execute("ALTER TABLE benchmark_run ADD COLUMN snapshot_id uuid REFERENCES snapshot(snapshot_id)")
    op.execute("""
        UPDATE benchmark_run r SET snapshot_id = (
            SELECT s.snapshot_id FROM benchmark_run_snapshot s
             WHERE s.run_id = r.run_id AND s.snapshot_id IS NOT NULL
             ORDER BY s.captured_at DESC LIMIT 1)""")
    op.execute("DROP TABLE benchmark_run_snapshot")
    op.execute("ALTER TABLE benchmark_run DROP COLUMN oldest_comp_age")
    op.execute("ALTER TABLE benchmark_run DROP COLUMN as_of")

    op.execute("DROP TABLE seller_line_identity_history")
    op.execute("ALTER TABLE seller_line DROP CONSTRAINT seller_line_identity_approved")
    op.execute("ALTER TABLE seller_line DROP COLUMN flags")
    op.execute("ALTER TABLE seller_line DROP COLUMN wine_id_approved_at")
    op.execute("ALTER TABLE seller_line DROP COLUMN wine_id_approved_by")
    op.execute("ALTER TABLE seller_line DROP COLUMN wine_id_source")

    op.execute("ALTER TABLE offer DROP CONSTRAINT offer_condition_flags_check")
    op.execute("ALTER TABLE offer DROP CONSTRAINT offer_stock_type_check")
    op.execute("ALTER TABLE offer ALTER COLUMN wine_id DROP NOT NULL")

    op.execute("DROP TABLE snapshot_merchant")

    op.execute("ALTER TABLE wine_exclusion DROP CONSTRAINT wine_exclusion_check")
    op.execute("ALTER TABLE wine_exclusion ADD CONSTRAINT wine_exclusion_check "
               "CHECK (wine_id_a <> wine_id_b)")
