"""Justerini & Brooks (decision pending — UK breadth, 10 October 2026). House
style as in test_traps.py: name the merchant, the wine, and the size of the
error the test prevents.

The fixture (tests/fixtures/justerini-brooks-2026-10-10.json) is real,
captured live from four family pages — Krug Grande Cuvée Edition, Dom
Pérignon Rosé, Louis Roederer Cristal, Taittinger Blanc de Blancs Comtes de
Champagne — each already reduced to the extracted listing dicts
`extract_listings()` would hand to `normalise()` (the RSC-chunk extraction
itself is a thin DOM shim, same convention as every other adapter's own
`extract_cards`/`extract_livetrade_items`, and is not unit-tested by name).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.adapters.base import Candidate, Rejected
from app.adapters.justerini_brooks import (
    JusteriniBrooksAdapter, parse_measure, parse_vintage_name)
from app.core.enums import DutyStatus, PriceKind, Reject, StockType

FIXTURE = json.loads((Path(__file__).parent / "fixtures/justerini-brooks-2026-10-10.json").read_text())
AS_OF = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def by_vintage(vintage_name: str, stock_type: str | None = None) -> dict:
    for item in FIXTURE:
        if item["vintageName"] == vintage_name and (stock_type is None or item["stockType"] == stock_type):
            return item
    raise AssertionError(f"no fixture item for {vintage_name!r}/{stock_type!r}")


def test_measure_parsing():
    assert parse_measure("6x75cl") == (6, 750)
    assert parse_measure("1x1.5L") == (1, 1500)
    assert parse_measure("3x1.5L") == (3, 1500)
    assert parse_measure("1x3L") == (1, 3000)
    assert parse_measure("1x6L") == (1, 6000)
    assert parse_measure("") is None
    assert parse_measure("garbled") is None


def test_vintage_name_parsing():
    """"167TH" is Krug's edition ordinal, read clean off its own field —
    nothing here is guessed from a title string the way split_release_code
    reads Bordeaux Index's."""
    assert parse_vintage_name("2015") == (2015, None)
    assert parse_vintage_name("167TH") == (1000, "167")
    assert parse_vintage_name("170TH") == (1000, "170")
    assert parse_vintage_name("NV") == (1000, None)
    assert parse_vintage_name("") == (1000, None)
    assert parse_vintage_name(None) == (1000, None)
    assert parse_vintage_name("garbled") is None


def test_krug_edition_167th_is_a_broking_indication_not_an_ask():
    """stockType "BR" ("Broking Wines") is read the same conservative way
    FINE+RARE's aggregated indication is (decision 0013): a specific price
    and quantity are shown, which reads more confirmed than FINE+RARE's own
    quantity-0 convention, but nothing on the page distinguishes a firm
    broked order from a sourceable quote — so it never prices."""
    item = by_vintage("167TH")
    [case, bottle] = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert case.offer.price_kind is PriceKind.INDICATION
    assert case.offer.stock_type is StockType.BROKERED
    assert case.producer_text == "Krug" and case.cuvee_text == "Grande Cuvée"
    assert case.release_code == "167"


def test_krug_editions_170th_and_173rd_are_real_portfolio_asks():
    item = by_vintage("170TH")
    [case, bottle] = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert case.offer.price_kind is PriceKind.ASK
    assert case.offer.stock_type is StockType.MERCHANT_STOCK
    assert case.release_code == "170"


def test_one_listing_yields_a_case_candidate_and_a_loose_bottle_candidate():
    """Confirmed live: a "6x75cl" case listing's stockBottles and stockCases
    are SEPARATE pools, not the same count read two ways — Taittinger Rosé
    Comtes de Champagne 2009 shows loose bottles AND cases of one listing at
    once. The loose-bottle candidate is the one commercial unit a
    loose-bottle cellar actually needs, and it is never just the headline
    case price divided by six — it is J&B's own separately quoted
    bottlePriceExcTaxes, at pack_size 1."""
    item = by_vintage("170TH")
    [case, bottle] = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert (case.offer.pack_size, case.offer.price) == (6, Decimal("1140"))
    assert (bottle.offer.pack_size, bottle.offer.price) == (1, Decimal("190"))
    assert case.offer.bottle_ml == bottle.offer.bottle_ml == 750
    # Each candidate's own stock pool, read separately, never swapped.
    assert case.offer.offered_units == item["stockCases"] == 0
    assert bottle.offer.offered_units == item["stockBottles"] == 3
    assert case.offer.is_buyable is False and bottle.offer.is_buyable is True


def test_a_single_unit_measure_yields_only_one_candidate():
    """1x1.5L is already pack_size 1 — there is no separate "loose" unit to
    split out from it, and emitting one anyway would double the depth one
    real position actually has."""
    [item] = [i for i in FIXTURE if i["measureName"] == "1x1.5L" and i["vintageName"] == "2012"]
    out = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert len(out) == 1
    assert out[0].offer.pack_size == 1 and out[0].offer.bottle_ml == 1500


def test_in_bond_is_the_exctaxes_price_never_the_inctaxes_one():
    """J&B publishes ONE listing with two tax views of the same stock — not
    two listings. bottlePriceIncTaxes/casePriceIncTaxes (duty paid, landed)
    must never surface as a second, separate offer."""
    item = by_vintage("170TH")
    assert item["casePriceIncTaxes"] != item["casePriceExcTaxes"]
    out = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    for c in out:
        assert c.offer.duty_status is DutyStatus.IN_BOND
        assert c.offer.price in (Decimal(str(item["casePriceExcTaxes"])),
                                 Decimal(str(item["bottlePriceExcTaxes"])))
        assert c.offer.price not in (Decimal(str(item["casePriceIncTaxes"])),
                                     Decimal(str(item["bottlePriceIncTaxes"])))


def test_familyname_is_not_reliably_producer_first():
    """Confirmed live across eleven producers: Dom Pérignon and Taittinger's
    familyName leads with the producer; Louis Roederer's and Pierre Peters'
    does not ("Cristal, Brut", not "Louis Roederer, Cristal, Brut"). Guessing
    which pattern applies per producer would invent an identity split nobody
    approved, so the producer is never read from the page — the caller
    already supplied it, and the strip only fires on an actual match."""
    dp = by_vintage("2004")
    assert dp["familyName"] == "Dom Pérignon, Rosé"
    [case, bottle] = JusteriniBrooksAdapter().normalise(dp, captured_at=AS_OF)
    assert case.cuvee_text == "Rosé"                     # producer stripped: it matched

    cristal = by_vintage("1999")
    assert cristal["familyName"] == "Cristal, Brut"       # no "Louis Roederer" at all
    [case, bottle] = JusteriniBrooksAdapter().normalise(cristal, captured_at=AS_OF)
    assert case.producer_text == "Louis Roederer"          # supplied by the caller, not guessed
    assert case.cuvee_text == "Cristal, Brut"              # kept whole: nothing matched to strip


def test_taittinger_blanc_de_blancs_producer_is_stripped_correctly():
    item = by_vintage("2011")
    assert item["familyName"] == "Taittinger, Blanc de Blancs, Comtes de Champagne"
    [one] = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert one.producer_text == "Taittinger"
    assert one.cuvee_text == "Blanc de Blancs, Comtes de Champagne"


def test_a_jeroboam_and_an_imperial_are_read_at_their_real_size_not_misread_as_750():
    """"1x3L" and "1x6L" are 3000ml and 6000ml - large formats this cellar
    does not hold at those sizes, so they correctly become NO_MARKET
    downstream rather than silently matching a 750ml or 1500ml line."""
    jero = by_vintage("2008")
    assert jero["measureName"] == "1x3L"
    [one] = JusteriniBrooksAdapter().normalise(jero, captured_at=AS_OF)
    assert one.offer.bottle_ml == 3000

    [imperial] = [i for i in FIXTURE if i["measureName"] == "1x6L"]
    [one2] = JusteriniBrooksAdapter().normalise(imperial, captured_at=AS_OF)
    assert one2.offer.bottle_ml == 6000


def test_a_record_with_no_producer_is_rejected():
    bare = {"familyName": "Krug, Grande Cuvée", "vintageName": "NV",
           "measureName": "6x75cl", "stockType": "RT",
           "casePriceExcTaxes": 900, "stockCases": 1, "uniqueId": "x"}
    out = JusteriniBrooksAdapter().normalise(bare, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.UNRESOLVED_IDENTITY


def test_an_unreadable_vintage_name_is_rejected_not_guessed_as_nv():
    item = dict(by_vintage("170TH"))
    item["vintageName"] = "???"
    out = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.VINTAGE


def test_an_unreadable_measure_is_rejected():
    item = dict(by_vintage("170TH"))
    item["measureName"] = "half a case"
    out = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.SIZE


def test_an_unknown_stock_type_is_rejected_not_assumed_an_ask():
    item = dict(by_vintage("170TH"))
    item["stockType"] = "XX"
    out = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.UNRESOLVED_IDENTITY


def test_zero_price_both_pools_is_rejected():
    item = dict(by_vintage("170TH"))
    item["casePriceExcTaxes"] = 0
    item["bottlePriceExcTaxes"] = 0
    out = JusteriniBrooksAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.NON_POSITIVE_PRICE
