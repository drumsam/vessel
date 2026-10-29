from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from urllib.parse import urlencode
import pytest
from services.market_data.observations.models import Candidate, MarketUnit, utcnow
from services.market_data.observations.store import Store
from services.market_data.reference.snapshot import reference, freshness
from services.market_data.collectors.runner import run_source, refresh, due_units
from services.market_data.auction_import.importer import import_auction
from services.market_data.api.server import make_server

UNIT = MarketUnit("canonical-cuvee-edition", "2015", 750, 6, "UK", "IB", "GBP")

class ConfirmedResolver:
    # Test double only: production must call the real canonical identity layer.
    def resolve(self, candidate):
        return UNIT if candidate.get("confirmed") else None

@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "evidence.sqlite3", ConfirmedResolver())


def candidate(price="100", kind="MERCHANT_ASK", source="merchant-a", ref="listing-1", days=1, basis="BOTTLE"):
    return Candidate(source, "MERCHANT", Decimal(price), "GBP", basis, kind,
                     (utcnow() - timedelta(days=days)).isoformat(), ref,
                     {"original_price": price, "original_ref": ref}, {"confirmed": True})


def test_merchant_sources_units_decimal_and_no_recommendation(store):
    store.ingest(candidate("100.10"))
    store.ingest(candidate("110.10", source="merchant-b"))
    result = reference(store, UNIT)
    assert result["merchant"]["floor"] == "600.60"
    assert result["merchant"]["median"] == "630.60"
    assert result["merchant"]["source_count"] == 2
    assert result["merchant"]["count"] == 2
    assert result["merchant"]["age"]["freshness"] == "fresh"
    assert result["transactions"]["AUCTION_HAMMER"]["count"] == 0
    assert "recommendation" not in result


def test_cache_invalidated_and_latest_listing_replaces_old_price(store):
    store.ingest(candidate("90", days=40))
    assert reference(store, UNIT)["merchant"]["floor"] == "540"
    store.ingest(candidate("100", days=1))
    result = reference(store, UNIT)["merchant"]
    assert result["floor"] == "600"
    assert result["count"] == 1
    assert len(store.observations(UNIT)) == 2


def test_idempotent_import_and_auditable_evidence(store):
    row = candidate()
    oid = store.ingest(row)
    assert store.ingest(row) is None
    assert store.observations(UNIT)[0]["raw_evidence"]["original_price"] == "100"
    assert reference(store, UNIT)["merchant"]["observation_ids"] == [oid]


def test_unresolved_then_canonical_resolution_invalidates_cache(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    store.ingest(candidate())
    assert reference(store, UNIT)["merchant"]["floor"] is None
    assert len(store.observations(unresolved=True)) == 1
    store.resolver = ConfirmedResolver()
    assert store.resolve_pending() == 1
    assert reference(store, UNIT)["merchant"]["floor"] == "600"
    assert not store.observations(unresolved=True)


@pytest.mark.parametrize("field,value", [("currency", "USD"), ("market", "HK"), ("tax_status", "DP"),
                                         ("pack_size", 1), ("bottle_ml", 1500), ("vintage", "2016"),
                                         ("wine_id", "other-edition")])
def test_exact_units_never_mix(store, field, value):
    store.ingest(candidate())
    assert reference(store, replace(UNIT, **{field: value}))["merchant"]["count"] == 0


def test_auction_rails_are_separate_from_asks_and_each_other(store):
    store.ingest(candidate("500", kind="AUCTION_HAMMER", basis="PACK"))
    store.ingest(candidate("600", kind="AUCTION_ALL_IN", basis="PACK"))
    store.ingest(candidate("200"))
    result = reference(store, UNIT)
    assert result["transactions"]["AUCTION_HAMMER"]["median"] == "500"
    assert result["transactions"]["AUCTION_ALL_IN"]["median"] == "600"
    assert result["merchant"]["floor"] == "1200"


@pytest.mark.parametrize("days,label", [(0,"fresh"),(14,"fresh"),(15,"usable"),(30,"usable"),
                                        (31,"stale"),(90,"stale"),(91,"historical")])
def test_freshness(days,label):
    now = utcnow()
    assert freshness((now-timedelta(days=days)).isoformat(), now)["freshness"] == label


def test_old_evidence_remains_and_age_updates_with_cache(store):
    row = candidate(days=43)
    store.ingest(row)
    assert reference(store, UNIT)["merchant"]["age"]["age_days"] == 43
    assert reference(store, UNIT, utcnow()+timedelta(days=70))["merchant"]["age"]["freshness"] == "historical"


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "0", "not-money"])
def test_bad_prices_rejected(store, price):
    row = candidate()
    row.price = price
    with pytest.raises(ValueError):
        store.ingest(row)


def test_liquidity_best_sides_and_age(store):
    store.ingest(candidate("90", kind="LIVE_BID"))
    store.ingest(candidate("100", kind="LIVE_OFFER"))
    rail = reference(store, UNIT)["liquidity"]
    assert rail["best_bid"] == "540"
    assert rail["best_offer"] == "600"
    assert rail["spread"] == "60"
    assert rail["bid_age"]["age_days"] == 1


def test_collector_failure_isolation_and_rejections(store):
    class Broken:
        source_id = "broken"
        def collect(self, unit):
            raise RuntimeError("private credential never persisted")
    class Working:
        source_id = "merchant-a"
        def collect(self, unit):
            yield candidate()
            yield candidate("-1")
    store.set_universe(UNIT, "CORE", "A")
    result = refresh(store, [Broken(), Working()])
    assert [r["status"] for r in result[0]["runs"]] == ["FAILED", "PARTIAL"]
    assert len(store.observations(UNIT)) == 1
    assert "private credential" not in json.dumps(store.runs())
    assert len(due_units(store)) == 1


@pytest.mark.parametrize("priority,days", [("A",7),("B",14),("C",30)])
def test_schedule_and_discovery(store, priority, days):
    class Empty:
        source_id = "feed"
        def collect(self, unit):
            return []
    store.set_universe(UNIT)
    assert due_units(store) == []
    store.request_refresh(UNIT)
    assert due_units(store) == [UNIT]
    refresh(store, [Empty()])
    assert due_units(store) == []
    store.set_universe(UNIT, "CORE", priority)
    now = utcnow()
    refresh(store, [Empty()], now)
    assert due_units(store, now+timedelta(days=days-1)) == []
    assert due_units(store, now+timedelta(days=days)) == [UNIT]


def test_csv_xlsx_rejections_and_duplicates(store, tmp_path):
    from openpyxl import Workbook
    headers = ["sale_date", "lot", "hammer", "all_in_price", "currency", "quantity"]
    data = ["2026-01-01", "lot-42", "600", "720", "GBP", "6"]
    csv = tmp_path / "sale.csv"
    csv.write_text(",".join(headers)+"\n"+",".join(data)+"\n2026-01-01,bad,-4,,GBP,6\n")
    result = import_auction(store, csv, "auction-a")
    assert (result["written"], result["rejected"], result["status"]) == (2, 1, "PARTIAL")
    assert len(store.observations(unresolved=True)) == 2
    assert import_auction(store, csv, "auction-a")["duplicates"] == 2
    book = Workbook()
    book.active.append(headers)
    book.active.append(data)
    xlsx = tmp_path / "sale.xlsx"
    book.save(xlsx)
    assert import_auction(store, xlsx, "auction-b")["written"] == 2
    assert store.runs()[0]["status"] == "SUCCEEDED"


def test_http_contract_with_real_evidence(store):
    store.ingest(candidate())
    server = make_server(store, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base+"/health") as response:
            assert json.load(response)["status"] == "ok"
        query = urlencode(json.loads(UNIT.key()))
        with urlopen(base+"/v1/reference?"+query) as response:
            assert json.load(response)["merchant"]["floor"] == "600"
        with urlopen(Request(base+"/v1/refresh", data=UNIT.key().encode(),
                             headers={"Content-Type": "application/json"})) as response:
            assert response.status == 202
        assert due_units(store) == [UNIT]
        with pytest.raises(HTTPError) as error:
            urlopen(base+"/v1/reference?wine_id=unknown")
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_distinct_transaction_dates_survive_reused_lot_reference(store):
    store.ingest(candidate("400", kind="AUCTION_HAMMER", days=80, basis="PACK"))
    store.ingest(candidate("600", kind="AUCTION_HAMMER", days=3, basis="PACK"))
    rail = reference(store, UNIT)["transactions"]["AUCTION_HAMMER"]
    assert rail["count"] == 2
    assert (rail["low"], rail["high"], rail["median"]) == ("400", "600", "500")
    assert rail["latest"]["price"] == "600"


def test_import_resolves_only_when_canonical_adapter_confirms(tmp_path):
    class AuctionResolver:
        def resolve(self, hints):
            if hints.get("producer") == "Confirmed" and str(hints.get("quantity")) == "6":
                return UNIT
            return None
    store = Store(tmp_path / "resolved.sqlite3", AuctionResolver())
    path = tmp_path / "auction.csv"
    path.write_text("sale_date,lot,producer,quantity,hammer,all_in_price,currency\n"
                    "2026-01-01,sale-42,Confirmed,6,600,720,GBP\n"
                    "2026-01-01,sale-43,Ambiguous,,300,,GBP\n")
    result = import_auction(store, path, "licensed-auction")
    assert result["written"] == 3
    assert len(store.observations(unresolved=True)) == 1
    snapshot = reference(store, UNIT)
    assert snapshot["transactions"]["AUCTION_ALL_IN"]["latest"]["price"] == "720"
    assert snapshot["merchant"]["floor"] is None
