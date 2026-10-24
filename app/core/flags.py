"""Flag vocabulary and the single definition of what forces operator review.

One rule, one place. If a flag is in REVIEW_FLAGS the line cannot be READY —
with exactly one named exception, decided in `BenchmarkResult.state`
(`app/core/benchmark.py`), not here: DERIVED_FROM_CASE stops gating once two
or more merchants' comps agree WITH EACH OTHER, within AGREEMENT_THRESHOLD —
region-independent (decision 0028, correcting 0023's own first attempt,
which expressed agreement only through a vintage band that exists for
Burgundy alone and so could never fire anywhere else). Where a band also
exists for the line's region, it must agree too
(`SellerLine.derivation_confirmed`) — the band is strictly more information
and is not given up for Burgundy. The set below is unchanged by that
exception — DERIVED_FROM_CASE is still a member, still gates a single-comp
line, and is still shown on every line it was ever added to. The exception
lives where it is checked, so this file keeps being the one place the
MEMBERSHIP is defined, even though membership alone no longer decides every
line's state.
"""
from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Optional

from .enums import ConditionFlag


class Flag(str, Enum):
    # market-shape flags
    ONE_COMP = "ONE_COMP"
    WIDE_SPREAD = "WIDE_SPREAD"
    NO_MARKET = "NO_MARKET"
    QUANTITY_SHORTFALL = "QUANTITY_SHORTFALL"
    #: A two-sided market's own bid and ask for the same wine, vintage and
    #: format disagree by more than WIDE_SPREAD_THRESHOLD (decision 0026,
    #: from a live BI LiveTrade find: Krug 162e bid £660 against offer
    #: £1,596 on the same 6x75cl listing). Informational, like WIDE_SPREAD
    #: itself — see REVIEW_FLAGS below for why it is not there.
    TWO_SIDED_WIDE_SPREAD = "TWO_SIDED_WIDE_SPREAD"

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
    #: sell_price >= uk_floor (decision 0033). With exactly two comps,
    #: Reference is the DEARER of the two, so a buyer_discount price below
    #: Reference can still land at or above the cheapest ask we actually
    #: found — found live on four real Champagne lines, one of them only
    #: 1.7% above floor. "Below market" must mean below the cheapest ask,
    #: not below whichever number the benchmark happened to call Reference.
    #: Same family as NEGATIVE_GP/SELL_ABOVE_UK_REFERENCE (an operator can
    #: still accept and export it), but the market claim is a stronger,
    #: unconditional rule: this flag's own presence suppresses the claim
    #: outright, acceptance or not (app/db/repo.py's own `_claim`) — "X%
    #: below market" would be false regardless of who accepted the gate.
    SELL_AT_OR_ABOVE_UK_FLOOR = "SELL_AT_OR_ABOVE_UK_FLOOR"


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

#: WIDE_SPREAD is deliberately NOT a review flag for THREE OR MORE
#: independent merchants — there the Reference is sound even when the tail
#: is long, and the spread is shown to the operator as context. "Revisit
#: if operators disagree in practice" was this comment's own instruction,
#: and decision 0033 is that revisit: with EXACTLY two comps the reasoning
#: does not hold — the tail IS the whole sample, and the Reference is just
#: the dearer of two numbers that contradict each other, not one outlier
#: against a body of agreement. `BenchmarkResult.state` (benchmark.py) adds
#: WIDE_SPREAD to the gating set specifically when `comp_count == 2`; this
#: set and membership here are both unchanged, matching how 0028 already
#: overrides DERIVED_FROM_CASE's own gating in the same property rather
#: than here. The original reasoning was correct as written and
#: incomplete, not wrong — it is still exactly right for 3+ comps.
#:
#: TWO_SIDED_WIDE_SPREAD is the same kind of context, for a different shape of
#: evidence: a bid is never a comparable (the KIND screen excludes it exactly
#: like an INDICATION), so there is no arithmetic for a wide bid/ask spread to
#: corrupt. It exists so the operator sees, named, that a market's own bid and
#: ask disagree enough that neither should be read as confirming the other —
#: not a gate, because nothing it touches was ever priced from it.

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
#: That same reasoning is why decision 0023 (corrected by 0028) trusts SOURCE
#: AGREEMENT rather than this constant: a line with two or more comps that
#: independently agree WITH EACH OTHER, within AGREEMENT_THRESHOLD, has
#: evidence this specific wine's derived price is right, regardless of what
#: CASE_PREMIUM says about wines in general. DERIVED_FROM_CASE stops gating
#: on that evidence; it never stops being added, and one comp is never
#: enough to supply it.
#:
#: See docs/research/case-premium-measurement.md and decisions 0016, 0023,
#: 0028.
CASE_PREMIUM = Decimal("1.00")

#: Decision 0028. DERIVED_FROM_CASE stops gating a 2+-comp line when every
#: merchant_best price sits within this fraction of the lowest one —
#: region-independent, no vintage band required (0023's own spec required a
#: band that only exists for Burgundy, so outside it the exemption could
#: never fire at all — the Champagne sweep's whole 454-bottle Krug position
#: is proof of exactly that dead end). Where a band DOES exist, both tests
#: are required (see `app/worker/jobs.benchmark_with_band`): the band is
#: strictly more information and is not given up for Burgundy.
#:
#: Set from the live Champagne sweep's own spread, 9-10 October 2026 — the
#: full ladder of every 2+-comp line found, Floor to Reference:
#:   5.7, 8.7, 12.6, 18.5, 20.0, 23.8, 27.1, 27.3, 40.5, 57.0  (%)
#: 10% draws the line after the first two (Dom Pérignon Rosé 2006 at 5.7%,
#: Louis Roederer Cristal 2005 at 8.7%) and holds every other real gap found,
#: including Taittinger Comtes de Champagne 2006 and 2008 at 57.0% and
#: 40.5% — two merchants 40% apart is not agreement, however many of them
#: there are. See docs/decisions/0028.
AGREEMENT_THRESHOLD = Decimal("0.10")

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

#: Decision 0034. A line below this saving against Floor carries no percentage
#: claim at all — same discipline as a line with no UK Reference (invariant
#: 15): absent, not a number too small to be worth printing. A starting value,
#: not a measured one ("I'd start at 5%" — Doug, 19 October 2026); revisit
#: once more real drops have gone out the door than this one.
MIN_CLAIM_THRESHOLD = Decimal("0.05")


def floor_saving(sell_price: Decimal, uk_floor: Optional[Decimal]) -> Optional[Decimal]:
    """(1 - sell/floor), or None if there is no Floor to measure against.

    Decision 0034: every percentage claim is computed against Floor, the
    cheapest ask actually found — never against Reference, which decision
    0033 already showed can itself be the dearer of only two numbers. Pure
    arithmetic from figures already stored on `pricing_result`; nothing here
    is a price and nothing here is recomputed by a client — this is the one
    place it is computed, and every caller (the Desk, a client document)
    reads the result, never the two figures it came from.
    """
    if uk_floor is None or uk_floor <= 0:
        return None
    return ((uk_floor - sell_price) / uk_floor).quantize(Decimal("0.0001"))


def claims_a_saving(sell_price: Decimal, uk_floor: Optional[Decimal]) -> Optional[Decimal]:
    """`floor_saving`, but None also when it exists and is too small to print
    (decision 0034's own `MIN_CLAIM_THRESHOLD`) — Dom Pérignon Vintage 2010 at
    0.9% below Floor and Louis Roederer Cristal 2007 at 4.0%, both real, both
    found the moment Floor replaced Reference as the basis: a line that is
    barely below the cheapest ask is not advertisable as a discount, though
    it is still perfectly sellable at that price."""
    saving = floor_saving(sell_price, uk_floor)
    if saving is None or saving < MIN_CLAIM_THRESHOLD:
        return None
    return saving
