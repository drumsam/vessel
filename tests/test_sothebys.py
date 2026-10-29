"""Sotheby's (decision 0042). House style as in test_traps.py: name the
merchant, the wine, and the size of the error the test prevents.

The fixture (tests/fixtures/sothebys-krug-1985-2026-10-26.html) is a
trimmed, real response captured live 26 October 2026 from
https://www.sothebys.com/en/buy/auction/2024/finest-rarest-wines-2/krug-
1985-4-bt — unedited apart from cutting the Auction's own `lotCards` array
(595 unrelated lots on the same page) down to two. The other real title
strings this module's pure functions are tested against (mixed-format lots,
"MV", the unmapped "HB"/"JM50" formats) were read from the SAME live page's
own `lotCards` list before it was trimmed out of the committed fixture —
real titles, not invented ones, even though the full list is not committed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.adapters.base import Candidate, Rejected
from app.adapters.sothebys import (
    SothebysAdapter,
    extract_lot,
    is_mixed_format,
    parse_lot_size,
    parse_vintage_and_name,
    split_producer_cuvee,
)
from app.core.enums import DutyStatus, PriceKind, Reject

FIXTURE_HTML = (Path(__file__).parent / "fixtures/sothebys-krug-1985-2026-10-26.html").read_text()
AS_OF = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def test_extract_lot_finds_the_one_real_lot_via_root_query():
    raw = extract_lot(FIXTURE_HTML)
    assert raw["lot"]["lotId"] == "320e8bf2-73d5-4945-a627-598c74026f05"
    assert raw["lot"]["title"] == "Krug 1985  (4 BT)"


def test_extract_lot_returns_none_for_a_page_with_no_next_data():
    assert extract_lot("<html><body>not a lot page</body></html>") is None


# ------------------------------------------------------------- lot size

def test_lot_size_parses_the_confirmed_vocabulary():
    assert parse_lot_size("Petrus 1981  (2 MAG)") == (2, 1500)
    assert parse_lot_size("Petrus 1976  (1 BT)") == (1, 750)
    assert parse_lot_size("Château Lafite 1996  (1 DM)") == (1, 375)
    assert parse_lot_size("Château Trotanoy 1989  (1 IMP)") == (1, 6000)


def test_lot_size_refuses_a_format_outside_the_confirmed_vocabulary():
    """"1 JM50" (five real Bordeaux lots) and "1 HB" (one real 1811 Cognac
    lot) are both real, live titles — neither format was confirmed, so
    neither is guessed at as a millilitre figure."""
    assert parse_lot_size("Château Lafite 1996  (1 JM50)") is None
    assert parse_lot_size("Cognac Fine Champagne 1811  (1 HB)") is None


def test_mixed_format_lot_is_detected_before_size_is_even_parsed():
    """"Château Haut Marbuzet 1996  (4 BT, 1 MAG)" — a real live title."""
    assert is_mixed_format("Château Haut Marbuzet 1996  (4 BT, 1 MAG)") is True
    assert is_mixed_format("Petrus 1981  (2 MAG)") is False


# ------------------------------------------------------------- vintage/name

def test_vintage_and_name_split_a_simple_title():
    assert parse_vintage_and_name("Krug 1985  (4 BT)") == (1985, "Krug")


def test_vintage_and_name_reads_nv_as_1000():
    assert parse_vintage_and_name("Krug Grande Cuvée NV  (1 BT)") == (1000, "Krug Grande Cuvée")


def test_vintage_and_name_refuses_mv_rather_than_guess_a_year():
    """Vega Sicilia 'Unico' Reserva Especial is a genuine multi-vintage
    blend, printed "... MV  (4 BT)" on a real live lot. MV is neither a
    4-digit year nor NV, so vintage comes back None rather than guessed."""
    vintage, name = parse_vintage_and_name("Vega Sicilia 'Unico', Reserva Especial MV  (4 BT)")
    assert vintage is None


def test_producer_cuvee_split_with_no_comma_is_the_whole_name_as_producer():
    assert split_producer_cuvee("Krug") == ("Krug", "")


def test_producer_cuvee_split_on_first_comma_producer_first():
    assert split_producer_cuvee("Laurent Perrier, Cuvée Grand Siecle") == (
        "Laurent Perrier", "Cuvée Grand Siecle")


# ------------------------------------------------------------- normalise()

def test_the_krug_lot_normalises_with_the_settled_price_never_the_last_bid():
    """BidState.sold.premiums.finalPriceV2.amount ("3250") is what the lot
    actually sold for. The page's own JSON-LD `offers.price` reads "1800.00"
    on this same real lot — current_bid, not the settled price — and this
    adapter must not have used it."""
    raw = extract_lot(FIXTURE_HTML)
    cand = SothebysAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    o = cand.offer
    assert o.price == Decimal("3250")
    assert o.currency == "EUR"
    assert (o.vintage, o.bottle_ml, o.pack_size) == (1985, 750, 4)
    assert cand.producer_text == "Krug"
    assert cand.cuvee_text == ""
    assert o.price_kind is PriceKind.LAST_TRADE
    assert o.duty_status is DutyStatus.UNKNOWN
    assert o.is_buyable is False
    assert o.captured_at == datetime(2024, 3, 25, 15, 16, 47, 999255, tzinfo=timezone.utc)
    assert o.source_url == (
        "https://www.sothebys.com/en/buy/auction/2024/finest-rarest-wines-2/krug-1985-4-bt")
    assert o.offer_id == "sothebys:320e8bf2-73d5-4945-a627-598c74026f05"


def test_an_unsold_lot_is_rejected_never_priced_at_the_estimate_or_current_bid():
    raw = {"lot": {"title": "Petrus 1981  (2 MAG)", "lotId": "x1"},
          "auction": {"currency": "GBP",
                      "dates": {"closed": "2026-10-26T12:00:00.000000Z"}},
          "bid_state": {"isClosed": True, "sold": {"isSold": False}}}
    out = SothebysAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.NON_POSITIVE_PRICE


def test_a_mixed_format_lot_is_rejected_as_a_mixed_lot():
    raw = {"lot": {"title": "Château Haut Marbuzet 1996  (4 BT, 1 MAG)", "lotId": "x2"},
          "auction": {"currency": "GBP"}, "bid_state": {"sold": {"isSold": True}}}
    out = SothebysAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.MIXED_LOT


def test_a_lot_with_no_currency_on_its_auction_is_rejected():
    raw = {"lot": {"title": "Krug 1985  (4 BT)", "lotId": "x3"},
          "auction": {},
          "bid_state": {"sold": {"isSold": True,
                                "premiums": {"finalPriceV2": {"amount": "3250"}}}}}
    out = SothebysAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.CURRENCY


def test_a_record_with_no_title_or_lot_id_is_rejected_as_unreadable():
    out = SothebysAdapter().normalise({"lot": {}, "auction": {}, "bid_state": {}}, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.ROW_UNREADABLE


def test_a_sold_lot_with_no_settled_price_field_is_rejected_not_priced_at_zero():
    raw = {"lot": {"title": "Krug 1985  (4 BT)", "lotId": "x4"},
          "auction": {"currency": "EUR"},
          "bid_state": {"sold": {"isSold": True, "premiums": {}}}}
    out = SothebysAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.NON_POSITIVE_PRICE
