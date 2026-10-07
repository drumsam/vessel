"""VESSEL Private Sale — persistence. Every write goes through here.

Reads the existing engine's already-computed state (the latest benchmark run
and its vintage-band check) rather than recomputing anything: VESSEL decides
what to do with evidence the pricing core already produced, it never asks the
core a new question. app/core/ is not imported here.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from app.db import repo as db
from app.vessel.engine import (
    CannotList,
    DEFAULT_MARKET,
    MARKET_LABELS,
    MIN_LISTING_VALUE_GBP,
    PROOF_OF_PAYMENT_EXTENSION,
    commission_due,
    evidence_claim,
    hold_duration,
    meets_minimum_value,
    price_listing,
    resolve_discount,
)

CENT = Decimal("0.01")

#: Why a line is not among those recommended, for the seller-facing summary
#: counts ("319 no UK market · 147 thin evidence · 53 better held").
NO_MARKET = "NO_MARKET"
THIN_EVIDENCE = "THIN_EVIDENCE"
BELOW_MINIMUM_VALUE = "BELOW_MINIMUM_VALUE"
IDENTITY_PENDING = "IDENTITY_PENDING"
BETTER_HELD = "BETTER_HELD"


@dataclass(frozen=True)
class Excluded:
    line_id: str
    reason: str
    detail: str


# -------------------------------------------------------------- recommending


def recommend_lines(conn: psycopg.Connection, deal_id: str, *, currency: str,
                    fx_hkd_per_gbp: Optional[Decimal], fx_source: Optional[str],
                    fx_rate_date: Optional[date], stock_location: str,
                    warehouse: Optional[str] = None,
                    line_choices: Optional[dict[str, dict]] = None,
                    held_back: frozenset[str] = frozenset(),
                    minimum_gbp: Decimal = MIN_LISTING_VALUE_GBP) -> tuple[list[dict], list[Excluded]]:
    """For every line of a deal: either create a RECOMMENDED `vessel_listing`
    (and return it), or report why not. Never both, and nothing is listed
    twice — a line that already has a listing is skipped silently so this can
    be re-run as more lines get benchmarked.

    `line_choices` is {line_id: {"band": ..., "discount": Decimal(...),
    "reference_market": "UK_IN_BOND" | "HK_RETAIL"}}, operator overrides; a
    line not named here prices at the default band (NORMAL, at its shallow
    edge) from the default market (UK_IN_BOND, the only one the core
    produces on its own). Choosing "HK_RETAIL" requires the operator to
    also supply "hk_reference_price" (the lot total, in `currency`),
    "hk_source_count" and, optionally, "hk_evidence" (a list of source
    notes/URLs) — there is no HK adapter yet, so this market's evidence is
    entered by hand, same discipline as any other operator figure: missing
    it excludes the line rather than guessing. One currency and FX rate per
    call: a seller's cellar is reviewed in one sitting, in one currency.
    """
    line_choices = line_choices or {}
    listings, excluded = [], []
    for row in db.deal_lines(conn, deal_id):
        line_id = str(row["line_id"])
        if conn.execute("SELECT 1 FROM vessel_listing WHERE line_id = %s",
                        (line_id,)).fetchone():
            continue                                        # already recommended once

        if row["wine_id"] is None:
            excluded.append(Excluded(line_id, IDENTITY_PENDING,
                                     "identity not yet approved"))
            continue

        choice = line_choices.get(line_id, {})
        reference_market = choice.get("reference_market", DEFAULT_MARKET)
        if reference_market not in MARKET_LABELS:
            excluded.append(Excluded(line_id, NO_MARKET,
                                     f"{reference_market!r} is not a recognised reference market"))
            continue

        run = None
        if reference_market == DEFAULT_MARKET:
            run = db.latest_run(conn, line_id)
            if run is None or run["state"] == "NO_MARKET" or run["uk_reference"] is None:
                excluded.append(Excluded(line_id, NO_MARKET, "no UK market"))
                continue
            band_row = db.run_band(conn, str(run["run_id"]))
            source_count = run["comp_count"]
            band_passed = bool(band_row and band_row["band_low"] is not None)
            evidence = [str(run["run_id"])]
        else:
            hk_price, hk_count = choice.get("hk_reference_price"), choice.get("hk_source_count")
            if hk_price is None or hk_count is None:
                excluded.append(Excluded(
                    line_id, NO_MARKET,
                    "HK_RETAIL needs a manually entered reference price and source count"))
                continue
            source_count, band_passed = hk_count, False
            evidence = list(choice.get("hk_evidence") or [])

        claim = evidence_claim(source_count, vintage_band_passed=band_passed,
                               market=reference_market)
        if not claim.can_list:
            excluded.append(Excluded(line_id, THIN_EVIDENCE, claim.reason))
            continue

        if line_id in held_back:
            excluded.append(Excluded(line_id, BETTER_HELD,
                                     "qualifies; held for a later drop"))
            continue

        wine = db.get_wine(conn, str(row["wine_id"]))
        bottles = row["quantity"]
        if reference_market == DEFAULT_MARKET:
            per_bottle_gbp = Decimal(str(run["uk_reference"]))
            market_reference_gbp = per_bottle_gbp * bottles
            market_reference = (market_reference_gbp if currency == "GBP"
                                else market_reference_gbp * fx_hkd_per_gbp)
            market_reference = market_reference.quantize(CENT)
        else:
            market_reference = Decimal(str(choice["hk_reference_price"])).quantize(CENT)

        band = choice.get("band", "NORMAL")
        try:
            discount = resolve_discount(band, choice.get("discount"))
            priced = price_listing(market_reference, band=band, currency=currency,
                                   discount=discount)
        except CannotList as e:
            excluded.append(Excluded(line_id, THIN_EVIDENCE, str(e)))
            continue

        if not meets_minimum_value(priced.vessel_price, currency, fx_hkd_per_gbp,
                                   minimum_gbp=minimum_gbp):
            excluded.append(Excluded(line_id, BELOW_MINIMUM_VALUE,
                                     f"below the GBP {minimum_gbp} minimum line value"))
            continue

        full_claim = evidence_claim(source_count, vintage_band_passed=band_passed,
                                    market=reference_market,
                                    market_reference=market_reference,
                                    vessel_price=priced.vessel_price)

        reference = conn.execute(
            """INSERT INTO vessel_reference (line_id, market, reference_price, currency,
                                             source_count, evidence)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING reference_id""",
            (line_id, reference_market, market_reference, currency, source_count,
             Jsonb(evidence))).fetchone()

        listing = conn.execute(
            """INSERT INTO vessel_listing
                   (deal_id, line_id, run_id, state, display_producer, display_wine,
                    vintage, release_code, bottle_ml, bottles, stock_location, warehouse,
                    currency, fx_hkd_per_gbp, fx_source, fx_rate_date,
                    market_reference, band, discount_applied, vessel_price, seller_net,
                    source_count, vintage_band_passed, derived, percentage_claim_pct,
                    reference_market, reference_id)
               VALUES (%(deal_id)s, %(line_id)s, %(run_id)s, 'RECOMMENDED',
                       %(producer)s, %(cuvee)s, %(vintage)s, %(release_code)s,
                       %(bottle_ml)s, %(bottles)s, %(stock_location)s, %(warehouse)s,
                       %(currency)s, %(fx_hkd_per_gbp)s, %(fx_source)s, %(fx_rate_date)s,
                       %(market_reference)s, %(band)s, %(discount)s, %(vessel_price)s,
                       %(seller_net)s, %(source_count)s, %(band_passed)s,
                       %(derived)s, %(pct)s, %(reference_market)s, %(reference_id)s)
               RETURNING *""",
            {"deal_id": deal_id, "line_id": line_id,
             "run_id": run["run_id"] if run is not None else None,
             "producer": wine["producer"], "cuvee": wine["cuvee"], "vintage": row["vintage"],
             "release_code": wine["release_code"], "bottle_ml": row["bottle_ml"],
             "bottles": bottles, "stock_location": stock_location, "warehouse": warehouse,
             "currency": currency, "fx_hkd_per_gbp": fx_hkd_per_gbp, "fx_source": fx_source,
             "fx_rate_date": fx_rate_date, "market_reference": market_reference,
             "band": band, "discount": discount,
             "vessel_price": priced.vessel_price, "seller_net": priced.seller_net,
             "source_count": source_count, "band_passed": band_passed,
             "derived": run is not None and "DERIVED_FROM_CASE" in (run["flags"] or []),
             "pct": full_claim.percentage_claim_pct,
             "reference_market": reference_market,
             "reference_id": reference["reference_id"]},
        ).fetchone()
        listings.append(listing)

    with conn.cursor() as cur:
        if listings:
            cur.executemany(
                "DELETE FROM vessel_exclusion WHERE deal_id = %s AND line_id = %s",
                [(deal_id, l["line_id"]) for l in listings])
        if excluded:
            cur.executemany(
                """INSERT INTO vessel_exclusion (deal_id, line_id, reason, detail)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (deal_id, line_id) DO UPDATE
                      SET reason = EXCLUDED.reason, detail = EXCLUDED.detail,
                          created_at = now()""",
                [(deal_id, e.line_id, e.reason, e.detail) for e in excluded])
    return listings, excluded


def excluded_summary(conn: psycopg.Connection, deal_id: str) -> dict[str, int]:
    """The seller-approval screen's "why not the rest" counts, readable at
    any later visit — not only in the response of the operator action that
    computed them."""
    rows = conn.execute(
        "SELECT reason, count(*) AS n FROM vessel_exclusion WHERE deal_id = %s GROUP BY reason",
        (deal_id,)).fetchall()
    return {r["reason"]: r["n"] for r in rows}


def why_not_recommended(excluded: list[Excluded]) -> dict[str, int]:
    """'319 no UK market * 147 thin evidence * 53 better held' — the seller
    sees counts, not a line-by-line audit of what wasn't offered."""
    counts: dict[str, int] = {}
    for e in excluded:
        counts[e.reason] = counts.get(e.reason, 0) + 1
    return counts


def recommended_listings(conn: psycopg.Connection, deal_id: str) -> list[dict]:
    return conn.execute(
        """SELECT * FROM vessel_listing WHERE deal_id = %s AND state = 'RECOMMENDED'
            ORDER BY vessel_price DESC""", (deal_id,)).fetchall()


# ----------------------------------------------------------------- mandate


SETTLEMENT_MODES = frozenset({"AGENCY", "PRINCIPAL"})
DEFAULT_SETTLEMENT_MODE = "AGENCY"

#: AGENCY (decision 0022, the only mode Doug actually uses): the buyer pays
#: the seller directly, VESSEL never holds the money, and invoices an 8%
#: commission on each wine once sold.
MANDATE_TEMPLATE_AGENCY = (
    "VESSEL may market these wines for {days} days at a price of no less "
    "than the amount shown against each line. The buyer pays you directly, "
    "in full, on collection; VESSEL invoices you an 8% commission on each "
    "wine once it sells, rather than holding any part of the sale "
    "ourselves. We handle release timing, presentation and price "
    "positioning within that. We'll tell you what sold, when, and what "
    "didn't. You warrant that the wine is yours to sell, free of any "
    "charge or encumbrance, and agree to its remaining in bonded storage "
    "while it is listed."
)

#: PRINCIPAL: the original assumption (VESSEL receives the buyer's funds,
#: then pays the seller net) — unused and untested until someone needs it
#: (decision 0022). Preserved verbatim from before the agency revision.
MANDATE_TEMPLATE_PRINCIPAL = (
    "VESSEL may market these wines for {days} days at a net to you of no less "
    "than the amount shown against each line. We handle release timing, "
    "presentation and price positioning within that. We'll tell you what sold, "
    "when, and what didn't. You warrant that the wine is yours to sell, free "
    "of any charge or encumbrance, and agree to its remaining in bonded "
    "storage while it is listed."
)

MANDATE_TEMPLATES = {"AGENCY": MANDATE_TEMPLATE_AGENCY, "PRINCIPAL": MANDATE_TEMPLATE_PRINCIPAL}


def approve_mandate(conn: psycopg.Connection, deal_id: str, *, move_line_ids: list[str],
                    keep_line_ids: list[str], approved_by_name: str,
                    window_days: int = 30, settlement_mode: str = DEFAULT_SETTLEMENT_MODE,
                    storage_facility: Optional[str] = None,
                    as_of: Optional[datetime] = None) -> dict:
    """The seller's one button. Everything it does happens together: write
    the mandate (never touched again), move every ticked listing to APPROVED
    under it, decline the rest. A line not named in either list is left
    exactly as it was — the seller saw only the lines offered to them.

    `settlement_mode` is a term of the mandate, never per line (decision
    0022): every listing under one mandate settles the same way. Defaults
    to AGENCY — the only mode actually used; PRINCIPAL is accepted (the
    database knows the value) but exercised nowhere in this codebase.

    `as_of` defaults to the real clock for callers that do not care (every
    API route); tests that need `listing.approved_at` to agree with a fake
    `reserve_listing`/`add_to_drop` clock pass it explicitly.
    """
    if not approved_by_name.strip():
        raise ValueError("a mandate needs a named approver")
    if not move_line_ids:
        raise ValueError("a mandate needs at least one line")
    if settlement_mode not in SETTLEMENT_MODES:
        raise ValueError(f"{settlement_mode!r} is not a recognised settlement mode")
    as_of = as_of or datetime.now(timezone.utc)

    mandate = conn.execute(
        """INSERT INTO vessel_mandate (deal_id, mandate_text, window_days, approved_by_name,
                                       settlement_mode, storage_facility)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (deal_id, MANDATE_TEMPLATES[settlement_mode].format(days=window_days), window_days,
         approved_by_name, settlement_mode, storage_facility),
    ).fetchone()

    with conn.cursor() as cur:
        cur.executemany(
            """UPDATE vessel_listing SET state = 'APPROVED', mandate_id = %s, approved_at = %s
                WHERE line_id = %s AND deal_id = %s AND state = 'RECOMMENDED'""",
            [(mandate["mandate_id"], as_of, lid, deal_id) for lid in move_line_ids])
        if keep_line_ids:
            cur.executemany(
                """UPDATE vessel_listing SET state = 'DECLINED'
                    WHERE line_id = %s AND deal_id = %s AND state = 'RECOMMENDED'""",
                [(lid, deal_id) for lid in keep_line_ids])
    moved = conn.execute(
        "SELECT count(*) AS n FROM vessel_listing WHERE mandate_id = %s",
        (mandate["mandate_id"],)).fetchone()["n"]
    if moved != len(move_line_ids):
        raise ValueError("one or more lines were not RECOMMENDED for this deal; "
                         "nothing was approved")
    return mandate


def mandate_estimate(conn: psycopg.Connection, mandate_id: str) -> list[dict]:
    """Net proceeds by currency, computed from the listings themselves —
    never stored on the mandate, so it can never disagree with them."""
    return conn.execute(
        """SELECT currency, count(*) AS lines, sum(seller_net) AS net_total
             FROM vessel_listing WHERE mandate_id = %s GROUP BY currency""",
        (mandate_id,)).fetchall()


#: Completed, in the sense that matters for a commission invoice: the sale
#: happened, whatever stage of transfer/settlement it has since reached.
COMPLETED_SALE_STATES = ("PAID", "TRANSFERRING", "SETTLED")


def commission_invoice(conn: psycopg.Connection, mandate_id: str) -> dict:
    """One invoice per mandate, not per sale (decision 0022) — at two to
    three deals a year nobody wants an invoice per bottle. Every figure is
    read from the listings themselves, same discipline as mandate_estimate:
    nothing is stored on the invoice, so it can never disagree with them.
    """
    mandate = conn.execute("SELECT * FROM vessel_mandate WHERE mandate_id = %s",
                           (mandate_id,)).fetchone()
    if mandate is None:
        raise LookupError(f"no mandate {mandate_id}")
    if mandate["settlement_mode"] != "AGENCY":
        raise ValueError(
            f"mandate {mandate_id} settles as {mandate['settlement_mode']}: VESSEL already "
            "deducted its fee before paying the seller, there is nothing to invoice")

    rows = conn.execute(
        """SELECT listing_id, display_producer, display_wine, vintage, release_code,
                  currency, vessel_price, seller_net
             FROM vessel_listing
            WHERE mandate_id = %s AND state = ANY(%s)
            ORDER BY display_producer, display_wine, vintage""",
        (mandate_id, list(COMPLETED_SALE_STATES))).fetchall()

    lines = []
    totals: dict[str, Decimal] = {}
    for row in rows:
        commission = commission_due(Decimal(str(row["vessel_price"])),
                                    Decimal(str(row["seller_net"])))
        lines.append({**row, "commission": commission})
        totals[row["currency"]] = totals.get(row["currency"], Decimal("0")) + commission

    return {"mandate_id": mandate_id, "lines": lines,
           "totals": [{"currency": c, "commission_total": t} for c, t in totals.items()]}


# -------------------------------------------------------------------- drops


def create_drop(conn: psycopg.Connection, *, label: str, drop_date: date,
                created_by: str) -> dict:
    return conn.execute(
        "INSERT INTO vessel_drop (label, drop_date, created_by) VALUES (%s, %s, %s) "
        "RETURNING *", (label, drop_date, created_by)).fetchone()


def add_to_drop(conn: psycopg.Connection, drop_id: str, listing_ids: list[str], *,
                as_of: Optional[datetime] = None) -> int:
    """APPROVED -> LISTED. A drop can be empty, and a listing can be added to
    exactly one drop, ever, at launch — no re-list."""
    as_of = as_of or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.executemany(
            """UPDATE vessel_listing SET state = 'LISTED', drop_id = %s, listed_at = %s
                WHERE listing_id = %s AND state = 'APPROVED'""",
            [(drop_id, as_of, lid) for lid in listing_ids])
    return conn.execute(
        "SELECT count(*) AS n FROM vessel_listing WHERE drop_id = %s", (drop_id,)
    ).fetchone()["n"]


def drop_listings(conn: psycopg.Connection, drop_id: str) -> list[dict]:
    """Every listing ever added to this drop, SOLD ones included and greyed —
    they stay visible for the life of the drop (v3/v4)."""
    return conn.execute(
        """SELECT l.*, (SELECT min(r.fulfilled_at) FROM vessel_reservation r
                         WHERE r.listing_id = l.listing_id AND r.state = 'FULFILLED') AS sold_at
             FROM vessel_listing l WHERE l.drop_id = %s
            ORDER BY l.state = 'PAID' DESC, l.state = 'SETTLED' DESC, l.vessel_price DESC""",
        (drop_id,)).fetchall()


def get_listing(conn: psycopg.Connection, listing_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM vessel_listing WHERE listing_id = %s",
                        (listing_id,)).fetchone()


def get_reservation(conn: psycopg.Connection, reservation_id: str) -> Optional[dict]:
    """The reservation and the listing it holds, in one row: the payment
    screen needs the reference and amount from one, the state from the
    other, and they must never be read at two different moments."""
    return conn.execute(
        """SELECT r.*, l.vessel_price, l.currency, l.display_producer, l.display_wine,
                  l.vintage, l.bottles, l.state AS listing_state
             FROM vessel_reservation r JOIN vessel_listing l ON l.listing_id = r.listing_id
            WHERE r.reservation_id = %s""", (reservation_id,)).fetchone()


# ------------------------------------------------------- reservation and buy


class AlreadyReserved(Exception):
    """Someone else's BUY won the race."""


class AlreadyExtended(Exception):
    """Proof of payment has already been submitted once for this
    reservation. Capped in code: a second extension does not happen."""


class AgencyMandate(Exception):
    """A code path tried to record VESSEL as having received funds for a
    reservation under an AGENCY mandate (decision 0022). Caught here, in
    Python, with a clear message; the database's own trigger
    (vessel_forbid_payment_match_for_agency) is the backstop for any path
    that does not go through record_payment."""


def _new_reference() -> str:
    return "VS" + secrets.token_hex(3).upper()


def reserve_listing(conn: psycopg.Connection, listing_id: str, *, buyer_contact: str,
                    as_of: datetime) -> dict:
    """BUY. One live reservation per listing is a database constraint
    (vessel_one_live_reservation_per_listing), not this function: two
    concurrent calls race the same INSERT, and exactly one of them returns.
    """
    listing = get_listing(conn, listing_id)
    if listing is None:
        raise LookupError(f"listing {listing_id} not found")
    if listing["state"] != "LISTED":
        raise AlreadyReserved(f"listing {listing_id} is {listing['state']}, not LISTED")

    hold = hold_duration(Decimal(str(listing["vessel_price"])), listing["currency"],
                         Decimal(str(listing["fx_hkd_per_gbp"])) if listing["fx_hkd_per_gbp"] else None)
    # The partial unique index is the lock, not this code: a UniqueViolation
    # here is not a transient failure to retry, it is the correct signal that
    # another BUY already holds this listing. Caught, not raced.
    try:
        with conn.transaction():
            reservation = conn.execute(
                """INSERT INTO vessel_reservation
                       (listing_id, state, payment_reference, buyer_contact,
                        held_at, expires_at)
                   VALUES (%s, 'HELD', %s, %s, %s, %s) RETURNING *""",
                (listing_id, _new_reference(), buyer_contact, as_of, as_of + hold),
            ).fetchone()
            updated = conn.execute(
                """UPDATE vessel_listing SET state = 'RESERVED' WHERE listing_id = %s
                    AND state = 'LISTED' RETURNING listing_id""", (listing_id,)
            ).fetchone()
            if updated is None:
                raise AlreadyReserved(f"listing {listing_id} was reserved first")
    except UniqueViolation:
        raise AlreadyReserved(f"listing {listing_id} already has a live reservation")
    return reservation


def submit_proof_of_payment(conn: psycopg.Connection, reservation_id: str, *,
                           as_of: datetime) -> dict:
    """Extends the hold automatically: nobody loses a wine to reconciliation
    lag (v4). ONE extension, a fixed 2 hours — never the original
    hold_duration() again, and never a second time: a reservation that has
    already used its extension and still lapses needs an operator to close
    it out, not another timer (revision, 7 October 2026).
    """
    row = conn.execute(
        """SELECT * FROM vessel_reservation WHERE reservation_id = %s AND state = 'HELD'""",
        (reservation_id,)).fetchone()
    if row is None:
        raise LookupError(f"no live reservation {reservation_id}")
    if row["proof_submitted_at"] is not None:
        raise AlreadyExtended(
            f"reservation {reservation_id} already used its one extension")
    return conn.execute(
        """UPDATE vessel_reservation SET expires_at = %s, proof_submitted_at = %s
            WHERE reservation_id = %s RETURNING *""",
        (as_of + PROOF_OF_PAYMENT_EXTENSION, as_of, reservation_id)).fetchone()


def expire_overdue_reservations(conn: psycopg.Connection, *, as_of: datetime) -> list[str]:
    """Timeout returns the listing to LISTED. `as_of` is an argument, never
    the clock: this stays testable without waiting.

    A reservation that has already submitted proof of payment is NOT swept
    here even if its extended deadline has passed — it stops being
    something a timer resolves, and stays HELD (blocking the listing from a
    second sale) until an operator either records the payment
    (`record_payment`, if it does land late) or cancels it explicitly
    (`cancel_reservation`). See `reservations_needing_confirmation`.
    """
    expired = conn.execute(
        """UPDATE vessel_reservation SET state = 'EXPIRED'
            WHERE state = 'HELD' AND expires_at <= %s AND proof_submitted_at IS NULL
        RETURNING reservation_id, listing_id""", (as_of,)).fetchall()
    if expired:
        with conn.cursor() as cur:
            cur.executemany(
                """UPDATE vessel_listing SET state = 'LISTED'
                    WHERE listing_id = %s AND state = 'RESERVED'""",
                [(r["listing_id"],) for r in expired])
    return [str(r["reservation_id"]) for r in expired]


def reservations_needing_confirmation(conn: psycopg.Connection, *, as_of: datetime) -> list[dict]:
    """HELD, past its one extension, unresolved by payment either way — the
    operator's queue, not a timer's."""
    return conn.execute(
        """SELECT r.*, l.display_producer, l.display_wine, l.vintage, l.vessel_price,
                  l.currency
             FROM vessel_reservation r JOIN vessel_listing l ON l.listing_id = r.listing_id
            WHERE r.state = 'HELD' AND r.proof_submitted_at IS NOT NULL AND r.expires_at <= %s
            ORDER BY r.expires_at""", (as_of,)).fetchall()


def cancel_reservation(conn: psycopg.Connection, reservation_id: str, *,
                       as_of: datetime) -> dict:
    """The operator's confirmation that payment did not, in fact, arrive:
    releases the listing back to the pool. The other resolution — payment
    arrived after all — needs no special function, it is `record_payment`,
    exactly as if it had landed on time."""
    reservation = conn.execute(
        """UPDATE vessel_reservation SET state = 'CANCELLED', cancelled_at = %s
            WHERE reservation_id = %s AND state = 'HELD' RETURNING *""",
        (as_of, reservation_id)).fetchone()
    if reservation is None:
        raise LookupError(f"no live reservation {reservation_id}")
    conn.execute(
        """UPDATE vessel_listing SET state = 'LISTED' WHERE listing_id = %s AND state = 'RESERVED'""",
        (reservation["listing_id"],))
    return reservation


def confirm_seller_receipt(conn: psycopg.Connection, reservation_id: str, *,
                           confirmed_by: str, as_of: datetime) -> dict:
    """The AGENCY fulfilment path (decision 0022): the buyer paid the seller
    directly, and this is the seller telling VESSEL so — recorded as who
    confirmed and when, never a boolean, and VESSEL asserts nothing about
    funds it never held. `record_payment` is the PRINCIPAL equivalent; the
    two are mutually exclusive by mandate, not by listing or by line."""
    if not confirmed_by.strip():
        raise ValueError("a confirmation needs a named confirmer")
    reservation = conn.execute(
        """SELECT r.*, l.listing_id, m.settlement_mode
             FROM vessel_reservation r
             JOIN vessel_listing l ON l.listing_id = r.listing_id
             JOIN vessel_mandate m ON m.mandate_id = l.mandate_id
            WHERE r.reservation_id = %s AND r.state = 'HELD'""", (reservation_id,)).fetchone()
    if reservation is None:
        raise LookupError(f"no live reservation {reservation_id}")
    if reservation["settlement_mode"] != "AGENCY":
        raise AgencyMandate(
            f"reservation {reservation_id} is under a {reservation['settlement_mode']} "
            "mandate: confirm_seller_receipt is the AGENCY path, use record_payment")
    updated = conn.execute(
        """UPDATE vessel_reservation
              SET state = 'FULFILLED', fulfilled_at = %s,
                  seller_confirmed_at = %s, seller_confirmed_by = %s
            WHERE reservation_id = %s RETURNING *""",
        (as_of, as_of, confirmed_by, reservation_id)).fetchone()
    conn.execute("UPDATE vessel_listing SET state = 'PAID' WHERE listing_id = %s",
                (reservation["listing_id"],))
    record_event(conn, reservation["listing_id"], "BOUGHT",
                buyer_contact=reservation["buyer_contact"])
    return updated


# ------------------------------------------------------------------ payment


def record_payment(conn: psycopg.Connection, *, reference: str, amount: Decimal,
                   currency: str, received_at: datetime) -> dict:
    """Matching by reference AND amount AND currency: a reference nobody is
    holding, or money that is short, over, or in the wrong currency, is
    UNMATCHED and ships nothing — sent to a queue for a person, never
    rounded or waved through. No title moves before cleared funds.

    This is the PRINCIPAL path: VESSEL asserting it received the buyer's
    funds. Refused in Python for an AGENCY reservation (`AgencyMandate`),
    backed by the database's own trigger
    (`vessel_forbid_payment_match_for_agency`) for any path that reaches the
    INSERT some other way.
    """
    reservation = conn.execute(
        """SELECT r.*, l.listing_id, l.currency AS listing_currency,
                  l.vessel_price AS listing_price, m.settlement_mode
             FROM vessel_reservation r
             JOIN vessel_listing l ON l.listing_id = r.listing_id
             JOIN vessel_mandate m ON m.mandate_id = l.mandate_id
            WHERE r.payment_reference = %s AND r.state = 'HELD'""", (reference,)).fetchone()
    if reservation is not None and reservation["settlement_mode"] == "AGENCY":
        raise AgencyMandate(
            f"reservation {reservation['reservation_id']} is under an AGENCY mandate: "
            "VESSEL never holds funds for it, use confirm_seller_receipt instead")
    matched = bool(
        reservation
        and reservation["listing_currency"] == currency
        and Decimal(str(reservation["listing_price"])) == Decimal(str(amount)))
    payment = conn.execute(
        """INSERT INTO vessel_payment (reference, amount, currency, received_at,
                                       matched_reservation_id, state)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (reference, amount, currency, received_at,
         reservation["reservation_id"] if matched else None,
         "MATCHED" if matched else "UNMATCHED"),
    ).fetchone()
    if matched:
        conn.execute(
            """UPDATE vessel_reservation SET state = 'FULFILLED', fulfilled_at = %s
                WHERE reservation_id = %s""", (received_at, reservation["reservation_id"]))
        conn.execute(
            """UPDATE vessel_listing SET state = 'PAID' WHERE listing_id = %s""",
            (reservation["listing_id"],))
        record_event(conn, reservation["listing_id"], "BOUGHT",
                    buyer_contact=reservation["buyer_contact"])
    return payment


# -------------------------------------------------------------- behaviour


def record_event(conn: psycopg.Connection, listing_id: str, event_type: str, *,
                 buyer_contact: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO vessel_event (listing_id, event_type, buyer_contact) VALUES (%s, %s, %s)",
        (listing_id, event_type, buyer_contact))


# ----------------------------------------------------------------- analytics


def sell_through_report(conn: psycopg.Connection) -> list[dict]:
    """Quality-adjusted sell-through by band and region — the one report
    the brief asks for. 'Quality' is the band: STRONG/NORMAL/CLEARANCE is
    already a quality tier, chosen by a human on named evidence.

    Time to sell is listed_at to the fulfilling payment's fulfilled_at — the
    moment funds matched, which is also the moment the listing read PAID.
    Nothing in drop one writes settled_at (that is the transfer step, rule 4,
    not built), so it is not what this reads.
    """
    return conn.execute(
        """SELECT l.band, w.region,
                  count(*) AS listed,
                  count(*) FILTER (WHERE l.state IN ('PAID','TRANSFERRING','SETTLED')) AS sold,
                  round(100.0 * count(*) FILTER (WHERE l.state IN ('PAID','TRANSFERRING','SETTLED'))
                        / count(*), 1) AS sell_through_pct,
                  percentile_disc(0.5) WITHIN GROUP (ORDER BY (r.fulfilled_at - l.listed_at))
                      AS median_time_to_sell
             FROM vessel_listing l
             JOIN seller_line sl ON sl.line_id = l.line_id
             JOIN wine w ON w.wine_id = sl.wine_id
             LEFT JOIN vessel_reservation r
                 ON r.listing_id = l.listing_id AND r.state = 'FULFILLED'
            WHERE l.drop_id IS NOT NULL
            GROUP BY l.band, w.region
            ORDER BY w.region, l.band""").fetchall()
