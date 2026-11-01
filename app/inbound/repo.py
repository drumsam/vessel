"""Persistence for `inbound_offer` — VESSEL Pocket, build brief Phase 1b
step 2 (NEW + CANDIDATE). Nothing here calls an AI provider; that
happens in `app/api/inbound.py`, around these calls, so the raw record's
insert is always a separate, already-committed fact before any provider
call is attempted — never in the same transaction, so a slow or failing
provider can never cost the raw capture.
"""
from __future__ import annotations

from typing import Optional

import psycopg
from psycopg.types.json import Jsonb

from app.db import repo as deal_repo
from app.identity.resolver import norm
from app.identity.want_list import match_want_list


def _cuvee_rank(proposed: Optional[str], actual: str) -> tuple:
    """Closest cuvée first, using norm() — the resolver's own comparison,
    not a reimplementation — so "Meursault Perrieres" ranks "Meursault
    Les Perrières" ahead of an unrelated cuvée despite neither the accent
    nor the inserted "Les" matching literally."""
    p, a = norm(proposed or ""), norm(actual)
    if not p:
        return (3, 0, a)
    if p == a:
        return (0, 0, a)
    if p in a or a in p:
        return (1, 0, a)
    overlap = len(set(p.split()) & set(a.split()))
    return (2, -overlap, a) if overlap else (3, 0, a)


def candidate_wine_groups(conn: psycopg.Connection, *, producer: Optional[str],
                          cuvee: Optional[str]) -> list[dict]:
    """Screen 2's own filtered wine list — the proposed producer's wines
    only, closest cuvée first, never the full register: 234 unfiltered
    options trains an operator to grab the first plausible row, which
    undermines the want-list acknowledgement rather than reinforcing it.

    An always_review match (bare "Leroy") additionally returns its real-
    world fork (Maison Leroy) as its own group, so the fork the matcher
    already knows about is visible in the list itself, not only in a
    warning sentence above it. Nothing here is selected by the caller —
    this only narrows the options; picking one stays a deliberate,
    separate act."""
    if not producer or not producer.strip():
        return []
    matches = match_want_list(producer)
    targets: list[tuple[str, bool]] = []  # (producer name, is_fork_alternate)
    if matches:
        for m in matches:
            targets.append((m.producer, False))
            for alt in m.fork_with:
                targets.append((alt, True))
    else:
        targets.append((producer.strip(), False))

    all_wines = conn.execute("SELECT * FROM wine ORDER BY producer, cuvee").fetchall()
    groups: list[dict] = []
    seen: set[str] = set()
    for name, is_fork in targets:
        key = norm(name)
        if key in seen:
            continue
        seen.add(key)
        rows = sorted((w for w in all_wines if norm(w["producer"]) == key),
                     key=lambda w: _cuvee_rank(cuvee, w["cuvee"]))
        groups.append({"producer": name, "is_fork_alternate": is_fork, "wines": rows})
    return groups


class NotConfirmable(Exception):
    """Raised when confirm_identity is asked to confirm a row that is not
    a parsed wine — not found, not yet parsed, or a whisky (never priced,
    never given an identity)."""


def create_inbound_offer(conn: psycopg.Connection, *, channel: str, raw_body: Optional[str],
                         raw_media: Optional[bytes], media_mime: Optional[str],
                         created_by: str) -> dict:
    return conn.execute(
        """INSERT INTO inbound_offer (channel, raw_body, raw_media, media_mime, created_by)
           VALUES (%(channel)s, %(raw_body)s, %(raw_media)s, %(media_mime)s, %(created_by)s)
           RETURNING *""",
        {"channel": channel, "raw_body": raw_body, "raw_media": raw_media,
         "media_mime": media_mime, "created_by": created_by}).fetchone()


def get_inbound_offer(conn: psycopg.Connection, inbound_offer_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM inbound_offer WHERE inbound_offer_id = %s",
                        (inbound_offer_id,)).fetchone()


def mark_parse_attempt_failed(conn: psycopg.Connection, inbound_offer_id: str, *,
                              error: str) -> dict:
    """The provider call itself failed (outage, rate limit, malformed
    response) — never the same thing as the AI successfully reading the
    text and finding nothing in it. Stays 'pending': this is a reason to
    retry, not a verdict that the source is unparseable."""
    return conn.execute(
        """UPDATE inbound_offer SET parsed_at = now(), parse_state = 'pending', parse_error = %s
           WHERE inbound_offer_id = %s RETURNING *""",
        (error, inbound_offer_id)).fetchone()


def mark_parsed(conn: psycopg.Connection, inbound_offer_id: str, *, category: str) -> dict:
    assert category in ("wine", "whisky"), category
    return conn.execute(
        """UPDATE inbound_offer
           SET parsed_at = now(), parse_state = 'parsed', category = %s, parse_error = NULL
           WHERE inbound_offer_id = %s RETURNING *""",
        (category, inbound_offer_id)).fetchone()


def mark_unparseable(conn: psycopg.Connection, inbound_offer_id: str, *, reason: str) -> dict:
    """The provider ran fine and concluded there is no identifiable wine
    or whisky here — a real, checked answer, not a failure to check."""
    return conn.execute(
        """UPDATE inbound_offer
           SET parsed_at = now(), parse_state = 'unparseable', category = 'unknown', parse_error = %s
           WHERE inbound_offer_id = %s RETURNING *""",
        (reason, inbound_offer_id)).fetchone()


def confirm_identity(conn: psycopg.Connection, inbound_offer_id: str, *, wine_id: str,
                     vintage: int, bottle_ml: int, pack_size: int, quantity: int,
                     supplier_id: str, confirmed_by: str,
                     packaging: Optional[str] = None, bond_status: Optional[str] = None,
                     stock_location: Optional[str] = None,
                     asking_price=None, asking_currency: Optional[str] = None,
                     asking_basis: Optional[str] = None) -> dict:
    """The photo gate's technical enforcement point lives one level up, in
    app/api/inbound.py, which checks wine.want_list before ever calling
    this — this function only persists the fact that a named operator
    confirmed, and refuses to confirm anything that is not a parsed wine.

    `supplier_id` is required by the type system at the API boundary
    (ConfirmIdentityIn declares it with no default), the same "capture
    never blocked, confirmation always is" shape want_list_ack uses one
    level up — supplier-attribution-spec.md's own point 1. The
    asking_basis blocking check (a price with no unit on a multi-bottle
    line) is likewise enforced one level up, before this is ever called."""
    row = conn.execute(
        """UPDATE inbound_offer
           SET confirmed_wine_id = %(wine_id)s, confirmed_vintage = %(vintage)s,
               confirmed_bottle_ml = %(bottle_ml)s, confirmed_pack_size = %(pack_size)s,
               confirmed_quantity = %(quantity)s, confirmed_packaging = %(packaging)s,
               confirmed_bond_status = %(bond_status)s,
               confirmed_stock_location = %(stock_location)s,
               confirmed_asking_price = %(asking_price)s,
               confirmed_asking_currency = %(asking_currency)s,
               confirmed_asking_basis = %(asking_basis)s,
               supplier_id = %(supplier_id)s,
               identity_confirmed_by = %(confirmed_by)s, identity_confirmed_at = now()
           WHERE inbound_offer_id = %(inbound_offer_id)s
             AND parse_state = 'parsed' AND category = 'wine'
           RETURNING *""",
        {"wine_id": wine_id, "vintage": vintage, "bottle_ml": bottle_ml, "pack_size": pack_size,
         "quantity": quantity, "packaging": packaging, "bond_status": bond_status,
         "stock_location": stock_location, "asking_price": asking_price,
         "asking_currency": asking_currency, "asking_basis": asking_basis,
         "supplier_id": supplier_id, "confirmed_by": confirmed_by,
         "inbound_offer_id": inbound_offer_id}).fetchone()
    if row is None:
        raise NotConfirmable(
            "this offer is not confirmable — not found, not yet parsed, or a whisky "
            "(whisky is captured for the record but never priced or given an identity)")
    return row


# --------------------------------------------------------- supplier attribution


def create_supplier(conn: psycopg.Connection, *, name: str, phone: Optional[str],
                    created_by: str) -> dict:
    """The quick-add chip's own two-field form (name and phone only) —
    "the rest of the record can be filled in later or never." The
    supplier's own name is captured as its first alias automatically —
    "matching improves with use rather than requiring a backfill," and
    the name itself is the one alias guaranteed to exist with no extra
    field."""
    row = conn.execute(
        """INSERT INTO supplier (name, phone, created_by)
           VALUES (%s, %s, %s) RETURNING *""",
        (name, phone, created_by)).fetchone()
    add_supplier_alias(conn, supplier_id=str(row["supplier_id"]), alias=name)
    return row


def get_supplier(conn: psycopg.Connection, supplier_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM supplier WHERE supplier_id = %s",
                        (supplier_id,)).fetchone()


def list_suppliers(conn: psycopg.Connection) -> list[dict]:
    """Most-recently-used first — the chip row's own ordering, so the
    suppliers Doug actually deals with surface without scrolling. Ties
    (never used, or used at the same moment) fall back to name."""
    return conn.execute("""
        SELECT s.*, MAX(io.identity_confirmed_at) AS last_used_at
          FROM supplier s
          LEFT JOIN inbound_offer io ON io.supplier_id = s.supplier_id
         WHERE s.active
         GROUP BY s.supplier_id
         ORDER BY last_used_at DESC NULLS LAST, s.name
    """).fetchall()


def match_supplier_aliases(conn: psycopg.Connection, raw_body: Optional[str]) -> list[str]:
    """Deterministic pre-highlight only — the model never touches this.
    `alias` is stored already normalised (norm(), identity/resolver.py),
    so this is a plain substring check against the normalised raw text.
    Zero, one, or several matches; several are all returned, unordered,
    per the spec's own rule ("highlight both, no ordering preference")."""
    if not raw_body:
        return []
    text = norm(raw_body)
    rows = conn.execute("SELECT supplier_id, alias FROM supplier_alias").fetchall()
    return list({str(r["supplier_id"]) for r in rows if r["alias"] and r["alias"] in text})


def add_supplier_alias(conn: psycopg.Connection, *, supplier_id: str, alias: str) -> None:
    conn.execute(
        """INSERT INTO supplier_alias (supplier_id, alias) VALUES (%s, %s)
           ON CONFLICT (supplier_id, alias) DO NOTHING""",
        (supplier_id, norm(alias)))


# ---------------------------------------------------------------------- EVALUATE


class NotReadyToEvaluate(Exception):
    """Confirmation (wine_id, vintage, bottle_ml, pack_size, quantity) is
    a prerequisite for EVALUATE, not something it can derive itself."""


def ensure_evaluation_line(conn: psycopg.Connection, inbound_offer: dict, *,
                           created_by: str) -> tuple[str, str]:
    """Idempotent: one deal, one line, per inbound offer -- "a Pocket
    trade is a deal with one or two seller_lines" (the build brief),
    never the single shared batch deal decision 0039's own manual tool
    uses. Opening EVALUATE again later reuses the same line rather than
    creating a second one; `app/api/inbound.py` re-benchmarks it fresh
    every time regardless, so a repeat open always reflects current
    evidence."""
    if inbound_offer["confirmed_wine_id"] is None:
        raise NotReadyToEvaluate("identity has not been confirmed yet")
    # Two EVALUATEs at once (a double tap; React's dev double effect) both
    # read deal_id NULL before either commits and each made a deal — the
    # orphan then listed as a cellar. The row lock makes the second wait and
    # see the first's deal.
    locked = conn.execute("SELECT deal_id FROM inbound_offer WHERE inbound_offer_id = %s FOR UPDATE",
                          (str(inbound_offer["inbound_offer_id"]),)).fetchone()
    inbound_offer = {**inbound_offer, "deal_id": locked["deal_id"]}
    if inbound_offer["deal_id"]:
        line = conn.execute("SELECT line_id FROM seller_line WHERE deal_id = %s LIMIT 1",
                            (str(inbound_offer["deal_id"]),)).fetchone()
        if line:
            _sync_line(conn, str(line["line_id"]), inbound_offer, created_by=created_by)
            return str(inbound_offer["deal_id"]), str(line["line_id"])

    deal = deal_repo.create_deal(conn, {
        "name": f"Pocket {inbound_offer['received_at']:%Y-%m-%d} {str(inbound_offer['inbound_offer_id'])[:8]}",
        "seller": None, "city": None, "source_file": None, "currency": None,
        "target_margin": None, "buyer_discount": None, "margin_on_sale": None,
        "created_by": created_by,
    }, [])
    line = conn.execute(
        """INSERT INTO seller_line (deal_id, row_index, raw_description, raw_row, quantity)
           VALUES (%s, 0, %s, %s, %s) RETURNING *""",
        (deal["deal_id"], inbound_offer["raw_body"] or "(captured by photo)",
         Jsonb({"inbound_offer_id": str(inbound_offer["inbound_offer_id"])}),
         inbound_offer["confirmed_quantity"])).fetchone()
    deal_repo.set_line_identity(
        conn, str(line["line_id"]), wine_id=str(inbound_offer["confirmed_wine_id"]),
        vintage=inbound_offer["confirmed_vintage"], bottle_ml=inbound_offer["confirmed_bottle_ml"],
        pack_size=inbound_offer["confirmed_pack_size"], flags=[], source="operator",
        approved_by=created_by)
    _sync_want_list_ack(conn, str(line["line_id"]), inbound_offer)
    conn.execute("UPDATE inbound_offer SET deal_id = %s WHERE inbound_offer_id = %s",
                (deal["deal_id"], inbound_offer["inbound_offer_id"]))
    return str(deal["deal_id"]), str(line["line_id"])


def _sync_line(conn: psycopg.Connection, line_id: str, inbound_offer: dict, *,
               created_by: str) -> None:
    """A re-confirmed identity (a corrected quantity, a different wine) must
    reach the line EVALUATE prices, or the line keeps pricing the old one."""
    line = deal_repo.get_line(conn, line_id)
    wanted = (str(inbound_offer["confirmed_wine_id"]), inbound_offer["confirmed_vintage"],
              inbound_offer["confirmed_bottle_ml"], inbound_offer["confirmed_pack_size"])
    if (str(line["wine_id"]), line["vintage"], line["bottle_ml"], line["pack_size"]) != wanted:
        deal_repo.set_line_identity(
            conn, line_id, wine_id=wanted[0], vintage=wanted[1], bottle_ml=wanted[2],
            pack_size=wanted[3], flags=[], source="operator", approved_by=created_by)
    if line["quantity"] != inbound_offer["confirmed_quantity"]:
        conn.execute("UPDATE seller_line SET quantity = %s WHERE line_id = %s",
                     (inbound_offer["confirmed_quantity"], line_id))
    _sync_want_list_ack(conn, line_id, inbound_offer)


def _sync_want_list_ack(conn: psycopg.Connection, line_id: str, inbound_offer: dict) -> None:
    """confirm-identity refuses a want-list wine without the acknowledgement,
    so a confirmed inbound offer for one already carries it — recorded on the
    line too, where decision 0038's export check reads it, as the same
    person at the same moment. Cleared when the wine is not on the list."""
    wine = deal_repo.get_wine(conn, str(inbound_offer["confirmed_wine_id"]))
    by, at = ((inbound_offer["identity_confirmed_by"], inbound_offer["identity_confirmed_at"])
              if wine["want_list"] else (None, None))
    conn.execute("""UPDATE seller_line SET want_list_ack_by = %s, want_list_ack_at = %s
                     WHERE line_id = %s""", (by, at, line_id))


# ---------------------------------------------------------- offer and confirm


def set_availability(conn: psycopg.Connection, inbound_offer_id: str,
                     availability: Optional[str]) -> None:
    conn.execute("UPDATE inbound_offer SET availability = %s WHERE inbound_offer_id = %s",
                 (availability, inbound_offer_id))


def get_fulfilment(conn: psycopg.Connection, inbound_offer_id: str) -> Optional[dict]:
    return conn.execute(
        """SELECT f.*, s.name AS supplier_name, c.name AS client_name FROM fulfilment f
             JOIN supplier s USING (supplier_id)
             LEFT JOIN client c ON c.client_id = f.client_id
            WHERE f.inbound_offer_id = %s""", (inbound_offer_id,)).fetchone()


def create_fulfilment(conn: psycopg.Connection, **facts) -> dict:
    row = conn.execute(
        """INSERT INTO fulfilment
               (inbound_offer_id, line_id, pricing_id, pricing_requires_ack, ack_id, supplier_id,
                buyer_name, wine_id, wine_name, vintage, bottle_ml, pack_size, quantity,
                packaging, bond_status, stock_location, availability, currency,
                supplier_price, vessel_sell_price, gross_total, confirmed_by, client_id)
           VALUES (%(inbound_offer_id)s, %(line_id)s, %(pricing_id)s, %(pricing_requires_ack)s,
                   %(ack_id)s, %(supplier_id)s, %(buyer_name)s, %(wine_id)s, %(wine_name)s,
                   %(vintage)s, %(bottle_ml)s, %(pack_size)s, %(quantity)s, %(packaging)s,
                   %(bond_status)s, %(stock_location)s, %(availability)s, %(currency)s,
                   %(supplier_price)s, %(vessel_sell_price)s, %(gross_total)s, %(confirmed_by)s,
                   %(client_id)s)
           RETURNING inbound_offer_id""", {"client_id": None, **facts}).fetchone()
    return get_fulfilment(conn, str(row["inbound_offer_id"]))


def complete_fulfilment(conn: psycopg.Connection, fulfilment_id: str, *,
                        completed_by: str) -> Optional[dict]:
    row = conn.execute(
        """UPDATE fulfilment SET state = 'COMPLETE', completed_by = %s, completed_at = now()
            WHERE fulfilment_id = %s AND state = 'OPEN' RETURNING inbound_offer_id""",
        (completed_by, fulfilment_id)).fetchone()
    return get_fulfilment(conn, str(row["inbound_offer_id"])) if row else None


def list_trades(conn: psycopg.Connection, limit: int = 30) -> list[dict]:
    """Pocket offers that have a committed VESSEL sell price, newest first —
    how Doug gets back to one when the buyer replies hours later."""
    return conn.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (line_id) line_id, sell_price, priced_at
              FROM pricing_result WHERE price_basis = 'parcel_trade'
             ORDER BY line_id, priced_at DESC, pricing_id DESC)
        SELECT io.inbound_offer_id, w.producer, w.cuvee, l.vintage, l.quantity, l.pack_size,
               l.bottle_ml, latest.sell_price AS vessel_sell, latest.priced_at,
               s.name AS supplier_name, f.state AS fulfilment_state, f.buyer_name,
               io.confirmed_asking_basis AS asking_basis
          FROM inbound_offer io
          JOIN seller_line l ON l.deal_id = io.deal_id
          JOIN latest ON latest.line_id = l.line_id
          JOIN wine w ON w.wine_id = l.wine_id
          LEFT JOIN supplier s ON s.supplier_id = io.supplier_id
          LEFT JOIN fulfilment f ON f.inbound_offer_id = io.inbound_offer_id
         WHERE io.discarded_at IS NULL
         ORDER BY latest.priced_at DESC
         LIMIT %s""", (limit,)).fetchall()


# ------------------------------------------------- offer actions (decision 0050)


class NotDiscardable(Exception):
    """A confirmed trade is immutable: it can be viewed, never deleted."""


def discard_offer(conn: psycopg.Connection, inbound_offer_id: str, *, discarded_by: str) -> dict:
    """Delete, as a soft delete: the raw capture, the line and its prices all
    stay (the original is never destroyed); the offer is hidden everywhere and
    can no longer be priced or confirmed. Nothing cascades."""
    if get_fulfilment(conn, inbound_offer_id):
        raise NotDiscardable("a confirmed trade can't be deleted")
    row = conn.execute(
        """UPDATE inbound_offer SET discarded_at = now(), discarded_by = %s
            WHERE inbound_offer_id = %s AND discarded_at IS NULL RETURNING *""",
        (discarded_by, inbound_offer_id)).fetchone()
    if row is None:
        raise LookupError("offer not found, or already deleted")
    return row


def duplicate_offer(conn: psycopg.Connection, inbound_offer_id: str, *, created_by: str) -> dict:
    """A new, unconfirmed draft from the same raw message. Identity is NOT
    carried over: a want-list wine needs its acknowledgement every time, so
    the copy is confirmed afresh (the source's values prefill the form)."""
    src = get_inbound_offer(conn, inbound_offer_id)
    if src is None:
        raise LookupError("offer not found")
    return conn.execute(
        """INSERT INTO inbound_offer (channel, raw_body, raw_media, media_mime, parsed_at,
                                      parse_state, category, supplier_id, availability,
                                      duplicated_from, created_by)
           VALUES (%s, %s, %s, %s, now(), %s, %s, %s, %s, %s, %s) RETURNING *""",
        (src["channel"], src["raw_body"], src["raw_media"], src["media_mime"],
         src["parse_state"], src["category"], src["supplier_id"], src["availability"],
         inbound_offer_id, created_by)).fetchone()


def pocket_offers(conn: psycopg.Connection, limit: int = 200) -> list[dict]:
    """Every live Pocket offer with what the Workbench and Trades need to say
    where it stands: its wine (once confirmed), supplier, committed VESSEL sell
    and confirmation. Discarded offers are not live."""
    return conn.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (line_id) line_id, sell_price, priced_at
              FROM pricing_result WHERE price_basis = 'parcel_trade'
             ORDER BY line_id, priced_at DESC, pricing_id DESC)
        SELECT io.inbound_offer_id, io.received_at, io.channel, io.parse_state, io.parse_error,
               io.category, left(io.raw_body, 120) AS raw_snippet,
               io.raw_media IS NOT NULL AS has_media, io.identity_confirmed_at,
               io.confirmed_vintage AS vintage, io.confirmed_quantity AS quantity,
               io.confirmed_pack_size AS pack_size, io.confirmed_bottle_ml AS bottle_ml,
               io.confirmed_asking_basis AS asking_basis, io.duplicated_from,
               io.confirmed_asking_price AS asking_price,
               io.confirmed_asking_currency AS asking_currency, io.deal_id,
               w.producer, w.cuvee, io.supplier_id, s.name AS supplier_name,
               latest.sell_price AS vessel_sell, latest.priced_at,
               f.fulfilment_id, f.state AS fulfilment_state, f.buyer_name, f.client_id,
               c.name AS client_name, f.confirmed_at
          FROM inbound_offer io
          LEFT JOIN wine w ON w.wine_id = io.confirmed_wine_id
          LEFT JOIN supplier s ON s.supplier_id = io.supplier_id
          LEFT JOIN seller_line l ON l.deal_id = io.deal_id
          LEFT JOIN latest ON latest.line_id = l.line_id
          LEFT JOIN fulfilment f ON f.inbound_offer_id = io.inbound_offer_id
          LEFT JOIN client c ON c.client_id = f.client_id
         WHERE io.discarded_at IS NULL
         ORDER BY GREATEST(io.received_at, coalesce(latest.priced_at, io.received_at),
                           coalesce(f.confirmed_at, io.received_at)) DESC
         LIMIT %s""", (limit,)).fetchall()


def pocket_deal_ids(conn: psycopg.Connection) -> set[str]:
    """Every deal a Pocket offer made for itself — linked from the offer, or
    marked by its line's raw_row, which also catches the orphans an
    EVALUATE race left before ensure_evaluation_line locked the row."""
    return {str(r["deal_id"]) for r in conn.execute(
        """SELECT deal_id FROM inbound_offer WHERE deal_id IS NOT NULL
           UNION SELECT deal_id FROM seller_line WHERE raw_row ? 'inbound_offer_id'""")}


def cellar_deals(conn: psycopg.Connection) -> list[dict]:
    """Deals that are cellars, not the deal a Pocket offer creates for itself."""
    pocket = pocket_deal_ids(conn)
    return [d for d in deal_repo.list_deals(conn) if str(d["deal_id"]) not in pocket]
