"""Supplier and client registers (decision 0050) — commercial memory, not a
CRM: one canonical record per counterparty, aliases so name variants land on
it, and the few defaults that save typing. Nothing here is required at trade
capture; a supplier or client can be created inline from a name alone."""
from __future__ import annotations

from typing import Optional

import psycopg

from app.identity.resolver import norm

SUPPLIER_FIELDS = ("name", "contact_name", "phone", "email", "notes", "active",
                   "default_currency", "usual_stock_location", "usual_bond_status", "payment_terms")
CLIENT_FIELDS = ("name", "contact_name", "phone", "email", "notes", "active",
                 "default_currency", "delivery_notes", "payment_terms")


def _update(conn, table: str, key: str, id_: str, fields: tuple, changes: dict) -> Optional[dict]:
    sets = {k: v for k, v in changes.items() if k in fields}
    if not sets:
        return conn.execute(f"SELECT * FROM {table} WHERE {key} = %s", (id_,)).fetchone()
    assignments = ", ".join(f"{k} = %({k})s" for k in sets)
    return conn.execute(f"UPDATE {table} SET {assignments} WHERE {key} = %(id)s RETURNING *",
                        {**sets, "id": id_}).fetchone()


# ------------------------------------------------------------------ suppliers


def get_supplier(conn: psycopg.Connection, supplier_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM supplier WHERE supplier_id = %s", (supplier_id,)).fetchone()
    if row:
        row["aliases"] = [r["alias"] for r in conn.execute(
            "SELECT alias FROM supplier_alias WHERE supplier_id = %s ORDER BY alias", (supplier_id,))]
        row["trades"] = conn.execute(
            "SELECT count(*) AS n FROM inbound_offer WHERE supplier_id = %s AND discarded_at IS NULL",
            (supplier_id,)).fetchone()["n"]
    return row


def update_supplier(conn: psycopg.Connection, supplier_id: str, changes: dict) -> Optional[dict]:
    if _update(conn, "supplier", "supplier_id", supplier_id, SUPPLIER_FIELDS, changes) is None:
        return None
    return get_supplier(conn, supplier_id)


def all_suppliers(conn: psycopg.Connection) -> list[dict]:
    """Every supplier, active first, most recently used first — the register
    view (GET /suppliers keeps returning the active chip-row list)."""
    return conn.execute("""
        SELECT s.*, MAX(io.identity_confirmed_at) AS last_used_at
          FROM supplier s LEFT JOIN inbound_offer io ON io.supplier_id = s.supplier_id
         GROUP BY s.supplier_id
         ORDER BY s.active DESC, last_used_at DESC NULLS LAST, s.name""").fetchall()


def add_supplier_alias(conn: psycopg.Connection, supplier_id: str, alias: str) -> None:
    conn.execute("""INSERT INTO supplier_alias (supplier_id, alias) VALUES (%s, %s)
                    ON CONFLICT DO NOTHING""", (supplier_id, norm(alias)))


# -------------------------------------------------------------------- clients


def create_client(conn: psycopg.Connection, *, name: str, created_by: str,
                  phone: Optional[str] = None) -> dict:
    row = conn.execute("INSERT INTO client (name, phone, created_by) VALUES (%s, %s, %s) RETURNING *",
                       (name.strip(), phone, created_by)).fetchone()
    add_client_alias(conn, str(row["client_id"]), name)
    return get_client(conn, str(row["client_id"]))


def get_client(conn: psycopg.Connection, client_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM client WHERE client_id = %s", (client_id,)).fetchone()
    if row:
        row["aliases"] = [r["alias"] for r in conn.execute(
            "SELECT alias FROM client_alias WHERE client_id = %s ORDER BY alias", (client_id,))]
        row["trades"] = conn.execute("SELECT count(*) AS n FROM fulfilment WHERE client_id = %s",
                                     (client_id,)).fetchone()["n"]
    return row


def update_client(conn: psycopg.Connection, client_id: str, changes: dict) -> Optional[dict]:
    if _update(conn, "client", "client_id", client_id, CLIENT_FIELDS, changes) is None:
        return None
    return get_client(conn, client_id)


def list_clients(conn: psycopg.Connection) -> list[dict]:
    """Active first, most recently traded first — the picker's own order."""
    return conn.execute("""
        SELECT c.*, MAX(f.confirmed_at) AS last_used_at
          FROM client c LEFT JOIN fulfilment f ON f.client_id = c.client_id
         GROUP BY c.client_id
         ORDER BY c.active DESC, last_used_at DESC NULLS LAST, c.name""").fetchall()


def add_client_alias(conn: psycopg.Connection, client_id: str, alias: str) -> None:
    conn.execute("""INSERT INTO client_alias (client_id, alias) VALUES (%s, %s)
                    ON CONFLICT DO NOTHING""", (client_id, norm(alias)))

