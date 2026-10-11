"""Cross-case-size comparables, with a measured-or-assumed case premium.

Spec: docs/research/burgundy-unit-policy.md, built as decision 0016; extended
to every region by decision 0018 ("don't worry about case pricing, use
whatever we can find" — Doug, 5 October 2026). House style as in
test_traps.py: name the merchant, the wine, and the size of the error the
test prevents.

The premium is measured for Burgundy and assumed elsewhere, and these tests
exist as much to hold that distinction visible as to check the arithmetic: a
derived figure must never be able to reach a client document without a person
having seen it, and without being told honestly whether the number behind it
is evidence or a carried-over guess.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.benchmark import benchmark, derive_price
from app.core.enums import DutyStatus, PriceKind, Reject, State, StockType
from app.core.flags import CASE_PREMIUM, REVIEW_FLAGS, Flag
from app.core.models import Offer, SellerLine
from app.market.units import (
    MEASURED_REGIONS, PREMIUM_CAVEAT, PREMIUM_EVIDENCE, case_pairs, derivation_allowed,
    derivation_note, is_measured_region)
from app.market.vintage_band import band_flags, check_vintage_band, without_high_outliers

REGISTER = Path(__file__).parents[1] / "docs/research/vintage-tiers.csv"


def tiers(region: str = "BURGUNDY_RED") -> dict[int, int]:
    with REGISTER.open(newline="", encoding="utf-8") as fh:
        return {int(r["vintage"]): int(r["tier"])
                for r in csv.DictReader(fh) if r["region"] == region}

AS_OF = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
MUGNERET = "w-mugneret-gibourg-vosne"
LAMBRAYS = "w-clos-des-lambrays"


def offer(merchant_id: str, price: str, *, pack_size: int, bottle_ml: int = 750,
          vintage: int = 2020, wine_id: str = MUGNERET, merchant: str | None = None,
          **kw) -> Offer:
    base = dict(
        offer_id=f"{merchant_id}:{vintage}:{pack_size}x{bottle_ml}:{price}",
        merchant_id=merchant_id, merchant=merchant or merchant_id, wine_id=wine_id,
        vintage=vintage, bottle_ml=bottle_ml, pack_size=pack_size, price=Decimal(price),
        currency="GBP", duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK,
        is_buyable=True, offered_units=6, stock_type=StockType.MERCHANT_STOCK,
        captured_at=AS_OF - timedelta(days=1))
    base.update(kw)
    return Offer(**base)


def line(pack_size: int = 6, bottle_ml: int = 750, *, derive: bool = True,
         wine_id: str = MUGNERET, vintage: int = 2020) -> SellerLine:
    """A Burgundy line: the caller has set derive_units from the wine's region."""
    return SellerLine(line_id="L21", raw_description="Mugneret-Gibourg Vosne-Romanée 2020",
                      wine_id=wine_id, vintage=vintage, bottle_ml=bottle_ml,
                      pack_size=pack_size, quantity=1, derive_units=derive)


def test_burgundy_loose_bottle_derives_to_case_at_the_measured_premium():
    """Bordeaux Index's loose 2020 Mugneret-Gibourg Vosne-Romanée bottle is £197,
    so six is £1,182.

    The premium started as an assumed 5%, which would have said £1,241.10 —
    £59.10 too much, and a figure too high raises the UK Reference, which is how
    we overpay. Measured at Bordeaux Index the premium is parity: median 1.0000
    across 27 same-day pairs, 10 of them identical to the penny. See
    docs/research/case-premium-measurement.md.
    """
    loose = offer("bordeaux-index", "197.00", pack_size=1, merchant="Bordeaux Index")
    price, basis, premium = derive_price(loose, 6)
    assert CASE_PREMIUM == Decimal("1.00")
    assert price == Decimal("1182.00") == Decimal("197.00") * 6 * CASE_PREMIUM
    assert price != Decimal("1241.10")                  # the assumed 5%, now measured away
    assert premium is True and "measured case premium" in basis

    result = benchmark(line(), [loose], as_of=AS_OF)
    assert result.uk_floor == Decimal("1182.00")
    [derived] = result.derived
    assert derived.source is loose and derived.offer.price == Decimal("1182.00")
    assert Flag.DERIVED_FROM_CASE in result.flags


def test_the_premium_is_measured_and_the_spread_is_why_it_still_flags():
    """Parity is the median, not the rule. A quarter of the 27 pairs sat more
    than 5% out and the tails ran to -30% (2014 Lignier-Michelot Clos de la
    Roche: £175 loose against £123.17 a bottle in six) and +15% (2006 Roumier
    Les Cras: £600 against £691.50). No constant can be right about one wine,
    which is why the flag is the safeguard and the constant never was."""
    assert PREMIUM_EVIDENCE["pairs"] == 27
    assert PREMIUM_EVIDENCE["median"] == Decimal("1.0000") == CASE_PREMIUM
    assert (PREMIUM_EVIDENCE["low"], PREMIUM_EVIDENCE["high"]) == (Decimal("0.7038"),
                                                                   Decimal("1.1525"))
    assert "not a fact about this wine" in PREMIUM_CAVEAT
    assert str(PREMIUM_EVIDENCE["median"]) in PREMIUM_CAVEAT

    # A wine at either tail is derived at the median and flagged, not corrected.
    at_the_tail = offer("bordeaux-index", "175.00", pack_size=1, merchant="Bordeaux Index")
    result = benchmark(line(), [at_the_tail], as_of=AS_OF)
    assert result.uk_floor == Decimal("1050.00")        # 175 x 6, not 123.17 x 6
    assert result.state is State.REVIEW
    assert Flag.DERIVED_FROM_CASE in result.flags and Flag.DERIVED_FROM_CASE in REVIEW_FLAGS


def test_case_to_case_carries_no_premium():
    """Bordeaux Index's 3x75 Henri Germain Morgeot 2021 at £225 is £450 at 6x75,
    not £472.50. Both sides are cases: the premium is the difference between
    loose and cased, and applying it between two cases invents £22.50."""
    three = offer("bordeaux-index", "225.00", pack_size=3, merchant="Bordeaux Index")
    price, basis, premium = derive_price(three, 6)
    assert price == Decimal("450.00") == Decimal("225.00") * 2
    assert price != Decimal("472.50")
    assert premium is False and "no premium, case to case" in basis

    result = benchmark(line(), [three], as_of=AS_OF)
    assert result.uk_floor == Decimal("450.00")
    assert result.derived[0].premium_applied is False


def test_magnum_never_derives_to_750():
    """Bordeaux Index's 2015 Clos des Lambrays 3x150 at £1,310 is £436.67 a
    magnum. Read as bottles it says £218 each and £1,310 for a six-pack — a
    number no one has offered. A large format carries a scarcity premium that
    has nothing to do with the wine in the bottle, so it never converts."""
    magnums = offer("bordeaux-index", "1310.00", pack_size=3, bottle_ml=1500,
                    wine_id=LAMBRAYS, vintage=2015, merchant="Bordeaux Index")
    assert derive_price(magnums, 6) is None

    target = line(6, 750, wine_id=LAMBRAYS, vintage=2015)
    result = benchmark(target, [magnums], as_of=AS_OF)
    assert result.state is State.NO_MARKET and result.derived == []
    assert [r.reason for r in result.rejections] == [Reject.SIZE]
    assert result.cross_unit == []          # not even cross-unit: a different wine's price


def test_750_never_derives_to_magnum():
    """The mirror. A 6x75 at £1,200 tells a 6x150 line nothing, and inventing
    £2,400 from it would price a magnum case off bottle evidence."""
    bottles = offer("bordeaux-index", "1200.00", pack_size=6, wine_id=LAMBRAYS,
                    vintage=2015, merchant="Bordeaux Index")
    magnum_line = line(6, 1500, wine_id=LAMBRAYS, vintage=2015)
    result = benchmark(magnum_line, [bottles], as_of=AS_OF)
    assert result.state is State.NO_MARKET and result.derived == []
    assert [r.reason for r in result.rejections] == [Reject.SIZE]
    # And the derivation helper refuses it whichever way it is asked.
    assert derive_price(bottles, 6) is None          # same pack size, nothing to derive
    assert derive_price(offer("m", "400.00", pack_size=3, bottle_ml=1500), 6) is None


def test_derived_comp_forces_review():
    """The 5% is an assumption. A line whose Reference rests on one is never
    READY, however many merchants it has — that is the whole safeguard."""
    three = offer("bordeaux-index", "225.00", pack_size=3, merchant="Bordeaux Index")
    loose = offer("farr", "80.00", pack_size=1, merchant="Farr Vintners")
    result = benchmark(line(), [three, loose], as_of=AS_OF)

    assert result.comp_count == 2 and result.uk_reference == Decimal("480.00")
    assert Flag.DERIVED_FROM_CASE in result.flags
    assert Flag.DERIVED_FROM_CASE in REVIEW_FLAGS
    assert result.state is State.REVIEW


def test_exact_unit_outranks_derived():
    """With two merchants holding the seller's own 6x75, the other case sizes
    stay what they always were: evidence, shown and not priced from. A £180
    3x75 would derive to £360 and become the Floor, displacing a real £600 ask
    on an assumption."""
    exact = [offer("lea-sandeman", "600.00", pack_size=6, merchant="Lea & Sandeman"),
             offer("farr", "650.00", pack_size=6, merchant="Farr Vintners")]
    cheap_three = offer("bordeaux-index", "180.00", pack_size=3, merchant="Bordeaux Index")

    result = benchmark(line(), exact + [cheap_three], as_of=AS_OF)
    assert result.derived == [] and Flag.DERIVED_FROM_CASE not in result.flags
    assert result.uk_floor == Decimal("600.00") and result.uk_reference == Decimal("650.00")
    assert result.uk_median == Decimal("625.00")
    assert result.state is State.READY
    # Still visible, still explained, still not priced from.
    assert [e.offer.merchant for e in result.cross_unit] == ["Bordeaux Index"]

    # Drop to one exact-unit merchant and the derived comp fills in.
    thin = benchmark(line(), exact[:1] + [cheap_three], as_of=AS_OF)
    assert thin.uk_floor == Decimal("360.00") and thin.comp_count == 2
    assert Flag.DERIVED_FROM_CASE in thin.flags


def test_a_merchant_holding_the_exact_unit_is_never_derived_over():
    """Bordeaux Index at £620 for the seller's 6x75 and £180 for a 3x75: the
    derived £360 must not replace BI's own real price. The merchant said what it
    wants for the unit we are pricing."""
    result = benchmark(line(), [offer("bordeaux-index", "620.00", pack_size=6,
                                      merchant="Bordeaux Index"),
                                offer("bordeaux-index", "180.00", pack_size=3,
                                      merchant="Bordeaux Index")], as_of=AS_OF)
    assert result.comp_count == 1 and result.uk_floor == Decimal("620.00")
    assert result.derived == [] and Flag.DERIVED_FROM_CASE not in result.flags


def test_derivation_without_the_switch_set_is_still_refused():
    """The core does not know what a region is: the caller sets
    `derive_units`, and app/market/units.py decides the switch. A line this
    helper built with `derive=False` must still refuse the same shapes UNIT
    always refused, whatever region it is."""
    three = offer("bordeaux-index", "225.00", pack_size=3, merchant="Bordeaux Index")
    off = benchmark(line(derive=False), [three], as_of=AS_OF)
    assert off.state is State.NO_MARKET and off.derived == []
    assert [r.reason for r in off.rejections] == [Reject.UNIT]
    assert [e.per_bottle for e in off.cross_unit] == [Decimal("75")]


def test_derivation_is_now_general_decision_0018():
    """"Don't worry about case pricing, use whatever we can find" (Doug,
    5 October 2026). A third of a loose-bottle cellar was coming back
    NO_MARKET on unit grounds alone for every region but Burgundy — Champagne
    and Bordeaux among them. Any region with both a region AND a colour
    recorded now derives; only a wine with neither is refused, because there
    is nothing to widen from."""
    assert derivation_allowed("BURGUNDY_RED") and derivation_allowed("BURGUNDY_WHITE")
    for elsewhere in ("BORDEAUX_RED", "CHAMPAGNE_WHITE", "RHONE_NORTH_RED",
                      "CHAMPAGNE_NV"):
        assert derivation_allowed(elsewhere)
    for unidentified in (None, ""):
        assert not derivation_allowed(unidentified)


def test_only_burgundy_is_measured_everywhere_else_is_assumed():
    """The premium is the SAME number everywhere derivation runs — it is the
    LABEL that changes. Burgundy's 27 pairs earn it "measured"; every other
    region is told plainly that the same constant is a carried-over
    assumption until its own pairs say otherwise."""
    assert MEASURED_REGIONS == {"BURGUNDY_RED", "BURGUNDY_WHITE"}
    assert is_measured_region("BURGUNDY_RED") and is_measured_region("BURGUNDY_WHITE")
    assert not is_measured_region("BORDEAUX_RED")
    assert not is_measured_region("CHAMPAGNE_WHITE")
    assert not is_measured_region(None)

    bottles = offer("bordeaux-index", "200.00", pack_size=1, wine_id=LAMBRAYS,
                    merchant="Bordeaux Index")
    derived_comp = benchmark(line(wine_id=LAMBRAYS), [bottles], as_of=AS_OF).derived[0]

    measured = derivation_note(derived_comp, "BURGUNDY_RED")
    assert "measured median 1.0000 across 27 paired observations" in measured
    assert measured == derivation_note(derived_comp)       # the default: measured

    assumed = derivation_note(derived_comp, "BORDEAUX_RED")
    assert "assumed at the measured Burgundy rate" in assumed
    assert "no bordeaux red observations yet" in assumed.lower()
    assert "measured median" not in assumed                # never claims evidence it lacks


def test_a_bordeaux_case_derives_at_the_same_arithmetic_as_burgundy():
    """The region decides only whether derivation is ALLOWED and how the
    caveat reads; the arithmetic in app/core/benchmark.py has never known or
    cared what region a wine is. A Bordeaux 6x75 case behaves exactly as a
    Burgundy one would, case to case, no premium."""
    bordeaux_wine = "w-chateau-example"
    case = offer("bordeaux-index", "900.00", pack_size=3, wine_id=bordeaux_wine,
                 merchant="Bordeaux Index")
    result = benchmark(line(wine_id=bordeaux_wine), [case], as_of=AS_OF)
    assert result.uk_floor == Decimal("1800.00")           # 900 / 3 x 6, no premium
    assert Flag.DERIVED_FROM_CASE in result.flags and Flag.DERIVED_FROM_CASE in REVIEW_FLAGS
    assert result.derived[0].premium_applied is False


def test_derived_money_is_decimal_and_rounded_once():
    """A 7x75 at £1,000 is £142.857142... a bottle. The derived figure is
    quantised to whole pence exactly once, half-even, at the point of
    derivation — and never touches a float on the way."""
    odd = offer("bordeaux-index", "1000.00", pack_size=7, merchant="Bordeaux Index")
    price, _, _ = derive_price(odd, 6)
    assert isinstance(price, Decimal)
    assert price == Decimal("857.14")                    # 857.142857... half-even
    assert price == price.quantize(Decimal("0.01"))

    # Half-even, not half-up: £0.15 for 4 is £0.0375 a bottle, £0.225 for six,
    # which lands on the even penny. Half-up would say £0.23. A run of ties
    # rounded the other way drifts upward, which is a drift into overpricing.
    assert derive_price(offer("m", "0.15", pack_size=4), 6)[0] == Decimal("0.22")

    result = benchmark(line(), [odd], as_of=AS_OF)
    assert result.uk_floor == Decimal("857.14")
    assert all(isinstance(o.price, Decimal) for o in result.merchant_bests)


def test_operator_sees_source_unit_and_price():
    """The real offer is never replaced by its derived figure. The operator
    reads what Bordeaux Index actually asks, for what unit, and is told in words
    that the 5% is an assumption."""
    three = offer("bordeaux-index", "225.00", pack_size=3, merchant="Bordeaux Index")
    loose = offer("farr", "80.00", pack_size=1, merchant="Farr Vintners")
    result = benchmark(line(), [three, loose], as_of=AS_OF)

    by_merchant = {d.source.merchant: d for d in result.derived}
    bi = by_merchant["Bordeaux Index"]
    assert (bi.source.price, bi.source.pack_size) == (Decimal("225.00"), 3)
    assert bi.source.raw == three.raw and bi.source is three     # untouched
    assert "Derived from a 3x75cl at 225.00 from Bordeaux Index" in derivation_note(bi)
    assert "No premium applied: case to case." in derivation_note(bi)

    farr = by_merchant["Farr Vintners"]
    assert "Derived from a 1x75cl at 80.00 from Farr Vintners" in derivation_note(farr)
    assert "measured median 1.0000 across 27 paired observations" in derivation_note(farr)
    # Both figures are on the run, each beside the offer it came from.
    assert [d.offer.price for d in result.derived] == [Decimal("450.00"), Decimal("480.00")]


def test_half_bottles_are_not_usable():
    """375ml is the magnum rule in the other direction: a half bottle is not
    half a bottle's worth of evidence. Bordeaux Index's 12x37.5 at £700 tells a
    6x75 line nothing."""
    halves = offer("bordeaux-index", "700.00", pack_size=12, bottle_ml=375,
                   merchant="Bordeaux Index")
    assert derive_price(halves, 6) is None
    result = benchmark(line(), [halves], as_of=AS_OF)
    assert result.state is State.NO_MARKET and result.derived == []
    assert [r.reason for r in result.rejections] == [Reject.SIZE]


# --- measuring the premium instead of assuming it -----------------------------
#
# docs/research/case-premium-measurement.md: "Every adapter that meets a wine in
# two units on the same day should record the pair."


def test_a_wine_met_in_two_pack_sizes_is_one_paired_observation():
    """2013 Mugneret-Gibourg Vosne-Romanée at Bordeaux Index: £225 loose and
    £225 a bottle in 2s, 6s and 12s alike — one of the ten pairs that came back
    identical to the penny, which is what a merchant pricing per bottle and
    multiplying looks like."""
    found = case_pairs([
        offer("bordeaux-index", "225.00", pack_size=1),
        offer("bordeaux-index", "450.00", pack_size=2),
        offer("bordeaux-index", "1350.00", pack_size=6),
        offer("bordeaux-index", "2700.00", pack_size=12),
    ])
    assert [(p.smaller_pack, p.larger_pack, p.ratio) for p in found] == [
        (1, 2, Decimal("1.000000")), (1, 6, Decimal("1.000000")),
        (1, 12, Decimal("1.000000"))]
    assert all(p.is_loose_pair for p in found)

    # The tails are recorded exactly as they are, never corrected toward the
    # median: 2014 Lignier-Michelot Clos de la Roche, £175 loose against
    # £123.17 a bottle in six.
    [tail] = case_pairs([offer("bordeaux-index", "175.00", pack_size=1),
                         offer("bordeaux-index", "739.02", pack_size=6)])
    assert tail.larger_price / tail.larger_pack == Decimal("123.17")
    assert round(tail.ratio, 4) == Decimal("0.7038")      # as recorded


def test_each_pack_size_is_paired_against_the_smallest_present():
    """One baseline, no double counting. Three pack sizes are two observations,
    not three, and where a loose bottle exists it is the baseline — that is the
    ratio CASE_PREMIUM is about."""
    found = case_pairs([offer("bi", "600.00", pack_size=3),
                        offer("bi", "1150.00", pack_size=6),
                        offer("bi", "2200.00", pack_size=12)])
    assert [(p.smaller_pack, p.larger_pack) for p in found] == [(3, 6), (3, 12)]
    assert not any(p.is_loose_pair for p in found)   # case-to-case measures something else


def test_a_merchant_listing_one_wine_twice_is_still_one_observation():
    """Bordeaux Index lists the same case twice. The best price wins for each
    pack size, as in the measurement method, or a merchant with a long listing
    tail would quietly outvote every other merchant."""
    [pair] = case_pairs([
        offer("bordeaux-index", "200.00", pack_size=1),
        offer("bordeaux-index", "197.00", pack_size=1),       # the better loose price
        offer("bordeaux-index", "1250.00", pack_size=6),
        offer("bordeaux-index", "1182.00", pack_size=6),      # the better case price
    ])
    assert (pair.smaller_price, pair.larger_price) == (Decimal("197.00"), Decimal("1182.00"))
    assert pair.ratio == Decimal("1.000000")


def test_a_pair_needs_both_sides_to_be_the_same_thing():
    """Duty Paid against In Bond measures the duty, not the case. A magnum
    against a bottle measures the format. An indication is not a price at all,
    and an unbuyable listing is not an offer."""
    loose = offer("bi", "197.00", pack_size=1)
    assert case_pairs([loose, offer("bi", "1400.00", pack_size=6,
                                    duty_status=DutyStatus.DUTY_PAID)]) == []
    assert case_pairs([loose, offer("bi", "1182.00", pack_size=6, bottle_ml=1500)]) == []
    assert case_pairs([loose, offer("bi", "1182.00", pack_size=6,
                                    price_kind=PriceKind.INDICATION)]) == []
    assert case_pairs([loose, offer("bi", "1182.00", pack_size=6, is_buyable=False)]) == []
    assert case_pairs([loose, offer("bi", "1182.00", pack_size=6, is_mixed_lot=True)]) == []
    assert case_pairs([loose, offer("bi", "1182.00", pack_size=6, wine_id="w-other")]) == []
    assert case_pairs([loose, offer("bi", "1182.00", pack_size=6, vintage=2019)]) == []
    # And the pair that IS the same thing, to prove the helper is not just quiet.
    assert len(case_pairs([loose, offer("bi", "1182.00", pack_size=6)])) == 1


def test_the_measurement_never_touches_a_price():
    """A pair is an observation about pricing policy, not evidence about this
    wine. It must not add a comp, change depth, or move any figure."""
    offers = [offer("bordeaux-index", "197.00", pack_size=1, merchant="Bordeaux Index"),
              offer("bordeaux-index", "1182.00", pack_size=6, merchant="Bordeaux Index")]
    assert len(case_pairs(offers)) == 1

    result = benchmark(line(), offers, as_of=AS_OF)
    assert result.comp_count == 1 and result.uk_floor == Decimal("1182.00")
    # The exact-unit 6-pack is the comp; the loose bottle is not derived over it.
    assert result.derived == [] and Flag.DERIVED_FROM_CASE not in result.flags


# ===================================== decisions 0023/0028: source agreement, not the constant
#
# "Your flags.py comment argues against trusting the constant, and I agree -
# the rule trusts source agreement, not the constant" - Doug, 7 October 2026.
# 0023's first attempt expressed that agreement only through a vintage band,
# which exists for Burgundy alone — so outside Burgundy the exemption could
# never fire regardless of how well the comps actually agreed. 0028 (9-10
# October 2026, against the live Champagne sweep) corrects it: DERIVED_FROM_
# CASE stops GATING once 2+ merchants' comps agree WITH EACH OTHER, within
# AGREEMENT_THRESHOLD of the lowest, region-independent. Where a band also
# exists for the region, it must agree too — strictly more information, not
# given up for Burgundy. One comp never qualifies, confirmed or not.

RED = tiers()

#: Bordeaux Index's own price curve for this wine and unit (same fixture as
#: test_vintage_band.py's BI_NEIGHBOURS): a working band, 2016-2018.
NEIGHBOURS_2020 = [
    offer("bordeaux-index", "1489.00", pack_size=6, vintage=2016, merchant="Bordeaux Index"),
    offer("bordeaux-index", "1543.00", pack_size=6, vintage=2016, merchant="Bordeaux Index"),
    offer("bordeaux-index", "1489.00", pack_size=6, vintage=2017, merchant="Bordeaux Index"),
    offer("bordeaux-index", "1520.00", pack_size=6, vintage=2017, merchant="Bordeaux Index"),
    offer("bordeaux-index", "1223.00", pack_size=6, vintage=2018, merchant="Bordeaux Index"),
]
#: band_low=1223, band_high=1516 -> high edge 2046.60, low edge 794.95.


def _benchmark_then_band(ln: SellerLine, comps: list[Offer], neighbours: list[Offer]):
    """The real pipeline's own sequence (app.worker.jobs._benchmark_with_band,
    and scripts/rerun_burgundy_proof.py): benchmark, check the band, maybe
    re-benchmark without an excluded high outlier, then set derivation_
    confirmed from what the band (if any) found — the source-agreement test
    itself now lives in BenchmarkResult.state, not here. Exercised here
    exactly as the two real call sites exercise it, so a change to either
    drifts from this test too."""
    result = benchmark(ln, comps, as_of=AS_OF)
    check = check_vintage_band(ln, result.comparables, neighbour_offers=neighbours,
                              other_format_offers=(), as_of=AS_OF, tiers=RED)
    flags = band_flags(check)
    if flags or check.high_outliers:
        ln = replace(ln, inherited_flags=flags)
        kept = without_high_outliers(comps, check) if check.high_outliers else comps
        result = benchmark(ln, kept, as_of=AS_OF)
    result.line = replace(result.line, derivation_confirmed=(
        check.band_low is None or (not check.high_outliers and not check.low_outliers)))
    return result, check


def test_two_comps_that_agree_with_the_band_stop_gating():
    """One exact 6-pack ask, one derived from a loose bottle at the same
    rate, both comfortably inside the 2016-2018 band (£794.95-£2,046.60):
    DERIVED_FROM_CASE is still on the result, for display, but no longer
    forces review — comp_count 2, and the band agrees."""
    exact = offer("bordeaux-index", "1800.00", pack_size=6, vintage=2020, merchant="Bordeaux Index")
    loose = offer("lea-sandeman", "295.00", pack_size=1, vintage=2020, merchant="Lea & Sandeman")
    result, check = _benchmark_then_band(line(vintage=2020), [exact, loose], NEIGHBOURS_2020)

    assert result.comp_count == 2
    assert Flag.DERIVED_FROM_CASE in result.flags           # still shown
    assert check.band_low == Decimal("1223.00") and check.high_outliers == [] and check.low_outliers == []
    assert result.line.derivation_confirmed is True
    assert result.state is State.READY                      # the actual point of 0023


def test_one_derived_comp_never_qualifies_even_with_a_clean_band():
    """"It stays gating with one comp" - stated explicitly, tested literally:
    a single derived comp inside a perfectly clean band still goes to a
    person, because there is no second source for it to agree WITH.
    derivation_confirmed may still be True — it records only that the band
    agreed, a fact independent of comp count; comp_count >= 2 is state's
    own, separate condition, and it is THAT which must hold the line."""
    loose = offer("lea-sandeman", "295.00", pack_size=1, vintage=2020, merchant="Lea & Sandeman")
    result, check = _benchmark_then_band(line(vintage=2020), [loose], NEIGHBOURS_2020)

    assert result.comp_count == 1
    assert Flag.DERIVED_FROM_CASE in result.flags
    assert check.band_low is not None and check.high_outliers == [] and check.low_outliers == []
    assert result.state is State.REVIEW


def test_a_high_outlier_refuses_the_exemption_it_would_otherwise_earn():
    """2+ comps, but one is thrown out as too dear by the band: the comps did
    not agree, so confirmation is refused even though comp_count was 2
    going in. The line stays in review through COMP_EXCLUDED_VINTAGE_BAND
    on its own merits, same as it always has."""
    exact = offer("bordeaux-index", "1800.00", pack_size=6, vintage=2020, merchant="Bordeaux Index")
    dear_loose = offer("lea-sandeman", "500.00", pack_size=1, vintage=2020, merchant="Lea & Sandeman")
    result, check = _benchmark_then_band(line(vintage=2020), [exact, dear_loose], NEIGHBOURS_2020)

    assert check.high_outliers != []
    assert result.line.derivation_confirmed is False
    assert result.state is State.REVIEW


def test_no_band_now_rests_entirely_on_source_agreement_decision_0028():
    """The Champagne sweep's whole reason for existing: no tier for this
    region at all (invariant 18: no band, no flag) used to refuse the
    exemption outright, which meant a loose-bottle cellar priced from UK
    case sellers could never produce a READY line in ANY region without a
    vintage-tier register — Burgundy only. 0028 corrects it: no band means
    nothing EXTRA to check, not nothing to confirm agreement against — the
    two comps here are 1.7% apart (1800 against 1770 derived), well inside
    AGREEMENT_THRESHOLD, and that alone is enough."""
    exact = offer("bordeaux-index", "1800.00", pack_size=6, vintage=2020, merchant="Bordeaux Index")
    loose = offer("lea-sandeman", "295.00", pack_size=1, vintage=2020, merchant="Lea & Sandeman")
    result, check = _benchmark_then_band(line(vintage=2020), [exact, loose], [])  # no neighbours at all

    assert result.comp_count == 2
    assert check.band_low is None                            # band did not run
    assert result.line.derivation_confirmed is True           # vacuous pass, nothing to object
    assert result.state is State.READY


def test_no_band_and_disagreeing_comps_still_gates():
    """The mirror: with no band to ask, the line still needs its OWN comps to
    agree. Taittinger Comtes de Champagne 2006, live: £95.00 against
    £149.17 derived — 57% apart — stayed in review for exactly this reason,
    region-independent, band or no band."""
    cheap = offer("bordeaux-index", "570.00", pack_size=6, vintage=2020, merchant="Bordeaux Index")
    dear_loose = offer("lea-sandeman", "149.17", pack_size=1, vintage=2020, merchant="Lea & Sandeman")
    result, check = _benchmark_then_band(line(vintage=2020), [cheap, dear_loose], [])

    assert result.comp_count == 2
    assert check.band_low is None
    assert result.line.derivation_confirmed is True            # nothing to object to, band-wise
    assert result.state is State.REVIEW                        # but the comps themselves disagree


@pytest.mark.parametrize("floor,other,pct", [
    (Decimal("250.00"), Decimal("264.33"), "5.7"),    # Dom Perignon Rose 2006, live
    (Decimal("194.83"), Decimal("211.83"), "8.7"),    # Louis Roederer Cristal 2005, live
    (Decimal("116.67"), Decimal("131.33"), "12.6"),   # Taittinger Comtes Rose 2009, live
    (Decimal("88.33"), Decimal("104.67"), "18.5"),    # Charles Heidsieck Blanc de Mill. 2006, live
    (Decimal("158.33"), Decimal("190.00"), "20.0"),   # Louis Roederer Cristal 2007, live
    (Decimal("143.33"), Decimal("177.50"), "23.8"),   # Dom Perignon Vintage 2010, live
    (Decimal("138.83"), Decimal("176.50"), "27.1"),   # Dom Perignon Vintage 2004, live
    (Decimal("154.17"), Decimal("196.33"), "27.3"),   # Louis Roederer Cristal 2006, live
    (Decimal("142.33"), Decimal("200.00"), "40.5"),   # Taittinger Comtes 2008, live
    (Decimal("95.00"), Decimal("149.17"), "57.0"),    # Taittinger Comtes 2006, live
])
def test_the_live_champagne_sweep_spread_is_the_evidence_for_the_10pct_line(floor, other, pct):
    """Every 2+-merchant Champagne line found live, 9-10 October 2026 — the
    full ladder decision 0028 drew its line from. 10% holds the first two
    (5.7, 8.7) and refuses every other one, including both Taittinger
    Comtes de Champagne lines at 40.5% and 57.0%: two merchants that far
    apart are not agreement, however many of them there are."""
    assert round((other - floor) / floor * 100, 1) == Decimal(pct)
    exact = offer("bordeaux-index", str(floor * 6), pack_size=6, vintage=2020,
                  merchant="Bordeaux Index")
    loose = offer("lea-sandeman", str(other), pack_size=1, vintage=2020, merchant="Lea & Sandeman")
    result, check = _benchmark_then_band(line(vintage=2020), [exact, loose], [])
    should_be_ready = Decimal(pct) <= 10
    assert (result.state is State.READY) == should_be_ready
