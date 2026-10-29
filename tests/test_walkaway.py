"""The walk-away price (buy-side-margin-test.md). Pure, no database.
House style as in test_traps.py: name the rule and the size of the
error the test prevents. Verified against the spec's own worked
example (DRC Richebourg 2015, 3 x 75cl) to the penny.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.evaluate import walkaway


def test_walk_away_matches_the_specs_own_worked_example():
    """DRC Richebourg 2015: Floor £10,200, max sell £9,690, walk-away
    ~£8,972.22 -- the spec's own wireframe rounds to whole pounds for
    readability; the real figure carries pence, as every other money
    figure in this app does."""
    w = walkaway.compute(Decimal("10200.00"))
    assert w.max_sell == Decimal("9690.00")
    assert w.walk_away == Decimal("8972.22")


def test_margin_at_ask_matches_the_specs_own_worked_example():
    """Seller ask £8,400 against the same Floor: headroom £572.22,
    margin at this ask 15.4% -- margin is against max_sell (the best
    price the guards allow), not the bare walk-away threshold."""
    w = walkaway.compute(Decimal("10200.00"))
    ask = Decimal("8400.00")
    headroom = w.walk_away - ask
    assert headroom == Decimal("572.22")
    margin = walkaway.margin_at_ask(w.max_sell, ask)
    assert round(margin * 100, 1) == Decimal("15.4")


def test_an_ask_above_walk_away_matches_the_specs_second_worked_example():
    """Seller ask £9,600 against the same Floor: £627.78 above walk-away
    (the spec's wireframe rounds to £628), 8% on this ask needs a sell
    of exactly £10,368 -- above the £10,200 Floor, which decision 0033
    forbids."""
    w = walkaway.compute(Decimal("10200.00"))
    ask = Decimal("9600.00")
    assert ask > w.walk_away
    gap = ask - w.walk_away
    assert round(gap) == Decimal("628")
    required = walkaway.required_sell_for_margin(ask)
    assert required == Decimal("10368.00")
    assert required > w.uk_floor


def test_ask_per_unit_from_per_bottle_basis():
    # pack_size 6 (a case), ask stated per bottle -> price per unit (the
    # case) is pack_size times the per-bottle figure.
    assert walkaway.ask_per_unit(Decimal("420.00"), "per_bottle", pack_size=6,
                                 quantity=1) == Decimal("2520.00")


def test_ask_per_unit_from_total_basis():
    # Two cases of six (pack_size=6, quantity=2), ask stated as the lot
    # total -> price per unit is the total split across the two cases.
    assert walkaway.ask_per_unit(Decimal("5040.00"), "total", pack_size=6,
                                 quantity=2) == Decimal("2520.00")


def test_ask_per_unit_null_basis_is_only_safe_for_a_single_bottle():
    """A null basis is only ever reachable for pack_size=1, quantity=1 --
    confirm-identity blocks it otherwise -- where per_bottle, per_case
    and total are the same number, so returning the price unconverted
    makes no assumption at all."""
    assert walkaway.ask_per_unit(Decimal("420.00"), None, pack_size=1,
                                 quantity=1) == Decimal("420.00")


def test_ask_per_unit_refuses_an_unknown_basis():
    with pytest.raises(ValueError):
        walkaway.ask_per_unit(Decimal("420.00"), "per_bottle_and_a_half",
                              pack_size=1, quantity=1)
