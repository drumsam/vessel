"""Berry Bros. & Rudd (decision 0030). House style as in test_traps.py: name
the merchant, the wine, and the size of the error the test prevents.

The fixture (tests/fixtures/berry-bros-rudd-2026-10-11.json) is real, captured
live from two producer pages — Taittinger (Comtes de Champagne Blanc de
Blancs 2014 and 2013) and Krug (Grande Cuvée 173ème Édition, Rosé 26ème
Édition, Clos du Mesnil 2009) — each record already the flattened
`{hit context, **purchase_option}` dict `fetch()` would hand to `normalise()`
(the __NUXT__ evaluation itself is a thin Node shim, same convention as every
other adapter's own `extract_cards`/`extract_livetrade_items`, and is not
unit-tested by name).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.adapters.base import Candidate, Rejected
from app.adapters.berry_bros_rudd import (
    BerryBrosRuddAdapter, parse_bottle_volume, parse_cuvee)
from app.core.enums import DutyStatus, PriceKind, Reject, StockType

FIXTURE = json.loads((Path(__file__).parent / "fixtures/berry-bros-rudd-2026-10-11.json").read_text())
AS_OF = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def find(name_part: str, purchase_mode: str, stock_origin: str, case_size: int) -> dict:
    for item in FIXTURE:
        if (name_part in item["name"] and item["purchase_mode"] == purchase_mode
                and item["stock_origin"] == stock_origin and item["case_size"] == case_size):
            return item
    raise AssertionError(f"no fixture item for {name_part!r}/{purchase_mode!r}/{stock_origin!r}/{case_size!r}")


def test_bottle_volume_parsing():
    assert parse_bottle_volume("75 cl") == 750
    assert parse_bottle_volume("150 cl") == 1500
    assert parse_bottle_volume("300 cl") == 3000
    assert parse_bottle_volume("") is None
    assert parse_bottle_volume("garbled") is None


def test_cuvee_parsing_strips_vintage_champagne_prefix_and_trailing_brut():
    cuvee, code = parse_cuvee("2014 Champagne Taittinger, Comtes de Champagne, Blanc de Blancs, Brut",
                              "Champagne Taittinger", 2014)
    assert cuvee == "Comtes de Champagne, Blanc de Blancs"
    assert code is None


def test_cuvee_parsing_reads_krug_edition_as_a_release_code_not_cuvee_text():
    """"Grande Cuvée, 173ème Édition" — the comma before the edition number
    must not leak into the cleaned cuvée text as a trailing comma."""
    cuvee, code = parse_cuvee("Champagne Krug, Grande Cuvée, 173ème Édition, Brut", "Krug", None)
    assert cuvee == "Grande Cuvée"
    assert code == "173"


def test_cuvee_parsing_does_not_strip_extra_brut_as_if_it_were_the_generic_suffix():
    """Only a standalone trailing ", Brut" clause is BBR's generic sweetness
    suffix. "Extra Brut" is a real, distinct sweetness descriptor and must
    survive — stripping it would merge two different wines' identities."""
    cuvee, code = parse_cuvee("2007 Champagne Bollinger, RD, Extra Brut", "Bollinger", 2007)
    assert cuvee == "RD, Extra Brut"


def test_bbr_direct_in_bond_prices_a_whole_case_at_the_case_price():
    item = find("Comtes de Champagne, Blanc de Blancs", "In Bond", "BBR", 3)
    cand = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.duty_status is DutyStatus.IN_BOND
    assert cand.offer.stock_type is StockType.MERCHANT_STOCK
    assert (cand.offer.pack_size, cand.offer.price) == (3, Decimal("780"))
    assert cand.offer.bottle_ml == 1500


def test_bbx_in_bond_is_the_same_merchant_as_bbr_direct_never_a_second_comp():
    """BBX is Berry Bros' own exchange, not a different company — decision
    0030 reads it the same way decisions 0026/0027 already read Bordeaux
    Index LiveTrade: one merchant_id for both stock origins."""
    direct = find("Comtes de Champagne, Blanc de Blancs", "In Bond", "BBR", 3)
    exchange = find("Comtes de Champagne, Blanc de Blancs", "In Bond", "BBX", 6)
    adapter = BerryBrosRuddAdapter()
    c1 = adapter.normalise(direct, captured_at=AS_OF)
    c2 = adapter.normalise(exchange, captured_at=AS_OF)
    assert c1.offer.merchant_id == c2.offer.merchant_id == "berry-bros-rudd"
    assert c1.offer.stock_type is StockType.MERCHANT_STOCK
    assert c2.offer.stock_type is StockType.MARKETPLACE


def test_delivery_is_duty_paid_at_one_bottle_never_at_the_case_size():
    """"Delivery" quotes a PER-BOTTLE price regardless of the SKU's own
    case_size (confirmed live, zero exceptions across every nested
    purchase_option read): pack_size must follow the price actually quoted,
    not the case_size field, or the price would be read six times too
    cheap."""
    item = find("Comtes de Champagne, Blanc de Blancs", "Delivery", "BBR", 6)
    cand = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.duty_status is DutyStatus.DUTY_PAID
    assert (cand.offer.pack_size, cand.offer.price) == (1, Decimal("122.5"))
    assert cand.offer.bottle_ml == 750


def test_a_jeroboam_listed_as_case_size_one_still_prices_at_the_case_field():
    """case_size 1 does not mean "read price_per_bottle_exact" — that field
    is keyed by purchase_mode, never by case_size. A 300cl Jeroboam "In
    Bond" at case_size 1 still prices off price_per_case_exact, same as any
    other In Bond listing."""
    item = find("2013 Champagne Taittinger, Comtes de Champagne, Blanc de Blancs", "In Bond", "BBX", 1)
    assert item["bottle_volume"] == "300 cl"
    cand = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert (cand.offer.pack_size, cand.offer.bottle_ml, cand.offer.price) == (1, 3000, Decimal("990"))


def test_krug_nv_edition_is_vintage_1000_with_the_edition_as_a_release_code():
    item = find("Grande Cuvée", "In Bond", "BBR", 6)
    cand = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.vintage == 1000
    assert cand.producer_text == "Krug"
    assert cand.cuvee_text == "Grande Cuvée"
    assert cand.release_code == "173"


def test_krug_producer_field_is_already_bare_no_champagne_prefix_to_strip():
    """Confirmed live: BBR's own `producer` field is inconsistent across
    producers ("Krug" bare, "Champagne Taittinger" prefixed) — stripping
    must be a no-op when there is nothing to strip, not an error."""
    item = find("Rosé, 26", "In Bond", "BBX", 3)
    cand = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert cand.producer_text == "Krug"
    assert cand.cuvee_text == "Rosé"
    assert cand.release_code == "26"


def test_a_vintage_loose_bottle_krug_prices_at_the_case_field_even_at_pack_size_one():
    item = find("Clos du Mesnil", "In Bond", "BBR", 1)
    cand = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.vintage == 2009
    assert (cand.offer.pack_size, cand.offer.bottle_ml, cand.offer.price) == (1, 750, Decimal("1046"))


def test_an_unrecognised_purchase_mode_is_rejected_not_assumed_in_bond():
    item = dict(find("Grande Cuvée", "In Bond", "BBR", 6))
    item["purchase_mode"] = "Reserve"
    out = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.DUTY


def test_an_unrecognised_stock_origin_is_rejected():
    item = dict(find("Grande Cuvée", "In Bond", "BBR", 6))
    item["stock_origin"] = "THIRD_PARTY"
    out = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.ROW_UNREADABLE


def test_an_unreadable_bottle_volume_is_rejected():
    item = dict(find("Grande Cuvée", "In Bond", "BBR", 6))
    item["bottle_volume"] = "a bottle"
    out = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.SIZE


def test_a_missing_case_size_is_rejected():
    item = dict(find("Grande Cuvée", "In Bond", "BBR", 6))
    item["case_size"] = None
    out = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.SIZE


def test_a_zero_price_is_rejected_not_treated_as_a_free_wine():
    item = dict(find("Grande Cuvée", "In Bond", "BBR", 6))
    item["prices"] = {**item["prices"], "price_per_case_exact": 0}
    out = BerryBrosRuddAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.NON_POSITIVE_PRICE


def test_a_record_with_no_producer_is_rejected():
    bare = {"name": "Champagne Krug, Grande Cuvée, Brut", "producer": "",
           "vintage": None, "purchase_mode": "In Bond", "stock_origin": "BBR",
           "case_size": 6, "bottle_volume": "75 cl",
           "prices": {"price_per_case_exact": 900}}
    out = BerryBrosRuddAdapter().normalise(bare, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.ROW_UNREADABLE


def test_every_fixture_record_normalises_to_a_candidate():
    """The fixture is real, already-valid data — nothing in it should ever
    reject. A rejection here means the adapter drifted from the live shape
    it was built against."""
    adapter = BerryBrosRuddAdapter()
    for item in FIXTURE:
        out = adapter.normalise(item, captured_at=AS_OF)
        assert isinstance(out, Candidate), f"{item.get('name')!r} rejected: {out}"
        assert out.offer.price_kind is PriceKind.ASK
