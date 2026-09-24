"""Flag vocabulary and the single definition of what forces operator review.

One rule, one place. If a flag is in REVIEW_FLAGS the line cannot be READY.
"""
from __future__ import annotations
from decimal import Decimal
from enum import Enum

from .enums import ConditionFlag


class Flag(str, Enum):
    # market-shape flags
    ONE_COMP = "ONE_COMP"
    WIDE_SPREAD = "WIDE_SPREAD"
    NO_MARKET = "NO_MARKET"
    QUANTITY_SHORTFALL = "QUANTITY_SHORTFALL"

    # evidence-quality flags
    CONDITION_REVIEW = "CONDITION_REVIEW"
    STOCK_BASIS_UNCONFIRMED = "STOCK_BASIS_UNCONFIRMED"
    DERIVED_FROM_CASE = "DERIVED_FROM_CASE"

    # vintage-band flags (set by app/market/vintage_band.py after the benchmark
    # and inherited back into it; the core never computes a band). See 0015.
    COMP_EXCLUDED_VINTAGE_BAND = "COMP_EXCLUDED_VINTAGE_BAND"
    LOW_COMP_OUT_OF_BAND = "LOW_COMP_OUT_OF_BAND"

    # identity flags (set upstream by identity verification, carried through)
    NAME_REVIEW = "NAME_REVIEW"
    FORMAT_REVIEW = "FORMAT_REVIEW"

    # commercial flags (set by the pricing step, not the benchmark)
    COST_ABOVE_UK_REFERENCE = "COST_ABOVE_UK_REFERENCE"
    SELL_ABOVE_UK_REFERENCE = "SELL_ABOVE_UK_REFERENCE"
    NEGATIVE_GP = "NEGATIVE_GP"
    DEEP_DISCOUNT = "DEEP_DISCOUNT"


#: A line carrying any of these cannot be READY. Reviewed 2026-09-24.
#: ONE_COMP is here because a single merchant is not a market — a benchmark
#: resting on one comp is exactly the case an operator must look at.
#: The two band flags are here by Doug's decision of 24 September: a line where
#: a dear comp was thrown out, or where a cheap one looks wrong, always reaches
#: a person — not only when ONE_COMP happens to catch it. See 0015.
REVIEW_FLAGS: frozenset[Flag] = frozenset({
    Flag.ONE_COMP,
    Flag.CONDITION_REVIEW,
    Flag.STOCK_BASIS_UNCONFIRMED,
    Flag.DERIVED_FROM_CASE,
    Flag.NAME_REVIEW,
    Flag.FORMAT_REVIEW,
    Flag.COMP_EXCLUDED_VINTAGE_BAND,
    Flag.LOW_COMP_OUT_OF_BAND,
})

#: WIDE_SPREAD is deliberately NOT a review flag. With two or more independent
#: merchants the Reference is sound even when the tail is long; the spread is
#: shown to the operator as context. Revisit if operators disagree in practice.

#: Condition flags that make a comp questionable enough to force review.
#: REPACK and NO_ORIGINAL_CASE are excluded on purpose: in the loose-bottle
#: Burgundy market they are the norm, not a defect, and gating on them would
#: send every Burgundy line to review and train operators to click through.
CONDITION_REVIEW_FLAGS: frozenset[ConditionFlag] = frozenset({
    ConditionFlag.NON_PRISTINE,
    ConditionFlag.LABEL_DAMAGE,
    ConditionFlag.LEVEL_ISSUE,
    ConditionFlag.CAPSULE_OR_CORK,
    ConditionFlag.SIGNS_OF_SEEPAGE,
})

#: Spread above this counts as WIDE_SPREAD.
WIDE_SPREAD_THRESHOLD = 0.25

#: The vintage-band thresholds (decision 0015). They live here beside
#: WIDE_SPREAD_THRESHOLD because they decide which comps an operator is made to
#: look at, but the core never reads them: the band is computed in
#: app/market/vintage_band.py, after the benchmark, on its result.
#:
#: A comp above band_high x HIGH_MULTIPLE is excluded automatically. A comp
#: below band_low x LOW_MULTIPLE is flagged and KEPT — dropping a cheap comp
#: pushes the Reference up, which makes us overpay and lets us overprice a
#: client, and no automatic rule may be able to cause that.
HIGH_MULTIPLE = Decimal("1.35")
LOW_MULTIPLE = Decimal("0.65")

#: One merchant disagreeing with itself across formats by more than this, per
#: bottle, is evidence about that comp. It never becomes a comp of its own.
FORMAT_INCOHERENCE = Decimal("0.30")

#: See docs/decisions/0002-quantity-sufficiency.md.
#: False  -> offered quantity is ignored when deciding comparability; a shortfall
#:           is surfaced as the informational flag QUANTITY_SHORTFALL only.
#: True   -> an offer must cover the seller's quantity to be comparable.
REQUIRE_QUANTITY_COVER = False

#: See docs/decisions/0003-offer-freshness.md.
#: An offer captured more than this many days before the benchmark's `as_of`
#: (or after it, or at an unknown time) is rejected as STALE. It cannot become a
#: Floor, a Reference or a Median, however cheap it is.
MAX_OFFER_AGE_DAYS = 14
