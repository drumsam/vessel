"""VESSEL Private Sale — the pricing and evidence rules. Pure: no clock, no
network, no database.

VESSEL buys nothing. It lists a seller's own wine under a time-boxed mandate,
sets the price, and takes a fee on the buyer's price when it sells — a
different business from app/pricing/pricer.py's buyer-discount chain (direct
purchase and resale), even though both currently use an 8% figure. The two
are not the same constant wearing two names: they can diverge independently,
so each module owns its own.

docs/decisions/0020-vessel-private-sale.md,
docs/research/vessel-private-sale-v4.md (governs over v3 where they differ).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional

CENT = Decimal("0.01")
ROUNDING = ROUND_HALF_EVEN


class CannotList(Exception):
    """The evidence or the arithmetic does not support listing this line."""


def round_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUNDING)


#: VESSEL's fee, taken on the buyer-facing VESSEL price. A different number
#: from app/pricing/pricer.MARGIN_ON_SALE by coincidence of value, not of
#: meaning: that one prices a direct purchase-and-resale; this one prices a
#: consignment VESSEL never owns.
VESSEL_FEE = Decimal("0.08")

#: Three internal bands, invisible to the seller and the buyer alike. The
#: discount actually used must fall inside the band it is stored against —
#: enforced again at the database (vessel_listing_discount_in_band) so the
#: two can never disagree.
DEFAULT_BAND = "NORMAL"
BAND_RANGES: dict[str, tuple[Decimal, Optional[Decimal]]] = {
    "STRONG": (Decimal("0.10"), Decimal("0.15")),
    "NORMAL": (Decimal("0.15"), Decimal("0.20")),
    "CLEARANCE": (Decimal("0.20"), None),          # "20-25%+" — no stated ceiling
}

#: Nearest 500 in HKD, nearest 50 in GBP (task spec, 6 October 2026).
CLEAN_FIGURE_STEP: dict[str, Decimal] = {"HKD": Decimal("500"), "GBP": Decimal("50")}

#: Below this, in GBP, freight, transfer, payment and insurance eat the fee
#: (v4, "still open" §2). Configurable: pass `minimum` to recommend() to
#: override.
MIN_LISTING_VALUE_GBP = Decimal("400")

#: 30 minutes under HK$50,000, 2 hours at or above it — bank transfers at
#: size are not instant (v3, "four decisions" §3; confirmed by the brief).
HOLD_THRESHOLD_HKD = Decimal("50000")
HOLD_SHORT = timedelta(minutes=30)
HOLD_LONG = timedelta(hours=2)

#: Submitting proof of payment extends the hold ONCE, by this fixed amount —
#: never the original hold_duration() again, and never a second time.
#: Capped in code (app/vessel/repo.submit_proof_of_payment): after this
#: extension lapses unpaid, a timer no longer resolves it, an operator does
#: (revision, 7 October 2026).
PROOF_OF_PAYMENT_EXTENSION = timedelta(hours=2)


def round_to_clean_figure(value: Decimal, currency: str) -> Decimal:
    """HK$69,473 -> HK$69,500. A computed price that looks computed invites
    haggling (v3). Nearest step, half-even, never a fixed direction — v3 said
    "rounded down"; v4 and the brief both just say "a clean figure", and
    always-down would be the one place this design favours VESSEL over the
    seller for no stated reason. Treated as v4 superseding v3 here."""
    step = CLEAN_FIGURE_STEP[currency]
    return (value / step).quantize(Decimal("1"), rounding=ROUNDING) * step


def hkd_equivalent(amount: Decimal, currency: str, fx_hkd_per_gbp: Optional[Decimal]) -> Decimal:
    """`fx_hkd_per_gbp` is named for its direction on purpose — a bare
    "fx_rate" is exactly how a 100x conversion error happens unnoticed
    (revision, 7 October 2026). Stored on the listing at pricing time. This
    is a business-rule conversion (which hold window, which minimum
    applies), never a display conversion — the stored currency and amount
    are what is shown, always."""
    if currency == "HKD":
        return amount
    if not fx_hkd_per_gbp:
        raise CannotList(f"no FX rate to convert {currency} to HKD")
    return amount * fx_hkd_per_gbp


def gbp_equivalent(amount: Decimal, currency: str, fx_hkd_per_gbp: Optional[Decimal]) -> Decimal:
    if currency == "GBP":
        return amount
    if not fx_hkd_per_gbp:
        raise CannotList(f"no FX rate to convert {currency} to GBP")
    return amount / fx_hkd_per_gbp


def resolve_discount(band: str, discount: Optional[Decimal] = None) -> Decimal:
    """The discount actually applied, validated against the band it is
    stored with. Defaults to the band's shallow edge — the most conservative
    choice, best for the seller — when the operator does not name one."""
    if band not in BAND_RANGES:
        raise CannotList(f"{band!r} is not a recognised band")
    low, high = BAND_RANGES[band]
    if discount is None:
        return low
    if discount < low or (high is not None and discount >= high):
        raise CannotList(f"{discount} is outside the {band} band ({low}-{high or 'open'})")
    return discount


@dataclass(frozen=True)
class VesselPrice:
    vessel_price: Decimal      # clean figure, lot total, in the listing's currency
    seller_net: Decimal        # vessel_price x (1 - VESSEL_FEE)


def price_listing(market_reference: Decimal, *, band: str, currency: str,
                  discount: Optional[Decimal] = None) -> VesselPrice:
    """market_reference is the LOT TOTAL (all bottles), in `currency` — the
    same units everything else on the listing is in. VESSEL price is rounded
    to a clean figure and never changes inside a drop; seller net is not
    separately rounded, it is simply 92% of the already-clean figure."""
    if market_reference <= 0:
        raise CannotList("a listing needs a positive market reference")
    discount = resolve_discount(band, discount)
    raw = market_reference * (Decimal(1) - discount)
    vessel_price = round_to_clean_figure(raw, currency)
    if vessel_price <= 0:
        raise CannotList("this line prices at zero or less and cannot be listed")
    seller_net = round_money(vessel_price * (Decimal(1) - VESSEL_FEE))
    return VesselPrice(vessel_price=vessel_price, seller_net=seller_net)


def commission_due(vessel_price: Decimal, seller_net: Decimal) -> Decimal:
    """What VESSEL invoices under an AGENCY mandate (decision 0022): the
    complement of seller_net, never independently rounded, so commission +
    seller_net always equals vessel_price exactly — the buyer pays the
    seller the full vessel_price directly, and this is the figure VESSEL
    separately bills for."""
    return vessel_price - seller_net


def meets_minimum_value(vessel_price: Decimal, currency: str, fx_hkd_per_gbp: Optional[Decimal],
                        *, minimum_gbp: Decimal = MIN_LISTING_VALUE_GBP) -> bool:
    return gbp_equivalent(vessel_price, currency, fx_hkd_per_gbp) >= minimum_gbp


def hold_duration(vessel_price: Decimal, currency: str,
                  fx_hkd_per_gbp: Optional[Decimal]) -> timedelta:
    hkd = hkd_equivalent(vessel_price, currency, fx_hkd_per_gbp)
    return HOLD_SHORT if hkd < HOLD_THRESHOLD_HKD else HOLD_LONG


#: Named reference markets a listing may price from (decision 0020 revision,
#: 7 October 2026, from docs/research/hk-vs-uk-market-reference.md — the
#: median and range it reports, median HK retail +22% over UK In Bond, 9
#: matched pairs, range -21% to +46%, are reported directly in this
#: decision's documentation, not encoded here: the discount a listing
#: actually uses still comes from the operator's band choice, same as UK
#: In Bond. "A listing needs a named reference market, not one implicit
#: one" — UK_IN_BOND was always the market; it just was not named before.
MARKET_LABELS: dict[str, str] = {"UK_IN_BOND": "UK In Bond", "HK_RETAIL": "Hong Kong retail"}
DEFAULT_MARKET = "UK_IN_BOND"


@dataclass(frozen=True)
class EvidenceClaim:
    """What a listing may say about its own evidence (the load-bearing rule).

    `can_list` is False exactly when source_count is 0, or it is 1 and
    either the market is not UK_IN_BOND (no HK-equivalent single-source
    sanity check exists yet — refused rather than guessed at) or the
    vintage-band sanity check did not both run and pass for this line's one
    comp. `percentage_claim_pct` is set only with two or more sources — the
    database repeats this as a CHECK constraint so the rule cannot be
    bypassed by a future code path that forgets this function exists.
    """
    can_list: bool
    reference_label: str                    # "Market reference" | "Indicative reference" | ""
    percentage_claim_pct: Optional[Decimal]
    reason: Optional[str] = None             # set when can_list is False


def reference_label(market: str, source_count: int) -> str:
    """UK_IN_BOND keeps its original, unqualified wording — every listing
    built before markets were named used exactly this text, and nothing
    about naming the market retroactively changes what they said. Any other
    market names itself: "Hong Kong retail reference"."""
    if market == DEFAULT_MARKET:
        return "Market reference" if source_count >= 2 else "Indicative reference"
    label = MARKET_LABELS.get(market, market)
    return f"{label} reference" if source_count >= 2 else f"Indicative {label} reference"


def market_claim_sentence(market: str, percentage_claim_pct: Optional[Decimal]) -> Optional[str]:
    """"34% below the best Hong Kong retail offer we can find" — the exact
    page-claim shape from the request. None when there is no percentage
    claim to make (invariant 15: absent, not blank)."""
    if percentage_claim_pct is None:
        return None
    pct = int((percentage_claim_pct * 100).to_integral_value(rounding=ROUNDING))
    label = MARKET_LABELS.get(market, market)
    return f"{pct}% below the best {label} offer we can find"


def evidence_claim(source_count: int, *, vintage_band_passed: bool,
                   market: str = DEFAULT_MARKET,
                   market_reference: Optional[Decimal] = None,
                   vessel_price: Optional[Decimal] = None) -> EvidenceClaim:
    if source_count <= 0:
        return EvidenceClaim(False, "", None, "no market: zero independent sources")
    if source_count == 1:
        if market != DEFAULT_MARKET:
            return EvidenceClaim(
                False, "", None,
                f"thin evidence: one {MARKET_LABELS.get(market, market)} source, and no "
                "sanity check like the UK In Bond vintage band exists yet for this market")
        if not vintage_band_passed:
            return EvidenceClaim(
                False, "", None,
                "thin evidence: one source, and the vintage-band sanity check "
                "did not pass for it")
        return EvidenceClaim(True, reference_label(market, 1), None)
    pct = None
    if market_reference is not None and vessel_price is not None and market_reference > 0:
        pct = ((market_reference - vessel_price) / market_reference).quantize(
            Decimal("0.0001"), rounding=ROUNDING)
    return EvidenceClaim(True, reference_label(market, source_count), pct)
