"""iDealwine (decision 0042). House style as in test_traps.py: name the
merchant, the wine, and the size of the error the test prevents.

The fixture (tests/fixtures/idealwine-sylvain-pataille-2023-2026-10-26.html)
is the real, unedited response captured live 26 October 2026 from
https://www.idealwine.com/en/buy-a-wine/2502373-1-bottle-Bourgogne-Sylvain-
Pataille-Domaine-2023-Red — the direct shop, never the auction/estimate
side (see the adapter module and decision 0042).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.adapters.base import Candidate, Rejected
from app.adapters.idealwine import IdealwineAdapter, cuvee_from_name, extract_product
from app.core.enums import DutyStatus, PriceKind, Reject, StockType

FIXTURE_HTML = (Path(__file__).parent
               / "fixtures/idealwine-sylvain-pataille-2023-2026-10-26.html").read_text()
AS_OF = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def test_extract_product_finds_the_variant_query():
    raw = extract_product(FIXTURE_HTML)
    assert raw["id"] == 2502373
    assert raw["name"] == "Bourgogne Sylvain Pataille (Domaine) 2023"


def test_extract_product_returns_none_for_a_page_with_no_next_data():
    assert extract_product("<html><body>not a product page</body></html>") is None


def test_cuvee_from_name_subtracts_the_owner_fields_own_text_and_the_vintage():
    """"Bourgogne Sylvain Pataille (Domaine) 2023" minus the owner field's
    own text and the vintage token leaves "Bourgogne" -- confirmed live."""
    assert cuvee_from_name("Bourgogne Sylvain Pataille (Domaine) 2023",
                           "Sylvain Pataille (Domaine)", 2023) == "Bourgogne"


def test_cuvee_from_name_with_no_owner_match_keeps_the_rest_whole():
    assert cuvee_from_name("Grand Vin 2020", "Someone Else", 2020) == "Grand Vin"


def test_the_real_product_normalises_as_a_standing_ask_in_eur():
    """Confirmed live: the rendered page shows "€26", not "£21.67",
    even when fetched with requestCountryCode=GB -- priceByCountry is a
    tax-zone adjustment, not a currency conversion. This adapter must read
    the plain EUR `price` field, never `priceByCountry`."""
    raw = extract_product(FIXTURE_HTML)
    cand = IdealwineAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    o = cand.offer
    assert o.price == Decimal("26.00")
    assert o.currency == "EUR"
    assert (o.vintage, o.bottle_ml, o.pack_size) == (2023, 750, 1)
    assert cand.producer_text == "Sylvain Pataille (Domaine)"
    assert cand.cuvee_text == "Bourgogne"
    assert o.price_kind is PriceKind.ASK
    assert o.duty_status is DutyStatus.UNKNOWN
    assert o.is_buyable is True
    assert o.offered_units == 305
    assert o.stock_type is StockType.MERCHANT_STOCK
    assert o.offer_id == "idealwine:2502373"


def test_fetch_attaches_the_real_source_url(monkeypatch):
    """normalise() reads `_source_url`, which only `fetch()` attaches (the
    page's own JSON carries no URL/slug field of its own) -- confirmed by
    wiring a fake client in rather than hitting the network."""
    class FakeResponse:
        status_code = 200
        text = FIXTURE_HTML
        def raise_for_status(self): pass

    class FakeClient:
        def get(self, url):
            return FakeResponse()

    out = IdealwineAdapter().fetch(["en/buy-a-wine/2502373-x"], client=FakeClient())
    assert len(out) == 1
    assert out[0]["_source_url"] == "https://www.idealwine.com/en/buy-a-wine/2502373-x"
    cand = IdealwineAdapter().normalise(out[0], captured_at=AS_OF)
    assert cand.offer.source_url == "https://www.idealwine.com/en/buy-a-wine/2502373-x"


def test_an_auction_lot_is_rejected_never_read_as_a_shop_ask():
    """`"auction": true` is this site's own flag for its OTHER business --
    decision 0042 reads the shop only."""
    raw = {"auction": True, "id": 1, "name": "x",
          "product": {"owner": "Someone"}, "productVintage": {"year": 2020}}
    out = IdealwineAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.KIND


def test_a_variant_with_no_vintage_year_is_rejected_never_guessed_as_nv():
    raw = {"auction": False, "id": 2, "name": "Grand Vin", "product": {"owner": "Someone"},
          "productVintage": {"year": None}, "customVolume": 750, "numberOfBottles": 1,
          "price": 1000}
    out = IdealwineAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.VINTAGE


def test_a_variant_with_no_bottle_count_or_volume_is_rejected_as_size():
    raw = {"auction": False, "id": 3, "name": "Grand Vin 2020", "product": {"owner": "Someone"},
          "productVintage": {"year": 2020}, "customVolume": None, "numberOfBottles": None,
          "price": 1000}
    out = IdealwineAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.SIZE


def test_a_zero_or_missing_price_is_rejected_never_priced_at_zero():
    raw = {"auction": False, "id": 4, "name": "Grand Vin 2020", "product": {"owner": "Someone"},
          "productVintage": {"year": 2020}, "customVolume": 750, "numberOfBottles": 1,
          "price": 0}
    out = IdealwineAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.NON_POSITIVE_PRICE


def test_a_record_with_no_owner_is_rejected_as_unreadable():
    raw = {"auction": False, "id": 5, "name": "Grand Vin 2020", "product": {"owner": ""},
          "productVintage": {"year": 2020}, "customVolume": 750, "numberOfBottles": 1,
          "price": 1000}
    out = IdealwineAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.ROW_UNREADABLE


def test_offered_units_falls_back_to_on_hand_minus_on_hold_without_variant_variations():
    raw = {"auction": False, "id": 6, "name": "Grand Vin 2020", "product": {"owner": "Someone"},
          "productVintage": {"year": 2020}, "customVolume": 750, "numberOfBottles": 1,
          "price": 1000, "inStock": True, "onHand": 10, "onHold": 2, "variantVariations": []}
    cand = IdealwineAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.offered_units == 8
