"""Operators, server-side sessions, and audit rows that point at an operator id.

Decision 0009. Every "who" column becomes a foreign key to `operator` instead of
a copied name, so renaming someone does not rewrite the past, and access is
revoked with `active` rather than by deleting a row the history points at.

Names written before this migration are preserved as INACTIVE operator rows,
one per distinct name, marked as imported. They cannot log in — they have no
usable password hash — but the audit trail keeps resolving.

Revision ID: 0006_operators_and_sessions
Revises: 0005_export_gate_alias_rules
Create Date: 2026-09-20
"""
from alembic import op

revision = "0006_operators_and_sessions"
down_revision = "0005_export_gate_alias_rules"
branch_labels = None
depends_on = None

#: table, column, NOT NULL
AUDIT_COLUMNS = [
    ("wine_alias", "approved_by", True),
    ("lwin_conflict", "resolved_by", False),
    ("merchant_lwin_untrusted", "marked_by", True),
    ("deal", "created_by", True),
    ("seller_line", "wine_id_approved_by", False),
    ("seller_line_identity_history", "changed_by", True),
    ("pricing_result", "priced_by", True),
    ("pricing_acknowledgement", "acknowledged_by", True),
    ("buyer_offer", "issued_by", True),
]

#: argon2id refuses to verify this, so an imported operator cannot log in.
NO_LOGIN = "imported-no-login"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE operator (
            operator_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            username      text NOT NULL UNIQUE,
            display_name  text NOT NULL,
            password_hash text NOT NULL,
            active        boolean NOT NULL DEFAULT true,
            created_at    timestamptz NOT NULL DEFAULT now(),
            note          text
        )""")
    op.execute("""
        CREATE TABLE operator_session (
            session_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            operator_id uuid NOT NULL REFERENCES operator(operator_id),
            token_hash  text NOT NULL UNIQUE,
            created_at  timestamptz NOT NULL DEFAULT now(),
            expires_at  timestamptz NOT NULL,
            revoked_at  timestamptz
        )""")
    op.execute("CREATE INDEX operator_session_operator ON operator_session (operator_id)")

    # One inactive operator per distinct name already written anywhere.
    names = " UNION ".join(
        f"SELECT DISTINCT {column} AS name FROM {table} WHERE {column} IS NOT NULL"
        for table, column, _ in AUDIT_COLUMNS)
    op.execute(f"""
        INSERT INTO operator (username, display_name, password_hash, active, note)
        SELECT name, name, '{NO_LOGIN}', false,
               'imported by migration 0006 from a pre-session audit row'
          FROM ({names}) n
         WHERE name <> ''""")

    for table, column, not_null in AUDIT_COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN {column}_operator uuid "
                   f"REFERENCES operator(operator_id)")
        op.execute(f"""UPDATE {table} t SET {column}_operator = o.operator_id
                         FROM operator o WHERE o.username = t.{column}""")
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        op.execute(f"ALTER TABLE {table} RENAME COLUMN {column}_operator TO {column}")
        # A renamed column keeps its constraint's old name; make it the one
        # CREATE TABLE would have generated, so schema.sql and head agree.
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT "
                   f"{table}_{column}_operator_fkey TO {table}_{column}_fkey")
        if not_null:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL")

    # Rebuilt because dropping a column drops the constraints that mention it.
    op.execute("""
        ALTER TABLE lwin_conflict ADD CONSTRAINT lwin_conflict_resolved CHECK (
            (resolution IS NULL AND resolved_by IS NULL AND resolved_at IS NULL)
         OR (resolution IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL))""")
    op.execute("""
        ALTER TABLE seller_line ADD CONSTRAINT seller_line_identity_approved CHECK (
            (wine_id IS NULL AND wine_id_source IS NULL
             AND wine_id_approved_by IS NULL AND wine_id_approved_at IS NULL)
         OR (wine_id IS NOT NULL AND wine_id_source IS NOT NULL
             AND wine_id_approved_by IS NOT NULL AND wine_id_approved_at IS NOT NULL))""")


def downgrade() -> None:
    for table, column, not_null in AUDIT_COLUMNS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN {column}_name text")
        op.execute(f"""UPDATE {table} t SET {column}_name = o.username
                         FROM operator o WHERE o.operator_id = t.{column}""")
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        op.execute(f"ALTER TABLE {table} RENAME COLUMN {column}_name TO {column}")
        if not_null:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL")

    op.execute("""
        ALTER TABLE lwin_conflict ADD CONSTRAINT lwin_conflict_resolved CHECK (
            (resolution IS NULL AND resolved_by IS NULL AND resolved_at IS NULL)
         OR (resolution IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL))""")
    op.execute("""
        ALTER TABLE seller_line ADD CONSTRAINT seller_line_identity_approved CHECK (
            (wine_id IS NULL AND wine_id_source IS NULL
             AND wine_id_approved_by IS NULL AND wine_id_approved_at IS NULL)
         OR (wine_id IS NOT NULL AND wine_id_source IS NOT NULL
             AND wine_id_approved_by IS NOT NULL AND wine_id_approved_at IS NOT NULL))""")

    op.execute("DROP TABLE operator_session")
    op.execute("DROP TABLE operator")
