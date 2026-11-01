"""Workbench, Trades, offer actions and counterparty registers (decision 0050).

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    python -m pytest -q tests/test_workbench.py
"""
from __future__ import annotations

from tests.test_inbound import (_offer, _priced_offer, _proposal, _supplier,  # noqa: F401
                                _use_provider, client, conn, pg)


def _capture(client, monkeypatch, text="3 x something, 2800 a bottle"):
    _use_provider(monkeypatch, _proposal())
    return client.post("/inbound-offers", json={"channel": "paste", "raw_body": text}).json()["offer"]


def _another_priced_offer(client, monkeypatch, conn, src_id):
    """A second priced offer for the same wine (the helper creates the wine)."""
    wine_id, supplier_id = conn.execute(
        "SELECT confirmed_wine_id, supplier_id FROM inbound_offer WHERE inbound_offer_id = %s",
        (src_id,)).fetchone().values()
    _use_provider(monkeypatch, _proposal())
    offer_id = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()[
        "offer"]["inbound_offer_id"]
    body = {"wine_id": str(wine_id), "vintage": 2015, "bottle_ml": 750, "pack_size": 1,
            "quantity": 3, "supplier_id": str(supplier_id), "asking_price": "2800.00",
            "asking_currency": "GBP", "asking_basis": "per_bottle", "bond_status": "UK IB",
            "stock_location": "LCB", "want_list_ack": False}
    assert client.post(f"/inbound-offers/{offer_id}/confirm-identity", json=body).status_code == 200
    assert client.post(f"/inbound-offers/{offer_id}/evaluate").status_code == 200
    return offer_id


def _statuses(client):
    return {t["inbound_offer_id"]: t["status"] for t in client.get("/trades").json()["pocket"]}


@pg
def test_the_workbench_groups_every_live_offer_by_what_it_needs_next(client, monkeypatch, conn):
    raw = _capture(client, monkeypatch, "2015 Rousseau Clos St Jacques\n£2,800 a bottle, 3 available")
    ready_id, _ = _priced_offer(client, conn, monkeypatch)
    out_id = _another_priced_offer(client, monkeypatch, conn, ready_id)
    _offer(client, out_id, "3150.00")
    done_id = _another_priced_offer(client, monkeypatch, conn, ready_id)
    _offer(client, done_id, "3150.00")
    client.post(f"/inbound-offers/{done_id}/confirm", json={"buyer_name": "Client X"})

    wb = client.get("/workbench").json()
    ids = lambda key: [i["inbound_offer_id"] for i in wb[key]]  # noqa: E731
    assert ids("to_review") == [raw["inbound_offer_id"]]
    assert wb["to_review"][0]["status"] == "NEEDS_IDENTITY"
    assert wb["to_review"][0]["title"] == "2015 Rousseau Clos St Jacques"     # first line, not the dump
    assert ids("ready_to_price") == [ready_id]
    assert ids("offers_out") == [out_id]
    assert ids("confirmed") == [done_id]
    assert wb["confirmed"][0]["buyer_name"] == "Client X"
    assert wb["offers_out"][0]["next_action"] == "Await client"
    assert wb["to_review"][0]["next_action"] == "Review identity"
    assert wb["confirmed"][0]["next_action"] == "Arrange ops"
    assert (wb["review_counts"]["cellar_lines"], wb["review_counts"]["lwin_conflicts"]) == (0, 0)
    assert wb["recent"][0]["text"].startswith("Confirmed with Client X")


@pg
def test_delete_is_a_soft_delete_hidden_everywhere_and_never_destroys_the_capture(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, offer_id, "3150.00")
    r = client.post(f"/inbound-offers/{offer_id}/discard")
    assert r.status_code == 200 and r.json()["discarded_at"]
    assert offer_id not in _statuses(client)
    assert all(t["inbound_offer_id"] != offer_id for t in client.get("/pocket/trades").json())
    assert all(offer_id not in [i["inbound_offer_id"] for i in v]
               for k, v in client.get("/workbench").json().items() if isinstance(v, list)
               and k != "recent")
    row = conn.execute("SELECT raw_body, deal_id FROM inbound_offer WHERE inbound_offer_id = %s",
                       (offer_id,)).fetchone()
    assert row["raw_body"] == "x" and row["deal_id"] is not None          # nothing destroyed
    assert conn.execute("SELECT count(*) AS n FROM pricing_result").fetchone()["n"] == 1
    assert _offer(client, offer_id, "3200.00").status_code == 409
    assert client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "X"}).status_code == 409
    assert client.post(f"/inbound-offers/{offer_id}/discard").status_code == 404   # already deleted


@pg
def test_a_confirmed_trade_can_never_be_deleted(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, offer_id, "3150.00")
    client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "Client X"})
    r = client.post(f"/inbound-offers/{offer_id}/discard")
    assert r.status_code == 409 and "can't be deleted" in r.json()["detail"]
    assert _statuses(client)[offer_id] == "CONFIRMED"


@pg
def test_duplicate_is_a_new_unconfirmed_draft_from_the_same_message(client, monkeypatch, conn):
    src_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, src_id, "3150.00")
    r = client.post(f"/inbound-offers/{src_id}/duplicate")
    assert r.status_code == 201
    dup = r.json()
    assert dup["inbound_offer_id"] != src_id and dup["duplicated_from"] == src_id
    assert dup["parse_state"] == "parsed" and dup["identity_confirmed_at"] is None   # confirmed afresh
    assert dup["confirmed_wine_id"] is None and dup["deal_id"] is None
    assert dup["supplier_id"] is not None
    assert _statuses(client)[dup["inbound_offer_id"]] == "NEEDS_IDENTITY"
    assert _statuses(client)[src_id] == "OFFER_OUT"                                  # untouched


@pg
def test_the_client_register_and_confirming_a_trade_against_a_client(client, monkeypatch, conn):
    r = client.post("/clients", json={"name": "Hong Kong Collector", "phone": "+852 1234"})
    assert r.status_code == 201
    cl = r.json()
    assert cl["aliases"] == ["hong kong collector"] and cl["trades"] == 0
    assert client.post("/clients", json={"name": "Hong Kong Collector"}).status_code == 409
    r = client.patch(f"/clients/{cl['client_id']}", json={"default_currency": "HKD",
                                                          "payment_terms": "7 days"})
    assert (r.json()["default_currency"], r.json()["payment_terms"]) == ("HKD", "7 days")
    r = client.post(f"/clients/{cl['client_id']}/aliases", json={"alias": "HK Collector"})
    assert "hk collector" in r.json()["aliases"]

    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, offer_id, "3150.00")
    r = client.post(f"/inbound-offers/{offer_id}/confirm", json={"client_id": cl["client_id"]})
    assert r.status_code == 200, r.text
    f = r.json()["fulfilment"]
    assert (f["client_id"], f["client_name"], f["buyer_name"]) == (
        cl["client_id"], "Hong Kong Collector", "Hong Kong Collector")
    assert client.get(f"/clients/{cl['client_id']}").json()["trades"] == 1
    assert client.get("/clients").json()[0]["client_id"] == cl["client_id"]


@pg
def test_confirm_needs_a_client_or_a_buyer_name(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, offer_id, "3150.00")
    assert client.post(f"/inbound-offers/{offer_id}/confirm", json={}).status_code == 422


@pg
def test_the_supplier_register_holds_its_commercial_defaults(client, monkeypatch, conn):
    sid = _supplier(client, "Vinum")
    r = client.patch(f"/suppliers/{sid}", json={
        "contact_name": "James", "email": "james@vinum.example", "default_currency": "GBP",
        "usual_stock_location": "LCB", "usual_bond_status": "UK IB", "payment_terms": "30 days"})
    assert r.status_code == 200
    body = r.json()
    assert (body["usual_stock_location"], body["usual_bond_status"], body["payment_terms"]) == (
        "LCB", "UK IB", "30 days")
    assert client.post(f"/suppliers/{sid}/aliases", json={"alias": "Vinum Ltd"}).json()["aliases"] == [
        "vinum", "vinum ltd"]
    client.patch(f"/suppliers/{sid}", json={"active": False})
    assert all(s["supplier_id"] != sid for s in client.get("/suppliers").json())       # chip row
    assert any(s["supplier_id"] == sid for s in client.get("/suppliers?all=true").json())  # register


@pg
def test_trades_lists_pocket_offers_once_and_cellars_without_the_pocket_deals(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    from app.db import repo
    op = conn.execute("SELECT operator_id FROM operator LIMIT 1").fetchone()["operator_id"]
    repo.create_deal(conn, {"name": "WFS Cellar", "seller": "WFS", "city": None, "source_file": None,
                            "currency": None, "target_margin": None, "buyer_discount": None,
                            "margin_on_sale": None, "created_by": op}, [])
    t = client.get("/trades").json()
    assert [c["name"] for c in t["cellars"]] == ["WFS Cellar"]          # no "Pocket ..." deal
    assert [p["inbound_offer_id"] for p in t["pocket"]] == [offer_id]
    assert t["pocket"][0]["title"].startswith("Armand Rousseau Clos St Jacques 2015")


@pg
def test_an_orphaned_pocket_deal_is_never_listed_as_a_cellar(client, monkeypatch, conn):
    """Found live in the browser check: two overlapping EVALUATEs each made a
    deal, and the orphan showed on Trades as a cellar called "Pocket …"."""
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    from app.db import repo
    from psycopg.types.json import Jsonb
    op = conn.execute("SELECT operator_id FROM operator LIMIT 1").fetchone()["operator_id"]
    orphan = repo.create_deal(conn, {"name": "Pocket 2026-11-01 orphan", "seller": None, "city": None,
                                     "source_file": None, "currency": None, "target_margin": None,
                                     "buyer_discount": None, "margin_on_sale": None,
                                     "created_by": op}, [])
    conn.execute("""INSERT INTO seller_line (deal_id, row_index, raw_description, raw_row, quantity)
                    VALUES (%s, 0, 'x', %s, 3)""",
                 (orphan["deal_id"], Jsonb({"inbound_offer_id": offer_id})))
    assert client.get("/trades").json()["cellars"] == []


@pg
def test_evaluate_twice_reuses_one_deal(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    client.post(f"/inbound-offers/{offer_id}/evaluate")
    assert conn.execute("SELECT count(*) AS n FROM deal").fetchone()["n"] == 1


@pg
def test_ready_to_price_says_what_is_missing_in_plain_words(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    item = client.get("/workbench").json()["ready_to_price"][0]
    assert item["next_action"] == "Set price"
    conn.execute("UPDATE inbound_offer SET deal_id = NULL WHERE inbound_offer_id = %s", (offer_id,))
    assert client.get("/workbench").json()["ready_to_price"][0]["next_action"] == "Check market"
    conn.execute("UPDATE inbound_offer SET confirmed_asking_price = NULL WHERE inbound_offer_id = %s",
                 (offer_id,))
    assert client.get("/workbench").json()["ready_to_price"][0]["next_action"] == "Complete details"
