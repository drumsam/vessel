"""Shareable public offer links (decision 0035): a signed, unguessable,
read-only, time-boxed view of a chosen set of a deal's lines, for a buyer
or a seller who has no operator session and never will.

`kind` decides what `build_public_payload` ever puts in the dict it
returns -- a buyer-kind payload has no seller_price_gbp or commission_gbp
key at all, not merely a null one, and never the deal's own name or any
line outside the chosen set. No open-receipt or analytics column exists
on purpose -- Doug asked for none. Revocation does not exist either:
expiry is the only lifecycle a link has, out of scope for this decision.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional

import psycopg

from app.core.flags import claims_a_saving
from app.db import repo

#: secrets.token_urlsafe(32): 256 bits. Not guessable by iterating an id,
#: not shortened for looks -- this token is the only thing standing
#: between a buyer or seller and lines nobody else approved for them.
TOKEN_BYTES = 32
#: The offer's own stated validity window (matches the document's own
#: footer text, "open for 7 days").
DEFAULT_TTL_DAYS = 7


class LineNotInDeal(Exception):
    """A requested line_id does not belong to the deal named."""


class LineNotSendable(Exception):
    """A line still gated under invariant 12 cannot leave the system
    through a public link any more than through the buyer export -- a
    link given to someone outside this app IS an export."""


def create_link(conn: psycopg.Connection, *, deal_id: str, line_ids: list[str],
                kind: Literal["buyer", "seller"], fx_rate: Optional[Decimal],
                created_by: str, ttl_days: int = DEFAULT_TTL_DAYS) -> dict:
    deal_line_ids = {str(l["line_id"]) for l in repo.deal_lines(conn, deal_id)}
    unknown = [i for i in line_ids if str(i) not in deal_line_ids]
    if unknown:
        raise LineNotInDeal(f"not lines of this deal: {', '.join(str(i) for i in unknown)}")

    for line_id in line_ids:
        pricing = repo.latest_pricing(conn, str(line_id))
        if pricing is None:
            raise LineNotSendable(f"line {line_id} has not been priced")
        if pricing["requires_acknowledgement"] and not pricing["acknowledgement"]:
            raise LineNotSendable(f"line {line_id} is still REVIEW and has not been accepted")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    return conn.execute(
        """INSERT INTO shared_offer_link
               (token, deal_id, line_ids, kind, fx_rate, created_by, expires_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (token, deal_id, [str(i) for i in line_ids], kind, fx_rate, created_by, expires_at),
    ).fetchone()


def get_valid_link(conn: psycopg.Connection, token: str) -> Optional[dict]:
    """None for an unknown OR an expired token -- the public endpoint
    reads the two the same way, a plain 404, so a stale link reveals
    nothing about whether it ever existed."""
    return conn.execute(
        """SELECT * FROM shared_offer_link
            WHERE token = %s AND expires_at > now()""", (token,)).fetchone()


def build_public_payload(conn: psycopg.Connection, link: dict) -> dict:
    """The dict that becomes `PublicOfferOut`. Built fresh from
    `pricing_result` and the line's own benchmark run every time the link
    is opened -- a buyer re-opening it a day later sees today's state, not
    a snapshot frozen at creation, same discipline as everywhere else in
    this app ("as_of" is read, never cached as a decision).

    Only `line.benchmark`/`line.pricing` fields already safe for the
    public are read into the per-line dict below; seller_price_gbp and
    commission_gbp are added as a SEPARATE step, only when kind == "seller"
    -- so a buyer-kind payload's dict never holds the key, not merely a
    null value. Nothing here reads deal.name or deal.seller.
    """
    lines = []
    for line_id in link["line_ids"]:
        line = repo.get_line(conn, str(line_id))
        if line is None:
            continue
        pricing = repo.latest_pricing(conn, str(line_id))
        run = repo.latest_run(conn, str(line_id))
        if pricing is None or run is None:
            continue
        wine = repo.get_wine(conn, str(line["wine_id"])) if line["wine_id"] else None
        comps = [{**c["offer_snapshot"], "role": c["role"], "reject_reason": c["reject_reason"],
                 "offer_pk": c["offer_pk"]}
                for c in repo.run_comps(conn, run["run_id"]) if c["role"] == "merchant_best"]

        row = {
            "line_id": line["line_id"],
            "producer": wine["producer"] if wine else line["raw_description"],
            "cuvee": wine["cuvee"] if wine else "",
            "vintage": line["vintage"],
            "bottle_ml": line["bottle_ml"],
            "quantity": line["quantity"],
            "uk_floor": pricing["uk_floor"],
            "uk_reference": pricing["uk_reference"],
            "offer_price_gbp": pricing["buyer_price_gbp"] if pricing["buyer_price_gbp"] is not None
                                else pricing["sell_price"],
            "floor_saving_claim": (claims_a_saving(pricing["sell_price"], pricing["uk_floor"])
                                   if pricing["sell_price"] is not None else None),
            "comp_count": pricing["comp_count"],
            "price_basis": pricing["price_basis"],
            "buyer_discount": pricing["buyer_discount"],
            "as_of": run["as_of"],
            "comps": comps,
        }
        if link["kind"] == "seller":
            row["seller_price_gbp"] = (pricing["seller_price_gbp"]
                                       if pricing["seller_price_gbp"] is not None
                                       else pricing["sell_price"])
            row["commission_gbp"] = pricing["gp"]
        lines.append(row)

    return {"kind": link["kind"], "fx_rate": link["fx_rate"], "expires_at": link["expires_at"],
            "lines": lines}
