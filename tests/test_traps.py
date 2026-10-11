"""Every trap found against live merchant data is a permanent regression test.

Each test names the merchant, the wine and the size of the error it prevents.
If one of these fails, a wrong price is about to reach a client.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import pytest

from app.adapters.base import Candidate, whole_pence
from app.adapters.bordeaux_index import BordeauxIndexAdapter, parse_offer_row, parse_title
from app.adapters.condition import normalise_condition
from app.adapters.farr import FarrAdapter, parse_size, split_wine_field
from app.adapters.fine_and_rare import (
    FineAndRareAdapter, parse_producer_index, parse_unit, product_urls)
from app.adapters.goedhuis import GoedhuisAdapter, is_eligible_variant, parse_sku
from app.adapters.lea_sandeman import (
    LeaSandemanAdapter, dedupe_rows, parse_pack, parse_rows)
from app.adapters.lw_trading import (
    PER_PAGE, LayWheelerTradingAdapter, attributes, cuvee_from_name, lwin_from_sku,
    parse_price)
from app.core.benchmark import benchmark as _benchmark
from app.core.enums import ConditionFlag, DutyStatus, PriceKind, Reject, State, StockType
from app.core.flags import MAX_OFFER_AGE_DAYS, REVIEW_FLAGS, WIDE_SPREAD_THRESHOLD, Flag
from app.core.models import Offer, SellerLine
from app.market.parcel import SAME_PRICE_AS_ANOTHER_MERCHANT, price_coincidences
from app.worker.politeness import allowed, crawl_delay
from app.identity.resolver import (
    PRODUCER_EXCLUSIONS, STRUCTURAL_EXCLUSIONS, Alias, CanonicalWine, Registry,
    collided_lwins, norm_producer, producers_excluded, split_release_code, wine_key)

WINE = "w-rousseau-chambertin"

#: Every offer below is captured at the moment it is benchmarked unless a test
#: says otherwise, so freshness only decides the tests that are about it.
AS_OF = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def benchmark(line, offers, as_of=AS_OF):
    return _benchmark(line, offers, as_of=as_of)


def offer(**kw) -> Offer:
    base = dict(
        offer_id="x", merchant_id="m1", merchant="M1", wine_id=WINE, vintage=2011,
        bottle_ml=750, pack_size=1, price=Decimal("600"), currency="GBP",
        duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK,
        is_buyable=True, offered_units=1, captured_at=AS_OF,
    )
    base.update(kw)
    return Offer(**base)


def line(**kw) -> SellerLine:
    base = dict(line_id="L1", raw_description="Rousseau Chambertin 11 1bt",
                wine_id=WINE, vintage=2011, bottle_ml=750, pack_size=1, quantity=1)
    base.update(kw)
    return SellerLine(**base)


# --------------------------------------------------------------- the ONE_COMP bug

def test_one_comp_forces_review_not_ready():
    """Regression: a single-merchant benchmark previously returned READY+ONE_COMP.
    One merchant is not a market."""
    r = benchmark(line(), [offer()])
    assert r.comp_count == 1
    assert Flag.ONE_COMP in r.flags
    assert r.state is State.REVIEW


def test_two_merchants_can_be_ready():
    r = benchmark(line(), [offer(merchant_id="m1", price=Decimal("600")),
                           offer(merchant_id="m2", price=Decimal("650"))])
    assert r.comp_count == 2
    assert r.uk_floor == Decimal("600")
    assert r.uk_reference == Decimal("650")
    assert r.state is State.READY


# ------------------------------------------------- Bordeaux Index: DP inside IB

def test_bi_duty_paid_row_nested_in_in_bond_block_is_rejected():
    """2009 Rousseau Gevrey-Chambertin: In Bond £590 and Duty Paid £420 sit in the
    same panel. Taking the DP row under-prices by 29%."""
    ib = "Case (1 x 75cl) LIVETRADE CONDITION Repack STATUS In-Bond ETA In Stock LIVETRADE You buy £590.00 1 BUY 1 Case(s) Remaining"
    dp = "Bottle (75cl) CONDITION Repack STATUS Duty Paid ETA In Stock Buy at £420.00 1 BUY 1 Bottle(s) Available"

    a, b = parse_offer_row(ib), parse_offer_row(dp)
    assert a["duty_status"] is DutyStatus.IN_BOND and a["price"] == Decimal("590")
    assert b["duty_status"] is DutyStatus.DUTY_PAID and b["price"] == Decimal("420")

    r = benchmark(line(vintage=2009),
                  [offer(vintage=2009, price=Decimal("590")),
                   offer(vintage=2009, price=Decimal("420"), duty_status=DutyStatus.DUTY_PAID,
                         merchant_id="m2")])
    assert r.uk_floor == Decimal("590")
    assert any(x.reason is Reject.DUTY for x in r.rejections)


def test_bi_bottle_and_case_of_one_are_the_same_commercial_unit():
    """BI prints both 'Case (1 x 75cl)' and 'Bottle (75cl)'. Both are one bottle."""
    a = parse_offer_row("Case (1 x 75cl) CONDITION Repack STATUS In-Bond You buy £980.00 1 BUY 1 Case(s) Remaining")
    b = parse_offer_row("Bottle (75cl) CONDITION Repack STATUS In-Bond Buy at £980.00 1 BUY 1 Bottle(s) Available")
    assert a["pack_size"] == b["pack_size"] == 1
    assert a["bottle_ml"] == b["bottle_ml"] == 750


def test_bi_magnum_case_parses_size_not_pack():
    p = parse_offer_row("Case (1 x 150cl) CONDITION Original Case STATUS In-Bond You buy £2,500.00 1 2 3 BUY 3 Case(s) Remaining")
    assert (p["pack_size"], p["bottle_ml"]) == (1, 1500)
    assert p["offered_units"] == 3


def test_bi_title_is_producer_first_and_code_is_never_identity():
    """roush-2005 is CHARMES-Chambertin; rouc-2011 is Chambertin. Codes lie."""
    t = parse_title("2005 Domaine Armand Rousseau, Charmes-Chambertin Grand Cru")
    assert t["producer"] == "Domaine Armand Rousseau"
    assert t["cuvee"] == "Charmes-Chambertin Grand Cru"
    assert t["vintage"] == 2005


def test_bi_nv_champagne_title_has_no_leading_vintage_token_at_all():
    """Champagne sweep, 9 October 2026: confirmed live across Bollinger, Eric
    Rodez, Henri Giraud, Krug and Savart -- an NV card's title on BI's own
    regular listing endpoint carries no vintage token, not even "NV" itself.
    "Krug, Grande Cuvee 161eme Edition" starts directly with the producer.
    Every one of 40 live rows like it was silently "unparseable title" before
    this fix, including the whole of this cellar's Krug position."""
    t = parse_title("Krug, Grande Cuvee 161eme Edition")
    assert t == {"vintage": 1000, "producer": "Krug", "cuvee": "Grande Cuvee 161eme Edition"}
    assert parse_title("") is None
    assert parse_title(None) is None


def test_bi_normalise_splits_the_edition_number_out_of_the_cuvee():
    """The gap decision 0019 built for and 0027 found unwired elsewhere
    (release_code never reaching resolve_candidate) also applied to this
    adapter's own normalise(): it never called split_release_code at all."""
    card = {"title": "Krug, Grande Cuvee 161eme Edition", "code": "KRU161", "url": "u",
            "offers": ["Case (6 x 75cl) STATUS In-Bond You buy £1,800.00 1 BUY 1 Case(s) Remaining"]}
    [c] = BordeauxIndexAdapter().normalise(card, captured_at=AS_OF)
    assert (c.producer_text, c.cuvee_text, c.release_code) == ("Krug", "Grande Cuvee", "161")


def test_bi_third_party_marker_marks_basis_unconfirmed():
    p = parse_offer_row("Case (6 x 75cl) BR CONDITION Original Case STATUS In-Bond ETA In Stock You buy £31,800.00 1 Buy 1 Case(s) Remaining")
    assert p["third_party_marker"] is True
    r = benchmark(line(vintage=2009, pack_size=6),
                  [offer(vintage=2009, pack_size=6, price=Decimal("31800"),
                         stock_type=StockType.UNKNOWN, stock_type_basis="unconfirmed")])
    assert Flag.STOCK_BASIS_UNCONFIRMED in r.flags
    assert r.state is State.REVIEW


# ------------------------------------------------------ Goedhuis: the SKU trap

@pytest.mark.parametrize("sku,eligible", [
    ("09A6CCBR1PK-IB-InBond-ExcVAT", True),
    ("09B8NGMMU6PK-IB-BR-675-InBond-ExcVAT", True),      # broking IB ask — allowed
    ("09A6CCBR1PK-DP-InBond-ExcVAT", False),             # DUTY PAID despite 'InBond'
    ("09A6CCBR1PK-IB-Retail-IncVAT", False),             # IB stock, retail inc-VAT basis
    ("09A6CCBR1PK-DP-Retail-IncVAT", False),
    ("09A6CCBR1PK-DP-InBond-IncVAT", False),
])
def test_goedhuis_sku_duty_vs_presentation(sku, eligible):
    """Both -IB-InBond- and -DP-InBond- contain 'InBond'. Only one is an In Bond
    price. A substring match here ingests duty-paid stock as an IB comp."""
    parts = parse_sku(sku)
    assert parts is not None
    assert is_eligible_variant(parts) is eligible


def test_goedhuis_broker_price_is_captured_and_marked_brokered():
    parts = parse_sku("09C0CMAMU3PK-IB-BR-4200-InBond-ExcVAT")
    assert parts["broker_price"] == Decimal("4200")
    assert parts["duty"] == "IB"


def test_goedhuis_zero_price_sold_out_variant_never_becomes_a_floor():
    product = {
        "handle": "h", "title": "09A9MVVV3PK _ 2009 - Musigny Grand Cru Vieilles Vignes Comte Georges de Vogue - 3x75cl",
        "variants": [
            {"sku": "09A9MVVV3PK-IB-InBond-ExcVAT", "price": "0.00", "available": False},
        ],
    }
    out = GoedhuisAdapter().normalise(product)
    assert out.__class__.__name__ == "Rejected"


def test_goedhuis_title_parses_pack_and_size():
    from app.adapters.goedhuis import parse_title
    t = parse_title("09A6CCBR1PK _ 2006 - Chambertin Clos de Beze Grand Cru Armand Rousseau - 1x75cl")
    assert (t["vintage"], t["pack"], t["bottle_ml"]) == (2006, 1, 750)


# ---------------------------------------------------------- Farr: naming + sizes

def test_farr_burgundy_is_cuvee_first():
    """The root cause of the Burgundy blackout: 'Chambertin, Domaine Armand Rousseau'."""
    assert split_wine_field("Chambertin, Domaine Armand Rousseau") == (
        "Domaine Armand Rousseau", "Chambertin")
    assert split_wine_field("Musigny VV, Domaine Comte Georges de Vogüé") == (
        "Domaine Comte Georges de Vogüé", "Musigny VV")


@pytest.mark.parametrize("raw,expect", [
    ("12×75cl", (12, 750)),      # U+00D7, not the letter x
    ("12x75cl", (12, 750)),
    ("1×75cl", (1, 750)),
    ("1×1.5L", (1, 1500)),
    ("3×75cl", (3, 750)),
    ("nonsense", None),
])
def test_farr_size_parsing(raw, expect):
    assert parse_size(raw) == expect


def test_farr_mixed_lot_is_rejected():
    raw = {"WineId": 52484, "Wine": "Mixed Case Mugnier, Domaine Mugnier", "Vintage": "2014",
           "Size": "6×75cl", "SellGBP": 5750, "Per": 6, "Units": 6,
           "Variation": "Contains 2bts each Chambolle Amoureuses, Chambolles Fuees & Bonnes Mares"}
    out = FarrAdapter().normalise(raw)
    assert getattr(out, "reason", None) is Reject.MIXED_LOT


def test_farr_per_must_agree_with_size():
    """A Per/Size disagreement means we do not understand the row. Fail closed."""
    raw = {"WineId": 1, "Wine": "Chambertin, Domaine Armand Rousseau", "Vintage": "2014",
           "Size": "6×75cl", "SellGBP": 12000, "Per": 12, "Units": 6, "Variation": None}
    out = FarrAdapter().normalise(raw)
    assert getattr(out, "reason", None) is Reject.UNIT


def test_farr_two_parcels_stay_two_records():
    """The HTML page renders 2014 Chambertin as '£2,000.00 / £1,800.00'. Those are
    a 6x75cl case at £12,000 and a single bottle at £1,800, not a quantity break."""
    case = FarrAdapter().normalise(
        {"WineId": 1, "Wine": "Chambertin, Domaine Armand Rousseau", "Vintage": "2014",
         "Size": "6×75cl", "SellGBP": 12000, "Per": 6, "Units": 6, "Variation": None})
    btl = FarrAdapter().normalise(
        {"WineId": 2, "Wine": "Chambertin, Domaine Armand Rousseau", "Vintage": "2014",
         "Size": "1×75cl", "SellGBP": 1800, "Per": 1, "Units": 1,
         "Variation": "Not in original carton"})
    assert case.offer.pack_size == 6 and case.offer.price == Decimal("12000")
    assert btl.offer.pack_size == 1 and btl.offer.price == Decimal("1800")
    assert btl.offer.price != case.offer.price / 6


# -------------------------------------------------------- core pricing invariants

def test_duplicate_listings_never_create_depth():
    """2011 Clos de la Roche: two Bordeaux Index rows at £610. Counting listings
    would let one merchant set its own second-lowest reference."""
    r = benchmark(line(), [offer(offer_id="a", price=Decimal("610")),
                           offer(offer_id="b", price=Decimal("610"))])
    assert r.comp_count == 1
    assert r.duplicate_listings == 1
    assert Flag.ONE_COMP in r.flags


def test_merchant_best_is_the_cheapest_of_that_merchants_listings():
    r = benchmark(line(), [offer(offer_id="a", price=Decimal("19950")),
                           offer(offer_id="b", price=Decimal("19000")),
                           offer(offer_id="c", merchant_id="m2", price=Decimal("20500"))])
    assert r.uk_floor == Decimal("19000")
    assert r.uk_reference == Decimal("20500")


def test_cross_unit_evidence_is_excluded_but_visible():
    """6x75cl never prices a loose bottle. The arithmetic is shown, not used."""
    r = benchmark(line(pack_size=1), [offer(pack_size=6, price=Decimal("4425"))])
    assert r.comp_count == 0
    assert r.state is State.NO_MARKET
    assert len(r.cross_unit) == 1
    assert r.cross_unit[0].per_bottle == Decimal("737.5")


def test_different_case_size_is_simply_not_a_comp():
    r = benchmark(line(pack_size=6), [offer(pack_size=12, price=Decimal("12234"))])
    assert r.comp_count == 0
    assert any(x.reason is Reject.UNIT for x in r.rejections)


def test_non_gbp_offer_is_rejected():
    """Bordeaux Index prices are session-currency scoped. Defence in depth."""
    r = benchmark(line(), [offer(currency="HKD", price=Decimal("6000"))])
    assert any(x.reason is Reject.CURRENCY for x in r.rejections)
    assert r.state is State.NO_MARKET


def test_unbuyable_offer_is_rejected():
    r = benchmark(line(), [offer(is_buyable=False)])
    assert any(x.reason is Reject.NOT_BUYABLE for x in r.rejections)


def test_zero_offered_units_is_rejected():
    r = benchmark(line(), [offer(offered_units=0)])
    assert any(x.reason is Reject.NO_QUANTITY for x in r.rejections)


def test_non_positive_price_is_rejected():
    r = benchmark(line(), [offer(price=Decimal("0"))])
    assert any(x.reason is Reject.NON_POSITIVE_PRICE for x in r.rejections)


def test_bid_is_not_an_offer():
    """BI LiveTrade separates best bid, best offer and last trade."""
    r = benchmark(line(), [offer(price=Decimal("3854"), price_kind=PriceKind.BID),
                           offer(price=Decimal("4247"), merchant_id="m2")])
    assert r.uk_floor == Decimal("4247")
    assert any(x.reason is Reject.KIND for x in r.rejections)


def test_money_is_exact():
    """£2,353.10 stays £2,353.10."""
    r = benchmark(line(), [offer(price=Decimal("2353.10")),
                           offer(merchant_id="m2", price=Decimal("2350.00"))])
    assert r.uk_floor == Decimal("2350.00")
    assert r.uk_reference == Decimal("2353.10")
    assert str(r.uk_reference) == "2353.10"


def test_repack_alone_does_not_force_review():
    """Repack is the norm in the loose-bottle Burgundy market. Gating on it would
    send every Burgundy line to review."""
    r = benchmark(line(), [offer(condition_flags=frozenset({ConditionFlag.REPACK})),
                           offer(merchant_id="m2", price=Decimal("650"))])
    assert Flag.CONDITION_REVIEW not in r.flags
    assert r.state is State.READY


def test_non_pristine_does_force_review():
    r = benchmark(line(), [offer(condition_flags=frozenset({ConditionFlag.NON_PRISTINE})),
                           offer(merchant_id="m2", price=Decimal("650"))])
    assert Flag.CONDITION_REVIEW in r.flags
    assert r.state is State.REVIEW


def test_quantity_shortfall_is_informational_only():
    """Documented decision 0002: comparability does not currently require the
    offer to cover the seller's quantity."""
    r = benchmark(line(quantity=6),
                  [offer(offered_units=1), offer(merchant_id="m2", offered_units=1,
                                                 price=Decimal("650"))])
    assert Flag.QUANTITY_SHORTFALL in r.flags
    assert r.comp_count == 2
    assert r.state is State.READY          # shortfall does not gate


def test_mixed_lot_never_becomes_a_comp():
    r = benchmark(line(), [offer(is_mixed_lot=True)])
    assert any(x.reason is Reject.MIXED_LOT for x in r.rejections)


def test_offer_without_approved_identity_never_prices():
    r = benchmark(line(), [offer(wine_id="")])
    assert any(x.reason is Reject.UNRESOLVED_IDENTITY for x in r.rejections)
    assert r.state is State.NO_MARKET


def test_every_rejection_is_retained():
    offers = [offer(wine_id="other"), offer(vintage=2012), offer(pack_size=6),
              offer(duty_status=DutyStatus.DUTY_PAID), offer(currency="USD")]
    r = benchmark(line(), offers)
    assert len(r.rejections) == len(offers)
    assert all(x.reason for x in r.rejections)


# -------------------------------------------------------------- identity guards

@pytest.mark.parametrize("a,b", STRUCTURAL_EXCLUSIONS)
def test_structural_exclusions_never_collapse(a, b):
    assert a != b
    reg = Registry([
        CanonicalWine("id-a", *a.split("|")),
        CanonicalWine("id-b", *b.split("|")),
    ])
    pa, ca = a.split("|")
    pb, cb = b.split("|")
    assert reg.resolve(pa, ca) == "id-a"
    assert reg.resolve(pb, cb) == "id-b"


def test_wine_key_is_accent_and_abbreviation_stable():
    assert wine_key("Domaine Comte Georges de Vogüé", "Musigny Grand Cru") == \
           wine_key("Dom. Comte Georges de Vogue", "Musigny Grand Cru")
    assert wine_key("Ch Lafite Rothschild", "Grand Vin") == \
           wine_key("Château Lafite-Rothschild", "Grand Vin")


def test_dom_perignon_is_not_read_as_domaine_perignon():
    """"Dom" before "Pérignon" is the monastic title (Dom Pierre Pérignon),
    not an abbreviation of "Domaine" — Champagne sweep, 9 October 2026, 136
    bottles. Confirmed harmless by accident before this fix (both sides of
    every match went through the same wrong expansion); this asserts the
    producer key itself now reads correctly, not just that it matched
    itself."""
    assert norm_producer("Dom Pérignon") == "dom perignon"
    assert norm_producer("Dom Perignon") == "dom perignon"
    # the abbreviation still expands for an actual Domaine, prefix unchanged
    assert norm_producer("Dom. Leflaive") == "domaine leflaive"


def test_krug_grande_cuvee_editions_require_release_code_or_collapse_to_one():
    """The negative control for decision 0019/0027's release_code fix:
    app/worker/jobs.ingest() never passed Candidate.release_code to
    resolve_candidate from 0019 until the LiveTrade adapter exposed the gap
    (8 October 2026). Every Krug edition ever ingested by any adapter
    resolved without it. This proves the practical size of that bug against
    real cellar data: 156e-169e (454 bottles, Doug's largest single
    position) must resolve as 14 distinct wines WITH the code, and WOULD
    collapse to one WITHOUT it."""
    editions = [str(n) for n in range(156, 170)]
    with_code = {wine_key("Krug", "Grande Cuvée", code) for code in editions}
    without_code = {wine_key("Krug", "Grande Cuvée", None) for _ in editions}
    assert len(with_code) == 14
    assert without_code == {"krug|grande cuvee"}

    reg = Registry([CanonicalWine(f"krug-{code}", "Krug", "Grande Cuvée", release_code=code)
                    for code in editions])
    for code in editions:
        assert reg.resolve("Krug", "Grande Cuvée", release_code=code) == f"krug-{code}"
    # a candidate that fails to carry its edition fails closed to review,
    # never guesses which of the 14 it meant
    assert reg.resolve("Krug", "Grande Cuvée") is None


def test_split_release_code_reads_the_edition_word_first_too():
    """Bordeaux Index's OWN regular listing feed names the same edition two
    ways in two different cards: "Krug, Grande Cuvee 161eme Edition" (number
    first, the pattern above) and "Krug Grande Cuvee Edition 162" (the word
    "Edition" first, number last) -- one merchant, two orderings, in the
    same feed, confirmed live 9 October 2026."""
    assert split_release_code("Grande Cuvee Edition 162") == ("Grande Cuvee", "162")
    assert split_release_code("Grande Cuvée Édition 156") == ("Grande Cuvée", "156")
    # a classification with more text after "Edition N" is not this pattern
    assert split_release_code("Edition 162 Grand Cru") == ("Edition 162 Grand Cru", None)


def test_condition_normalisation_from_live_strings():
    assert normalise_condition("Not in original carton") == frozenset({ConditionFlag.NO_ORIGINAL_CASE})
    assert normalise_condition("Non OWC") == frozenset({ConditionFlag.NO_ORIGINAL_CASE})
    assert normalise_condition("Individual OWC") == frozenset({ConditionFlag.ORIGINAL_CASE})
    assert normalise_condition("Repack") == frozenset({ConditionFlag.REPACK})
    assert ConditionFlag.NON_PRISTINE in normalise_condition("Repack Bottle: Non Pristine")
    flags = normalise_condition("Excellent levels, not in original carton, stained labels")
    assert ConditionFlag.LABEL_DAMAGE in flags
    assert ConditionFlag.NO_ORIGINAL_CASE in flags


# -------------------------------------------------- freshness (decision 0003)

def test_six_month_old_capture_never_becomes_the_uk_reference():
    """Before 0003 nothing stopped a March capture of a sold-out Rousseau
    Chambertin at £600 from being the Reference in September: an undercut of
    whatever the market now is, with nothing on the line to say so."""
    old = offer(merchant_id="m1", price=Decimal("600"), captured_at=AS_OF - timedelta(days=182))
    fresh = offer(merchant_id="m2", price=Decimal("900"))
    r = benchmark(line(), [old, fresh])
    assert r.uk_reference == Decimal("900") and r.comp_count == 1
    assert [x.reason for x in r.rejections] == [Reject.STALE]
    assert r.state is State.REVIEW


@pytest.mark.parametrize("age,fresh", [
    (timedelta(0), True),
    (timedelta(days=MAX_OFFER_AGE_DAYS), True),                        # boundary is inclusive
    (timedelta(days=MAX_OFFER_AGE_DAYS, seconds=1), False),
    (timedelta(seconds=-1), False),                                     # captured after as_of
])
def test_freshness_window_boundaries(age, fresh):
    r = benchmark(line(), [offer(captured_at=AS_OF - age)])
    assert (r.comp_count == 1) is fresh
    if not fresh:
        assert r.rejections[0].reason is Reject.STALE


def test_undated_offer_is_not_provably_fresh():
    r = benchmark(line(), [offer(captured_at=None)])
    assert r.state is State.NO_MARKET
    assert r.rejections[0].reason is Reject.STALE


def test_stale_case_is_not_shown_as_cross_unit_evidence():
    """Cross-unit evidence is 'otherwise a valid In Bond ask'. A stale case price
    shown per bottle next to a fresh line would read as current."""
    r = benchmark(line(), [offer(pack_size=6, price=Decimal("3600"),
                                 captured_at=AS_OF - timedelta(days=30))])
    assert r.cross_unit == []


def test_oldest_contributing_comp_age_is_exposed():
    r = benchmark(line(), [offer(merchant_id="m1", captured_at=AS_OF - timedelta(days=9)),
                           offer(merchant_id="m2", price=Decimal("650"),
                                 captured_at=AS_OF - timedelta(days=2))])
    assert r.oldest_comp_age == timedelta(days=9)
    assert benchmark(line(), []).oldest_comp_age is None


def test_as_of_must_be_timezone_aware():
    with pytest.raises(ValueError):
        benchmark(line(), [offer()], as_of=AS_OF.replace(tzinfo=None))


# ------------------------------------------------------------- median rounding


@pytest.mark.parametrize("a,b,median", [
    ("610.01", "610.02", "610.02"),     # £610.015 -> up to the even penny
    ("610.02", "610.03", "610.02"),     # £610.025 -> down to the even penny
    ("0.99", "1.00", "1.00"),           # £0.995 -> up, across the pound
    ("100.00", "100.01", "100.00"),     # £100.005 -> down
])
def test_even_count_median_is_banker_rounded_both_directions(a, b, median):
    """uk_median is numeric(14,2). Rounding it here, once, by a stated rule means
    Postgres never rounds it silently on insert."""
    r = benchmark(line(), [offer(merchant_id="m1", price=Decimal(a)),
                           offer(merchant_id="m2", price=Decimal(b))])
    assert str(r.uk_median) == median
    assert (str(r.uk_floor), str(r.uk_reference)) == (a, b)     # never rounded


def test_odd_count_median_is_an_offer_price_unchanged():
    r = benchmark(line(), [offer(merchant_id=m, price=Decimal(p)) for m, p in
                           (("m1", "600.00"), ("m2", "610.01"), ("m3", "700.00"))])
    assert str(r.uk_median) == "610.01"


# ------------------------------------------------ inherited flags (decision 0005)

INHERITABLE = (Flag.NAME_REVIEW, Flag.FORMAT_REVIEW, Flag.DERIVED_FROM_CASE)
MARKETS = {
    "ready": [offer(merchant_id="m1"), offer(merchant_id="m2", price=Decimal("650"))],
    "one_comp": [offer()],
    "no_market": [],
}
SUBSETS = [frozenset(c) for n in range(len(INHERITABLE) + 1)
           for c in combinations(INHERITABLE, n)]


@pytest.mark.parametrize("market", MARKETS)
@pytest.mark.parametrize("inherited", SUBSETS, ids=lambda s: "+".join(sorted(f.value for f in s)) or "none")
def test_inherited_flags_only_ever_move_a_line_towards_review(market, inherited):
    """A line flagged NAME_REVIEW by identity verification must never come out
    of the benchmark READY. Adding flags can hold a line back; it cannot release
    one, and it cannot conjure a market where there is none."""
    rank = {State.READY: 0, State.REVIEW: 1}
    base = benchmark(line(), MARKETS[market])
    got = benchmark(line(inherited_flags=inherited), MARKETS[market])
    assert inherited <= got.flags
    if base.state is State.NO_MARKET:
        assert got.state is State.NO_MARKET
    else:
        assert rank[got.state] >= rank[base.state]
        assert got.state is (State.REVIEW if inherited else base.state)
    assert (got.uk_floor, got.uk_reference, got.uk_median) == \
           (base.uk_floor, base.uk_reference, base.uk_median)


@pytest.mark.parametrize("flag", sorted(set(Flag) - REVIEW_FLAGS, key=lambda f: f.value))
def test_a_non_review_flag_cannot_be_inherited(flag):
    """Only review flags can be inherited. An upstream WIDE_SPREAD or NO_MARKET
    on the line would be a claim about the market the benchmark did not make."""
    with pytest.raises(ValueError):
        benchmark(line(inherited_flags=frozenset({flag})), [offer()])


# ------------------------------------------- Farr: LWIN, float prices, wording

FARR_FEED = json.loads((Path(__file__).parent / "fixtures/farr-feed-2026-09-19.json").read_text())
FARR = {r["WineId"]: r for r in FARR_FEED["data"]}


def farr_candidate(wine_id: int) -> Candidate:
    out = FarrAdapter().normalise(FARR[wine_id], captured_at=AS_OF)
    assert isinstance(out, Candidate), out
    return out


def test_farr_lwin7_is_carried_not_discarded():
    """Farr publishes LWIN-7 for Bordeaux as an integer; we used to throw it away."""
    assert farr_candidate(237136).lwin7 == "1011872"          # Lafite Rothschild
    assert farr_candidate(236920).lwin7 is None               # Rousseau: null in feed


def test_a_merchant_lwin_never_resolves_identity_on_its_own():
    """Farr's 'Lafite Rothschild' has no comma, so wine_key misses it. The LWIN
    knows what it is, but it is the MERCHANT's mapping of its own listing, not
    the LWIN database: see the Rosé case below for what that buys. The record
    waits for an alias instead (decision 0006)."""
    c = farr_candidate(237136)
    reg = Registry([CanonicalWine("lafite", "Chateau Lafite Rothschild", "Grand Vin", "1011872")])
    assert reg.resolve_candidate(c.producer_text, c.cuvee_text, c.lwin7) is None
    # With the merchant's own spelling approved as an alias, it resolves, and
    # the LWIN agrees with the name.
    reg._by_key[wine_key("Lafite Rothschild", "")] = "lafite"
    assert reg.resolve_candidate(c.producer_text, c.cuvee_text, c.lwin7) == "lafite"


def test_farr_rose_alone_under_brut_lwin_is_not_priced_as_brut():
    """Farr publishes LWIN-7 1083129 for both Veuve Clicquot and Veuve Clicquot
    Rosé. A feed carrying only the Rosé would have resolved it to the Brut with
    nothing to contradict it. Requiring name agreement closes that."""
    r = farr_candidate(179277)
    reg = Registry([CanonicalWine("vcp-brut", "Veuve Clicquot", "Brut", "1083129")])
    assert reg.resolve_candidate(r.producer_text, r.cuvee_text, r.lwin7) is None


def test_lwin_disagreeing_with_an_approved_name_stops_the_record():
    """The cross-check earns its keep here: an alias says Carruades, Farr's LWIN
    says Lafite. One of them is wrong, so the record prices nothing."""
    k = farr_candidate(215140)                    # Carruades de Lafite, LWIN 1718931
    reg = Registry([CanonicalWine("lafite", "Chateau Lafite Rothschild", "Grand Vin", "1718931"),
                    CanonicalWine("carruades", "Chateau Lafite Rothschild", "Carruades")])
    reg._by_key[wine_key(k.producer_text, k.cuvee_text)] = "carruades"
    assert reg.resolve_candidate(k.producer_text, k.cuvee_text, k.lwin7) is None


def test_farr_shared_lwin_never_prices_lavaux_off_clos_saint_jacques():
    """Farr, 2026-09-19: LWIN-7 1038217 on both Jadot Gevrey-Chambertin Clos
    Saint Jacques (£960/6) and Lavaux Saint Jacques (£520/6). Trusting it would
    price one climat off the other: an 85% error either way."""
    csj, lav = farr_candidate(227986), farr_candidate(227984)
    assert csj.lwin7 == lav.lwin7 == "1038217"
    reg = Registry([
        CanonicalWine("csj", "Louis Jadot", "Gevrey Chambertin Clos Saint Jacques", "1038217"),
        CanonicalWine("lavaux", "Louis Jadot", "Gevrey Chambertin Lavaux Saint Jacques"),
    ])
    # LWIN says Clos Saint Jacques, the name says Lavaux: neither is trusted.
    assert reg.resolve_candidate(lav.producer_text, lav.cuvee_text, lav.lwin7) is None
    # Once an operator has judged this LWIN unreliable it is not consulted, and
    # the name stands on its own.
    assert reg.resolve_candidate(lav.producer_text, lav.cuvee_text, None) == "lavaux"


@pytest.mark.parametrize("ids,collides", [
    ((227986, 227984), True),     # Jadot Clos vs Lavaux Saint Jacques: a mapping error
    ((179275, 179277), True),     # Veuve Clicquot vs Rosé: a mapping error
    ((237136,), False),           # one name, no collision
])
def test_collided_lwins_are_reported_with_the_merchants_own_wording(ids, collides):
    cs = [farr_candidate(i) for i in ids]
    found = collided_lwins([(c.lwin7, c.producer_text, c.cuvee_text) for c in cs])
    assert bool(found) is collides
    if collides:
        [names] = found.values()
        assert len(names) == 2 and all(any(w in n for w in ("Jadot", "Clicquot")) for n in names)


def test_a_collision_is_not_proof_the_merchant_is_wrong():
    """Gaja's Costa Russi appears as both 'Barbaresco Costa Russi' and 'Costa
    Russi' because the wine changed appellation. Here the LWIN is right and our
    name key is wrong to split it, so a collision goes to an operator rather
    than being discarded: discarding it would lose real depth."""
    batch = [("1099722", "Gaja", "Barbaresco Costa Russi"), ("1099722", "Gaja", "Costa Russi")]
    assert collided_lwins(batch) == {"1099722": ["Gaja / Barbaresco Costa Russi",
                                                 "Gaja / Costa Russi"]}
    # Once the operator approves the alias, both spellings are one wine and the
    # LWIN agrees with the name.
    reg = Registry([CanonicalWine("costa-russi", "Gaja", "Costa Russi", "1099722")])
    reg._by_key[wine_key("Gaja", "Barbaresco Costa Russi")] = "costa-russi"
    for _, p, c in batch:
        assert reg.resolve_candidate(p, c, "1099722") == "costa-russi"


@pytest.mark.parametrize("raw,vintage", [
    ("2011", 2011), ("NV", 1000), ("N.V.", 1000),
    ("M.V.", None),          # multi-vintage: meaning not established
    ("BV14", None),          # coded form: meaning not established
])
def test_farr_non_vintage_is_1000_not_a_rejection(raw, vintage):
    """166 of 5,841 Farr records carry a non-numeric Vintage. NV is the LWIN
    convention's 1000; int('N.V.') raised and dropped every one of them,
    including the vintage Champagne and Port that the NV wines sit beside."""
    from app.adapters.farr import parse_vintage
    assert parse_vintage(raw) == vintage
    out = FarrAdapter().normalise({**FARR[237136], "Vintage": raw}, captured_at=AS_OF)
    if vintage is None:
        assert out.reason is Reject.VINTAGE
    else:
        assert out.offer.vintage == vintage


def test_bordeaux_index_unreadable_row_is_kept_as_a_rejection():
    """A card's rows were skipped silently when they did not parse. Evidence we
    cannot read is still evidence that something was there."""
    card = {"title": "2011 Domaine Armand Rousseau, Charmes-Chambertin Grand Cru", "url": "u",
            "offers": ["Case (6 x 75cl) STATUS In-Bond price on application",
                       "Bottle (75cl) CONDITION Original Case STATUS In-Bond "
                       "You buy £650.00 2 Bottle(s) Available"]}
    bad, good = BordeauxIndexAdapter().normalise(card, captured_at=AS_OF)
    assert bad.reason is Reject.ROW_UNREADABLE and "price on application" in bad.detail
    assert good.offer.price == Decimal("650.00")


def test_farr_float32_price_is_not_whole_pence():
    """Farr, WineId 230806, Conterno Cascina Francia 2008 magnum: SellGBP is
    308.329986. Stored as-is it breaks numeric(14,2); rounded it is an estimate.
    It is rejected. Before this screen it aborted ALL Farr ingest for the run."""
    c = FarrAdapter().normalise(FARR[230806], captured_at=AS_OF)
    assert c.offer.price == Decimal("308.329986")
    assert not whole_pence(c.offer.price)
    assert whole_pence(farr_candidate(145009).offer.price)             # 112.5 is fine
    assert whole_pence(farr_candidate(237136).offer.price)


def test_every_farr_fixture_record_normalises_without_exception():
    for rec in FARR_FEED["data"]:
        FarrAdapter().normalise(rec, captured_at=AS_OF)


def test_a_price_that_is_not_whole_pence_never_becomes_floor_or_reference():
    """The refusal is in the core too, not only at storage: a 308.329986 that
    reached the benchmark would otherwise be the Floor."""
    r = benchmark(line(), [offer(merchant_id="m1", price=Decimal("308.329986")),
                           offer(merchant_id="m2", price=Decimal("900.00"))])
    assert r.uk_floor == Decimal("900.00") and r.comp_count == 1
    assert [x.reason for x in r.rejections] == [Reject.NOT_WHOLE_PENCE]


def test_a_price_that_is_not_whole_pence_is_not_cross_unit_evidence_either():
    r = benchmark(line(), [offer(pack_size=6, price=Decimal("1849.979980"))])
    assert r.cross_unit == []


# --------------------------------- condition wording kept (all three adapters)


def test_a_flag_without_the_merchants_wording_is_refused_by_the_contract():
    o = offer(condition_flags=frozenset({ConditionFlag.LABEL_DAMAGE}), condition_notes=None)
    with pytest.raises(ValueError, match="without the merchant's wording"):
        Candidate(offer=o, producer_text="p", cuvee_text="c")


def test_farr_keeps_condition_wording():
    """Farr, Armailhac 2000 12x75cl: 'OWC, 1 slightly damaged label'."""
    c = farr_candidate(238416)
    assert ConditionFlag.LABEL_DAMAGE in c.offer.condition_flags
    assert c.offer.condition_notes == "OWC, 1 slightly damaged label"


def test_bordeaux_index_keeps_condition_wording():
    card = {"title": "2009 Domaine Armand Rousseau Chambertin Grand Cru", "url": "u",
            "offers": ["Case (6 x 75cl) CONDITION Original Case, stained labels STATUS In-Bond "
                       "ETA In Stock You buy £31,800.00 1 Buy 1 Case(s) Remaining"]}
    [c] = BordeauxIndexAdapter().normalise(card, captured_at=AS_OF)
    assert ConditionFlag.LABEL_DAMAGE in c.offer.condition_flags
    assert c.offer.condition_notes == "Original Case, stained labels"


@pytest.mark.parametrize("wording,flag", [
    ("Non OC", ConditionFlag.NO_ORIGINAL_CASE),
    ("Repack", ConditionFlag.REPACK),                 # was flagged but DROPPED before
    ("Stained Labels", ConditionFlag.LABEL_DAMAGE),   # was flagged but DROPPED before
])
def test_goedhuis_keeps_condition_wording_not_only_for_non_oc(wording, flag):
    """Goedhuis writes condition into the title. Only 'Non OC' used to be kept;
    any other flagged wording reached the operator as a bare flag."""
    product = {"handle": "h", "title": f"09A6CCBR1PK _ 2006 - Chambertin Clos de Beze Grand Cru "
                                       f"Armand Rousseau {wording} - 1x75cl",
               "variants": [{"sku": "09A6CCBR1PK-IB-InBond-ExcVAT", "price": "2400.00",
                             "available": True}]}
    c = GoedhuisAdapter().normalise(product, captured_at=AS_OF)
    assert flag in c.offer.condition_flags
    assert wording in c.offer.condition_notes


# ------------------------------- FINE+RARE: a brokerage, not a stockholder
#
# Its unitPrice is an aggregated pan-European broking indication. Nobody has
# said they hold the wine at it, which is why every variant reads quantity 0.
# See docs/decisions/0013-brokerage-indications.md.

FRW_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/fine-rare-2026-09-22.json").read_text())
FRW = {r["product"]["name"]: r for r in FRW_FIXTURE["products"]}


def frw_candidate(name: str) -> Candidate:
    out = FineAndRareAdapter().normalise(FRW[name], captured_at=AS_OF)
    assert isinstance(out, Candidate), out
    return out


def indication(**kw) -> Offer:
    """A FINE+RARE indication for the line under test."""
    base = dict(offer_id="frw:1", merchant_id="fine-rare", merchant="FINE+RARE",
                price=Decimal("590.00"), price_kind=PriceKind.INDICATION,
                duty_status=DutyStatus.UNKNOWN, is_buyable=False, offered_units=0,
                stock_type=StockType.BROKERED, stock_type_basis="declared")
    base.update(kw)
    return offer(**base)


def test_an_indication_can_never_become_the_uk_reference():
    """FINE+RARE's £590 sits beside Farr's £610 and Bordeaux Index's £650 for
    2011 Rousseau Charmes — close enough to look like a comparable. It is not
    one: nobody has offered stock at it, so it cannot price anything."""
    r = benchmark(line(), [indication(price=Decimal("590.00")),
                           offer(merchant_id="farr", price=Decimal("610.00")),
                           offer(merchant_id="bordeaux-index", price=Decimal("650.00"))])
    assert (r.uk_floor, r.uk_reference) == (Decimal("610.00"), Decimal("650.00"))
    assert r.comp_count == 2
    assert all(o.merchant_id != "fine-rare" for o in r.merchant_bests)
    assert all(o.merchant_id != "fine-rare" for o in r.comparables)


def test_an_indication_alone_is_no_market():
    """A market is somewhere you can buy. An indication is a view about one."""
    r = benchmark(line(), [indication()])
    assert r.state is State.NO_MARKET
    assert r.uk_reference is None and r.comp_count == 0


def test_an_indication_is_surfaced_as_corroboration_with_its_variance():
    r = benchmark(line(), [indication(price=Decimal("590.00")),
                           offer(merchant_id="farr", price=Decimal("610.00")),
                           offer(merchant_id="bordeaux-index", price=Decimal("650.00"))])
    [evidence] = r.indications
    assert evidence.offer.price == Decimal("590.00")
    assert evidence.variance_vs_reference == (Decimal("590") - Decimal("650")) / Decimal("650")
    assert r.indications[0].offer.merchant == "FINE+RARE"


def test_an_indication_with_no_reference_to_compare_against_has_no_variance():
    r = benchmark(line(), [indication()])
    assert r.indications[0].variance_vs_reference is None


@pytest.mark.parametrize("kw", [
    dict(vintage=2012),                                  # another vintage
    dict(pack_size=6, price=Decimal("3540.00")),         # another commercial unit
    dict(bottle_ml=1500),                                # another size
    dict(currency="EUR"),
    dict(captured_at=AS_OF - timedelta(days=30)),        # stale
])
def test_an_indication_for_something_else_is_not_corroboration(kw):
    """Corroboration has to be of the same thing, or it corroborates nothing."""
    r = benchmark(line(), [indication(**kw), offer(merchant_id="farr")])
    assert r.indications == []


# ------------------------------- Bordeaux Index LiveTrade: bid, offer, last
# trade
#
# docs/research/bi-livetrade-champagne-findings.md, 7 October 2026. Krug
# 167e: bid £908, offer £977, last trade £904 (14/09/2026) — a real,
# liquid two-sided market. Krug 162e: bid £660 against offer £1,596 on the
# same 6x75cl listing, a 142% spread — two people a long way apart, not a
# market a midpoint could honestly summarise. See docs/decisions/0026.

def bid(**kw) -> Offer:
    base = dict(offer_id="bi-bid:1", merchant_id="bordeaux-index", merchant="Bordeaux Index",
               price=Decimal("908.00"), price_kind=PriceKind.BID)
    base.update(kw)
    return offer(**base)


def last_trade(**kw) -> Offer:
    base = dict(offer_id="bi-trade:1", merchant_id="bordeaux-index", merchant="Bordeaux Index",
               price=Decimal("904.00"), price_kind=PriceKind.LAST_TRADE)
    base.update(kw)
    return offer(**base)


def test_a_bid_can_never_become_the_uk_reference():
    """Krug 167e: a £908 bid beside Farr's £950 and Bordeaux Index's own
    £977 offer. The bid is real, executable demand — and still never prices
    anything; only the two asks compete for Floor and Reference."""
    r = benchmark(line(), [bid(price=Decimal("908.00")),
                          offer(merchant_id="farr", price=Decimal("950.00")),
                          offer(merchant_id="bordeaux-index", price=Decimal("977.00"))])
    assert (r.uk_floor, r.uk_reference) == (Decimal("950.00"), Decimal("977.00"))
    assert r.comp_count == 2
    assert all(o.price_kind is PriceKind.ASK for o in r.merchant_bests)


def test_a_bid_alone_is_no_market():
    """Demand with nobody selling into it is not a market to price from."""
    r = benchmark(line(), [bid()])
    assert r.state is State.NO_MARKET
    assert r.uk_reference is None and r.comp_count == 0


def test_a_bid_is_surfaced_as_corroboration_with_its_variance():
    r = benchmark(line(), [bid(price=Decimal("908.00")),
                          offer(merchant_id="farr", price=Decimal("950.00")),
                          offer(merchant_id="bordeaux-index", price=Decimal("977.00"))])
    [evidence] = r.bids
    assert evidence.offer.price == Decimal("908.00")
    assert evidence.variance_vs_reference == (Decimal("908") - Decimal("977")) / Decimal("977")


def test_a_last_trade_is_surfaced_as_corroboration_with_its_date():
    """"The strongest single number on the page" — shown, with the date
    money actually changed hands, never priced from."""
    r = benchmark(line(), [last_trade(price=Decimal("904.00"), captured_at=AS_OF),
                          offer(merchant_id="farr", price=Decimal("950.00")),
                          offer(merchant_id="bordeaux-index", price=Decimal("977.00"))])
    [evidence] = r.last_trades
    assert evidence.offer.price == Decimal("904.00")
    assert evidence.offer.captured_at == AS_OF
    assert all(o.price_kind is not PriceKind.LAST_TRADE for o in r.merchant_bests)


def test_a_stale_last_trade_is_still_shown_not_dropped():
    """BI's own Krug GC 1x150cl last traded January 2025 — long outside the
    14-day ASK freshness window. A last trade is a historical fact, not a
    live ask: freshness does not screen it out, the date simply says so."""
    old_trade = last_trade(price=Decimal("900.00"), captured_at=AS_OF - timedelta(days=400))
    r = benchmark(line(), [old_trade, offer(merchant_id="farr", price=Decimal("950.00"))])
    assert len(r.last_trades) == 1
    assert r.last_trades[0].offer.captured_at == AS_OF - timedelta(days=400)


def test_a_stale_bid_is_not_corroboration():
    """Unlike a last trade, a bid is a currently-standing order — the same
    freshness rule as an ask applies, because an old bid may no longer
    stand."""
    stale_bid = bid(price=Decimal("908.00"), captured_at=AS_OF - timedelta(days=30))
    r = benchmark(line(), [stale_bid, offer(merchant_id="farr", price=Decimal("950.00"))])
    assert r.bids == []


def test_two_sided_wide_spread_is_flagged_but_never_gates():
    """Krug 162e: bid £660, offer £1,596, same merchant, same 6x75cl listing
    — a 142% spread. Flagged so an operator never reads the bid as
    confirming the offer, and never a review flag: nothing here was ever
    priced from either figure."""
    r = benchmark(line(), [bid(price=Decimal("660.00")),
                          offer(merchant_id="bordeaux-index", price=Decimal("1596.00")),
                          offer(merchant_id="farr", price=Decimal("1600.00"))])
    assert Flag.TWO_SIDED_WIDE_SPREAD in r.flags
    assert Flag.TWO_SIDED_WIDE_SPREAD not in REVIEW_FLAGS
    assert r.state is State.READY          # two asks, no other flag — never gates


def test_a_tight_two_sided_market_is_not_flagged():
    """Krug 167e: bid £908, offer £977 from the same merchant — a 7.6%
    spread, a real liquid market, well under the threshold."""
    assert (Decimal("977") - Decimal("908")) / Decimal("908") < Decimal(str(WIDE_SPREAD_THRESHOLD))
    r = benchmark(line(), [bid(price=Decimal("908.00")),
                          offer(merchant_id="bordeaux-index", price=Decimal("977.00"))])
    assert Flag.TWO_SIDED_WIDE_SPREAD not in r.flags


@pytest.mark.parametrize("kw", [
    dict(vintage=2012), dict(pack_size=6, price=Decimal("5448.00")), dict(bottle_ml=1500),
    dict(currency="EUR"), dict(duty_status=DutyStatus.DUTY_PAID),
])
def test_a_bid_for_something_else_is_not_corroboration(kw):
    r = benchmark(line(), [bid(**kw), offer(merchant_id="farr")])
    assert r.bids == []


def test_fine_and_rare_counts_as_one_merchant_however_many_it_polled():
    """merchantCount is context. Depth counts merchants we have an offer from,
    not merchants a brokerage says it polled — 8 of them behind one indication
    is still one FINE+RARE, and an indication is not an offer at all."""
    c = frw_candidate("2011 Chambertin")
    assert c.offer.raw["market"]["merchantCount"] == 8
    r = benchmark(line(vintage=2011), [
        replace(c.offer, wine_id=WINE, bottle_ml=750, pack_size=1, captured_at=AS_OF),
        offer(merchant_id="farr", price=Decimal("1800.00")),
    ])
    assert r.comp_count == 1                      # Farr only
    assert Flag.ONE_COMP in r.flags
    assert len(r.indications) == 1


def test_fine_and_rare_publishes_an_indication_not_an_ask():
    c = frw_candidate("2009 Charmes Chambertin")
    assert c.offer.price_kind is PriceKind.INDICATION
    assert c.offer.price == Decimal("860")
    assert c.offer.is_buyable is False and c.offer.offered_units == 0
    assert c.offer.duty_status is DutyStatus.UNKNOWN     # nobody has said IB or DP
    assert c.offer.stock_type is StockType.BROKERED
    assert (c.producer_text, c.cuvee_text) == ("Domaine Armand Rousseau", "Charmes Chambertin")


def test_fine_and_rare_assortment_case_is_a_mixed_lot():
    """FINE+RARE writes 'Assortment', never 'mixed': a pattern looking only for
    'mixed' ingests a twelve-bottle DRC assortment as one wine."""
    out = FineAndRareAdapter().normalise(FRW["2002 DRC Assortment (2xEZ, 2xGDE, 3xLT, 1xRI"
                                             ", 1xRC, 3xRSV)"], captured_at=AS_OF)
    assert out.reason is Reject.MIXED_LOT


@pytest.mark.parametrize("name", ["2016 Assorted Case Bordeaux", "NV Trimbach Mixed Case",
                                  "2002 DRC Assortment (2xEZ)"])
def test_mixed_lot_matches_assort_and_assortment(name):
    product = {"url": "u", "product": {"_id": "1", "name": name,
                                       "parent": {"name": name, "producer": {"name": "P"}}},
               "productMarketInfo": {"unitSize": "75", "unit": "cl",
                                     "unitPrice": {"amount": 100, "currencyCode": "GBP"}}}
    assert FineAndRareAdapter().normalise(product, captured_at=AS_OF).reason is Reject.MIXED_LOT


def test_a_product_with_no_published_indication_is_a_rejection():
    """Most of the back catalogue carries no market info at all."""
    product = {"url": "u", "product": {"_id": "1", "name": "1959 Charmes Chambertin",
                                       "parent": {"name": "Charmes Chambertin",
                                                  "producer": {"name": "Domaine Armand Rousseau"}}},
               "productMarketInfo": None}
    out = FineAndRareAdapter().normalise(product, captured_at=AS_OF)
    assert out.reason is Reject.NON_POSITIVE_PRICE and "no broking indication" in out.detail


def test_fine_and_rare_normalise_splits_the_edition_number_out_of_the_cuvee():
    """Same gap as the regular Bordeaux Index adapter: FINE+RARE's own
    normalise() never called split_release_code either, so a Krug edition
    indication would have resolved against the bare, trap-prone "Grande
    Cuvee" key rather than its own edition. Champagne sweep, 9 Oct 2026."""
    raw = {"url": "https://www.frw.co.uk/product/x/nv-krug-grande-cuvee-161eme-edition-krug",
           "product": {"_id": "id-1", "name": "NV Krug Grande Cuvee 161eme Edition",
                       "parent": {"name": "Grande Cuvee 161eme Edition",
                                 "producer": {"name": "Krug"}}},
           "productMarketInfo": {"unitSize": "75", "unit": "cl",
                                 "unitPrice": {"amount": 150, "currencyCode": "GBP"}}}
    c = FineAndRareAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(c, Candidate), c
    assert (c.producer_text, c.cuvee_text, c.release_code) == ("Krug", "Grande Cuvee", "161")


@pytest.mark.parametrize("size,unit,ml", [
    ("75", "cl", 750), ("150", "cl", 1500), ("1.5", "l", 1500), ("750", "ml", 750),
    ("75", None, None), ("", "cl", None),
])
def test_fine_and_rare_unit_parsing(size, unit, ml):
    assert parse_unit(size, unit) == ml


def test_fine_and_rare_product_urls_select_a_producer_and_vintage_exactly():
    """The URL ends /<vintage>-<wine>-<producer-slug>, so deep search selects
    rather than searches — and 2011 must not pick up 2011-something-else."""
    xml = "".join(f"<url><loc>{u}</loc></url>" for u in [
        "https://www.frw.co.uk/product/a/2011-charmes-chambertin-domaine-armand-rousseau",
        "https://www.frw.co.uk/product/b/2009-charmes-chambertin-domaine-armand-rousseau",
        "https://www.frw.co.uk/product/c/2011-chambertin-jacques-frederic-mugnier",
        "https://www.frw.co.uk/product/d/nv-trimbach-mixed-case-1989-2001-trimbach",
    ])
    assert product_urls(xml, "domaine-armand-rousseau", 2011) == [
        "https://www.frw.co.uk/product/a/2011-charmes-chambertin-domaine-armand-rousseau"]
    assert product_urls(xml, "trimbach", 1000) == [
        "https://www.frw.co.uk/product/d/nv-trimbach-mixed-case-1989-2001-trimbach"]
    assert product_urls(xml, "domaine-armand-rousseau", 2014) == []


def test_fine_and_rare_fetch_accepts_producer_slugs_from_by_slug():
    """app.worker.jobs._by_slug always calls adapter.fetch(slug, vintage,
    producer_slugs=...) for every TARGETED merchant using it, whether or not
    a union was wanted. FineAndRareAdapter.fetch() never declared that
    keyword, so every real (unpatched) collect_targeted call for fine-rare
    raised TypeError — undetected because every existing test replaces
    `fetch` outright rather than calling the real adapter through `_by_slug`.
    Found running the Champagne sweep live, 9 October 2026."""
    from app.worker.jobs import _by_slug
    calls = []

    class _Stub(FineAndRareAdapter):
        def fetch(self, producer_slug=None, vintage=None, *, producer_slugs=None):
            calls.append((producer_slug, vintage, producer_slugs))
            return []

    _by_slug(_Stub(), {"producer_slug": "krug"}, 1000)
    assert calls == [("krug", 1000, None)]
    calls.clear()
    _by_slug(_Stub(), {"producer_slugs": ["louis-roederer", "louis-roederer-et-philippe-starck"]}, 2006)
    assert calls == [(None, 2006, ["louis-roederer", "louis-roederer-et-philippe-starck"])]


def test_fine_and_rare_unions_two_slugs_for_one_producer():
    """FINE+RARE's own sitemap lists "louis-roederer" and "louis-roederer-et-
    philippe-starck" as two different producer slugs for one house (same
    pattern as Bordeaux Index's Pol Roger / Berry Bros. split) — a search
    that only tries one silently halves that producer's depth. `fetch()`
    itself is network-only (no injectable client, matching the rest of this
    adapter), so the union is exercised at the `product_urls` layer it
    unions over, one call per slug, same as `fetch`'s own loop does."""
    xml = "".join(f"<url><loc>{u}</loc></url>" for u in [
        "https://www.frw.co.uk/product/a/2006-cristal-louis-roederer",
        "https://www.frw.co.uk/product/b/2006-cristal-louis-roederer-et-philippe-starck",
    ])
    assert product_urls(xml, "louis-roederer", 2006) == [
        "https://www.frw.co.uk/product/a/2006-cristal-louis-roederer"]
    assert product_urls(xml, "louis-roederer-et-philippe-starck", 2006) == [
        "https://www.frw.co.uk/product/b/2006-cristal-louis-roederer-et-philippe-starck"]
    both = (product_urls(xml, "louis-roederer", 2006)
            + product_urls(xml, "louis-roederer-et-philippe-starck", 2006))
    assert len(both) == 2 and len(set(both)) == 2


def test_fine_and_rare_producer_index_is_the_deep_search_key():
    keys = parse_producer_index(
        "<url><loc>https://www.frw.co.uk/producer/612ec2800600000000000554/"
        "domaine-armand-rousseau</loc></url>")
    assert keys == {"domaine armand rousseau": "domaine-armand-rousseau"}
    assert wine_key("Domaine Armand Rousseau", "x").startswith(
        norm_producer("domaine armand rousseau"))


def test_an_indication_for_another_wine_of_the_same_producer_is_not_corroboration():
    """FINE+RARE lists every Rousseau grand cru at the same vintage and size.
    Charmes-Chambertin 2011 corroborates nothing about a Chambertin 2011 line:
    they are different wines at £590 and £1,750. The predicate requires the
    approved wine_id, whichever screen rejected the offer."""
    chambertin_line = line(wine_id="w-rousseau-chambertin")
    charmes = indication(wine_id="w-rousseau-charmes", price=Decimal("590.00"))
    r = benchmark(chambertin_line, [charmes,
                                    offer(wine_id="w-rousseau-chambertin",
                                          merchant_id="farr", price=Decimal("1800.00"))])
    assert r.indications == []
    assert [x.reason for x in r.rejections] == [Reject.WINE]


def test_the_indication_predicate_requires_every_part_of_the_format():
    """wine_id, vintage, bottle size and commercial unit, all four, or it is not
    corroboration of this line."""
    same = dict(wine_id=WINE, vintage=2011, bottle_ml=750, pack_size=1)
    assert benchmark(line(), [indication(**same)]).indications != []
    for field, wrong in [("wine_id", "w-somebody-else"), ("vintage", 2012),
                         ("bottle_ml", 1500), ("pack_size", 6)]:
        r = benchmark(line(), [indication(**{**same, field: wrong})])
        assert r.indications == [], field


# ---------------------------- Bordeaux Index: what a 404 means

def bi_client(pages: dict, index: str = None):
    """An httpx client that answers from `pages`: {path+query: (status, body)}."""
    import httpx

    default_index = "".join(
        f"<url><loc>https://bordeauxindex.com/fine-wine/producer/{slug}</loc></url>"
        for slug in ("domaine_armand_rousseau", "domaine_armand_rousseau_selection",
                     "chateau_haut-brion"))

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path + ("?" + str(request.url.query.decode()) if request.url.query else "")
        if request.url.path == "/filters.xml":
            return httpx.Response(200, text=index if index is not None else default_index)
        if request.url.path == "/currency-set/GBP":
            return httpx.Response(200, text="")
        status, body = pages.get(key, (404, ""))
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler),
                        base_url="https://bordeauxindex.com")


def bi_listing(title: str, price: str, code: str) -> str:
    return (f'<div class="wine-inbond"><h2 class="wine-name">{title}</h2>'
            f'<a class="livetrade" href="/livetrade/{code}"></a>'
            f'<div class="offer">Bottle (75cl) CONDITION Original Case STATUS In-Bond '
            f'You buy £{price} 2 Bottle(s) Available</div></div>')


def test_bordeaux_index_404_on_a_known_producer_is_an_empty_vintage_not_an_error():
    """Bordeaux Index 404s a producer page for a vintage it holds nothing in.
    That is a real, empty answer: the producer was searched and has nothing."""
    import app.adapters.bordeaux_index as bi
    bi._index_cache = None
    with bi_client({}) as client:
        rows = BordeauxIndexAdapter().fetch("domaine_armand_rousseau", 2011, client=client)
    assert rows == []


def test_bordeaux_index_404_on_an_unknown_slug_is_an_error_not_an_empty_market():
    """The rehearsal searched `domaine-armand-rousseau`, got a 404, and recorded
    a merchant with nothing to offer. The slug form is underscored, and a slug
    Bordeaux Index does not publish is our mistake — never a quiet no-market."""
    import app.adapters.bordeaux_index as bi
    bi._index_cache = None
    with bi_client({}) as client:
        with pytest.raises(bi.UnknownProducerSlug, match="domaine-armand-rousseau"):
            BordeauxIndexAdapter().fetch("domaine-armand-rousseau", 2011, client=client)


def test_bordeaux_index_unions_a_producers_slugs_and_keeps_each_wine_once():
    """A producer published under two slugs is one producer. Searching only the
    first would halve its depth; counting a wine listed under both twice would
    invent depth that is not there."""
    import app.adapters.bordeaux_index as bi
    bi._index_cache = None
    pages = {
        "/fine-wine/all?producer=domaine_armand_rousseau&vintage=2011":
            (200, bi_listing("2011 Domaine Armand Rousseau, Chambertin Grand Cru", "3,300.00",
                             "rouc-2011")),
        "/fine-wine/all?producer=domaine_armand_rousseau_selection&vintage=2011":
            (200, bi_listing("2011 Domaine Armand Rousseau, Chambertin Grand Cru", "3,300.00",
                             "rouc-2011")
                  + bi_listing("2011 Domaine Armand Rousseau, Charmes-Chambertin Grand Cru",
                               "610.00", "roush-2011")),
    }
    with bi_client(pages) as client:
        rows = BordeauxIndexAdapter().fetch(
            producer_slugs=["domaine_armand_rousseau", "domaine_armand_rousseau_selection"],
            vintage=2011, client=client)
    assert len(rows) == 2
    assert sorted(r["code"] for r in rows) == ["rouc-2011", "roush-2011"]


# ------------------------------------- Lea & Sandeman: the live In Bond list
#
# Spec: docs/research/adapter-spec-pack.md §1. Fixture captured 23 September
# 2026 from /fine-wine.html?resultsPerPage=192 — 174 rows, one request.

LS_LIST = (Path(__file__).parent / "fixtures/lea-sandeman-list-2026-09-23.html").read_text()
LS_PRODUCT = (Path(__file__).parent / "fixtures/lea-sandeman-product-2026-09-23.html").read_text()
LS_ROWS = dedupe_rows(parse_rows(LS_LIST))


def ls_row(needle: str, cells_equal: dict | None = None) -> dict:
    """A live row by wine wording, narrowed by cell position where needed."""
    for row in LS_ROWS:
        cells = row["cells"]
        if needle.lower() in cells[3].lower() and all(
                cells[i] == v for i, v in (cells_equal or {}).items()):
            return row
    raise AssertionError(f"no live row for {needle!r} {cells_equal}")


def ls_offer(needle: str, cells_equal: dict | None = None) -> Offer:
    out = LeaSandemanAdapter().normalise(ls_row(needle, cells_equal), captured_at=AS_OF)
    assert isinstance(out, Candidate), out
    return out.offer


def test_lea_sandeman_maps_price_by_row_position_not_header():
    """Thirteen cells, twelve headers: the stock code is unlabelled, so mapping
    by header name reads `inc VAT` as the price. 2021 Henri Germain Morgeot
    6x75 IB (stock 44599) is £435.00 ex VAT; the header-shifted read gives
    £542.74, 24.8% over."""
    offer = ls_offer("Morgeot Domaine Henri Germain")
    assert offer.price == Decimal("435.00")
    assert offer.price != Decimal("542.74")
    assert offer.raw["inc_vat"] == "542.74"        # kept, never priced from
    assert (offer.pack_size, offer.bottle_ml) == (6, 750)
    assert offer.raw["stock_code"] == "44599"


def test_lea_sandeman_duty_status_is_per_row():
    """2020 Volnay 1er Roncerets 6x75 appears under one stock code (41846) as
    DP £502.91 and IB £485.00. The DP row is not a cheaper version of the IB
    one, and only the IB row may become an In Bond offer."""
    in_bond = ls_offer("Roncerets", {2: "2020", 9: "IB"})
    duty_paid = ls_offer("Roncerets", {2: "2020", 9: "DP"})
    assert (in_bond.price, in_bond.duty_status) == (Decimal("485.00"), DutyStatus.IN_BOND)
    assert (duty_paid.price, duty_paid.duty_status) == (Decimal("502.91"), DutyStatus.DUTY_PAID)
    assert in_bond.raw["stock_code"] == duty_paid.raw["stock_code"] == "41846"
    assert in_bond.offer_id != duty_paid.offer_id


@pytest.mark.parametrize("pack,region,expected", [
    ("1 x Jero", "Burgundy", (1, 3000)),
    ("1 x Jero", "Champagne", (1, 3000)),
    ("1 x Jero", "Bordeaux", (1, 4500)),
    ("1 x Jero", "", None),                        # no region, no answer
    ("1 x Jero", "Tuscany", None),
    ("1 x Neb", "Bordeaux", None),                 # unconfirmed until a live row says
    ("6 x 75cl", "Burgundy", (6, 750)),
    ("1 x Mags", "Tuscany", (1, 1500)),
    ("1 x DM", "Tuscany", (1, 3000)),
])
def test_lea_sandeman_jeroboam_depends_on_region(pack, region, expected):
    """L&S writes `N x Jero` for a 3000ml Burgundy jeroboam and a 4500ml
    Bordeaux one. A 50% size error either way; with no region there is no
    answer, so the row is rejected rather than assumed."""
    assert parse_pack(pack, region) == expected


def test_lea_sandeman_product_page_is_never_collected():
    """Product pages quote duty-paid retail per bottle, not the In Bond trade
    price: £68.95 a bottle against £675.00 for 6x75cl on the list. The page
    yields no list rows, and a record that is not a list row is refused."""
    assert parse_rows(LS_PRODUCT) == []
    out = LeaSandemanAdapter().normalise({"source_url": "https://www.leaandsandeman.co.uk/wine/x"},
                                         captured_at=AS_OF)
    assert out.reason is Reject.ROW_UNREADABLE and "not a list row" in out.detail


def test_lea_sandeman_duplicate_rows_are_one_listing():
    """2021 Germain Morgeot appears twice, identical, under stock code 44599.
    One listing — but the Roncerets pair above differs in duty status and is
    two."""
    raw = parse_rows(LS_LIST)
    morgeot = [r for r in raw if "44599" == r["cells"][4]]
    assert len(morgeot) == 2 and morgeot[0]["cells"] == morgeot[1]["cells"]
    assert len([r for r in LS_ROWS if r["cells"][4] == "44599"]) == 1
    assert len([r for r in LS_ROWS if r["cells"][4] == "41846"]) == 2   # IB and DP both kept


def test_lea_sandeman_mazoyeres_labelled_as_charmes_goes_to_review():
    """"CHARMES CHAMBERTIN 'Aux Mazoyeres' Grand Cru Virgile Lignier-Michelot"
    is a real L&S row. Mazoyeres may be sold as Charmes but they are not the
    same wine, and this title must not auto-resolve to either: no match, so the
    line waits for a person."""
    offer_row = ls_row("Mazoy")
    out = LeaSandemanAdapter().normalise(offer_row, captured_at=AS_OF)
    registry = Registry([
        CanonicalWine("charmes", "Virgile Lignier-Michelot", "Charmes-Chambertin Grand Cru"),
        CanonicalWine("mazoyeres", "Virgile Lignier-Michelot", "Mazoyeres-Chambertin Grand Cru"),
    ])
    assert registry.resolve_candidate(out.producer_text, out.cuvee_text) is None


def test_lea_sandeman_courcel_grand_clos_is_not_les_grands_epenots():
    """Courcel's Grand Clos des Epenots is a monopole; Les Grands Epenots is a
    different parcel. Both answer to [courcel, epenots], and L&S lists the
    Grand Clos while Lay & Wheeler Trading had Les Grands Epenots for 2019."""
    grand_clos = "domaine de courcel|pommard 1er cru grand clos des epenots"
    les_grands = "domaine de courcel|pommard 1er cru les grands epenots"
    assert (grand_clos, les_grands) in STRUCTURAL_EXCLUSIONS
    registry = Registry([
        CanonicalWine("grand-clos", "Domaine de Courcel", "Pommard 1er Cru Grand Clos des Epenots"),
        CanonicalWine("les-grands", "Domaine de Courcel", "Pommard 1er Cru Les Grands Epenots"),
    ])
    assert registry.resolve("Domaine de Courcel", "Pommard 1er Cru Grand Clos des Epenots") \
        == "grand-clos"
    assert registry.resolve("Domaine de Courcel", "Pommard 1er Cru Les Grands Epenots") \
        == "les-grands"
    # And the live L&S row is the Grand Clos, not the other.
    assert "Grand Clos des Épenots" in ls_row("Grand Clos des Épenots")["cells"][3]


# --------------------- producers that must never be read as one another
#
# Every pair was seen on live merchant data in the control-set sweep
# (docs/research/burgundy-control-set-report.md, 21 and 23 September 2026).

@pytest.mark.parametrize("one,other", PRODUCER_EXCLUSIONS,
                         ids=lambda p: p.replace("domaine ", "").replace(" ", "-"))
def test_confusable_producers_never_collapse(one, other):
    """One grower's wine priced off another's is the catastrophic case, and
    these names are close enough that a merchant sweep put them side by side."""
    assert one != other
    assert producers_excluded(one, other) and producers_excluded(other, one)
    registry = Registry([CanonicalWine("a", one, "Bourgogne Rouge"),
                         CanonicalWine("b", other, "Bourgogne Rouge")])
    assert registry.resolve(one, "Bourgogne Rouge") == "a"
    assert registry.resolve(other, "Bourgogne Rouge") == "b"


def test_the_same_climat_from_two_growers_is_two_wines():
    """Combe d'Orveau is made by Anne Gros and by Faiveley. The cuvee alone
    names neither: identity is producer and cuvee together."""
    registry = Registry([
        CanonicalWine("gros", "Domaine Anne Gros", "Chambolle-Musigny 1er Cru La Combe d'Orveau"),
        CanonicalWine("faiveley", "Domaine Faiveley",
                      "Chambolle-Musigny 1er Cru La Combe d'Orveau"),
    ])
    assert registry.resolve("Domaine Anne Gros", "Chambolle-Musigny 1er Cru La Combe d'Orveau") \
        == "gros"
    assert registry.resolve("Domaine Faiveley", "Chambolle-Musigny 1er Cru La Combe d'Orveau") \
        == "faiveley"
    assert registry.resolve_candidate("", "Chambolle-Musigny 1er Cru La Combe d'Orveau") is None


# ------------------------------ Lay & Wheeler Trading: the Store API
#
# Spec: docs/research/adapter-spec-pack.md §2. Fixture captured 23 September
# 2026 from the WooCommerce Store API, Crawl-delay 10 honoured.

LW = json.loads((Path(__file__).parent / "fixtures/lay-wheeler-trading-2026-09-23.json").read_text())
LW_PRODUCTS = [p for r in LW["responses"] for p in r["products"]]


def lw_product(needle: str) -> dict:
    for product in LW_PRODUCTS:
        if needle.lower() in product["name"].lower():
            return product
    raise AssertionError(f"no live product for {needle!r}")


def lw_offer(needle: str) -> Candidate:
    out = LayWheelerTradingAdapter().normalise(lw_product(needle), captured_at=AS_OF)
    assert isinstance(out, Candidate), out
    return out


def test_lw_trading_normalise_splits_the_edition_number_out_of_the_cuvee():
    """Same gap as the other two targeted-search adapters: normalise() never
    called split_release_code either. Built from a real product record with
    the name/producer/vintage attribute overridden to a Krug edition, same
    shape L&W actually publishes. Champagne sweep, 9 Oct 2026."""
    import copy
    product = copy.deepcopy(lw_product("Combe au Moine"))
    product["name"] = "NV Krug, Grande Cuvee 161eme Edition 6x75cl"
    for attr in product["attributes"]:
        if attr["name"] == "Producer":
            attr["terms"] = [{"id": 1, "name": "Krug", "slug": "krug"}]
        elif attr["name"] == "Vintage":
            attr["terms"] = [{"id": 2, "name": "NV", "slug": "nv"}]
    c = LayWheelerTradingAdapter().normalise(product, captured_at=AS_OF)
    assert isinstance(c, Candidate), c
    assert (c.producer_text, c.cuvee_text, c.release_code) == ("Krug", "Grande Cuvee", "161")


def test_lw_trading_price_is_minor_units():
    """`prices.price` is "80000" with currency_minor_unit 2 — £800.00. Read as
    pounds it is a 100x error, and one such row is the Floor for every line it
    touches."""
    offer = lw_offer("2009 Domaine Faiveley, Gevrey-Chambertin Premier Cru, Combe au Moine").offer
    assert offer.price == Decimal("800.00")
    assert lw_product("Combe au Moine")["prices"]["price"] == "80000"
    assert parse_price({"price": "141400", "currency_minor_unit": 2}) == Decimal("1414.00")
    assert parse_price({"price": "141400", "currency_minor_unit": 0}) == Decimal("141400")


def test_lw_trading_paginates_past_100():
    """Faiveley returns exactly 100 of 185 on page 1 (X-WP-TotalPages: 2). A
    single page looks like a whole answer and the missing half is silent."""
    import httpx

    pages = {1: [{"name": f"2019 Domaine Faiveley, wine {i} 6x75cl"} for i in range(PER_PAGE)],
             2: [{"name": "2019 Domaine Faiveley, the hundred-and-first 6x75cl"}]}
    asked = []

    def handler(request):
        page = int(dict(request.url.params)["page"])
        asked.append(page)
        return httpx.Response(200, json=pages[page],
                              headers={"X-WP-Total": "101", "X-WP-TotalPages": "2"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = LayWheelerTradingAdapter().fetch("Faiveley", client=client, sleep=lambda s: None)
    assert asked == [1, 2]
    assert len(rows) == PER_PAGE + 1
    assert LW["responses"][0]["headers"]["x-wp-totalpages"] == "2"


def test_lw_trading_two_sku_schemes_identity_from_attributes():
    """Both schemes are live. Identity and format come from the attributes; the
    SKU is never parsed for a price, a duty status or a size, and the LWIN in
    one of them is a proposal the resolver must see the name agree with."""
    lwin_sku = lw_offer("2019 Domaine de Courcel, Pommard Premier Cru, Les Grands Epenots")
    hub_sku = lw_offer("2020 Bernard Dugat-Py, Gevrey-Chambertin, Coeur du Roy")
    assert lwin_sku.offer.raw["sku"].startswith("LXSIB") and lwin_sku.lwin7 == "1027606"
    assert lwin_from_sku("LXSIB102760620190600750") == "1027606"
    assert lwin_from_sku("hub-VS10135589-6-IB-13287647") is None
    assert hub_sku.offer.raw["sku"].startswith("hub-") and hub_sku.lwin7 is None
    # "IB" inside the hub SKU is not where the duty status comes from.
    assert "-IB-" in hub_sku.offer.raw["sku"]
    assert hub_sku.offer.duty_status is DutyStatus.IN_BOND
    assert attributes(lw_product("Coeur du Roy"))["Duty Status"] == "In Bond"
    # And a LWIN out of a SKU never resolves on its own (decision 0006).
    registry = Registry([CanonicalWine("grands-epenots", "Domaine de Courcel",
                                       "Pommard 1er Cru Les Grands Epenots", "1027606")])
    assert registry.resolve_candidate("Someone Else", "A Different Wine", lwin_sku.lwin7) is None


def test_lw_trading_courcel_les_grands_epenots_rejected_for_grand_clos():
    """L&W has Les Grands Epenots for 2019; Lea & Sandeman lists the Grand Clos
    des Epenots monopole. Both answer to [courcel, epenots] and they are two
    parcels: a false comp in either direction."""
    candidate = lw_offer("2019 Domaine de Courcel, Pommard Premier Cru, Les Grands Epenots")
    registry = Registry([
        CanonicalWine("grand-clos", "Domaine de Courcel", "Pommard 1er Cru Grand Clos des Epenots"),
    ])
    assert registry.resolve_candidate(candidate.producer_text, candidate.cuvee_text) is None
    assert ("domaine de courcel|pommard 1er cru grand clos des epenots",
            "domaine de courcel|pommard 1er cru les grands epenots") in STRUCTURAL_EXCLUSIONS


def test_lw_trading_coeur_du_roy_is_one_wine_under_two_spellings():
    """L&W lists Dugat-Py "Coeur du Roy Tres Vieilles Vignes" 2020 at £765 and
    a seller writes "Coeur de Roy". L&W itself spells the same cuvee both ways
    across vintages, and sometimes prefixes "Cuvee". An operator has ruled them
    one wine (23 September 2026), so they are one wine by approved alias — not
    by a rule that du and de are interchangeable, which would also merge wines
    that are genuinely different. Each merchant's wording is kept verbatim.

    Left unmerged, the 2020 would price against nothing: £765 is the only UK
    offer of that vintage in the sweep, and the line would read NO_MARKET."""
    candidate = lw_offer("2020 Bernard Dugat-Py, Gevrey-Chambertin, Coeur du Roy")
    assert candidate.offer.price == Decimal("765.00")

    canonical = CanonicalWine("coeur-de-roy", "Bernard Dugat-Py",
                              "Gevrey-Chambertin Coeur de Roy Tres Vieilles Vignes")
    bare = Registry([canonical])
    assert bare.resolve_candidate(candidate.producer_text, candidate.cuvee_text) is None

    aliases = [
        Alias(key=wine_key("Bernard Dugat-Py",
                           "Gevrey-Chambertin Coeur du Roy Tres Vieilles Vignes"),
              wine_id="coeur-de-roy", approved_by="operator", approved_at="2026-09-23",
              note="Dugat-Py spells this cuvee du Roy and de Roy; one wine"),
        Alias(key=wine_key("Bernard Dugat-Py",
                           "Gevrey-Chambertin Cuvee Coeur de Roy Tres Vieilles Vignes"),
              wine_id="coeur-de-roy", approved_by="operator", approved_at="2026-09-23",
              note="the same cuvee with L&W's Cuvee prefix"),
    ]
    registry = Registry([canonical], aliases)
    resolved = {c.cuvee_text: registry.resolve_candidate(c.producer_text, c.cuvee_text)
                for c in (lw_offer(name) for name in [
                    "2020 Bernard Dugat-Py, Gevrey-Chambertin, Coeur du Roy",
                    "2004 Bernard Dugat-Py, Gevrey-Chambertin, Coeur de Roy",
                    "2022 Dugat-Py, Gevrey-Chambertin, Cuvee Coeur de Roy"])}
    assert set(resolved.values()) == {"coeur-de-roy"}
    # Three merchant spellings, one wine, and every spelling still on the record.
    assert sorted(resolved) == [
        "Gevrey-Chambertin, Coeur de Roy Tres Vieilles Vignes",
        "Gevrey-Chambertin, Coeur du Roy Tres Vieilles Vignes",
        "Gevrey-Chambertin, Cuvee Coeur de Roy Tres Vieilles Vignes",
    ]
    assert lw_product("Coeur du Roy")["name"] == \
        "2020 Bernard Dugat-Py, Gevrey-Chambertin, Coeur du Roy Tres Vieilles Vignes 6x75cl"

    # The merge is this domaine's, by name. It is not a licence to read one
    # Dugat as another: Claude Dugat and Dugat-Py stay excluded.
    assert producers_excluded("Domaine Claude Dugat", "Domaine Dugat-Py")


def test_lw_trading_vintage_and_pack_never_enter_the_identity_key():
    """The Store API writes the whole listing into `name`. Handed over whole,
    "2020 ... 6x75cl" and "2022 ... 12x75cl" are two different wines and neither
    can ever match the canonical table. The vintage and the format come from the
    attributes; the name contributes the cuvee only."""
    for needle in ["2020 Bernard Dugat-Py, Gevrey-Chambertin, Coeur du Roy",
                   "2018 Dugat-Py, Gevrey-Chambertin, Cuvee Coeur de Roy"]:
        candidate = lw_offer(needle)
        assert candidate.producer_text == "Bernard Dugat-py"
        assert not re.search(r"\d{4}|x75cl", candidate.cuvee_text)
        assert candidate.offer.raw["name"].startswith(needle)   # kept verbatim
    assert cuvee_from_name("2019 Domaine Faiveley, Mazis-Chambertin Grand Cru 6x75cl",
                           "Domaine Faiveley") == "Mazis-Chambertin Grand Cru"
    # A cuvee that happens to lead with the producer's name is not stripped
    # twice: only a segment that IS the row's producer goes.
    assert cuvee_from_name("2019 Domaine Faiveley, Faiveley Selection 6x75cl",
                           "Domaine Faiveley") == "Faiveley Selection"


# ------------------------------------- robots.txt as merchants actually write it

UA = "UKFineWinePricer/1.0 (+https://example.invalid/contact)"

LEA_SANDEMAN_ROBOTS = """User-agent: *
Disallow: /details.html
Disallow: /search.html?*
Disallow: /*page=*
Disallow: /*term=*
Disallow: /*producer=*
"""

LW_TRADING_ROBOTS = """User-agent: *
Disallow: /cart/
Disallow: /*?wc-ajax
Disallow: /*blackhole
Crawl-delay: 10

User-agent: Scrapy
User-agent: node-fetch
User-agent: FirecrawlAgent
Disallow: /
"""


@pytest.mark.parametrize("url,is_allowed", [
    ("https://www.leaandsandeman.co.uk/fine-wine.html?resultsPerPage=192", True),
    ("https://www.leaandsandeman.co.uk/fine-wine.html?page=2", False),
    ("https://www.leaandsandeman.co.uk/fine-wine.html?category=burgundy&page=3", False),
    ("https://www.leaandsandeman.co.uk/search.html?term=rousseau", False),
    ("https://www.leaandsandeman.co.uk/details.html", False),
    ("https://www.leaandsandeman.co.uk/wine/2013-CHAMBERTIN.html", True),
])
def test_robots_wildcards_are_honoured(url, is_allowed):
    """urllib.robotparser has no wildcard support: it reads `Disallow: /*page=*`
    as a literal prefix, matches nothing, and reports every paginated URL as
    allowed. Under-blocking means fetching what a merchant asked us not to."""
    assert allowed(LEA_SANDEMAN_ROBOTS, url, UA) is is_allowed


def test_robots_crawl_delay_is_read():
    """Lay & Wheeler Trading asks for ten seconds. Ignoring it is not politeness
    with a user-agent attached."""
    assert crawl_delay(LW_TRADING_ROBOTS, UA) == 10.0
    assert crawl_delay(LEA_SANDEMAN_ROBOTS, UA) == 0.0


def test_robots_blocklists_apply_to_the_crawler_they_name():
    """The blocked group names Scrapy, node-fetch and FirecrawlAgent. We are
    none of them, and we do not borrow their names to find out."""
    assert allowed(LW_TRADING_ROBOTS, "https://laywheelertrading.com/wp-json/wc/store/v1/products",
                   UA) is True
    for blocked in ("Scrapy/2.11", "node-fetch/1.0", "FirecrawlAgent"):
        assert allowed(LW_TRADING_ROBOTS, "https://laywheelertrading.com/", blocked) is False


def test_robots_blackhole_traps_are_never_followed():
    assert allowed(LW_TRADING_ROBOTS, "https://laywheelertrading.com/blackhole/abc", UA) is False
    assert allowed(LW_TRADING_ROBOTS, "https://laywheelertrading.com/cart/", UA) is False


def test_robots_allow_beats_a_shorter_disallow():
    """Longest match wins, Allow wins a tie: the rule merchants rely on when
    they carve one path out of a blocked tree."""
    text = "User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n"
    assert allowed(text, "https://x/wp-admin/", UA) is False
    assert allowed(text, "https://x/wp-admin/admin-ajax.php", UA) is True


# ------------------------- brokered stock, and two merchants quoting one price
#
# Control set L68, 21 September 2026 (decision 0014).

def brokered(**kw) -> Offer:
    return offer(stock_type=StockType.BROKERED, **kw)


def test_l68_goedhuis_brokered_offer_stays_in_the_benchmark():
    """Goedhuis brokes (SKU -BR-) at £1,300 against Lea & Sandeman at £1,325.
    Dropping brokered offers would delete the cheaper of the only two UK prices
    on this line: the Floor would rise by £25 and the line would lose its
    second merchant and become ONE_COMP. A brokered offer is a real offer."""
    goedhuis = brokered(offer_id="gw:l68", merchant_id="goedhuis", merchant="Goedhuis",
                        price=Decimal("1300.00"))
    lea = offer(offer_id="ls:l68", merchant_id="lea-sandeman", merchant="Lea & Sandeman",
                price=Decimal("1325.00"))

    r = benchmark(line(), [goedhuis, lea])
    assert r.comp_count == 2 and r.state is State.READY
    assert r.uk_floor == Decimal("1300.00") and r.uk_reference == Decimal("1325.00")
    assert [o.merchant_id for o in r.merchant_bests] == ["goedhuis", "lea-sandeman"]
    assert price_coincidences(r.merchant_bests) == []


def test_l68_identical_price_is_an_operator_note_never_a_gate():
    """Goedhuis (brokered) £1,300.00 and Lea & Sandeman £1,300.00, to the penny:
    two listings, possibly one parcel. The operator is told. Nothing else
    changes — the comp stays, depth stays 2, the Reference stays £1,300, and
    the line stays READY."""
    goedhuis = brokered(offer_id="gw:l68", merchant_id="goedhuis", merchant="Goedhuis",
                        price=Decimal("1300.00"))
    lea = offer(offer_id="ls:l68", merchant_id="lea-sandeman", merchant="Lea & Sandeman",
                price=Decimal("1300.00"))

    r = benchmark(line(), [goedhuis, lea])
    [coincidence] = price_coincidences(r.merchant_bests)
    assert coincidence.merchants == ["Goedhuis", "Lea & Sandeman"]
    assert coincidence.price == Decimal("1300.00") and coincidence.any_brokered is True
    assert "may be the same parcel" in coincidence.note

    assert r.comp_count == 2 and r.state is State.READY
    assert r.uk_floor == r.uk_reference == Decimal("1300.00")
    assert SAME_PRICE_AS_ANOTHER_MERCHANT not in {f.value for f in REVIEW_FLAGS}
    assert not any(f.value == SAME_PRICE_AS_ANOTHER_MERCHANT for f in r.flags)


def test_a_penny_apart_is_two_merchants_not_one_parcel():
    """£1,300.00 against £1,299.99 is keen pricing, not a shared parcel. Only
    equality to the penny is reported, or the note becomes noise and is ignored
    on the day it matters."""
    assert price_coincidences([
        brokered(offer_id="a", merchant_id="goedhuis", merchant="Goedhuis",
                 price=Decimal("1300.00")),
        offer(offer_id="b", merchant_id="lea-sandeman", merchant="Lea & Sandeman",
              price=Decimal("1299.99")),
    ]) == []


def test_one_merchant_listing_twice_is_not_a_parcel_coincidence():
    """Bordeaux Index lists the same case twice at one price (control set §7).
    That is a duplicate listing, which merchant-best already collapses — it is
    not two merchants and must never read as one parcel seen by two."""
    twice = [offer(offer_id="bi:1", merchant_id="bordeaux-index", merchant="Bordeaux Index",
                   price=Decimal("1300.00")),
             offer(offer_id="bi:2", merchant_id="bordeaux-index", merchant="Bordeaux Index",
                   price=Decimal("1300.00"))]
    assert price_coincidences(twice) == []

    r = benchmark(line(), twice)
    assert r.comp_count == 1 and r.duplicate_listings == 1
    assert price_coincidences(r.merchant_bests) == []


# ------------------------------- non-vintage release-code identity (decision 0019)
#
# A live cellar: 41 Krug lines across Grande Cuvee 156e to 169e. Each edition
# trades at its own level, and LWIN's NV convention (vintage 1000) collapses
# them into one product.

KRUG = "Krug"


def test_grande_cuvee_156_and_169_are_different_wines():
    """Two editions of the same NV cuvee must never share a wine_id: a 156e
    offer priced against 169e evidence (or the reverse) is not a comparable,
    it is a different product wearing the same name."""
    registry = Registry([
        CanonicalWine("krug-156", KRUG, "Grande Cuvee", release_code="156"),
        CanonicalWine("krug-169", KRUG, "Grande Cuvee", release_code="169"),
    ])
    assert registry.resolve(KRUG, "Grande Cuvee", release_code="156") == "krug-156"
    assert registry.resolve(KRUG, "Grande Cuvee", release_code="169") == "krug-169"
    assert registry.resolve(KRUG, "Grande Cuvee", release_code="156") != \
        registry.resolve(KRUG, "Grande Cuvee", release_code="169")
    assert wine_key(KRUG, "Grande Cuvee", "156") != wine_key(KRUG, "Grande Cuvee", "169")


def test_a_codeless_candidate_never_resolves_to_a_specific_edition():
    """A seller writes "Krug Grande Cuvee" with no edition number — the private
    cellar owner does not know or state one. Fail closed to the identity
    queue, never a guess at which of fourteen editions it is."""
    registry = Registry([
        CanonicalWine("krug-156", KRUG, "Grande Cuvee", release_code="156"),
        CanonicalWine("krug-169", KRUG, "Grande Cuvee", release_code="169"),
    ])
    assert registry.resolve(KRUG, "Grande Cuvee") is None
    assert registry.resolve(KRUG, "Grande Cuvee", release_code=None) is None
    # The combined-field path (Goedhuis-style) is equally fail-closed.
    assert registry.resolve_candidate("", "Krug Grande Cuvee") is None


def test_a_wine_with_no_edition_at_all_is_unaffected():
    """Most NV wines never need a code. A bare producer|cuvee key still
    resolves exactly as it always has when no edition is registered for it."""
    registry = Registry([CanonicalWine("nv-plain", "Eric Rodez", "Cuvee des Crayeres")])
    assert registry.resolve("Eric Rodez", "Cuvee des Crayeres") == "nv-plain"


@pytest.mark.parametrize("text,remainder,code", [
    ("Grande Cuvee 156eme Edition", "Grande Cuvee", "156"),
    ("Grande Cuvée 156ème Édition", "Grande Cuvée", "156"),
    ("Grande Cuvee 169e", "Grande Cuvee", "169"),
    ("Grande Cuvee 156th Edition", "Grande Cuvee", "156"),
    ("156th", "", "156"),
])
def test_the_live_spellings_of_an_edition_number_all_parse(text, remainder, code):
    """156e, 156eme/156ème and 156th are the live spellings across merchants
    (adapter-spec-pack). All three resolve to the same code."""
    got_remainder, got_code = split_release_code(text)
    assert (got_remainder, got_code) == (remainder, code)


def test_a_bordeaux_classification_number_is_never_mistaken_for_an_edition():
    """'3eme Cru Classe' is a classification, not an edition: Bordeaux writes
    its growth number mid-name, with more words after it, where Krug's edition
    is always the last thing in the name. Splitting on the classification would
    invent an identity split nobody approved, and silently rename every third
    growth's cuvee to 'Cru Classe'."""
    text = "Chateau Exemple, 3eme Cru Classe"
    assert split_release_code(text) == (text, None)


def test_henri_giraud_and_bollinger_codes_need_no_split_at_all():
    """MV13 and PN VZ16 are each a complete, distinct cuvee name with no
    shared base to split from — unlike Krug's "Grande Cuvee", there is nothing
    here for split_release_code to find, and nothing here needs it: two
    different code strings are already two different wine_keys."""
    assert split_release_code("MV13") == ("MV13", None)
    assert split_release_code("PN VZ16") == ("PN VZ16", None)
    assert wine_key("Henri Giraud", "MV13") != wine_key("Henri Giraud", "MV15")
    assert wine_key("Bollinger", "PN VZ16") != wine_key("Bollinger", "PN VZ15")


def test_release_code_is_normalised_like_every_other_identity_field():
    """Case and whitespace in the code itself do not create a false split —
    the same normalisation wine_key already applies to producer and cuvee."""
    assert wine_key(KRUG, "Grande Cuvee", "156") == wine_key(KRUG, "grande cuvee", "156")
    assert wine_key("Henri Giraud", "MV13") == wine_key("Henri Giraud", "mv13")


def test_combined_field_resolution_still_finds_an_edition():
    """Goedhuis packs producer and cuvee into one string with no separator.
    The combined-field path must still find a release-coded wine when the
    whole merchant string names one — not just fail safely, but succeed."""
    registry = Registry([
        CanonicalWine("krug-156", KRUG, "Grande Cuvee", release_code="156"),
        CanonicalWine("krug-169", KRUG, "Grande Cuvee", release_code="169"),
    ])
    assert registry.resolve_candidate("", "Krug Grande Cuvee", release_code="156") == "krug-156"
    assert registry.resolve_candidate("", "Krug Grande Cuvee", release_code="169") == "krug-169"
    # And still fail-closed with no code at all, through the same path.
    assert registry.resolve_candidate("", "Krug Grande Cuvee") is None
