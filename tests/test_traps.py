"""Every trap found against live merchant data is a permanent regression test.

Each test names the merchant, the wine and the size of the error it prevents.
If one of these fails, a wrong price is about to reach a client.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.adapters.bordeaux_index import BordeauxIndexAdapter, parse_offer_row, parse_title
from app.adapters.condition import normalise_condition
from app.adapters.farr import FarrAdapter, parse_size, split_wine_field
from app.adapters.goedhuis import GoedhuisAdapter, is_eligible_variant, parse_sku
from app.core.benchmark import benchmark
from app.core.enums import ConditionFlag, DutyStatus, PriceKind, Reject, State, StockType
from app.core.flags import Flag
from app.core.models import Offer, SellerLine
from app.identity.resolver import STRUCTURAL_EXCLUSIONS, Registry, CanonicalWine, wine_key

WINE = "w-rousseau-chambertin"


def offer(**kw) -> Offer:
    base = dict(
        offer_id="x", merchant_id="m1", merchant="M1", wine_id=WINE, vintage=2011,
        bottle_ml=750, pack_size=1, price=Decimal("600"), currency="GBP",
        duty_status=DutyStatus.IN_BOND, price_kind=PriceKind.ASK,
        is_buyable=True, offered_units=1,
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


def test_condition_normalisation_from_live_strings():
    assert normalise_condition("Not in original carton") == frozenset({ConditionFlag.NO_ORIGINAL_CASE})
    assert normalise_condition("Non OWC") == frozenset({ConditionFlag.NO_ORIGINAL_CASE})
    assert normalise_condition("Individual OWC") == frozenset({ConditionFlag.ORIGINAL_CASE})
    assert normalise_condition("Repack") == frozenset({ConditionFlag.REPACK})
    assert ConditionFlag.NON_PRISTINE in normalise_condition("Repack Bottle: Non Pristine")
    flags = normalise_condition("Excellent levels, not in original carton, stained labels")
    assert ConditionFlag.LABEL_DAMAGE in flags
    assert ConditionFlag.NO_ORIGINAL_CASE in flags
