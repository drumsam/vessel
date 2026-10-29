"""Christie's (decision 0042). House style as in test_traps.py: name the
merchant, the wine, and the size of the error the test prevents.

The fixture (tests/fixtures/christies-cheval-blanc-2003-2026-10-26.html) is
the real, unedited response captured live 26 October 2026 from
https://www.christies.com/en/lot/lot-6324831.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.adapters.base import Candidate, Rejected
from app.adapters.christies import (
    ChristiesAdapter,
    extract_lot,
    parse_lot_size,
    parse_vintage_and_name,
    split_producer_cuvee,
)
from app.core.enums import DutyStatus, PriceKind, Reject

FIXTURE_HTML = (Path(__file__).parent / "fixtures/christies-cheval-blanc-2003-2026-10-26.html").read_text()
AS_OF = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def test_extract_lot_picks_the_canonical_lot_not_the_sidebars_other_lots():
    """The page embeds a SECOND `"lots":[...]` array for a "rest of this
    sale" widget, confirmed live to carry ten OTHER object_ids. The
    canonical link is what must disambiguate, not array order."""
    raw = extract_lot(FIXTURE_HTML)
    assert raw["lot"]["object_id"] == "6324831"
    assert raw["lot"]["title_primary_txt"] == "Château Cheval-Blanc 2003"


def test_extract_lot_reads_currency_from_the_right_labels_object():
    """`window.chrGlobal` carries its own, unrelated, much smaller
    `"labels":{...}` object earlier on the same real page — confirmed
    live. The first "labels" match alone is not reliable."""
    raw = extract_lot(FIXTURE_HTML)
    assert raw["currency"] == "GBP"


def test_extract_lot_reads_the_sale():
    raw = extract_lot(FIXTURE_HTML)
    assert raw["sale"]["location_txt"] == "London"
    assert raw["sale"]["start_date"] == "2021-06-17T09:30Z"


def test_extract_lot_returns_none_for_a_page_with_no_canonical_lot():
    assert extract_lot("<html><body>no canonical link here</body></html>") is None


# ------------------------------------------------------------- lot size

def test_lot_size_reads_the_literal_unit_not_an_abbreviation_table():
    """"1 x 18L bottle per lot" -- an 18-LITRE bottle, confirmed real on
    this exact live lot. Parsed as printed, not "corrected"."""
    assert parse_lot_size("1 x 18L bottle per lot\n") == (1, 18000)


def test_lot_size_parses_cl_and_ml_generically():
    assert parse_lot_size("6 x 75CL bottle per lot") == (6, 750)
    assert parse_lot_size("1 x 750ML bottle per lot") == (1, 750)
    assert parse_lot_size("1 x 150CL bottle per lot") == (1, 1500)


def test_lot_size_is_none_when_unreadable():
    assert parse_lot_size("") is None
    assert parse_lot_size("a mixed case") is None


# ------------------------------------------------------------- vintage/name

def test_vintage_and_name_split_the_real_title():
    assert parse_vintage_and_name("Château Cheval-Blanc 2003") == (2003, "Château Cheval-Blanc")


def test_vintage_and_name_reads_nv():
    assert parse_vintage_and_name("Champagne Krug NV") == (1000, "Champagne Krug")


def test_vintage_and_name_is_none_with_no_year_token():
    vintage, name = parse_vintage_and_name("Finest and Rarest Wines and Spirits")
    assert vintage is None


def test_producer_cuvee_split_no_comma_is_the_whole_name():
    assert split_producer_cuvee("Château Cheval-Blanc") == ("Château Cheval-Blanc", "")


def test_producer_cuvee_split_on_first_comma():
    assert split_producer_cuvee("Louis Roederer, Cristal") == ("Louis Roederer", "Cristal")


# ------------------------------------------------------------- normalise()

def test_the_cheval_blanc_lot_normalises_with_the_bond_notice_read_as_in_bond():
    raw = extract_lot(FIXTURE_HTML)
    cand = ChristiesAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    o = cand.offer
    assert o.price == Decimal("13475.0")
    assert o.currency == "GBP"
    assert (o.vintage, o.bottle_ml, o.pack_size) == (2003, 18000, 1)
    assert cand.producer_text == "Château Cheval-Blanc"
    assert cand.cuvee_text == ""
    assert o.price_kind is PriceKind.LAST_TRADE
    assert o.duty_status is DutyStatus.UNKNOWN
    assert o.is_buyable is False
    assert o.source_url == "https://www.christies.com/en/lot/lot-6324831"
    assert o.offer_id == "christies:6324831"


def test_an_unsold_lot_is_rejected_never_priced_at_the_estimate():
    raw = {"lot": {"object_id": "x2", "title_primary_txt": "Petrus 1981",
                   "title_tertiary_txt": "1 x 750ML bottle per lot",
                   "price_realised": None, "is_unsold": True},
          "sale": {}, "currency": "GBP"}
    out = ChristiesAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.NON_POSITIVE_PRICE


def test_price_realised_as_a_string_is_read_the_same_as_a_number():
    """The sidebar's OTHER lots on the real page carry price_realised as a
    JSON string ("918"), not a number -- confirmed live. Decimal(str(...))
    must read either shape the same way."""
    raw = {"lot": {"object_id": "x3", "title_primary_txt": "Petrus 1981",
                   "title_tertiary_txt": "1 x 750ML bottle per lot",
                   "price_realised": "918", "is_unsold": False},
          "sale": {}, "currency": "GBP"}
    cand = ChristiesAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.price == Decimal("918")


def test_a_lot_with_no_currency_found_is_rejected():
    raw = {"lot": {"object_id": "x4", "title_primary_txt": "Petrus 1981",
                   "title_tertiary_txt": "1 x 750ML bottle per lot",
                   "price_realised": 500, "is_unsold": False},
          "sale": {}, "currency": None}
    out = ChristiesAdapter().normalise(raw, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.CURRENCY


def test_a_record_with_no_title_or_object_id_is_rejected_as_unreadable():
    out = ChristiesAdapter().normalise({"lot": {}, "sale": {}, "currency": None},
                                       captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.ROW_UNREADABLE
