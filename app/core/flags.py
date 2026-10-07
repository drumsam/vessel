"""Flag vocabulary and the single definition of what forces operator review.

One rule, one place. If a flag is in REVIEW_FLAGS the line cannot be READY —
with exactly one named exception, decided in `BenchmarkResult.state`
(`app/core/benchmark.py`), not here: DERIVED_FROM_CASE stops gating once two
or more merchants' comps agree with their own quality-matched neighbouring
vintages (decision 0023, `SellerLine.derivation_confirmed`). The set below is
unchanged by that exception — DERIVED_FROM_CASE is still a member, still
gates a single-comp line, and is still shown on every line it was ever added
to. The exception lives where it is checked, so this file keeps being the one
place the MEMBERSHIP is defined, even though membership alone no longer
decides every line's state.
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


#: A line carrying any of these cannot be READY, with one named exception
#: decided in `BenchmarkResult.state`, not here: DERIVED_FROM_CASE stops
#: gating a line with 2+ comps once they agree with the vintage band
#: (decision 0023). Reviewed 2026-09-24, exception added 7 October 2026.
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

#: The case premium, per bottle, when a comparable is derived across case sizes
#: (decision 0016). **Measured**, 24 September 2026, not assumed: 27 paired
#: same-day observations of the same wine, vintage and bottle size in loose and
#: case form, Bordeaux Index, In Bond, 750ml.
#:
#:     median 1.0000 · mean 0.9737 · n = 27 · range 0.7038 to 1.1525
#:     10 of 27 identical to the penny · 16 of 27 within 5% of parity
#:
#: A case is priced at the same rate per bottle as a loose bottle more often
#: than at any other rate, and when it differs it is slightly more often
#: CHEAPER per bottle, not dearer. The 5% this started as was not far off the
#: centre, but it was biased in the one direction that matters: a derived figure
#: that is too high raises the UK Reference, which is how we overpay and how a
#: client gets overpriced. Parity has no such bias.
#:
#: The SPREAD is the real finding, and it is why nothing else about 0016
#: changed: a quarter of the pairs sit more than 5% from parity and the tails
#: run to -30% and +15%. No constant can be right about an individual wine, so a
#: derived comparable always carries DERIVED_FROM_CASE and always ranks behind
#: a real offer at the seller's own unit.
#:
#: That same reasoning is why decision 0023 trusts SOURCE AGREEMENT rather
#: than this constant: a line with two or more comps that independently agree
#: with their own quality-matched neighbouring vintages has evidence this
#: specific wine's derived price is right, regardless of what CASE_PREMIUM
#: says about wines in general. DERIVED_FROM_CASE stops gating on that
#: evidence; it never stops being added, and one comp is never enough to
#: supply it.
#:
#: See docs/research/case-premium-measurement.md and decisions 0016, 0023.
CASE_PREMIUM = Decimal("1.00")

#: Derivation is 750ml only. Magnums and above carry a scarcity premium that has
#: nothing to do with the wine in the bottle, and half bottles the mirror of it,
#: so neither converts in either direction (decision 0016).
DERIVABLE_BOTTLE_ML = 750

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
