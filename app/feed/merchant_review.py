"""Minimal merchant review (decision 0051). A merchant a market feed
introduced arrives unapproved and sets no Floor (decision 0048). An operator
approves it or keeps it unapproved — never automatically. Approval changes
nothing here but `merchant.approved`: whether its evidence may then contribute
to Floor is decided, as always, by the core's own screens at benchmark time."""
from __future__ import annotations

from typing import Optional

import psycopg

_LIST = """
    SELECT m.merchant_id, m.name, m.reviewed_at,
           coalesce(array_agg(DISTINCT sm.scope_params->>'acquisition_source')
                    FILTER (WHERE sm.scope_params->>'acquisition_source' IS NOT NULL), ARRAY[]::text[]) AS sources,
           (SELECT count(*) FROM offer o WHERE o.merchant_id = m.merchant_id)
         + (SELECT count(*) FROM offer_reject r WHERE r.merchant_id = m.merchant_id) AS observations
      FROM merchant m
      LEFT JOIN snapshot_merchant sm ON sm.merchant_id = m.merchant_id
     WHERE NOT m.approved {extra}
     GROUP BY m.merchant_id
     ORDER BY m.name"""


def to_review(conn: psycopg.Connection) -> list[dict]:
    """Unapproved and never reviewed: what To Review counts and lists."""
    return conn.execute(_LIST.format(extra="AND m.reviewed_at IS NULL")).fetchall()


def kept_unapproved(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(_LIST.format(extra="AND m.reviewed_at IS NOT NULL")).fetchall()


def review(conn: psycopg.Connection, merchant_id: str, *, approve: bool,
           reviewed_by: str) -> Optional[dict]:
    """Approve, or keep unapproved. Only an unapproved merchant is reviewed
    here; an approved one is not un-approved by this path."""
    return conn.execute(
        """UPDATE merchant SET approved = %s, reviewed_by = %s, reviewed_at = now()
            WHERE merchant_id = %s AND NOT approved RETURNING merchant_id, name, approved""",
        (approve, reviewed_by, merchant_id)).fetchone()
