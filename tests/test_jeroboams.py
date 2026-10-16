"""Jeroboams (decision pending — UK breadth, third of three houses). House
style as in test_traps.py: name the merchant, the wine, and the size of the
error the test prevents.

The fixture (tests/fixtures/jeroboams-2026-10-16.json) is real, captured live
from six product pages — two Krug Grande Cuvée 173ème Édition pages (one "ib-"
In Bond, one duty-paid retail, for the SAME wine), 2002 Krug Vintage Brut,
Pierre Peters Cuvée de Reserve, Henri Giraud Argonne Rosé (a real loose
bottle), Chateau Léoville Las Cases 2022, and the Krug Soloist Orchestra
Assortment Case — each record already the flattened
`{product context, **initialUniqueItems entry}` dict `fetch()` would hand to
`normalise()` (the `__NEXT_DATA__` extraction itself is a thin shim, same
convention as every other adapter's own `extract_cards`/`extract_hits`, and
is not unit-tested by name).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.adapters.base import Candidate, Rejected
from app.adapters.jeroboams import (
    JeroboamsAdapter, parse_bottle_volume, parse_case_size, parse_cuvee,
    parse_vintage_label)
from app.core.enums import DutyStatus, PriceKind, Reject, StockType

FIXTURE = json.loads((Path(__file__).parent / "fixtures/jeroboams-2026-10-16.json").read_text())
AS_OF = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def find(name_part: str, sku_part: str) -> dict:
    for item in FIXTURE:
        if name_part in item["name"] and sku_part in item["sku"]:
            return item
    raise AssertionError(f"no fixture item for {name_part!r}/{sku_part!r}")


def by_sku(sku: str) -> dict:
    for item in FIXTURE:
        if item["sku"] == sku:
            return item
    raise AssertionError(f"no fixture item with sku {sku!r}")


def test_case_size_parsing():
    assert parse_case_size("6 x Bottle") == 6
    assert parse_case_size("1 x Bottle") == 1
    assert parse_case_size("3 x Magnum") == 3
    assert parse_case_size(None) is None
    assert parse_case_size("") is None


def test_bottle_volume_parsing():
    assert parse_bottle_volume("75 cl") == 750
    assert parse_bottle_volume("150 cl") == 1500
    assert parse_bottle_volume("") is None


def test_vintage_label_parsing():
    assert parse_vintage_label("2012") == 2012
    assert parse_vintage_label("N.V.") == 1000
    assert parse_vintage_label("NV") == 1000
    assert parse_vintage_label(None) is None
    assert parse_vintage_label("garbled") is None


def test_cuvee_parsing_when_the_name_leads_with_the_producer():
    """"2012 Henri Giraud, Argonne Rose" — producer first, confirmed live."""
    cuvee, code = parse_cuvee("2012 Henri Giraud, Argonne Rose", "Henri Giraud")
    assert cuvee == "Argonne Rose"
    assert code is None


def test_cuvee_parsing_when_the_name_leads_with_the_cuvee():
    """"2002 Vintage Brut, Champagne Krug" — producer LAST, confirmed live.
    Guessing "head is always the producer" (as a merchant that is always
    producer-first would let an adapter do) would read "Vintage Brut" as the
    producer here."""
    cuvee, code = parse_cuvee("2002 Vintage Brut, Champagne Krug", "Krug")
    assert cuvee == "Vintage Brut"
    assert code is None


def test_cuvee_parsing_reads_krug_edition_as_a_release_code_not_cuvee_text():
    cuvee, code = parse_cuvee("N.V. Grande Cuvee 173eme Edition, Champagne Krug", "Champagne Krug")
    assert cuvee == "Grande Cuvee"
    assert code == "173"


def test_cuvee_parsing_keeps_a_multi_segment_cuvee_whole():
    """"N.V. Champagne Pierre Peters, Cuvee de Reserve, Blanc de Blancs, Grand
    Cru" — only the FIRST comma separates producer from cuvée; the rest of
    the cuvée's own commas must survive untouched."""
    cuvee, code = parse_cuvee(
        "N.V. Champagne Pierre Peters, Cuvee de Reserve, Blanc de Blancs, Grand Cru",
        "Pierre Peters")
    assert cuvee == "Cuvee de Reserve, Blanc de Blancs, Grand Cru"


def test_a_main_placeholder_is_rejected_on_size_never_read_as_a_zero_price():
    """Every In Bond product's "-MAIN" entry is a useless parent placeholder
    — case_size/bottle_size/volume are always null. It must reject on SIZE,
    never slip through as a real zero-price offer."""
    item = find("Henri Giraud", "IB-MAIN")
    out = JeroboamsAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.SIZE


def test_a_real_loose_bottle_in_bond_is_the_reason_this_adapter_exists():
    """Confirmed live: Henri Giraud Argonne Rosé 2012, case_size "1 x
    Bottle", In Bond, a genuinely single-bottle quoted price — not a case
    divided down. No other adapter in this fleet reliably produces this for
    this cellar's back-vintage Champagne."""
    item = find("Henri Giraud", "0100750IB")
    cand = JeroboamsAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.duty_status is DutyStatus.IN_BOND
    assert (cand.offer.pack_size, cand.offer.bottle_ml, cand.offer.price) == (1, 750, Decimal("1531"))
    assert cand.offer.vintage == 2012


def test_duty_status_is_read_from_the_sku_suffix_never_the_url_prefix():
    """The SAME wine (Krug Grande Cuvée 173ème) appears on an "ib-" page
    (sku ending "IB") and a non-"ib-" duty-paid retail page (sku with no "IB"
    suffix at all). Reading the URL instead of the sku would get the
    duty-paid one backwards if it were ever fetched by mistake."""
    in_bond = find("Grande Cuvee", "600750IB")
    duty_paid = by_sku("308904800000600750")  # no IB suffix
    adapter = JeroboamsAdapter()
    c1 = adapter.normalise(in_bond, captured_at=AS_OF)
    c2 = adapter.normalise(duty_paid, captured_at=AS_OF)
    assert c1.offer.duty_status is DutyStatus.IN_BOND
    assert c2.offer.duty_status is DutyStatus.DUTY_PAID


def test_an_in_bond_sku_with_a_uuid_suffix_is_still_read_as_in_bond():
    """A second, independent In Bond listing for the identical commercial
    unit carries its own UUID after the "IB" (a different stock lot, a
    different price) — the regex must not require the sku to end exactly
    at "IB"."""
    item = find("Grande Cuvee", "263522a7")
    cand = JeroboamsAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate) and cand.offer.duty_status is DutyStatus.IN_BOND
    assert cand.offer.price == Decimal("911")


def test_a_duty_paid_float_noise_price_passes_through_unrounded():
    """204.999996 is float noise, not a price anyone printed — this adapter
    does not round or reject it itself; app.worker.jobs' own whole_pence()
    check does that centrally, same as it already does for Farr."""
    item = by_sku("308904800000600750")
    cand = JeroboamsAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert cand.offer.price == Decimal("204.999996")


def test_a_non_vintage_wine_is_vintage_1000_with_the_edition_as_a_release_code():
    item = find("Grande Cuvee", "600750IB")
    cand = JeroboamsAdapter().normalise(item, captured_at=AS_OF)
    assert cand.offer.vintage == 1000
    assert cand.producer_text == "Krug"
    assert cand.release_code == "173"


def test_an_assortment_case_is_a_mixed_lot_never_priced():
    """"2008 Krug Soloist Orchestra Assortment Case" bundles several distinct
    single-vineyard cuvées under one SKU — nothing in the data flags this
    structurally (mixed_products/case_only are both null), only the name's
    own "Assortment" wording does, same regex lw_trading.py already uses."""
    item = find("Assortment", "70b786a0")
    out = JeroboamsAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.MIXED_LOT


def test_a_magnum_case_is_read_at_its_real_size_not_misread_as_750():
    item = find("Pierre Peters", "301500IB")
    cand = JeroboamsAdapter().normalise(item, captured_at=AS_OF)
    assert isinstance(cand, Candidate)
    assert (cand.offer.pack_size, cand.offer.bottle_ml) == (3, 1500)


def test_a_record_with_no_producer_is_rejected():
    bare = {"name": "2012 Henri Giraud, Argonne Rose", "producer": "",
           "sku": "186126220120100750IB", "qty": 1,
           "price": {"amount": {"value": 1531}},
           "case_size": {"data": {"label": "1 x Bottle"}},
           "volume": {"data": {"label": "75 cl"}}}
    out = JeroboamsAdapter().normalise(bare, captured_at=AS_OF)
    assert isinstance(out, Rejected) and out.reason is Reject.ROW_UNREADABLE


def test_every_real_variant_in_the_fixture_normalises_to_a_candidate():
    """Only the "-MAIN" placeholders and the named assortment case (both its
    placeholder and its real variant — the name check runs before the size
    check, so the assortment's own MAIN rejects as MIXED_LOT, not SIZE)
    should ever reject in this fixture — every other record is real, valid
    stock and must come out as a Candidate."""
    adapter = JeroboamsAdapter()
    rejections = 0
    for item in FIXTURE:
        out = adapter.normalise(item, captured_at=AS_OF)
        if isinstance(out, Rejected):
            rejections += 1
            assert out.reason in (Reject.SIZE, Reject.MIXED_LOT), (item.get("sku"), out.reason)
        else:
            assert out.offer.price_kind is PriceKind.ASK
            assert out.offer.stock_type is StockType.MERCHANT_STOCK
    assert rejections == 7  # five "-MAIN" placeholders + the assortment's MAIN and its real variant
