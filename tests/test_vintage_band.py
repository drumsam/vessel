"""The vintage-neighbour sanity check, on the live numbers that prompted it.

Spec: docs/research/vintage-neighbour-check-spec.md §7. House style as in
test_traps.py: name the merchant, the wine, and the size of the error the test
prevents.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.benchmark import benchmark
from app.core.enums import DutyStatus, PriceKind, State, StockType
from app.core.flags import Flag
from app.core.models import Offer, SellerLine
from app.market.vintage_band import (
    COMP_EXCLUDED_VINTAGE_BAND,
    LOW_COMP_OUT_OF_BAND,
    MERCHANT_FORMAT_INCOHERENT,
    check_vintage_band,
    without_high_outliers,
)

AS_OF = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
MUGNERET = "w-mugneret-gibourg-vosne"


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


def line(vintage: int = 2020, pack_size: int = 6, quantity: int = 6) -> SellerLine:
    return SellerLine(line_id="L21", raw_description="Mugneret-Gibourg Vosne-Romanée 2020",
                      wine_id=MUGNERET, vintage=vintage, bottle_ml=750,
                      pack_size=pack_size, quantity=quantity)


#: Bordeaux Index's own price curve for this wine and unit, captured live
#: 23 September 2026 (spec §"The evidence that the idea works"). The 2016 pair
#: is in the captured curve but outside the V±3 window for a 2020 line, so it is
#: here to prove it is ignored: the band comes from 2017 and 2018.
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
    neighbouring vintages sit in a £1,223-£1,543 band."""
    comps = [LS_2020, BI_2020]
    before = benchmark(line(), comps, as_of=AS_OF)
    assert before.uk_reference == Decimal("2070.00") and before.state is State.READY

    check = check_vintage_band(line(), before.merchant_bests,
                               neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF)
    # One merchant, so each vintage's merchant-best is its cheaper listing:
    # 2017 £1,489 and 2018 £1,223. 2016 is outside V±3 and contributes nothing.
    assert (check.band_low, check.band_high) == (Decimal("1223.00"), Decimal("1489.00"))
    assert [(n.vintage, n.median, n.merchants) for n in check.neighbours] == [
        (2017, Decimal("1489.00"), 1), (2018, Decimal("1223.00"), 1)]
    assert [o.merchant for o in check.high_outliers] == ["Bordeaux Index"]
    assert check.high_outliers[0].flag == COMP_EXCLUDED_VINTAGE_BAND
    assert check.low_outliers == []

    after = benchmark(line(), without_high_outliers(comps, check), as_of=AS_OF)
    assert after.uk_reference == Decimal("1200.00")          # falls from £2,070
    assert after.state is State.REVIEW and Flag.ONE_COMP in after.flags


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

    check = check_vintage_band(target, comps, neighbour_offers=neighbours, as_of=AS_OF)
    assert [o.merchant for o in check.low_outliers] == ["Goedhuis"]
    assert check.low_outliers[0].flag == LOW_COMP_OUT_OF_BAND
    assert check.high_outliers == []

    kept = without_high_outliers(comps, check)
    assert len(kept) == 2
    assert benchmark(target, kept, as_of=AS_OF).uk_reference == Decimal("445.00")


def test_band_needs_two_neighbour_vintages():
    """One neighbouring vintage is an anecdote. Silence, not a guess."""
    check = check_vintage_band(line(), [BI_2020, LS_2020],
                               neighbour_offers=[offer("bordeaux-index", "1223.00", vintage=2018)],
                               as_of=AS_OF)
    assert (check.band_low, check.band_high) == (None, None)
    assert check.high_outliers == [] and check.low_outliers == []
    assert "not enough neighbouring vintages" in check.note


def test_band_never_sets_a_price():
    """Three neighbouring vintages and no comps at all: still NO_MARKET. A band
    is not a price and is never interpolated into a missing vintage."""
    result = benchmark(line(), [], as_of=AS_OF)
    check = check_vintage_band(line(), result.merchant_bests,
                               neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF)
    assert result.state is State.NO_MARKET and result.uk_reference is None
    assert check.ran and check.band_low == Decimal("1223.00")
    assert check.high_outliers == [] and check.low_outliers == []


def test_no_cross_unit_arithmetic_in_band():
    """A 3x75 neighbour says nothing about a 6x75 band. No division, ever."""
    three_packs = [offer("bordeaux-index", "705.00", vintage=2017, pack_size=3),
                   offer("bordeaux-index", "612.00", vintage=2018, pack_size=3)]
    check = check_vintage_band(line(), [BI_2020], neighbour_offers=three_packs, as_of=AS_OF)
    assert check.neighbours == [] and check.band_high is None

    mixed = check_vintage_band(line(), [BI_2020], neighbour_offers=BI_NEIGHBOURS + three_packs,
                               as_of=AS_OF)
    assert [n.vintage for n in mixed.neighbours] == [2017, 2018]
    assert mixed.band_low == Decimal("1223.00")              # the 3x75s contribute nothing


def test_format_incoherence_is_evidence_not_a_comp():
    """Bordeaux Index prices a single 2020 bottle at £197 while pricing its own
    six-pack at £345 a bottle — a 43% disagreement with itself. Evidence for the
    operator; no offer is created and the arithmetic is untouched."""
    loose = offer("bordeaux-index", "197.00", pack_size=1, merchant="Bordeaux Index")
    check = check_vintage_band(line(), [BI_2020, LS_2020], neighbour_offers=BI_NEIGHBOURS,
                               other_format_offers=[loose], as_of=AS_OF)
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


def test_tier_widens_never_scales():
    """2020 is a greater vintage than its neighbours here, so the band's top
    moves up and the check goes quiet. The comp's price does not move."""
    tiers = {2017: 3, 2018: 3, 2020: 1}               # 1 = greatest
    without = check_vintage_band(line(), [BI_2020], neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF)
    with_tiers = check_vintage_band(line(), [BI_2020], neighbour_offers=BI_NEIGHBOURS,
                                    as_of=AS_OF, tiers=tiers)
    assert without.high_outliers and not with_tiers.high_outliers
    assert with_tiers.band_high > without.band_high
    assert with_tiers.tiers_available is True and without.tiers_available is False
    assert "no vintage tiers recorded" in (without.note or "")
    # The number under test never changed, only the band around it.
    assert BI_2020.price == Decimal("2070.00")
    assert all(o.price == Decimal("2070.00") for o in [BI_2020])


def test_stale_neighbours_are_labelled():
    """Comps are fresh to 14 days; a band may lean on 90. If everything behind
    it is older than the comp window, the operator is told."""
    old = [offer("bordeaux-index", "1489.00", vintage=2017, days_old=60),
           offer("bordeaux-index", "1223.00", vintage=2018, days_old=45)]
    check = check_vintage_band(line(), [BI_2020], neighbour_offers=old, as_of=AS_OF)
    assert check.ran and all(n.stale for n in check.neighbours)
    assert "older than 14 days" in check.note
    assert check.high_outliers                              # the flag is still raised

    too_old = [offer("bordeaux-index", "1489.00", vintage=2017, days_old=120),
               offer("bordeaux-index", "1223.00", vintage=2018, days_old=100)]
    assert check_vintage_band(line(), [BI_2020], neighbour_offers=too_old,
                              as_of=AS_OF).band_high is None


@pytest.mark.parametrize("price,flagged", [
    ("2070.00", True),        # the live BI six-pack
    ("2011.00", True),        # just over 1.35 x £1,489
    ("2010.00", False),       # just under: the check stays quiet
    ("1200.00", False),       # the live L&S six-pack
])
def test_the_high_multiple_is_where_the_spec_says(price, flagged):
    check = check_vintage_band(line(), [offer("m", price)], neighbour_offers=BI_NEIGHBOURS,
                               as_of=AS_OF)
    assert bool(check.high_outliers) is flagged


def test_the_check_only_ever_looks_at_the_same_wine():
    """A neighbouring vintage of a different wine is not a neighbour at all."""
    other_wine = [offer("bordeaux-index", "1489.00", vintage=2017, wine_id="w-something-else"),
                  offer("bordeaux-index", "1223.00", vintage=2018, wine_id="w-something-else")]
    check = check_vintage_band(line(), [BI_2020], neighbour_offers=other_wine, as_of=AS_OF)
    assert check.neighbours == [] and check.band_high is None
    assert check.high_outliers == []


def test_excluding_only_the_merchant_best_promotes_its_twin():
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
                                    neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF)
    assert [o.price for o in bests_only.high_outliers] == [Decimal("2070.00")]
    survived = benchmark(line(), without_high_outliers(comps, bests_only), as_of=AS_OF)
    assert survived.uk_reference == Decimal("2074.00")      # the check achieved nothing

    every = check_vintage_band(line(), result.comparables,
                               neighbour_offers=BI_NEIGHBOURS, as_of=AS_OF)
    assert sorted(o.price for o in every.high_outliers) == [Decimal("2070.00"),
                                                            Decimal("2074.00")]
    after = benchmark(line(), without_high_outliers(comps, every), as_of=AS_OF)
    assert after.uk_reference == Decimal("1200.00")
    assert after.state is State.REVIEW and Flag.ONE_COMP in after.flags
