"""The vintage-neighbour sanity check, on the live numbers that prompted it.

Spec: docs/research/vintage-neighbour-check-spec.md §7. House style as in
test_traps.py: name the merchant, the wine, and the size of the error the test
prevents.

The tiers come from the register the system actually ships with
(`docs/research/vintage-tiers.csv`), not from numbers invented here. If a tier
in that file changes, these tests are where it shows up.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.benchmark import benchmark
from app.core.enums import DutyStatus, PriceKind, State, StockType
from app.core.flags import REVIEW_FLAGS, Flag
from app.core.models import Offer, SellerLine
from app.market.vintage_band import (
    COMP_EXCLUDED_VINTAGE_BAND,
    LOW_COMP_OUT_OF_BAND,
    MERCHANT_FORMAT_INCOHERENT,
    band_flags,
    check_vintage_band,
    without_high_outliers,
)

AS_OF = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
MUGNERET = "w-mugneret-gibourg-vosne"

REGISTER = Path(__file__).parents[1] / "docs/research/vintage-tiers.csv"


def tiers(region: str = "BURGUNDY_RED") -> dict[int, int]:
    """The shipped register, read as the loader reads it."""
    with REGISTER.open(newline="", encoding="utf-8") as fh:
        return {int(r["vintage"]): int(r["tier"])
                for r in csv.DictReader(fh) if r["region"] == region}


RED = tiers()
WHITE = tiers("BURGUNDY_WHITE")


def offer(merchant_id: str, price: str, *, vintage: int = 2020, pack_size: int = 6,
          wine_id: str = MUGNERET, bottle_ml: int = 750, days_old: int = 1,
          merchant: str | None = None, **kw) -> Offer:
    base = dict(
        offer_id=f"{merchant_id}:{vintage}:{pack_size}:{price}", merchant_id=merchant_id,
        merchant=merchant or merchant_id, wine_id=wine_id, vintage=vintage,
        bottle_ml=bottle_ml, pack_size=pack_size, price=Decimal(price), currency="GBP",
        duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK, is_buyable=True,
        offered_units=6, stock_type=StockType.MERCHANT_STOCK,
        captured_at=AS_OF - timedelta(days=days_old))
    base.update(kw)
    return Offer(**base)


def line(vintage: int = 2020, pack_size: int = 6, quantity: int = 6, **kw) -> SellerLine:
    return SellerLine(line_id="L21", raw_description="Mugneret-Gibourg Vosne-Romanée 2020",
                      wine_id=MUGNERET, vintage=vintage, bottle_ml=750,
                      pack_size=pack_size, quantity=quantity, **kw)


#: Bordeaux Index's own price curve for this wine and unit, captured live
#: 23 September 2026 (spec §"The evidence that the idea works").
BI_NEIGHBOURS = [
    offer("bordeaux-index", "1489.00", vintage=2016), offer("bordeaux-index", "1543.00", vintage=2016),
    offer("bordeaux-index", "1489.00", vintage=2017), offer("bordeaux-index", "1520.00", vintage=2017),
    offer("bordeaux-index", "1223.00", vintage=2018),
    # 2019: none
]
BI_2020 = offer("bordeaux-index", "2070.00", merchant="Bordeaux Index")
LS_2020 = offer("lea-sandeman", "1200.00", merchant="Lea & Sandeman")


def test_mugneret_gibourg_2020_six_pack_is_a_high_outlier():
    """Lea & Sandeman £1,200, Bordeaux Index £2,070 for 2020 Mugneret-Gibourg
    Vosne-Romanée 6x75 In Bond. Two merchants, so the Reference is the dearer:
    the line would price off a number 72% above a live UK ask. BI's own
    neighbouring vintages sit in a £1,223-£1,489 band."""
    comps = [LS_2020, BI_2020]
    before = benchmark(line(), comps, as_of=AS_OF)
    assert before.uk_reference == Decimal("2070.00") and before.state is State.READY

    check = check_vintage_band(line(), before.comparables, neighbour_offers=BI_NEIGHBOURS,
                               as_of=AS_OF, tiers=RED)
    # 2020 is tier 2. Of BI's curve only 2016 is also tier 2, which is one
    # vintage, so the selection widens once to tier 2±1 and takes 2017 and 2018.
    # One merchant, so each vintage's merchant-best is its cheaper listing.
    assert (check.band_low, check.band_high) == (Decimal("1223.00"), Decimal("1489.00"))
    assert [(n.vintage, n.median, n.tier) for n in check.neighbours] == [
        (2016, Decimal("1489.00"), 2), (2017, Decimal("1489.00"), 3),
        (2018, Decimal("1223.00"), 3)]
    assert [o.merchant for o in check.high_outliers] == ["Bordeaux Index"]
    assert check.high_outliers[0].flag == COMP_EXCLUDED_VINTAGE_BAND
    assert check.low_outliers == []

    after = benchmark(line(), without_high_outliers(comps, check), as_of=AS_OF)
    assert after.uk_reference == Decimal("1200.00")          # falls from £2,070
    assert after.state is State.REVIEW and Flag.ONE_COMP in after.flags


def test_an_excluded_comp_always_reaches_a_person():
    """Decision 0015: both band flags are review flags. A line whose dear comp
    was thrown out reaches a human even when two merchants remain — which
    ONE_COMP would not have caught."""
    third = offer("farr", "1250.00", merchant="Farr Vintners")
    comps = [LS_2020, BI_2020, third]
    check = check_vintage_band(line(), benchmark(line(), comps, as_of=AS_OF).comparables,
                               neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF, tiers=RED)
    assert band_flags(check) == frozenset({Flag.COMP_EXCLUDED_VINTAGE_BAND})

    flagged = line(inherited_flags=band_flags(check))
    after = benchmark(flagged, without_high_outliers(comps, check), as_of=AS_OF)
    assert after.comp_count == 2 and Flag.ONE_COMP not in after.flags
    assert Flag.COMP_EXCLUDED_VINTAGE_BAND in after.flags
    assert after.state is State.REVIEW
    assert {Flag.COMP_EXCLUDED_VINTAGE_BAND, Flag.LOW_COMP_OUT_OF_BAND} <= REVIEW_FLAGS


def test_low_outlier_is_never_auto_excluded():
    """Goedhuis brokered 2017 Faiveley NSG Les Damodes at £350 against Lea &
    Sandeman's £445. Dropping a cheap comp pushes the Reference UP, which makes
    us overpay and lets us overprice a client. It is flagged and kept."""
    faiveley = "w-faiveley-damodes"
    comps = [offer("goedhuis", "350.00", vintage=2017, wine_id=faiveley, merchant="Goedhuis"),
             offer("lea-sandeman", "445.00", vintage=2017, wine_id=faiveley,
                   merchant="Lea & Sandeman")]
    neighbours = [offer("bordeaux-index", "600.00", vintage=2016, wine_id=faiveley),
                  offer("bordeaux-index", "560.00", vintage=2018, wine_id=faiveley)]
    target = SellerLine("L61", "Faiveley Damodes 2017", faiveley, 2017, 750, 6, 6)

    check = check_vintage_band(target, comps, neighbour_offers=neighbours, as_of=AS_OF,
                               tiers=RED)
    assert [o.merchant for o in check.low_outliers] == ["Goedhuis"]
    assert check.low_outliers[0].flag == LOW_COMP_OUT_OF_BAND
    assert check.high_outliers == []
    assert band_flags(check) == frozenset({Flag.LOW_COMP_OUT_OF_BAND})

    kept = without_high_outliers(comps, check)
    assert len(kept) == 2
    assert benchmark(target, kept, as_of=AS_OF).uk_reference == Decimal("445.00")


def test_band_needs_two_neighbour_vintages():
    """One neighbouring vintage is an anecdote. Silence, not a guess."""
    check = check_vintage_band(line(), [BI_2020, LS_2020],
                               neighbour_offers=[offer("bordeaux-index", "1223.00", vintage=2018)],
                               as_of=AS_OF, tiers=RED)
    assert (check.band_low, check.band_high) == (None, None)
    assert check.high_outliers == [] and check.low_outliers == []
    assert "not enough neighbouring vintages" in check.note


def test_band_never_sets_a_price():
    """Three neighbouring vintages and no comps at all: still NO_MARKET. A band
    is not a price and is never interpolated into a missing vintage."""
    result = benchmark(line(), [], as_of=AS_OF)
    check = check_vintage_band(line(), result.comparables, neighbour_offers=BI_NEIGHBOURS,
                               as_of=AS_OF, tiers=RED)
    assert result.state is State.NO_MARKET and result.uk_reference is None
    assert check.ran and check.band_low == Decimal("1223.00")
    assert check.high_outliers == [] and check.low_outliers == []


def test_no_cross_unit_arithmetic_in_band():
    """A 3x75 neighbour says nothing about a 6x75 band. No division, ever."""
    three_packs = [offer("bordeaux-index", "705.00", vintage=2017, pack_size=3),
                   offer("bordeaux-index", "612.00", vintage=2018, pack_size=3)]
    check = check_vintage_band(line(), [BI_2020], neighbour_offers=three_packs, as_of=AS_OF,
                               tiers=RED)
    assert check.neighbours == [] and check.band_high is None

    mixed = check_vintage_band(line(), [BI_2020], neighbour_offers=BI_NEIGHBOURS + three_packs,
                               as_of=AS_OF, tiers=RED)
    assert [n.vintage for n in mixed.neighbours] == [2016, 2017, 2018]
    assert mixed.band_low == Decimal("1223.00")              # the 3x75s contribute nothing


def test_format_incoherence_is_evidence_not_a_comp():
    """Bordeaux Index prices a single 2020 bottle at £197 while pricing its own
    six-pack at £345 a bottle — a 43% disagreement with itself. Evidence for the
    operator; no offer is created and the arithmetic is untouched."""
    loose = offer("bordeaux-index", "197.00", pack_size=1, merchant="Bordeaux Index")
    check = check_vintage_band(line(), [BI_2020, LS_2020], neighbour_offers=BI_NEIGHBOURS,
                               other_format_offers=[loose], as_of=AS_OF, tiers=RED)
    [disagreement] = check.format_incoherent
    assert disagreement.merchant == "Bordeaux Index"
    assert disagreement.comp_per_bottle == Decimal("345")
    assert disagreement.other_per_bottle == Decimal("197")
    assert disagreement.difference > Decimal("0.30")
    assert disagreement.flag == MERCHANT_FORMAT_INCOHERENT

    # The loose bottle is not a comp for a six-pack line, before or after.
    result = benchmark(line(), [BI_2020, LS_2020, loose], as_of=AS_OF)
    assert result.comp_count == 2
    assert all(o.pack_size == 6 for o in result.merchant_bests)


# --- §4: quality-matched neighbours -------------------------------------------


def test_neighbours_are_quality_matched_not_just_near():
    """Doug's rule: an ordinary vintage prices near another ordinary vintage
    even years away, and a great vintage never prices like a weak one.

    2004 red Burgundy is tier 5 and 2005 is tier 1 — one year apart and not
    comparable at any price. 2000 is tier 4 and so is 2007, seven years away and
    a fair comparison. 2011 is tier 4 as well, but eleven years out: proximity
    still has a limit of ±8 years, because drift beyond that is real.
    """
    w = "w-burgundy-red"

    tier5 = SellerLine("L04", "a 2004 red", w, 2004, 750, 6, 6)
    near_but_great = [offer("m1", "900.00", vintage=2005, wine_id=w),
                      offer("m2", "880.00", vintage=2005, wine_id=w),
                      offer("m1", "600.00", vintage=2003, wine_id=w)]
    check = check_vintage_band(tier5, [], neighbour_offers=near_but_great, as_of=AS_OF,
                               tiers=RED)
    # 2005 is tier 1: four tiers away and refused however close it sits. 2003 is
    # tier 4, one step, so it comes in — and one vintage is not a band.
    assert [(n.vintage, n.tier) for n in check.neighbours] == [(2003, 4)]
    assert check.band_high is None
    assert "not enough neighbouring vintages" in check.note

    tier4 = SellerLine("L00", "a 2000 red", w, 2000, 750, 6, 6)
    far_but_alike = [offer("m1", "500.00", vintage=2007, wine_id=w),   # tier 4, 7 years
                     offer("m1", "520.00", vintage=2003, wine_id=w),   # tier 4, 3 years
                     offer("m1", "480.00", vintage=2011, wine_id=w),   # tier 4, 11 years: out
                     offer("m1", "999.00", vintage=2005, wine_id=w)]   # tier 1, 5 years: out
    far = check_vintage_band(tier4, [], neighbour_offers=far_but_alike, as_of=AS_OF, tiers=RED)
    assert [(n.vintage, n.tier) for n in far.neighbours] == [(2003, 4), (2007, 4)]
    assert (far.band_low, far.band_high) == (Decimal("500.00"), Decimal("520.00"))


def test_no_tier_means_no_band():
    """A region the register does not cover gets no band and no flag, and says
    so. Bordeaux, Champagne and the Rhône are not in the file yet: staying quiet
    is the correct failure, not comparing a great vintage with a weak one."""
    check = check_vintage_band(line(), [BI_2020, LS_2020], neighbour_offers=BI_NEIGHBOURS,
                               as_of=AS_OF, tiers=None)
    assert (check.band_low, check.band_high) == (None, None)
    assert check.high_outliers == [] and check.low_outliers == []
    assert check.tiers_available is False
    assert "no vintage quality data" in check.note

    # And a wine whose own vintage is unrated, in a region that is covered.
    unrated = SellerLine("L90", "a 1990 red", MUGNERET, 1990, 750, 6, 6)
    old = check_vintage_band(unrated, [], neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF,
                             tiers=RED)
    assert old.band_high is None and "no vintage quality data for 1990" in old.note


def test_tier_widening_stops_at_one_step():
    """With fewer than two same-tier neighbours the band may reach tier ±1 and
    never tier ±2. 2020 is tier 2, so 2017 and 2018 (tier 3) are allowed in;
    2021 (tier 4) never is, whatever it costs in coverage."""
    two_steps = [offer("bordeaux-index", "300.00", vintage=2021),      # tier 4
                 offer("bordeaux-index", "320.00", vintage=2013)]      # tier 3
    check = check_vintage_band(line(), [BI_2020], neighbour_offers=two_steps, as_of=AS_OF,
                               tiers=RED)
    assert [(n.vintage, n.tier) for n in check.neighbours] == [(2013, 3)]
    assert check.band_high is None                           # one neighbour is not a band

    widened = check_vintage_band(line(), [BI_2020], neighbour_offers=BI_NEIGHBOURS,
                                 as_of=AS_OF, tiers=RED)
    assert [n.tier for n in widened.neighbours] == [2, 3, 3]
    assert "tier 2±1 was used" in widened.note


def test_the_register_is_keyed_by_colour_as_well_as_region():
    """2014 Burgundy is tier 3 red and tier 1 white; 2009 is tier 2 red and
    tier 4 white. Reading a white wine off the red register would pair a great
    vintage with an ordinary one and call the difference an outlier."""
    assert (RED[2014], WHITE[2014]) == (3, 1)
    assert (RED[2009], WHITE[2009]) == (2, 4)
    assert (RED[2003], WHITE[2003]) == (4, 5)

    white = SellerLine("L14", "a 2014 white", "w-white", 2014, 750, 12, 12)
    offers = [offer("m1", "800.00", vintage=2019, wine_id="w-white", pack_size=12),
              offer("m1", "780.00", vintage=2022, wine_id="w-white", pack_size=12)]
    # On the white register 2014 is tier 1: 2022 (tier 1) is in, and 2019
    # (tier 2) comes in by the one permitted step.
    as_white = check_vintage_band(white, [], neighbour_offers=offers, as_of=AS_OF, tiers=WHITE)
    assert [(n.vintage, n.tier) for n in as_white.neighbours] == [(2019, 2), (2022, 1)]
    # On the red register 2014 is tier 3, and neither neighbour is within a step.
    as_red = check_vintage_band(white, [], neighbour_offers=offers, as_of=AS_OF, tiers=RED)
    assert as_red.neighbours == [] and as_red.band_high is None


def test_band_runs_over_every_comparable_not_merchant_bests():
    """Bordeaux Index lists the 2020 six-pack twice: £2,070 and £2,074. Run the
    check over merchant-bests alone and only £2,070 is excluded — £2,074 is
    promoted in its place and the Reference goes from £2,070 to £2,074. The 72%
    error survives the check intact. So the check runs over every comparable."""
    twin = offer("bordeaux-index", "2074.00", merchant="Bordeaux Index")
    comps = [LS_2020, BI_2020, twin]
    result = benchmark(line(), comps, as_of=AS_OF)
    assert result.uk_reference == Decimal("2070.00")
    assert [o.price for o in result.merchant_bests] == [Decimal("1200.00"), Decimal("2070.00")]

    bests_only = check_vintage_band(line(), result.merchant_bests,
                                    neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF, tiers=RED)
    assert [o.price for o in bests_only.high_outliers] == [Decimal("2070.00")]
    survived = benchmark(line(), without_high_outliers(comps, bests_only), as_of=AS_OF)
    assert survived.uk_reference == Decimal("2074.00")      # the check achieved nothing

    every = check_vintage_band(line(), result.comparables,
                               neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF, tiers=RED)
    assert sorted(o.price for o in every.high_outliers) == [Decimal("2070.00"),
                                                            Decimal("2074.00")]
    after = benchmark(line(), without_high_outliers(comps, every), as_of=AS_OF)
    assert after.uk_reference == Decimal("1200.00")
    assert after.state is State.REVIEW and Flag.ONE_COMP in after.flags


def test_stale_neighbours_are_labelled():
    """Comps are fresh to 14 days; a band may lean on 90. If everything behind
    it is older than the comp window, the operator is told."""
    old = [offer("bordeaux-index", "1489.00", vintage=2017, days_old=60),
           offer("bordeaux-index", "1223.00", vintage=2018, days_old=45)]
    check = check_vintage_band(line(), [BI_2020], neighbour_offers=old, as_of=AS_OF, tiers=RED)
    assert check.ran and all(n.stale for n in check.neighbours)
    assert "older than 14 days" in check.note
    assert check.high_outliers                              # the flag is still raised

    too_old = [offer("bordeaux-index", "1489.00", vintage=2017, days_old=120),
               offer("bordeaux-index", "1223.00", vintage=2018, days_old=100)]
    assert check_vintage_band(line(), [BI_2020], neighbour_offers=too_old,
                              as_of=AS_OF, tiers=RED).band_high is None


@pytest.mark.parametrize("price,flagged", [
    ("2070.00", True),        # the live BI six-pack
    ("2011.00", True),        # just over 1.35 x £1,489
    ("2010.00", False),       # just under: the check stays quiet
    ("1200.00", False),       # the live L&S six-pack
])
def test_the_high_multiple_is_where_the_spec_says(price, flagged):
    check = check_vintage_band(line(), [offer("m", price)], neighbour_offers=BI_NEIGHBOURS,
                               as_of=AS_OF, tiers=RED)
    assert bool(check.high_outliers) is flagged


def test_the_check_only_ever_looks_at_the_same_wine():
    """A neighbouring vintage of a different wine is not a neighbour at all."""
    other_wine = [offer("bordeaux-index", "1489.00", vintage=2017, wine_id="w-something-else"),
                  offer("bordeaux-index", "1223.00", vintage=2018, wine_id="w-something-else")]
    check = check_vintage_band(line(), [BI_2020], neighbour_offers=other_wine, as_of=AS_OF,
                               tiers=RED)
    assert check.neighbours == [] and check.band_high is None
    assert check.high_outliers == []
