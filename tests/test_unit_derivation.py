"""Cross-case-size comparables, Burgundy only, with a 5% case premium.

Spec: docs/research/burgundy-unit-policy.md, built as decision 0016. House style
as in test_traps.py: name the merchant, the wine, and the size of the error the
test prevents.

The premium is an assumption, not a measurement, and these tests exist as much
to hold that line as to check the arithmetic: a derived figure must never be
able to reach a client document without a person having seen it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core.benchmark import benchmark, derive_price
from app.core.enums import DutyStatus, PriceKind, Reject, State, StockType
from app.core.flags import CASE_PREMIUM, REVIEW_FLAGS, Flag
from app.core.models import Offer, SellerLine
from app.market.units import DERIVABLE_REGIONS, derivation_allowed, derivation_note

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


def test_burgundy_loose_bottle_derives_to_case_with_premium():
    """Bordeaux Index's loose 2020 Mugneret-Gibourg Vosne-Romanée bottle is £197.
    Multiplied flat it says £1,182 for six — but a case is not six loose bottles,
    and the policy's 5% says £1,241.10. Taking the flat figure understates the
    case by £59.10, and it would become the Floor of a line with no other
    evidence."""
    loose = offer("bordeaux-index", "197.00", pack_size=1, merchant="Bordeaux Index")
    price, basis, premium = derive_price(loose, 6)
    assert price == Decimal("1241.10") == Decimal("197.00") * 6 * CASE_PREMIUM
    assert price != Decimal("1182.00")
    assert premium is True and "assumption, not a measurement" in basis

    result = benchmark(line(), [loose], as_of=AS_OF)
    assert result.uk_floor == Decimal("1241.10")
    [derived] = result.derived
    assert derived.source is loose and derived.offer.price == Decimal("1241.10")
    assert Flag.DERIVED_FROM_CASE in result.flags


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

    assert result.comp_count == 2 and result.uk_reference == Decimal("504.00")
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


def test_derivation_is_burgundy_only():
    """The same shapes outside Burgundy are still rejected with UNIT. The core
    does not know what a region is: the caller sets `derive_units`, and the
    region list lives in app/market/units.py with the decision behind it."""
    three = offer("bordeaux-index", "225.00", pack_size=3, merchant="Bordeaux Index")
    bordeaux = benchmark(line(derive=False), [three], as_of=AS_OF)
    assert bordeaux.state is State.NO_MARKET and bordeaux.derived == []
    assert [r.reason for r in bordeaux.rejections] == [Reject.UNIT]
    assert [e.per_bottle for e in bordeaux.cross_unit] == [Decimal("75")]

    assert derivation_allowed("BURGUNDY_RED") and derivation_allowed("BURGUNDY_WHITE")
    for elsewhere in ("BORDEAUX_RED", "CHAMPAGNE", "RHONE_NORTH", None, ""):
        assert not derivation_allowed(elsewhere)
    assert DERIVABLE_REGIONS == {"BURGUNDY_RED", "BURGUNDY_WHITE"}


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
    assert "a working assumption, not a measurement" in derivation_note(farr)
    # Both figures are on the run, each beside the offer it came from.
    assert [d.offer.price for d in result.derived] == [Decimal("450.00"), Decimal("504.00")]


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
