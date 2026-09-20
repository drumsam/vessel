"""The pricing step: the rules, the precedence, the flags and the rounding.

House style as in test_traps.py: name the rule, and the size of the error the
test prevents. See docs/decisions/0007-pricing-rules-and-rounding.md.
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.core.flags import Flag
from app.pricing.pricer import CannotPrice, convert_cost, price_line, round_money

REF = D("1000.00")


def priced(**kw):
    base = dict(uk_reference=REF, cost=D("600.00"), cost_currency="GBP")
    return price_line(**{**base, **kw})


# ------------------------------------------------------------------ the rules


def test_sell_from_margin_is_margin_not_markup():
    """Cost £600 at a 25% target margin sells at £800, not £750. Markup would
    under-price by £50 a bottle and report a 25% margin that is really 20%."""
    p = priced(line_margin=D("0.25"))
    assert p.sell_price == D("800.00")
    assert p.gross_margin == D("0.2500")
    assert p.gp == D("200.00")


def test_sell_from_discount_prices_off_uk_reference():
    p = priced(line_discount=D("0.10"))
    assert p.sell_price == D("900.00")
    assert p.gp == D("300.00")
    assert p.gross_margin == D("0.3333")          # (900 - 600) / 900


def test_gross_margin_is_computed_on_sell_never_on_cost():
    p = priced(cost=D("750.00"), line_discount=D("0.00"))
    assert p.sell_price == REF
    assert p.gross_margin == D("0.2500")          # 250/1000, not 250/750


# ------------------------------------------------------------- the precedence


@pytest.mark.parametrize("kw,basis,sell", [
    (dict(manual_price=D("1234.00"), line_margin=D("0.25"), line_discount=D("0.10"),
          deal_margin=D("0.40")), "manual", D("1234.00")),
    (dict(line_margin=D("0.25"), line_discount=D("0.10"), deal_margin=D("0.40")),
     "line_margin", D("800.00")),
    (dict(line_discount=D("0.10"), deal_margin=D("0.40")), "line_discount", D("900.00")),
    (dict(deal_margin=D("0.40")), "global_margin", D("1000.00")),
])
def test_manual_beats_line_margin_beats_line_discount_beats_deal_margin(kw, basis, sell):
    p = priced(**kw)
    assert (p.price_basis, p.sell_price) == (basis, sell)


def test_a_line_with_no_rule_at_all_is_not_priced():
    with pytest.raises(CannotPrice):
        priced()


def test_a_margin_with_no_cost_is_not_priced():
    """Never invent a cost to satisfy a margin."""
    with pytest.raises(CannotPrice, match="cost"):
        priced(cost=None, cost_currency=None, line_margin=D("0.25"))


def test_a_discount_with_no_uk_reference_is_not_priced():
    with pytest.raises(CannotPrice, match="UK Reference"):
        priced(uk_reference=None, line_discount=D("0.10"))


# -------------------------------------------------------------------- the FX


def test_non_gbp_cost_without_a_rate_is_not_priced():
    """A GP on a USD parcel with no rate could never be reproduced."""
    with pytest.raises(CannotPrice, match="USD"):
        priced(cost=D("500.00"), cost_currency="USD", line_margin=D("0.20"))


def test_non_gbp_cost_converts_at_the_given_rate():
    p = priced(cost=D("500.00"), cost_currency="USD", fx_rate=D("0.7412"),
               line_margin=D("0.20"))
    assert p.cost_gbp == D("370.60")              # 500 x 0.7412
    assert p.sell_price == D("463.25")            # 370.60 / 0.8
    assert p.gross_margin == D("0.2000")


# -------------------------------------------------------------- the rounding


@pytest.mark.parametrize("cost,rate,gbp", [
    ("100.00", "0.741250", "74.12"),     # 74.125 -> down to the even penny
    ("100.00", "0.741350", "74.14"),     # 74.135 -> up to the even penny
    ("100.00", "0.745000", "74.50"),     # exact, untouched
])
def test_fx_conversion_rounds_to_pence_both_ways(cost, rate, gbp):
    assert convert_cost(D(cost), "USD", fx_rate=D(rate)) == D(gbp)


@pytest.mark.parametrize("cost,margin,sell", [
    ("100.005", "0.00", "100.00"),       # 100.005 -> down to the even penny
    ("100.015", "0.00", "100.02"),       # 100.015 -> up to the even penny
    ("66.67", "0.6667", "200.03"),       # 200.0300... -> nearest penny
])
def test_sell_price_rounds_to_pence_both_ways(cost, margin, sell):
    assert priced(cost=D(cost), line_margin=D(margin)).sell_price == D(sell)


def test_gp_is_a_difference_of_two_rounded_figures_and_is_not_rounded_again():
    p = priced(cost=D("500.00"), cost_currency="USD", fx_rate=D("0.741250"),
               line_discount=D("0.10"))
    assert p.cost_gbp == D("370.62")              # 370.625 -> down to the even penny
    assert p.sell_price == D("900.00")
    assert p.gp == D("529.38") == p.sell_price - p.cost_gbp


def test_round_money_is_the_only_rounding_helper_here():
    assert round_money(D("1.005")) == D("1.00")
    assert round_money(D("1.015")) == D("1.02")


# ----------------------------------------------------------------- the flags


def test_cost_above_uk_reference_is_flagged():
    p = priced(cost=D("1100.00"), line_margin=D("0.10"))
    assert Flag.COST_ABOVE_UK_REFERENCE in p.flags
    assert Flag.SELL_ABOVE_UK_REFERENCE in p.flags          # 1222.22 > 1000


def test_negative_gp_is_flagged():
    p = priced(cost=D("900.00"), manual_price=D("800.00"))
    assert p.gp == D("-100.00")
    assert Flag.NEGATIVE_GP in p.flags


@pytest.mark.parametrize("sell,deep", [
    ("760.00", False),      # 24% below Reference
    ("750.00", False),      # exactly 25% below: the threshold is not crossed
    ("749.99", True),       # more than 25% below
])
def test_deep_discount_is_more_than_a_quarter_below_reference(sell, deep):
    p = priced(manual_price=D(sell))
    assert (Flag.DEEP_DISCOUNT in p.flags) is deep


def test_the_deep_discount_threshold_is_configurable_and_recorded():
    """25% is a default, not a measured figure, so the value used is kept with
    the result: a price is explicable a year later."""
    p = priced(manual_price=D("800.00"), deep_discount_threshold=D("0.15"))
    assert Flag.DEEP_DISCOUNT in p.flags
    assert p.deep_discount_threshold == D("0.15")
    assert Flag.DEEP_DISCOUNT not in priced(manual_price=D("800.00")).flags


def test_a_priced_line_carries_no_review_flags_of_its_own():
    """Commercial flags are context. What forces review is REVIEW_FLAGS in
    app/core/flags.py, and none of these are in it."""
    from app.core.flags import REVIEW_FLAGS
    p = priced(cost=D("1100.00"), manual_price=D("700.00"))
    assert p.flags and not (p.flags & REVIEW_FLAGS)
