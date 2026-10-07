"""Operator-entered auction evidence — the one source of auction prices in
this system. Spec: docs/research/auction-evidence-form-spec.md.

Auction evidence is a health check, never a price: it never sets, moves or
substitutes for the UK Floor, Reference or Median, and it never appears on
a client document. Nothing under app/core/ or app/pricing/ imports this
module or app/auction/repo.py — test_auction_evidence_never_reaches_benchmark
proves that statically, not just by convention.

Doug, 7 October 2026: pull in Bonhams, Christie's, Heritage and Zachys. The
terms audit (docs/research/auction-access-pack.md,
auction-evidence-form-spec.md) found Heritage's and Zachys's own terms
restrict use to personal/non-commercial use, which hand-entry for a
commercial pricer still is. Doug chose to include them anyway, over that
finding — said out loud here, not done quietly. This stays hand-entry
only, never a scraper, for all four houses: a scraper against Heritage's
site would additionally breach their explicit, separate prohibition on
automated collection, which a person reading a public page and typing six
facts in does not.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional

CENT = Decimal("0.01")

#: Closed list. The spec's own audit cleared BONHAMS and CHRISTIES by their
#: terms; HERITAGE and ZACHYS are here over their stated restriction, on
#: Doug's explicit instruction (decision 0023). Adding a fifth house needs
#: the same: a decision record, not a quiet edit here.
ALLOWED_HOUSES: frozenset[str] = frozenset({"BONHAMS", "CHRISTIES", "HERITAGE", "ZACHYS"})

AMOUNT_BASES: frozenset[str] = frozenset({"HAMMER", "BUYER_PREMIUM_INCLUSIVE"})

#: The health check's own comparable window — a looser number than
#: MAX_OFFER_AGE_DAYS (decision 0003): an auction lot is a point in time,
#: not a live ask, so "fresh" means something wider here on purpose.
AUCTION_HEALTH_WINDOW_DAYS = 730

#: Informational only. Never added to app.core.flags.REVIEW_FLAGS — that
#: set is the single definition of what forces review, and a health-check
#: observation is exactly the kind of commercial/informational signal its
#: own comment says never belongs there.
AUCTION_BELOW_REFERENCE = "AUCTION_BELOW_REFERENCE"
AUCTION_BELOW_REFERENCE_THRESHOLD = Decimal("0.10")


class InvalidAuctionEvidence(Exception):
    """The evidence as typed cannot be recorded — checked in Python, with a
    clear reason, before the database's own CHECK constraints are reached."""


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def derive_hammer_gbp(*, amount: Decimal, currency: str, amount_basis: str,
                      premium_rate: Optional[Decimal],
                      fx_rate: Optional[Decimal]) -> Optional[Decimal]:
    """The one documented rounding point here (spec, server-side derivation
    step 1): BUYER_PREMIUM_INCLUSIVE divides the premium out first, then FX
    converts if needed. A missing FX rate on a non-GBP lot is not refused —
    `hammer_gbp` is simply absent ("FX unavailable"), never estimated. A
    missing premium rate on an inclusive price IS refused: a 25% premium
    read as hammer is a 25% error, and the six facts the form promises
    always include which basis the amount is in.
    """
    if amount_basis not in AMOUNT_BASES:
        raise InvalidAuctionEvidence(f"{amount_basis!r} is not a recognised amount basis")
    if amount_basis == "BUYER_PREMIUM_INCLUSIVE":
        if premium_rate is None:
            raise InvalidAuctionEvidence(
                "a premium rate is required when the price includes buyer's premium")
        hammer = round_money(amount / (Decimal(1) + premium_rate))
    else:
        hammer = amount
    if currency == "GBP":
        return hammer
    if fx_rate is None:
        return None
    return round_money(hammer * fx_rate)


def per_bottle_hammer_gbp(hammer_gbp: Decimal, bottles_in_lot: int) -> Decimal:
    """Read-time only (spec step 3): never stored, never exported. A
    6-bottle lot at £3,000 may be SHOWN as £500/btl; that figure must never
    flow into benchmark.py, pricing, or an export."""
    return round_money(hammer_gbp / bottles_in_lot)


@dataclass(frozen=True)
class AuctionHealth:
    lot_count: int
    median_per_bottle_gbp: Optional[Decimal]
    earliest_sale_date: Optional[date]
    latest_sale_date: Optional[date]
    source_urls: list[str]
    flag: Optional[str]                         # AUCTION_BELOW_REFERENCE | None
    note: Optional[str] = None


def auction_health(lots: list[dict], *, uk_reference_per_bottle: Optional[Decimal]) -> AuctionHealth:
    """Pure: `lots` are already filtered (non-retracted, non-quarantined,
    within the window) rows with hammer_gbp/bottles_in_lot/sale_date/
    source_url — app/auction/repo.py's job, reading the database; this
    function never touches a connection.

    `lot_count` counts every qualifying lot, including one whose
    `hammer_gbp` is absent for want of an FX rate — it is still a real
    auction result, just not one the median can use. If the line has no UK
    Reference, the note says plainly that auction evidence is not a price,
    whether or not there are any lots to show as context.
    """
    note = "No UK market. Auction evidence is not a price." if uk_reference_per_bottle is None else None
    if not lots:
        return AuctionHealth(0, None, None, None, [], None, note=note)

    priced = [l for l in lots if l["hammer_gbp"] is not None]
    per_bottle = sorted(per_bottle_hammer_gbp(Decimal(str(l["hammer_gbp"])), l["bottles_in_lot"])
                        for l in priced)
    median = None
    if per_bottle:
        n = len(per_bottle)
        median = (per_bottle[n // 2] if n % 2
                 else round_money((per_bottle[n // 2 - 1] + per_bottle[n // 2]) / 2))

    flag = None
    if (median is not None and uk_reference_per_bottle is not None
            and median < uk_reference_per_bottle * (Decimal(1) - AUCTION_BELOW_REFERENCE_THRESHOLD)):
        flag = AUCTION_BELOW_REFERENCE

    dates = sorted(l["sale_date"] for l in lots)
    return AuctionHealth(len(lots), median, dates[0], dates[-1],
                         [l["source_url"] for l in lots], flag, note=note)
