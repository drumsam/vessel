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


def test_a_line_with_no_rule_at_all_but_a_reference_now_prices_from_the_chain():
    """Before decision 0017 this raised CannotPrice. A private cellar's lines
    mostly arrive with nothing but a verified UK Reference, and the market
    chain is exactly the fallback built for that gap — see the chain tests
    below. The stray `cost=600.00` from `priced()`'s defaults is not consulted:
    test_a_cost_entered_for_other_reasons_is_not_used_by_the_chain."""
    p = priced()
    assert p.price_basis == "buyer_discount"
    assert p.sell_price == D("800.00")


def test_truly_nothing_at_all_is_still_not_priced():
    """No manual price, no margin, no discount, and no UK Reference either:
    the one case the chain cannot fill."""
    with pytest.raises(CannotPrice):
        priced(cost=None, cost_currency=None, uk_reference=None)


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


# --------------------------------------------- the market chain (decision 0017)
#
# A private cellar's lines mostly arrive with nothing but a verified UK
# Reference: no manual price, no line margin, no line discount, often no deal
# margin either. Before 0017 such a line raised CannotPrice outright.


def test_the_chain_is_the_fallback_when_nothing_else_is_set():
    """£1,000 Reference, nothing else: buyer pays £800 (20% below market),
    the seller receives £736 (our 8% fee on the buyer price) — not £950,
    which is what a single flat 20% discount straight off Reference would
    have paid the seller. Before this basis existed, this line could not be
    priced at all."""
    p = price_line(uk_reference=REF, cost=None, cost_currency=None)
    assert p.price_basis == "buyer_discount"
    assert p.buyer_price_gbp == D("800.00") == p.sell_price
    assert p.seller_price_gbp == D("736.00") == p.cost_gbp
    assert p.seller_price_gbp != D("950.00")            # not a single flat discount
    assert p.gp == D("64.00")                            # our fee: 800 - 736
    assert p.gross_margin == D("0.0800")                  # exactly MARGIN_ON_SALE
    assert p.buyer_discount == D("0.20") and p.margin_on_sale == D("0.08")


def test_five_hundred_thousand_pounds_of_buyer_price_is_forty_thousand_margin():
    """Doug's worked example: on £500,000 of buyer-side sales the sellers
    receive £460,000 and our margin is £40,000 — 8% of the buyer price, not
    8% of the market reference."""
    buyer_total = D("0")
    seller_total = D("0")
    # Evenly split across enough lines that whole-penny rounding washes out.
    for _ in range(500):
        p = price_line(uk_reference=D("1250.00"), cost=None, cost_currency=None)
        buyer_total += p.buyer_price_gbp
        seller_total += p.seller_price_gbp
    assert buyer_total == D("500000.00")
    assert seller_total == D("460000.00")
    assert buyer_total - seller_total == D("40000.00")


def test_manual_price_and_margin_still_outrank_the_chain():
    """The chain is the LAST resort, not a replacement for a known cost or an
    explicit override: manual price, line margin, line discount and the
    deal's own margin all still win outright when set."""
    assert price_line(uk_reference=REF, cost=D("600.00"), cost_currency="GBP",
                      manual_price=D("900.00")).price_basis == "manual"
    assert price_line(uk_reference=REF, cost=D("600.00"), cost_currency="GBP",
                      line_margin=D("0.25")).price_basis == "line_margin"
    assert price_line(uk_reference=REF, cost=None, cost_currency=None,
                      line_discount=D("0.10")).price_basis == "line_discount"
    assert price_line(uk_reference=REF, cost=D("600.00"), cost_currency="GBP",
                      deal_margin=D("0.25")).price_basis == "global_margin"
    # And with nothing at all but the reference, the chain is what is left.
    assert price_line(uk_reference=REF, cost=None, cost_currency=None
                      ).price_basis == "buyer_discount"


def test_without_a_reference_the_chain_cannot_fire_either():
    """No manual price, no margin, no discount, and no UK Reference: still
    CannotPrice. The chain fills a gap; it does not remove the floor."""
    with pytest.raises(CannotPrice):
        price_line(uk_reference=None, cost=None, cost_currency=None)


def test_the_deal_can_override_both_settings_and_the_override_is_recorded():
    """A deal that wants a steeper buyer discount or a different fee sets its
    own numbers; whichever were actually used are kept on the result, so a
    reprice is a diff against what was used, not a new guess."""
    p = price_line(uk_reference=REF, cost=None, cost_currency=None,
                   buyer_discount=D("0.30"), margin_on_sale=D("0.10"))
    assert p.buyer_price_gbp == D("700.00")               # 1000 x 0.70
    assert p.seller_price_gbp == D("630.00")              # 700 x 0.90
    assert p.buyer_discount == D("0.30") and p.margin_on_sale == D("0.10")


def test_the_chain_never_pays_the_seller_more_than_the_buyer_pays():
    """Our fee is taken on the buyer side, never invented from nowhere: GP is
    always positive and never NEGATIVE_GP, whatever the two settings are,
    because the seller price is derived FROM the buyer price, not supplied
    independently."""
    for bd, mos in [("0.05", "0.01"), ("0.20", "0.08"), ("0.50", "0.40")]:
        p = price_line(uk_reference=REF, cost=None, cost_currency=None,
                       buyer_discount=D(bd), margin_on_sale=D(mos))
        assert p.gp > 0 and Flag.NEGATIVE_GP not in p.flags
        assert p.seller_price_gbp < p.buyer_price_gbp < REF
        assert Flag.COST_ABOVE_UK_REFERENCE not in p.flags
        assert Flag.SELL_ABOVE_UK_REFERENCE not in p.flags


def test_a_buyer_discount_deeper_than_the_threshold_still_flags_deep_discount():
    """The chain's own settings can still trip the generic DEEP_DISCOUNT
    flag: a 30% buyer discount against the default 25% threshold is still
    worth an operator's eye, exactly as a manual price that deep would be."""
    shallow = price_line(uk_reference=REF, cost=None, cost_currency=None)
    deep = price_line(uk_reference=REF, cost=None, cost_currency=None,
                      buyer_discount=D("0.30"))
    assert Flag.DEEP_DISCOUNT not in shallow.flags       # 20% default: not deep
    assert Flag.DEEP_DISCOUNT in deep.flags              # 30%: deeper than 25%


def test_a_buyer_discount_or_fee_of_one_or_more_leaves_no_price():
    with pytest.raises(CannotPrice):
        price_line(uk_reference=REF, cost=None, cost_currency=None, buyer_discount=D("1.00"))
    with pytest.raises(CannotPrice):
        price_line(uk_reference=REF, cost=None, cost_currency=None, margin_on_sale=D("1.00"))


def test_a_cost_entered_for_other_reasons_is_not_used_by_the_chain():
    """A line can carry a `cost` figure for context (what the seller originally
    paid, say) without that figure driving THIS basis: the chain always derives
    the seller price from the market reference, never from a stray cost input
    that was not accompanied by a margin or discount instruction."""
    with_stray_cost = price_line(uk_reference=REF, cost=D("1.00"), cost_currency="GBP")
    assert with_stray_cost.price_basis == "buyer_discount"
    assert with_stray_cost.seller_price_gbp == D("736.00")   # from the chain, not £1.00
    assert with_stray_cost.cost_gbp == D("736.00")


def test_other_bases_never_carry_chain_fields():
    """buyer_price_gbp, seller_price_gbp, buyer_discount and margin_on_sale are
    specific to this one basis. A manually priced line must not look like it
    went through the chain."""
    p = priced(manual_price=D("900.00"))
    assert p.price_basis == "manual"
    assert (p.buyer_price_gbp, p.seller_price_gbp) == (None, None)
    assert (p.buyer_discount, p.margin_on_sale) == (None, None)
