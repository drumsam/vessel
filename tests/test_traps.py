"""Every trap found against live merchant data is a permanent regression test.

Each test names the merchant, the wine and the size of the error it prevents.
If one of these fails, a wrong price is about to reach a client.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import combinations
from pathlib import Path

import pytest

from app.adapters.base import Candidate, whole_pence
from app.adapters.bordeaux_index import BordeauxIndexAdapter, parse_offer_row, parse_title
from app.adapters.condition import normalise_condition
from app.adapters.farr import FarrAdapter, parse_size, split_wine_field
from app.adapters.goedhuis import GoedhuisAdapter, is_eligible_variant, parse_sku
from app.core.benchmark import benchmark as _benchmark
from app.core.enums import ConditionFlag, DutyStatus, PriceKind, Reject, State, StockType
from app.core.flags import MAX_OFFER_AGE_DAYS, REVIEW_FLAGS, Flag
from app.core.models import Offer, SellerLine
from app.identity.resolver import (
    STRUCTURAL_EXCLUSIONS, CanonicalWine, Registry, ambiguous_lwins, wine_key)

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


def test_farr_lwin_resolves_lafite_that_the_name_alone_cannot():
    """'Lafite Rothschild' has no comma, so the name gives no producer/cuvee
    split and wine_key misses. LWIN finds it."""
    c = farr_candidate(237136)
    reg = Registry([CanonicalWine("lafite", "Chateau Lafite Rothschild", "Grand Vin", "1011872"),
                    CanonicalWine("carruades", "Chateau Lafite Rothschild", "Carruades", "1718931")])
    assert reg.resolve_candidate(c.producer_text, c.cuvee_text, c.lwin7) == "lafite"
    k = farr_candidate(215140)
    assert reg.resolve_candidate(k.producer_text, k.cuvee_text, k.lwin7) == "carruades"


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
    # The same capture shows Farr using 1038217 for two names: it is ignored.
    batch = [(c.lwin7, c.producer_text, c.cuvee_text) for c in (csj, lav)]
    assert "1038217" in ambiguous_lwins(batch)
    assert reg.resolve_candidate(lav.producer_text, lav.cuvee_text, None) == "lavaux"


def test_farr_shared_lwin_is_ambiguous_when_both_wines_are_listed():
    """Veuve Clicquot and Veuve Clicquot Rosé share 1083129 in the same feed."""
    b, r = farr_candidate(179275), farr_candidate(179277)
    assert b.lwin7 == r.lwin7 == "1083129"
    assert "1083129" in ambiguous_lwins([(c.lwin7, c.producer_text, c.cuvee_text) for c in (b, r)])
    assert ambiguous_lwins([(b.lwin7, b.producer_text, b.cuvee_text)]) == frozenset()


@pytest.mark.xfail(strict=True, reason=(
    "Known gap: if a merchant lists ONLY the Rosé under the Brut's LWIN, and the "
    "canonical table has only the Brut, LWIN resolves the Rosé to the Brut. "
    "Closing it needs a policy decision on LWIN trust; see the 2026-09-19 report."))
def test_farr_rose_alone_under_brut_lwin_is_not_priced_as_brut():
    r = farr_candidate(179277)
    reg = Registry([CanonicalWine("vcp-brut", "Veuve Clicquot", "Brut", "1083129")])
    assert reg.resolve_candidate(r.producer_text, r.cuvee_text, r.lwin7) is None


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
