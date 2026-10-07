"""Bordeaux Index LiveTrade (decision 0027). House style as in test_traps.py:
name the merchant, the wine, and the size of the error the test prevents.

The fixture (tests/fixtures/bordeaux-index-livetrade-2026-10-08.html) is a
trimmed, real response: four complete `.livetrade-item` blocks captured
live 8 October 2026 from /livetrade/marketplace/krug, unedited apart from
being cut down from the page's full 100 items. One of them — Krug Grande
Cuvee Edition 162eme, bid £660 against offer £1,596 — is the same live
market docs/research/bi-livetrade-champagne-findings.md already described;
finding it again, unprompted, in a fresh fetch is the adapter's own proof
that decision 0026 was built for a real, persistent situation, not a
one-off reading.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.adapters.base import Candidate, Rejected
from app.adapters.bordeaux_index_livetrade import (
    MAX_ITEMS,
    BordeauxIndexLiveTradeAdapter,
    SearchTooBroad,
    _parse_bi_datetime,
    extract_livetrade_items,
)
from app.core.enums import ConditionFlag, DutyStatus, PriceKind

FIXTURE = (Path(__file__).parent / "fixtures/bordeaux-index-livetrade-2026-10-08.html").read_text()
ITEMS = {i["variantId"]: i for i in extract_livetrade_items(FIXTURE)}
AS_OF = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def test_extraction_finds_four_items_deduplicated_from_six_copies_each():
    """Each item's data-item JSON is repeated six times (desktop/mobile/
    tablet x bid-button/offer-button) in the real markup. Dedupe by
    variantId, not by position."""
    assert len(ITEMS) == 4
    assert set(ITEMS) == {1499243, 908825, 1569371, 1555635}


def test_the_krug_162_bid_offer_spread_matches_the_research_that_prompted_0026():
    """Bid £660, offer £1,596, same item, found again live and unprompted."""
    item = ITEMS[1569371]
    assert item["bids"][0]["casePrice"] == 660
    assert item["offers"][0]["casePrice"] == 1596


def test_normalise_reads_lwinproductname_not_productname_for_the_edition_number():
    """productName: "Krug Grande Cuvee Edition 162" (number last).
    lwinProductName: "Krug, Grande Cuvee 162eme Edition" (number in the
    middle, comma-separated) — this adapter reads the second, because it
    is comma-structured and split_release_code already handles "162eme
    Edition" at the end of a string, not "Edition 162" at the end."""
    item = ITEMS[1569371]
    assert item["productName"] == "Krug Grande Cuvee Edition 162"
    assert item["lwinProductName"] == "Krug, Grande Cuvee 162eme Edition"
    [ask, bid] = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    assert ask.producer_text == "Krug"
    assert ask.cuvee_text == "Grande Cuvee"
    assert ask.release_code == "162"


def test_grande_cuvee_162_yields_an_ask_and_a_bid_no_last_trade():
    item = ITEMS[1569371]
    out = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    assert len(out) == 2
    [ask, bid] = out
    assert ask.offer.price_kind is PriceKind.ASK and ask.offer.price == Decimal("1596")
    assert bid.offer.price_kind is PriceKind.BID and bid.offer.price == Decimal("660")
    assert ask.offer.vintage == 1000                     # NV, LWIN convention
    assert ask.offer.bottle_ml == 750 and ask.offer.pack_size == 6
    assert ask.offer.merchant_id == "bordeaux-index"      # NOT this adapter's own id
    assert ask.offer.merchant == "Bordeaux Index"
    assert ask.lwin7 == "1653340"                         # lwin16[:7]


def test_every_offer_is_published_under_the_sibling_merchant_id():
    """The one invariant this whole adapter exists to protect: LiveTrade and
    the fine-wine listing pages are one company, never two comps."""
    for item in ITEMS.values():
        for candidate in BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF):
            if isinstance(candidate, Candidate):
                assert candidate.offer.merchant_id == "bordeaux-index"
                assert candidate.offer.merchant == "Bordeaux Index"


def test_the_ask_is_the_lowest_offer_by_price_never_by_list_order_or_rank():
    """Every real offer list seen is already in ascending-price order, so a
    synthetic, deliberately-scrambled list proves min() is what decides
    this, not "first in the JSON" or a trusted `rank` field."""
    item = dict(ITEMS[1555635])
    item["offers"] = [
        {"casePrice": 5000, "quantityAvailable": 1, "rank": 1},   # wrong rank, listed first
        {"casePrice": 1900, "quantityAvailable": 1, "rank": 2},   # the real lowest
    ]
    [ask] = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    assert ask.offer.price == Decimal("1900")


def test_the_bid_is_the_best_highest_bid_from_a_three_rung_ladder():
    """Krug Vintage Brut 1990: three bids, £3,000/£2,400/£2,125 — the best
    bid is the highest, the ladder beneath it is not emitted as evidence of
    its own (decision 0026/0027: confirmatory context, not additional comps)."""
    item = ITEMS[908825]
    assert len(item["bids"]) == 3
    out = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    [bid] = [c for c in out if c.offer.price_kind is PriceKind.BID]
    assert bid.offer.price == Decimal("3000")


def test_the_last_trade_carries_its_own_date_not_the_pages_fetch_time():
    item = ITEMS[1499243]
    out = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    [trade] = [c for c in out if c.offer.price_kind is PriceKind.LAST_TRADE]
    assert trade.offer.price == Decimal("2650")
    assert trade.offer.captured_at == datetime(2026, 6, 10, 9, 39, 5, 640000, tzinfo=timezone.utc)
    assert trade.offer.captured_at != AS_OF


def test_an_item_with_no_bid_and_no_last_trade_yields_only_an_ask():
    item = ITEMS[1555635]
    assert item["bids"] is None and item["lastTrade"] is None
    out = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    assert len(out) == 1
    assert out[0].offer.price_kind is PriceKind.ASK
    assert out[0].offer.vintage == 1964


def test_original_case_and_pristine_are_kept_as_condition_prose():
    """A flag without the merchant's own wording is refused by Candidate
    itself (base.py's __post_init__) — this just confirms the wording
    survives, word for word, exactly as published."""
    item = ITEMS[1555635]
    [ask] = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    assert ConditionFlag.ORIGINAL_CASE in ask.offer.condition_flags
    assert ask.offer.condition_notes == "Original Case ; Pristine"


def test_duty_status_is_read_from_the_item_not_assumed():
    item = ITEMS[1555635]
    assert item["dutyStatusCode"] == "IB"
    [ask] = BordeauxIndexLiveTradeAdapter().normalise(item, captured_at=AS_OF)
    assert ask.offer.duty_status is DutyStatus.IN_BOND


def test_an_item_with_no_price_at_all_is_rejected_not_silently_dropped():
    bare = {"productProducer": "Krug", "lwinProductName": "Krug, Vintage Brut",
           "vintageYear": 1964, "itemVolume": 75, "packSize": 1, "variantId": 1,
           "dutyStatusCode": "IB", "lwin16": "1316935196400750"}
    out = BordeauxIndexLiveTradeAdapter().normalise(bare, captured_at=AS_OF)
    assert isinstance(out, Rejected)


def test_a_record_with_no_producer_or_cuvee_is_rejected():
    bare = {"vintageYear": 1964, "itemVolume": 75, "packSize": 1, "variantId": 2}
    out = BordeauxIndexLiveTradeAdapter().normalise(bare, captured_at=AS_OF)
    assert isinstance(out, Rejected)


def test_bi_datetime_without_an_offset_is_assumed_utc_not_left_naive():
    """"2026-06-10T09:39:05.64" has no timezone. Left naive, _is_fresh and
    benchmark() would both refuse it outright (as_of must be aware)."""
    parsed = _parse_bi_datetime("2026-06-10T09:39:05.64")
    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 6, 10, 9, 39, 5, 640000, tzinfo=timezone.utc)
    assert _parse_bi_datetime(None) is None
    assert _parse_bi_datetime("not-a-date") is None


def test_search_too_broad_is_raised_not_silently_truncated():
    """Verified live: /livetrade/marketplace/krug returns exactly 100 items
    with no pagination. A fetch that hits the cap must say so, loudly —
    not return 100 as if that were everything."""
    class _FakeResponse:
        text = "x"
        def raise_for_status(self): pass

    class _FakeClient:
        def get(self, url):
            return _FakeResponse()

    import app.adapters.bordeaux_index_livetrade as mod
    original = mod.extract_livetrade_items
    mod.extract_livetrade_items = lambda html: [{"variantId": i} for i in range(MAX_ITEMS)]
    try:
        with pytest.raises(SearchTooBroad):
            BordeauxIndexLiveTradeAdapter().fetch("krug", client=_FakeClient())
    finally:
        mod.extract_livetrade_items = original


def test_a_narrower_search_under_the_cap_is_returned_normally():
    class _FakeResponse:
        text = "x"
        def raise_for_status(self): pass

    class _FakeClient:
        def get(self, url):
            return _FakeResponse()

    import app.adapters.bordeaux_index_livetrade as mod
    original = mod.extract_livetrade_items
    mod.extract_livetrade_items = lambda html: [{"variantId": 1}, {"variantId": 2}]
    try:
        rows = BordeauxIndexLiveTradeAdapter().fetch("krug grande cuvee", client=_FakeClient())
        assert len(rows) == 2
    finally:
        mod.extract_livetrade_items = original
