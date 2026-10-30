"""Integrated evidence: real Postgres, existing identity and merchant ingestion."""

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import time
from uuid import uuid4
import pytest
from app.db import repo
from app.market.reference import market_reference
from app.worker import jobs
from app.auction.importer import file_rows
from tests.test_inbound import (
    conn,
    client,
    pg,
    _wine,
    _confirmed_offer,
    _seed_offers,
    _proposal,
    _use_provider,
)


def auction_csv(
    producer="Example Estate",
    wine="Example Cuvee",
    amount="600.00",
    lot="sale-42",
    **extra,
):
    import csv
    from io import StringIO

    row = {
        "producer": producer,
        "wine": wine,
        "vintage": "2015",
        "bottle_ml": "750",
        "bottles_in_lot": "6",
        "auction_house": "CHRISTIES",
        "sale_date": "2026-01-01",
        "lot_ref": lot,
        "source_url": "https://www.christies.com/en/lot/example",
        "currency": "GBP",
        "amount": amount,
        "amount_basis": "HAMMER",
        **extra,
    }
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return output.getvalue().encode()


def upload(client, content, name="auction.csv"):
    return client.post(
        "/auction-imports",
        json={"filename": name, "content_base64": base64.b64encode(content).decode()},
    )


def setup_offer(client, conn, monkeypatch, prices=("100.00", "110.00")):
    wid = _wine(conn, producer="Example Estate", cuvee="Example Cuvee", want_list=False)
    if prices:
        _seed_offers(conn, wine_id=wid, vintage=2015, prices=prices)
    _use_provider(monkeypatch, _proposal())
    oid = _confirmed_offer(client, conn, wine_id=wid)
    return wid, oid


@pg
def test_cached_pocket_merchant_and_auction_separate_with_raw_provenance(
    client, conn, monkeypatch
):
    wid, oid = setup_offer(client, conn, monkeypatch)
    first = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert first["merchant"]["floor"] == "100.00"
    assert first["cached"] is False
    second = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert second["cached"] is True and second["run_id"] == first["run_id"]
    data = auction_csv()
    imported = upload(client, data)
    assert imported.status_code == 200, imported.text
    assert imported.json()["written"] == 1
    assert upload(client, data).json()["duplicates"] == 1
    assert upload(client, auction_csv(amount="601.00")).json()["rejected"] == 1
    after = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert after["merchant"] == second["merchant"]
    assert after["transactions"]["count"] == 1
    assert after["transactions"]["low_per_bottle_gbp"] == "100.00"
    assert (
        after["transactions"]["evidence"][0]["raw_evidence"]["row"]["amount"]
        == "600.00"
    )
    assert after["transactions"]["latest"]["currency"] == "GBP"
    assert after["transactions"]["latest_sale_date"] == "2026-01-01"
    assert (
        conn.execute("SELECT count(*) AS n FROM auction_evidence").fetchone()["n"] == 1
    )


@pg
def test_unresolved_import_uses_existing_queue_then_existing_reresolution(
    client, conn, monkeypatch
):
    result = upload(client, auction_csv()).json()
    assert result["unresolved"] == 1
    assert (
        conn.execute("SELECT count(*) AS n FROM auction_evidence").fetchone()["n"] == 0
    )
    raw = conn.execute(
        "SELECT raw FROM offer_reject WHERE reason='UNRESOLVED_IDENTITY'"
    ).fetchone()["raw"]
    assert raw["row"]["wine"] == "Example Cuvee"
    _wine(conn, producer="Example Estate", cuvee="Example Cuvee", want_list=False)
    report = jobs.reresolve_rejects("christies")
    assert report["recovered"] == 1
    assert (
        conn.execute("SELECT count(*) AS n FROM auction_evidence").fetchone()["n"] == 1
    )
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM offer WHERE merchant_id='christies'"
        ).fetchone()["n"]
        == 0
    )
    assert not conn.execute(
        "SELECT 1 FROM offer_reject WHERE reason='UNRESOLVED_IDENTITY'"
    ).fetchone()


@pg
def test_xlsx_and_unknown_premium_preserve_evidence(client, conn, monkeypatch):
    from openpyxl import Workbook

    setup_offer(client, conn, monkeypatch)
    import csv
    from io import StringIO

    row = next(csv.DictReader(StringIO(auction_csv().decode())))
    book = Workbook()
    book.active.append(list(row))
    book.active.append(list(row.values()))
    content = BytesIO()
    book.save(content)
    assert upload(client, content.getvalue(), "auction.xlsx").json()["written"] == 1
    missing = upload(
        client, auction_csv(lot="sale-43", amount_basis="BUYER_PREMIUM_INCLUSIVE")
    ).json()
    assert missing["rejected"] == 1
    assert (
        conn.execute(
            "SELECT raw FROM offer_reject WHERE reason='AUCTION_IMPORT_INVALID'"
        ).fetchone()["raw"]["row"]["amount_basis"]
        == "BUYER_PREMIUM_INCLUSIVE"
    )


@pg
def test_new_capture_invalidates_and_empty_capture_never_resurrects_stock(
    client, conn, monkeypatch
):
    wid, oid = setup_offer(client, conn, monkeypatch, prices=("100.00",))
    first = client.post(f"/inbound-offers/{oid}/evaluate").json()
    _seed_offers(conn, wine_id=wid, vintage=2015, prices=["120.00"])
    second = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert (
        second["run_id"] != first["run_id"] and second["merchant"]["floor"] == "120.00"
    )
    merchant = conn.execute(
        "SELECT merchant_id FROM offer WHERE wine_id=%s LIMIT 1", (wid,)
    ).fetchone()["merchant_id"]
    now = datetime.now(timezone.utc)
    sid = repo.create_snapshot(conn, captured_at=now, schema_version="2", is_demo=False)
    repo.write_snapshot_merchant(conn, sid, merchant, captured_at=now, written=0)
    third = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert third["merchant"]["floor"] is None
    assert third["state"] == "NO_MARKET" and third["blocks_create_offer"] is False


@pg
def test_boundary_flags_currency_and_units_invalidate_cached_result(
    client, conn, monkeypatch
):
    wid, oid = setup_offer(client, conn, monkeypatch, prices=("100.00",))
    first = client.post(f"/inbound-offers/{oid}/evaluate").json()
    line = repo.get_line(conn, first["line_id"])
    old = conn.execute(
        "SELECT captured_at FROM offer WHERE wine_id=%s", (wid,)
    ).fetchone()["captured_at"]
    with conn.transaction():
        aged = market_reference(
            conn, line, now=old + timedelta(days=14, microseconds=1)
        )
    assert aged["merchant"]["floor"] is None and aged["merchant"]["historical"]
    conn.execute("UPDATE offer SET currency='USD' WHERE wine_id=%s", (wid,))
    currency = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert currency["merchant"]["floor"] is None
    conn.execute(
        "UPDATE offer SET currency='GBP', bottle_ml=1500 WHERE wine_id=%s", (wid,)
    )
    assert (
        client.post(f"/inbound-offers/{oid}/evaluate").json()["merchant"]["floor"]
        is None
    )
    conn.execute(
        "UPDATE seller_line SET flags=ARRAY['NAME_REVIEW'] WHERE line_id=%s",
        (line["line_id"],),
    )
    assert (
        client.post(f"/inbound-offers/{oid}/evaluate").json()["blocks_create_offer"]
        is True
    )


@pg
def test_reconfirmation_updates_bound_line_without_an_old_cached_identity(
    client, conn, monkeypatch
):
    wid, oid = setup_offer(client, conn, monkeypatch)
    first = client.post(f"/inbound-offers/{oid}/evaluate").json()
    other = _wine(conn, producer="Other Estate", cuvee="Other Cuvee", want_list=False)
    # Actual confirmation endpoint, including existing supplier attribution.
    supplier = conn.execute(
        "SELECT supplier_id FROM inbound_offer WHERE inbound_offer_id=%s", (oid,)
    ).fetchone()["supplier_id"]
    response = client.post(
        f"/inbound-offers/{oid}/confirm-identity",
        json={
            "wine_id": other,
            "vintage": 2016,
            "bottle_ml": 1500,
            "pack_size": 1,
            "quantity": 1,
            "supplier_id": str(supplier),
        },
    )
    assert response.status_code == 200, response.text
    after = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert after["line_id"] == first["line_id"] and after["merchant"]["floor"] is None
    assert str(repo.get_line(conn, after["line_id"])["wine_id"]) == other


@pg
def test_real_bordeaux_adapter_collect_now_updates_same_contract(
    client, conn, monkeypatch
):
    from tests.test_service import bi_card
    from app.identity.resolver import wine_key
    import app.api.inbound as inbound_mod

    producer = "Domaine Armand Rousseau"
    cuvee = "Charmes-Chambertin Grand Cru"
    wid = _wine(conn, producer=producer, cuvee=cuvee, want_list=False)
    conn.execute(
        "UPDATE wine SET wine_key=%s WHERE wine_id=%s", (wine_key(producer, cuvee), wid)
    )
    _use_provider(monkeypatch, _proposal())
    oid = _confirmed_offer(client, conn, wine_id=wid, vintage=2011)
    response = client.put(
        "/merchants/bordeaux-index/search-keys",
        json={
            "producer_key": "domaine armand rousseau",
            "params": {"producer_slug": "domaine_armand_rousseau"},
        },
    )
    assert response.status_code == 200, response.text
    original = jobs.collect_now

    def collect(wine_id, vintage):
        return original(
            wine_id,
            vintage,
            merchant_ids=["bordeaux-index"],
            fetch=lambda adapter, params, year: [bi_card("650.00", vintage=year)],
            robots=lambda url: None,
        )

    monkeypatch.setattr(inbound_mod.jobs, "collect_now", collect)
    result = client.post(f"/inbound-offers/{oid}/collect-now")
    assert result.status_code == 200, result.text
    assert result.json()["collected"][0]["outcome"] == "ok"
    assert result.json()["evaluation"]["merchant"]["floor"] == "650.00"
    assert result.json()["evaluation"]["merchant"]["source_count"] == 1
    again = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert again["cached"] is True
    assert again["merchant"]["floor"] == "650.00"


@pg
def test_cached_evaluation_latency_and_merchant_best_semantics(
    client, conn, monkeypatch
):
    wid, oid = setup_offer(client, conn, monkeypatch)
    # Two listings from the same merchant must never count as two sources.
    row = conn.execute(
        "SELECT * FROM offer WHERE wine_id=%s LIMIT 1", (wid,)
    ).fetchone()
    conn.execute(
        """INSERT INTO offer(snapshot_id,offer_id,merchant_id,wine_id,vintage,bottle_ml,pack_size,
        price,currency,duty_status,price_kind,is_buyable,captured_at)
        VALUES(%s,'duplicate-listing',%s,%s,2015,750,1,1000,'GBP','IB','ASK',true,%s)""",
        (row["snapshot_id"], row["merchant_id"], wid, row["captured_at"]),
    )
    client.post(f"/inbound-offers/{oid}/evaluate")
    times = []
    for _ in range(10):
        start = time.perf_counter()
        result = client.post(f"/inbound-offers/{oid}/evaluate")
        times.append((time.perf_counter() - start) * 1000)
        assert result.status_code == 200, result.text
        assert result.json()["cached"] is True
        assert result.json()["merchant"]["source_count"] == 2
        assert result.json()["merchant"]["median"] == "105.00"
    print("CACHE_TIMINGS_MS", sorted(round(t, 2) for t in times))
    assert max(times) < 500


@pg
def test_import_release_codes_stay_unresolved_until_canonical_edition_matches(
    client, conn
):
    _wine(conn, producer="Krug", cuvee="Grande Cuvee", want_list=False)
    result = upload(
        client,
        auction_csv(
            producer="Krug", wine="Grande Cuvee", vintage="1000", release_code="156"
        ),
    ).json()
    assert result["unresolved"] == 1
    assert (
        conn.execute("SELECT count(*) AS n FROM auction_evidence").fetchone()["n"] == 0
    )
    assert jobs.reresolve_rejects("christies")["recovered"] == 0


@pg
def test_retracted_event_can_be_corrected_and_import_snapshots_survive_pruning(
    client, conn, monkeypatch
):
    setup_offer(client, conn, monkeypatch)
    uploaded = upload(client, auction_csv()).json()
    assert uploaded["written"] == 1
    event = conn.execute("SELECT auction_evidence_id FROM auction_evidence").fetchone()[
        "auction_evidence_id"
    ]
    retracted = client.post(
        f"/auction-evidence/{event}/retract", json={"reason": "verified correction"}
    )
    assert retracted.status_code == 200, retracted.text
    assert upload(client, auction_csv(amount="650.00")).json()["written"] == 1
    unresolved = upload(
        client, auction_csv(producer="Unknown", lot="unresolved-lot")
    ).json()
    repo.prune_snapshots(conn, 1)
    assert repo.get_snapshot(conn, unresolved["snapshot_id"])
    assert conn.execute(
        "SELECT 1 FROM offer_reject WHERE reason='UNRESOLVED_IDENTITY'"
    ).fetchone()


@pg
def test_failed_collection_is_distinct_and_does_not_invent_a_floor(
    client, conn, monkeypatch
):
    wid, oid = setup_offer(client, conn, monkeypatch, prices=())
    before = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert before["collection_state"] == "NOT_SEARCHED"
    now = datetime.now(timezone.utc)
    sid = repo.create_snapshot(conn, captured_at=now, schema_version="2", is_demo=False)
    repo.write_snapshot_merchant(
        conn, sid, "bordeaux-index", captured_at=now, error="fixture failure"
    )
    failed = client.post(f"/inbound-offers/{oid}/evaluate").json()
    assert failed["collection_state"] == "CHECK_FAILED"
    assert (
        failed["merchant"]["floor"] is None and failed["blocks_create_offer"] is False
    )


def test_malformed_xlsx_is_rejected_before_writing():
    from zipfile import BadZipFile

    with pytest.raises(BadZipFile):
        list(file_rows("bad.xlsx", b"not a spreadsheet"))


@pg
def test_evidence_read_cannot_overwrite_a_later_identity_review(client, conn, monkeypatch):
    wid, oid = setup_offer(client, conn, monkeypatch)
    first = client.post(f'/inbound-offers/{oid}/evaluate').json()
    corrected = _wine(conn, producer='Reviewed Estate', cuvee='Reviewed Cuvee', want_list=False)
    conn.execute('UPDATE seller_line SET wine_id=%s WHERE line_id=%s', (corrected, first['line_id']))
    response = client.post(f'/inbound-offers/{oid}/evaluate')
    assert response.status_code == 422
    assert 'reconfirm' in response.json()['detail']
    assert str(repo.get_line(conn, first['line_id'])['wine_id']) == corrected
