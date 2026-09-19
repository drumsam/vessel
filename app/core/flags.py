"""Flag vocabulary and the single definition of what forces operator review.

One rule, one place. If a flag is in REVIEW_FLAGS the line cannot be READY.
"""
from __future__ import annotations
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

    # identity flags (set upstream by identity verification, carried through)
    NAME_REVIEW = "NAME_REVIEW"
    FORMAT_REVIEW = "FORMAT_REVIEW"

    # commercial flags (set by the pricing step, not the benchmark)
    COST_ABOVE_UK_REFERENCE = "COST_ABOVE_UK_REFERENCE"
    SELL_ABOVE_UK_REFERENCE = "SELL_ABOVE_UK_REFERENCE"
    NEGATIVE_GP = "NEGATIVE_GP"
    DEEP_DISCOUNT = "DEEP_DISCOUNT"


#: A line carrying any of these cannot be READY. Reviewed 2026-09-19.
#: ONE_COMP is here because a single merchant is not a market — a benchmark
#: resting on one comp is exactly the case an operator must look at.
REVIEW_FLAGS: frozenset[Flag] = frozenset({
    Flag.ONE_COMP,
    Flag.CONDITION_REVIEW,
    Flag.STOCK_BASIS_UNCONFIRMED,
    Flag.DERIVED_FROM_CASE,
    Flag.NAME_REVIEW,
    Flag.FORMAT_REVIEW,
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
