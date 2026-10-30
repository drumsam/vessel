"""VESSEL Pocket, build brief Phase 1b step 2: inbound_offer, NEW,
CANDIDATE, and the photo gate. House style as in test_traps.py: name the
rule and the size of the error the test prevents.

    TEST_DATABASE_URL=postgresql://pricer:pricer@localhost:5432/pricer_test \\
    python -m pytest -q tests/test_inbound.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import fakeredis
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from rq import Queue

from app.api import main as api
import app.api.inbound as inbound_mod
from app.ai.provider import InboundOfferProposal, Provenance
from app.evaluate import repo as evaluate_repo

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = os.environ.get("TEST_DATABASE_URL")
pg = pytest.mark.skipif(not TEST_DB, reason="TEST_DATABASE_URL not set")


def _reset(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT,
                   env={**os.environ, "DATABASE_URL": TEST_DB}, check=True, capture_output=True)


@pytest.fixture
def conn(monkeypatch):
    _reset(TEST_DB)
    _alembic("upgrade", "head")
    monkeypatch.setenv("DATABASE_URL", TEST_DB)
    with psycopg.connect(TEST_DB, row_factory=dict_row, autocommit=True,
                         prepare_threshold=None) as c:
        yield c


OPERATOR = {"username": "op", "display_name": "The Operator", "password": "correct horse"}


@pytest.fixture
def client(conn):
    from app.api import auth

    auth.create_operator(OPERATOR["username"], OPERATOR["display_name"], OPERATOR["password"])
    q = Queue(f"test-{uuid4().hex}", connection=fakeredis.FakeRedis())
    api.app.dependency_overrides[api.queue] = lambda: q
    c = TestClient(api.app, base_url="https://testserver")
    assert c.post("/session", json={"username": OPERATOR["username"],
                                    "password": OPERATOR["password"]}).status_code == 200
    yield c
    api.app.dependency_overrides.clear()


def _wine(conn, *, producer="Domaine de la Romanee-Conti", cuvee="Richebourg Grand Cru",
         want_list=True) -> str:
    row = conn.execute(
        "INSERT INTO wine (producer, cuvee, region, colour, wine_key, want_list) "
        "VALUES (%s, %s, 'Burgundy', 'red', %s, %s) RETURNING wine_id",
        (producer, cuvee, f"{producer.lower()}|{cuvee.lower()}", want_list)).fetchone()
    return str(row["wine_id"])


def _supplier(client, name: str = "Test Supplier", phone: str | None = None) -> str:
    r = client.post("/suppliers", json={"name": name, "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()["supplier_id"]


def _confirmed_offer(client, conn, *, wine_id=None, vintage=2015, bottle_ml=750, pack_size=1,
                     quantity=1, asking_price=None, asking_currency=None,
                     asking_basis=None) -> str:
    """Create, confirm, and return the inbound_offer_id of a ready-to-
    evaluate offer -- the shared setup every EVALUATE test starts from.
    Caller must have already called _use_provider(monkeypatch, ...)."""
    if wine_id is None:
        wine_id = _wine(conn, want_list=False)
    body = {"wine_id": wine_id, "vintage": vintage, "bottle_ml": bottle_ml,
           "pack_size": pack_size, "quantity": quantity, "supplier_id": _supplier(client)}
    if asking_price is not None:
        body["asking_price"] = asking_price
        body["asking_currency"] = asking_currency or "GBP"
    if asking_basis is not None:
        body["asking_basis"] = asking_basis
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity", json=body)
    assert r.status_code == 200, r.text
    return offer_id


def _seed_offers(conn, *, wine_id, vintage, prices, bottle_ml=750, pack_size=1,
                 merchant_prefix="Test Merchant") -> None:
    """Real `offer` rows, same table an adapter would write to — reused
    unchanged (decision 0039's own write path), so app.core.benchmark
    can never tell the difference."""
    evaluate_repo.write_evaluation_comps(
        conn, wine_id=wine_id, vintage=vintage,
        comps=[{"merchant": f"{merchant_prefix} {i}", "price": str(p), "currency": "GBP",
               "bottle_ml": bottle_ml, "pack_size": pack_size, "duty_status": "IB",
               "price_kind": "ASK", "is_buyable": True}
              for i, p in enumerate(prices, start=1)])


def _proposal(**kw) -> InboundOfferProposal:
    defaults = dict(category="wine", producer="Domaine de la Romanee-Conti",
                    cuvee="Richebourg Grand Cru", vintage=2015, bottle_ml=750, pack_size=1,
                    quantity=3, total_bottles=None, bond_status="UK In Bond",
                    stock_location="LCB", packaging=None,
                    asking_price="2,800", asking_currency="GBP", asking_basis="per_bottle",
                    reasoning="read directly from the text",
                    provenance=Provenance(provider="fake", model="fake"))
    defaults.update(kw)
    return InboundOfferProposal(**defaults)


class _FakeProvider:
    def __init__(self, result):
        self._result = result

    def propose_inbound_offer(self, raw_body, raw_media, media_mime):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _use_provider(monkeypatch, result) -> None:
    monkeypatch.setattr(inbound_mod, "get_provider", lambda: _FakeProvider(result))


@pg
def test_a_parsed_candidate_never_carries_a_price_field_the_model_computed(client, monkeypatch):
    """The proposal schema has no reference, buyer price, or margin field at
    all -- structural, not a convention a prompt could drift away from."""
    _use_provider(monkeypatch, _proposal())
    r = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "DRC Richebourg 2015"})
    assert r.status_code == 201
    proposal = r.json()["proposal"]
    assert set(proposal) == {
        "category", "producer", "cuvee", "vintage", "bottle_ml", "pack_size", "quantity",
        "total_bottles", "bond_status", "stock_location", "packaging", "asking_price",
        "asking_currency", "asking_basis", "reasoning", "want_list_hint"}
    assert proposal["asking_price"] == "2,800"  # exactly what the fake "read", never recomputed


@pg
def test_absent_information_stays_absent_not_guessed(client, monkeypatch):
    _use_provider(monkeypatch, _proposal(packaging=None, bond_status=None))
    r = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "some offer"})
    proposal = r.json()["proposal"]
    assert proposal["packaging"] is None
    assert proposal["bond_status"] is None


@pg
def test_a_provider_outage_is_502_and_leaves_the_raw_capture_untouched(client, monkeypatch, conn):
    """Decision 0040 at the provider boundary: an outage must read as
    'couldn't check', never as a clean parse, and the raw text that
    triggered the call must survive the failure."""
    _use_provider(monkeypatch, RuntimeError("simulated outage"))
    raw_text = "a seller's WhatsApp message, verbatim"
    r = client.post("/inbound-offers", json={"channel": "paste", "raw_body": raw_text})
    assert r.status_code == 502
    # the one field that matters survives the 502, or a first-call failure
    # leaves the caller with no id to ever retry against
    offer_id = r.json()["detail"]["inbound_offer_id"]
    row = conn.execute("SELECT * FROM inbound_offer WHERE inbound_offer_id = %s",
                       (offer_id,)).fetchone()
    assert row["raw_body"] == raw_text
    assert row["parse_state"] == "pending"          # retryable, not a verdict
    assert "simulated outage" in row["parse_error"]
    assert row["category"] is None


@pg
def test_provider_outage_is_distinct_from_the_model_finding_nothing(client, monkeypatch):
    """Two different 'nothing to show' outcomes must never collapse into
    the same shape: a transient failure (502, retry) is not the same fact
    as the model running fine and concluding there is no offer here (201,
    parse_state='unparseable')."""
    _use_provider(monkeypatch, RuntimeError("outage"))
    outage = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"})
    assert outage.status_code == 502

    _use_provider(monkeypatch, _proposal(category="unknown", producer=None, cuvee=None,
                                         vintage=None, bottle_ml=None, pack_size=None,
                                         quantity=None, bond_status=None, stock_location=None,
                                         asking_price=None, asking_currency=None,
                                         reasoning="not a wine or whisky offer"))
    nothing_found = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "y"})
    assert nothing_found.status_code == 201
    assert nothing_found.json()["offer"]["parse_state"] == "unparseable"


@pg
def test_a_bad_parse_is_reparsed_never_reconstructed(client, monkeypatch, conn):
    _use_provider(monkeypatch, RuntimeError("outage"))
    raw_text = "DRC Richebourg 2015, 3 bottles"
    r = client.post("/inbound-offers", json={"channel": "paste", "raw_body": raw_text})
    assert r.status_code == 502
    row = conn.execute("SELECT inbound_offer_id FROM inbound_offer").fetchone()

    _use_provider(monkeypatch, _proposal())
    r = client.post(f"/inbound-offers/{row['inbound_offer_id']}/reparse")
    assert r.status_code == 200
    assert r.json()["offer"]["parse_state"] == "parsed"
    # the retry read the SAME stored raw text, not a reconstruction of it
    assert conn.execute("SELECT raw_body FROM inbound_offer WHERE inbound_offer_id = %s",
                        (row["inbound_offer_id"],)).fetchone()["raw_body"] == raw_text


@pg
def test_the_photo_gate_refuses_a_want_list_wine_without_explicit_acknowledgement(
        client, monkeypatch, conn):
    wine_id = _wine(conn, want_list=True)
    supplier_id = _supplier(client)
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "photo", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]

    refused = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                          json={"wine_id": wine_id, "vintage": 2015, "bottle_ml": 750,
                                "pack_size": 1, "supplier_id": supplier_id})
    assert refused.status_code == 422
    assert "want-list" in refused.json()["detail"]

    confirmed = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                            json={"wine_id": wine_id, "vintage": 2015, "bottle_ml": 750,
                                  "pack_size": 1, "want_list_ack": True,
                                  "supplier_id": supplier_id})
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed_wine_id"] == wine_id
    assert confirmed.json()["identity_confirmed_by"]["username"] == OPERATOR["username"]


@pg
def test_no_confidence_score_field_exists_to_override_the_photo_gate(client, monkeypatch, conn):
    """There must be no threshold anywhere in this path -- asserted by the
    absence of the field, not by a behavioural probe that could rot."""
    import app.api.schemas as s
    assert "confidence" not in s.ConfirmIdentityIn.model_fields
    assert "confidence" not in s.InboundOfferProposalOut.model_fields


@pg
def test_an_ordinary_producer_needs_no_acknowledgement(client, monkeypatch, conn):
    wine_id = _wine(conn, producer="Chateau Nothing Special", cuvee="Grand Vin", want_list=False)
    _use_provider(monkeypatch, _proposal(producer="Chateau Nothing Special", cuvee="Grand Vin"))
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 1,
                         "supplier_id": _supplier(client)})
    assert r.status_code == 200


@pg
def test_a_whisky_offer_cannot_be_given_an_identity(client, monkeypatch, conn):
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal(category="whisky", producer=None, cuvee=None,
                                         vintage=None, bottle_ml=None, pack_size=None,
                                         reasoning="cask number and age statement, not a wine"))
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    assert offer["offer"]["category"] == "whisky"
    assert offer["offer"]["parse_state"] == "parsed"
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 1,
                         "supplier_id": _supplier(client)})
    assert r.status_code == 422


@pg
def test_the_photo_is_served_back_for_display_next_to_the_proposed_identity(client, monkeypatch):
    import base64
    _use_provider(monkeypatch, _proposal())
    media = base64.b64encode(b"not a real jpeg, just bytes").decode()
    r = client.post("/inbound-offers", json={"channel": "photo", "raw_media_base64": media,
                                             "media_mime": "image/jpeg"})
    assert r.status_code == 201
    assert r.json()["offer"]["has_media"] is True
    offer_id = r.json()["offer"]["inbound_offer_id"]
    got = client.get(f"/inbound-offers/{offer_id}/media")
    assert got.status_code == 200
    assert got.content == b"not a real jpeg, just bytes"
    assert got.headers["content-type"] == "image/jpeg"


@pg
def test_a_text_only_offer_has_no_media_to_serve(client, monkeypatch):
    _use_provider(monkeypatch, _proposal())
    r = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "text only"})
    offer_id = r.json()["offer"]["inbound_offer_id"]
    assert client.get(f"/inbound-offers/{offer_id}/media").status_code == 404


@pg
def test_creating_with_neither_text_nor_media_is_refused_before_any_provider_call(client):
    r = client.post("/inbound-offers", json={"channel": "paste"})
    assert r.status_code == 422


# ---------------------------------------------- candidate-wines filtering

@pg
def test_candidate_wines_is_empty_with_no_producer_proposed(client):
    r = client.get("/inbound-offers/candidate-wines")
    assert r.status_code == 200
    assert r.json() == []


@pg
def test_candidate_wines_filters_to_the_proposed_producer_only(client, conn):
    _wine(conn, producer="Coche-Dury", cuvee="Meursault Les Perrières", want_list=True)
    _wine(conn, producer="Coche-Dury", cuvee="Monthélie", want_list=True)
    _wine(conn, producer="Domaine Leflaive", cuvee="Bâtard-Montrachet", want_list=True)
    r = client.get("/inbound-offers/candidate-wines", params={"producer": "Coche-Dury"})
    assert r.status_code == 200
    groups = r.json()
    assert len(groups) == 1
    assert groups[0]["producer"] == "Coche-Dury"
    assert {w["cuvee"] for w in groups[0]["wines"]} == {"Meursault Les Perrières", "Monthélie"}


@pg
def test_candidate_wines_ranks_the_closest_cuvee_first_despite_accent_and_les(client, conn):
    """Doug's own example: "Meursault Perrieres" (AI's loose text) has
    neither the accent nor the inserted "Les" that "Meursault Les
    Perrières" carries, and must still rank it first among Coche-Dury's
    other, unrelated cuvées."""
    _wine(conn, producer="Coche-Dury", cuvee="Monthélie", want_list=True)
    _wine(conn, producer="Coche-Dury", cuvee="Meursault Les Perrières", want_list=True)
    _wine(conn, producer="Coche-Dury", cuvee="Auxey-Duresses", want_list=True)
    r = client.get("/inbound-offers/candidate-wines",
                   params={"producer": "Coche-Dury", "cuvee": "Meursault Perrieres"})
    cuvees = [w["cuvee"] for w in r.json()[0]["wines"]]
    assert cuvees[0] == "Meursault Les Perrières"


@pg
def test_candidate_wines_shows_the_always_review_fork_as_its_own_group(client, conn):
    """A bare "Leroy" match carries Maison Leroy as its known real-world
    fork — the list itself must show both groups, not only the warning
    text above it, even when the fork alternate has nothing registered."""
    _wine(conn, producer="Domaine Leroy", cuvee="Richebourg", want_list=True)
    r = client.get("/inbound-offers/candidate-wines", params={"producer": "Leroy"})
    groups = r.json()
    names = {g["producer"]: g for g in groups}
    assert "Domaine Leroy" in names and names["Domaine Leroy"]["is_fork_alternate"] is False
    assert "Maison Leroy" in names and names["Maison Leroy"]["is_fork_alternate"] is True
    assert names["Maison Leroy"]["wines"] == []


@pg
def test_candidate_wines_falls_back_to_literal_text_for_a_non_want_list_producer(client, conn):
    _wine(conn, producer="Chateau Nothing Special", cuvee="Grand Vin", want_list=False)
    r = client.get("/inbound-offers/candidate-wines",
                   params={"producer": "Chateau Nothing Special"})
    groups = r.json()
    assert len(groups) == 1
    assert groups[0]["producer"] == "Chateau Nothing Special"
    assert groups[0]["is_fork_alternate"] is False


def test_openai_and_gemini_stay_unimplemented_for_this_capability():
    from app.ai.openai_provider import OpenAIProvider
    from app.ai.gemini_provider import GeminiProvider
    for cls in (OpenAIProvider, GeminiProvider):
        with pytest.raises(NotImplementedError):
            cls()


# ------------------------------------------- AnthropicProvider, no network
#
# Confirmed live against the real API, 28 October 2026: Sonnet 5.5 (and the
# rest of the 5.x/Fable 5.1 generation) 400s on tool_choice={"type":
# "tool"|"any"} outright, which is what originally broke this in
# production. These mock client.messages.parse() directly -- no network,
# no API key spend -- and exist to keep that migration from regressing.

def _fake_response(stop_reason="end_turn", data=None):
    """`data=None` means no text block at all (e.g. a pure-thinking
    response); otherwise `data` is the dict that becomes the model's
    JSON text, read by TYPE (never by index) exactly as the real code
    does, so a thinking block ahead of it would never break this."""
    import json as _json
    content = []
    if data is not None:
        content.append(type("FakeBlock", (), {"type": "text", "text": _json.dumps(data)})())
    return type("FakeResponse", (), {"stop_reason": stop_reason, "content": content})()


def _provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    from app.ai.anthropic_provider import AnthropicProvider
    return AnthropicProvider()


def test_anthropic_provider_never_forces_tool_choice(monkeypatch):
    from app.ai.anthropic_provider import PROPOSAL_SCHEMA
    provider = _provider(monkeypatch)
    captured = {}

    def fake_create(**kw):
        captured.update(kw)
        return _fake_response(data={"category": "wine", "producer": "X", "reasoning": "y"})

    monkeypatch.setattr(provider._client.messages, "create", fake_create)
    result = provider.propose_inbound_offer("some text", None, None)
    assert "tool_choice" not in captured
    assert "tools" not in captured
    assert captured["output_config"] == {"format": {"type": "json_schema", "schema": PROPOSAL_SCHEMA}}
    assert result.producer == "X"


def test_anthropic_provider_sends_thinking_between_tools_alone(monkeypatch):
    provider = _provider(monkeypatch)
    captured = {}

    def fake_create(**kw):
        captured.update(kw)
        return _fake_response(data={"category": "unknown", "reasoning": "z"})

    monkeypatch.setattr(provider._client.messages, "create", fake_create)
    provider.propose_inbound_offer("x", None, None)
    assert captured["thinking"] == {"type": "between_tools"}


def test_anthropic_provider_never_sets_temperature_top_p_or_top_k(monkeypatch):
    """These three ERROR on this model generation -- asserted by absence,
    not by a call that would only fail once Anthropic's API is reached."""
    provider = _provider(monkeypatch)
    captured = {}

    def fake_create(**kw):
        captured.update(kw)
        return _fake_response(data={"category": "unknown", "reasoning": "z"})

    monkeypatch.setattr(provider._client.messages, "create", fake_create)
    provider.propose_inbound_offer("x", None, None)
    assert not {"temperature", "top_p", "top_k"} & captured.keys()


def test_anthropic_provider_refuses_a_truncated_or_refused_response(monkeypatch):
    """Truncated JSON that happens to still parse is exactly the silent-
    wrong-answer case the three-state discipline exists to prevent -- it
    must never become a candidate, whatever stop_reason produced it."""
    provider = _provider(monkeypatch)
    for bad_reason in ("max_tokens", "refusal", "pause_turn"):
        def fake_create(r=bad_reason, **kw):
            return _fake_response(stop_reason=r, data={"category": "wine", "reasoning": "x"})
        monkeypatch.setattr(provider._client.messages, "create", fake_create)
        with pytest.raises(RuntimeError, match="stop_reason"):
            provider.propose_inbound_offer("some text", None, None)


def test_anthropic_provider_schema_forbids_additional_properties():
    from app.ai.anthropic_provider import PROPOSAL_SCHEMA
    assert PROPOSAL_SCHEMA["additionalProperties"] is False


def test_anthropic_proposal_schema_never_uses_anyof():
    """Found live, 29-30 October 2026: "Error code: 400 - Schema is too
    complex" -- Anthropic's own structured-outputs grammar compiler,
    driven far more by the number of anyOf/union branches than by raw
    schema size. PROPOSAL_SCHEMA is hand-written specifically to avoid
    Pydantic's default Optional[X]=None -> anyOf pattern; this fails the
    moment anyOf creeps back in, by hand or by switching back to
    output_format=_ProposalWire."""
    import json as _json
    from app.ai.anthropic_provider import PROPOSAL_SCHEMA
    assert "anyOf" not in _json.dumps(PROPOSAL_SCHEMA)


def test_anthropic_proposal_schema_round_trips_through_the_validator():
    """The hand-written request schema and the Pydantic response
    validator must agree on every field name -- nothing here silently
    diverges the two."""
    from app.ai.anthropic_provider import PROPOSAL_SCHEMA, _ProposalWire
    assert set(PROPOSAL_SCHEMA["properties"]) == set(_ProposalWire.model_fields)


def test_asking_basis_never_combines_an_enum_with_a_nullable_type():
    """Found live, 30 October 2026: "Error code: 400 - output_config.
    format.schema: Invalid schema: Enum value 'per_bottle' does not
    match declared type ['string', 'null']" -- Anthropic's own schema
    compiler rejects an enum paired with a nullable type array. The grammar
    says text-or-null; _ProposalWire alone enforces the three real values."""
    from app.ai.anthropic_provider import PROPOSAL_SCHEMA, _ProposalWire
    basis = PROPOSAL_SCHEMA["properties"]["asking_basis"]
    assert basis == {"type": ["string", "null"]}
    for prop in PROPOSAL_SCHEMA["properties"].values():
        assert not ("enum" in prop and isinstance(prop["type"], list)), prop
    with pytest.raises(Exception):
        _ProposalWire.model_validate({**{k: None for k in PROPOSAL_SCHEMA["properties"]},
                                      "category": "wine", "reasoning": "x",
                                      "asking_basis": "per_magnum"})


def test_every_proposal_field_is_required_absence_is_null():
    """Measured live, 30 October 2026, on the real Salon request: 13
    OPTIONAL fields failed 9 calls of 9 ("Schema is too complex", or a
    connection cut at ~60s) whatever the thinking setting; every field
    required answered 3 of 3 in under 6s. Optional fields are the cost."""
    from app.ai.anthropic_provider import PROPOSAL_SCHEMA
    assert PROPOSAL_SCHEMA["required"] == list(PROPOSAL_SCHEMA["properties"])


def test_anthropic_client_timeout_stays_under_vercels_function_ceiling(monkeypatch):
    """Found live, 29 October 2026: the SDK's own default is a 10-minute
    timeout with 2 retries. Vercel kills this function at 60s
    (vercel.json's maxDuration) with NO response ever sent to the
    browser -- "taking forever and not fetching", not a clean 502 this
    app's own three-state handling could catch. The client's configured
    timeout must stay comfortably under that ceiling so a slow or flaky
    call fails fast into app/api/inbound.py's existing except Exception,
    never silently outlives the whole process."""
    provider = _provider(monkeypatch)
    assert provider._client.timeout < 60
    assert provider._client.max_retries == 0


def test_anthropic_client_timeout_leaves_room_for_a_real_parse(monkeypatch):
    """Found live, 30 October 2026: at 20s every production paste timed out
    at ~22.4s, while a real successful parse had taken 41.3s. The limit must
    cover that, and still leave the 60s function ceiling room to answer."""
    provider = _provider(monkeypatch)
    assert 45 <= provider._client.timeout <= 50


# ---------------------------------------- supplier attribution (spec, 29 Oct 2026)

@pg
def test_confirm_identity_requires_a_supplier_id(client, monkeypatch, conn):
    """Capture is never blocked; confirmation always is -- the same shape
    want_list_ack already uses, enforced here by the type system itself
    (no default on the field) rather than application logic."""
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 1})
    assert r.status_code == 422


@pg
def test_confirm_identity_refuses_an_unknown_supplier_id(client, monkeypatch, conn):
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 1,
                         "supplier_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 404


@pg
def test_confirmed_offer_carries_its_supplier_id(client, monkeypatch, conn):
    wine_id = _wine(conn, want_list=False)
    supplier_id = _supplier(client, name="Vinum")
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 1,
                         "supplier_id": supplier_id})
    assert r.status_code == 200
    assert r.json()["supplier_id"] == supplier_id
    assert client.get(f"/inbound-offers/{offer_id}").json()["supplier_id"] == supplier_id


@pg
def test_creating_a_supplier_registers_its_own_name_as_an_alias(client, monkeypatch, conn):
    """"Matching improves with use rather than requiring a backfill" —
    the name itself is the one alias guaranteed to exist with no extra
    field in the quick-add form."""
    _supplier(client, name="Vinum")
    _use_provider(monkeypatch, _proposal())
    r = client.post("/inbound-offers",
                    json={"channel": "paste", "raw_body": "Hi Doug, James at Vinum here"})
    assert len(r.json()["matched_supplier_ids"]) == 1


@pg
def test_supplier_alias_match_is_deterministic_not_the_model(client, monkeypatch, conn):
    """The AI never proposes a supplier, is never asked to, and the match
    fires even when the fake provider's proposal carries no hint of one —
    this is a plain substring check against raw_body, not a model call."""
    vinum = _supplier(client, name="Vinum")
    other = _supplier(client, name="Berry Bros")
    _use_provider(monkeypatch, _proposal())  # no supplier field exists to set
    r = client.post("/inbound-offers",
                    json={"channel": "paste", "raw_body": "offer from Vinum, 3 bottles"})
    assert r.json()["matched_supplier_ids"] == [vinum]

    r2 = client.post("/inbound-offers",
                     json={"channel": "paste", "raw_body": "no supplier mentioned here at all"})
    assert r2.json()["matched_supplier_ids"] == []


@pg
def test_two_alias_matches_highlight_both_with_no_ordering_preference(client, monkeypatch, conn):
    a = _supplier(client, name="Vinum")
    b = _supplier(client, name="Vinum Direct")
    _use_provider(monkeypatch, _proposal())
    r = client.post("/inbound-offers",
                    json={"channel": "paste", "raw_body": "from Vinum Direct this time"})
    assert set(r.json()["matched_supplier_ids"]) == {a, b}


@pg
def test_suppliers_list_orders_most_recently_used_first(client, monkeypatch, conn):
    wine_id = _wine(conn, want_list=False)
    older = _supplier(client, name="Older Supplier")
    newer = _supplier(client, name="Newer Supplier")
    _use_provider(monkeypatch, _proposal())

    def confirm_with(supplier_id):
        offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
        offer_id = offer["offer"]["inbound_offer_id"]
        return client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                           json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750,
                                 "pack_size": 1, "supplier_id": supplier_id})

    assert confirm_with(older).status_code == 200
    assert confirm_with(newer).status_code == 200
    names = [sp["name"] for sp in client.get("/suppliers").json()]
    assert names.index("Newer Supplier") < names.index("Older Supplier")


def test_the_ai_never_proposes_a_supplier():
    """Structural, not behavioural: there is no field for the model to
    fill in, on either the wire schema or the dataclass boundary — the
    same discipline InboundOfferProposal's own docstring already states
    for a price. Checked on all three surfaces the field could hide in."""
    import app.api.schemas as s
    from app.ai.anthropic_provider import SYSTEM_PROMPT, _ProposalWire
    from app.ai.provider import InboundOfferProposal

    assert "supplier" not in _ProposalWire.model_fields
    assert "supplier" not in {f.name for f in InboundOfferProposal.__dataclass_fields__.values()}
    assert "supplier" not in s.InboundOfferProposalOut.model_fields
    assert "supplier" not in SYSTEM_PROMPT.lower()


# ------------------------------------- commercial unit fork, asking_basis (29 Oct 2026)

@pg
def test_an_ambiguous_commercial_unit_carries_total_bottles_not_a_guessed_split(
        client, monkeypatch):
    """"6 x [wine] OWC" reads as one case of six or six loose bottles, and
    a case priced against single-bottle comps is simply wrong (decision
    0028) -- the proposal must carry the one clear fact (six bottles)
    and leave the split to the operator, never guess either answer."""
    _use_provider(monkeypatch, _proposal(pack_size=None, quantity=None, total_bottles=6))
    r = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "6 x wine OWC"})
    proposal = r.json()["proposal"]
    assert proposal["pack_size"] is None
    assert proposal["quantity"] is None
    assert proposal["total_bottles"] == 6


@pg
def test_confirm_identity_blocks_a_priced_multi_bottle_line_with_no_asking_basis(
        client, monkeypatch, conn):
    """A price with no stated unit is ambiguous by exactly the multiple
    pack_size would convert it by -- blocking, not a detail, the moment
    more than one bottle is involved."""
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 6,
                         "quantity": 1, "asking_price": "2520.00", "asking_currency": "GBP",
                         "supplier_id": _supplier(client)})
    assert r.status_code == 422
    assert "basis" in r.json()["detail"]


@pg
def test_confirm_identity_allows_a_single_bottle_line_with_no_asking_basis(client, monkeypatch, conn):
    """Exactly one bottle has no such ambiguity: per_bottle, per_case and
    total are numerically identical there."""
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 1,
                         "quantity": 1, "asking_price": "420.00", "asking_currency": "GBP",
                         "supplier_id": _supplier(client)})
    assert r.status_code == 200


@pg
def test_confirm_identity_persists_the_full_commercial_record(client, monkeypatch, conn):
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity", json={
        "wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 6, "quantity": 1,
        "packaging": "OWC", "bond_status": "UK In Bond", "stock_location": "LCB",
        "asking_price": "2520.00", "asking_currency": "GBP", "asking_basis": "per_case",
        "supplier_id": _supplier(client)})
    assert r.status_code == 200, r.text
    got = client.get(f"/inbound-offers/{offer_id}").json()
    assert got["confirmed_quantity"] == 1
    assert got["confirmed_packaging"] == "OWC"
    assert got["confirmed_bond_status"] == "UK In Bond"
    assert got["confirmed_stock_location"] == "LCB"
    assert got["confirmed_asking_price"] == "2520.00"
    assert got["confirmed_asking_currency"] == "GBP"
    assert got["confirmed_asking_basis"] == "per_case"


@pg
def test_a_price_with_no_quantity_given_needs_no_basis_to_confirm(client, monkeypatch, conn):
    """Confirmation never blocks on a price that was never offered in
    the first place -- only on an existing price with an ambiguous unit."""
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal(asking_price=None, asking_currency=None,
                                         asking_basis=None))
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity",
                    json={"wine_id": wine_id, "vintage": 2018, "bottle_ml": 750, "pack_size": 6,
                         "quantity": 1, "supplier_id": _supplier(client)})
    assert r.status_code == 200


# ---------------------------------------------- EVALUATE, facts only (29 Oct 2026)

@pg
def test_evaluate_refuses_an_offer_whose_identity_is_not_yet_confirmed(client, monkeypatch, conn):
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    r = client.post(f"/inbound-offers/{offer_id}/evaluate")
    assert r.status_code == 422


@pg
def test_no_market_is_the_primary_state_not_an_error_shape(client, monkeypatch, conn):
    """Merchant evidence on the 20 want-list producers is measurably
    thin to absent -- this must be a clean 200 with a real state and a
    named list of what was checked, never a 404/500-shaped surprise."""
    wine_id = _wine(conn, want_list=False)
    # A merchant needs SOME resolved capture, anywhere, for "sources" to
    # be non-empty at all -- otherwise the engine can't tell NO_MARKET
    # (searched, found nothing) apart from "nothing has ever run" at the
    # whole-system level. An unrelated wine's own offer supplies that,
    # while leaving THIS wine_id itself with zero comps.
    other_wine = _wine(conn, producer="Someone Else", cuvee="Unrelated Wine", want_list=False)
    _seed_offers(conn, wine_id=other_wine, vintage=2015, prices=["50.00"])
    _use_provider(monkeypatch, _proposal())
    offer_id = _confirmed_offer(client, conn, wine_id=wine_id)
    r = client.post(f"/inbound-offers/{offer_id}/evaluate")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "NO_MARKET"
    assert body["blocks_create_offer"] is True
    assert "no Floor" in body["block_reason"]
    assert body["checked_merchants"], "must name what was actually checked"
    assert body["walk_away"] is None


@pg
def test_a_real_floor_produces_the_walk_away_price(client, monkeypatch, conn):
    """Matches buy-side-margin-test.md's own worked example to the penny:
    Floor £3,400/bt, max sell £3,230, walk-away £2,990.74, ask £2,800/bt
    -> headroom £190.74/bt, £8,400 across the 3-bottle line, margin
    15.4%. pack_size=1 here, so uk_floor IS the per-bottle figure (the
    engine's own Offer.price is "for ONE unit as defined by pack_size")
    -- seeding comps at a line-total-shaped number under pack_size=1
    is exactly the bug this test exists to catch."""
    wine_id = _wine(conn, want_list=False)
    _seed_offers(conn, wine_id=wine_id, vintage=2015, prices=["3400.00", "3500.00"],
                bottle_ml=750, pack_size=1)
    _use_provider(monkeypatch, _proposal())
    offer_id = _confirmed_offer(client, conn, wine_id=wine_id, vintage=2015, bottle_ml=750,
                               pack_size=1, quantity=3,
                               asking_price="2800.00", asking_currency="GBP",
                               asking_basis="per_bottle")
    r = client.post(f"/inbound-offers/{offer_id}/evaluate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "READY"
    assert body["walk_away"]["uk_floor"] == "3400.00"
    assert body["walk_away"]["max_sell"] == "3230.00"
    assert body["walk_away"]["walk_away"] == "2990.74"
    # ask stated per bottle (£2,800); pack_size=1 so per-unit is identical;
    # total is across the line's own quantity=3
    assert body["ask"]["per_unit"] == "2800.00"
    assert body["ask"]["total"] == "8400.00"
    assert body["headroom"] == "190.74"
    assert round(Decimal(body["margin_at_ask_pct"]), 1) == Decimal("15.4")
    assert body["blocks_create_offer"] is False


@pg
def test_an_ask_above_walk_away_blocks_with_the_required_sell_named(client, monkeypatch, conn):
    """buy-side-margin-test.md's second worked example: ask £3,200/bt
    against the same £3,400/bt Floor needs a sell of £3,456/bt at 8% —
    above the Floor, which decision 0033 forbids."""
    wine_id = _wine(conn, want_list=False)
    _seed_offers(conn, wine_id=wine_id, vintage=2015, prices=["3400.00", "3500.00"])
    _use_provider(monkeypatch, _proposal())
    offer_id = _confirmed_offer(client, conn, wine_id=wine_id, vintage=2015, quantity=3,
                               asking_price="3200.00", asking_currency="GBP",
                               asking_basis="per_bottle")
    r = client.post(f"/inbound-offers/{offer_id}/evaluate")
    body = r.json()
    assert body["blocks_create_offer"] is True
    assert body["required_sell_for_margin"] == "3456.00"
    assert body["exceeds_floor"] is True
    assert "above walk-away" in body["block_reason"]


@pg
def test_a_one_comp_line_is_review_and_blocks_regardless_of_the_ask(client, monkeypatch, conn):
    """Review flags come first (buy-side-margin-test.md): ONE_COMP is
    already a REVIEW_FLAGS member, so this blocks even when the ask
    sits comfortably below walk-away."""
    wine_id = _wine(conn, want_list=False)
    _seed_offers(conn, wine_id=wine_id, vintage=2015, prices=["3400.00"])
    _use_provider(monkeypatch, _proposal())
    offer_id = _confirmed_offer(client, conn, wine_id=wine_id, vintage=2015, quantity=3,
                               asking_price="2000.00", asking_currency="GBP",
                               asking_basis="per_bottle")
    r = client.post(f"/inbound-offers/{offer_id}/evaluate")
    body = r.json()
    assert body["state"] == "REVIEW"
    assert "ONE_COMP" in body["flags"]
    assert body["blocks_create_offer"] is True
    assert "review" in body["block_reason"]
    # the number itself still shows -- a fact, not withheld as a verdict
    assert body["walk_away"] is not None


@pg
def test_evaluate_is_idempotent_reusing_the_same_deal_and_line(client, monkeypatch, conn):
    wine_id = _wine(conn, want_list=False)
    _use_provider(monkeypatch, _proposal())
    offer_id = _confirmed_offer(client, conn, wine_id=wine_id)
    first = client.post(f"/inbound-offers/{offer_id}/evaluate").json()
    second = client.post(f"/inbound-offers/{offer_id}/evaluate").json()
    assert first["deal_id"] == second["deal_id"]
    assert first["line_id"] == second["line_id"]


@pg
def test_evaluate_renders_no_verdict_language(client, monkeypatch, conn):
    """Structural: the response has no field a verdict could live in."""
    import app.api.schemas as s
    forbidden = {"verdict", "score", "rating", "recommendation", "is_good_buy"}
    assert not forbidden & set(s.EvaluateOut.model_fields)


# ------------------------------------------- Milestone 1: price, offer, confirm
# One real one-line trade: Rousseau-shaped, 3 x 75cl loose, supplier
# £2,800/bt, two merchants at £3,400 and £3,500 (Floor £3,400).


def _priced_offer(client, conn, monkeypatch, *, prices=("3400.00", "3500.00"), want_list=False,
                  asking_price="2800.00", currency="GBP", nothing_collected=False):
    wine_id = _wine(conn, producer="Armand Rousseau", cuvee="Clos St Jacques",
                    want_list=want_list)
    if nothing_collected:
        pass
    elif prices:
        _seed_offers(conn, wine_id=wine_id, vintage=2015, prices=list(prices))
    else:
        other = _wine(conn, producer="Someone Else", cuvee="Unrelated", want_list=False)
        _seed_offers(conn, wine_id=other, vintage=2015, prices=["50.00"])
    _use_provider(monkeypatch, _proposal())
    offer = client.post("/inbound-offers", json={"channel": "paste", "raw_body": "x"}).json()
    offer_id = offer["offer"]["inbound_offer_id"]
    body = {"wine_id": wine_id, "vintage": 2015, "bottle_ml": 750, "pack_size": 1, "quantity": 3,
            "supplier_id": _supplier(client, "ABC Wines"), "asking_price": asking_price,
            "asking_currency": currency, "asking_basis": "per_bottle",
            "bond_status": "UK IB", "stock_location": "LCB", "want_list_ack": want_list}
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity", json=body)
    assert r.status_code == 200, r.text
    ev = client.post(f"/inbound-offers/{offer_id}/evaluate")
    assert ev.status_code == 200, ev.text
    return offer_id, ev.json()


def _offer(client, offer_id, vessel_sell, **kw):
    return client.post(f"/inbound-offers/{offer_id}/offer",
                       json={"vessel_sell": vessel_sell, **kw})


@pg
def test_pricing_screen_carries_the_four_prices(client, monkeypatch, conn):
    """SUPPLIER £2,800/bt, MARKET the Floor £3,400/bt from two merchants,
    no AUCTION evidence at all, VESSEL SELL defaulting to £3,024 (+8%)."""
    _, ev = _priced_offer(client, conn, monkeypatch)
    assert ev["ask"]["per_bottle"] == "2800.00"
    assert ev["market"]["floor_per_bottle"] == "3400.00"
    assert ev["market"]["comp_count"] == 2
    assert [c["per_bottle"] for c in ev["market"]["comps"]] == ["3400.00", "3500.00"]
    assert ev["market"]["checked_at"] is not None
    assert ev["auction"] is None
    assert ev["default_vessel_sell"] == "3024.00"
    assert Decimal(ev["min_trade_margin"]) == Decimal("0.08")
    assert (ev["producer"], ev["quantity"], ev["bond_status"]) == ("Armand Rousseau", 3, "UK IB")
    assert ev["committed"] is None and ev["fulfilment"] is None


@pg
def test_auction_is_the_existing_health_median_never_blended_into_market(client, monkeypatch, conn):
    from datetime import date

    from app.auction import repo as auction_repo
    offer_id, ev = _priced_offer(client, conn, monkeypatch)
    op = conn.execute("SELECT operator_id FROM operator").fetchone()["operator_id"]
    wine_id = conn.execute("SELECT confirmed_wine_id FROM inbound_offer WHERE inbound_offer_id = %s",
                           (offer_id,)).fetchone()["confirmed_wine_id"]
    auction_repo.record_auction_evidence(
        conn, wine_id=str(wine_id), vintage=2015, bottle_ml=750, bottles_in_lot=3,
        auction_house="CHRISTIES", sale_date=date(2026, 9, 12), lot_ref="101",
        source_url="https://example.com/lot/101", currency="GBP", amount=Decimal("9150.00"),
        amount_basis="HAMMER", entered_by=str(op))
    ev = client.post(f"/inbound-offers/{offer_id}/evaluate").json()
    assert ev["auction"] == {"median_per_bottle": "3050.00", "lot_count": 1,
                             "latest_sale_date": "2026-09-12"}
    assert ev["market"]["floor_per_bottle"] == "3400.00"


@pg
def test_create_offer_commits_the_vessel_sell_price_exactly(client, monkeypatch, conn):
    """£3,150 on £2,800 x 3: £350/bt gross, £1,050 total — stored as one
    parcel_trade pricing_result, the sell price exactly as entered."""
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    r = _offer(client, offer_id, "3150.00", availability="Available now")
    assert r.status_code == 200, r.text
    c = r.json()["committed"]
    assert (c["vessel_sell"], c["supplier_price"], c["gp"]) == ("3150.00", "2800.00", "350.00")
    assert Decimal(c["gp"]) * r.json()["quantity"] == Decimal("1050.00")
    assert c["requires_acknowledgement"] is False
    assert r.json()["availability"] == "Available now"
    row = conn.execute("SELECT price_basis, sell_price, cost FROM pricing_result").fetchone()
    assert (row["price_basis"], row["sell_price"], row["cost"]) == (
        "parcel_trade", Decimal("3150.00"), Decimal("2800.00"))


@pg
def test_a_fractional_pence_sell_price_is_refused_not_rounded(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    assert _offer(client, offer_id, "3150.005").status_code == 422
    assert conn.execute("SELECT count(*) AS n FROM pricing_result").fetchone()["n"] == 0


@pg
def test_selling_at_the_floor_needs_an_accept_and_writes_nothing_without_one(
        client, monkeypatch, conn):
    """Decision 0033 holds for a parcel trade: £3,400 against a £3,400 Floor
    is not below the market. Refused with the reason, nothing written; one
    accept and it goes through, recorded as that operator's acknowledgement."""
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    r = _offer(client, offer_id, "3400.00")
    assert r.status_code == 409
    assert r.json()["detail"]["needs_accept"] is True
    assert "not actually priced below the market" in r.json()["detail"]["error"]
    assert "0033" not in r.json()["detail"]["error"]
    assert conn.execute("SELECT count(*) AS n FROM pricing_result").fetchone()["n"] == 0
    r = _offer(client, offer_id, "3400.00", accept=True)
    assert r.status_code == 200, r.text
    assert r.json()["committed"]["accepted"] is True


@pg
def test_no_market_still_lets_doug_proceed_with_an_accept(client, monkeypatch, conn):
    """The 20 want-list producers usually have no merchant evidence at all;
    NO_MARKET gates (invariant 12) but never dead-ends the trade."""
    offer_id, ev = _priced_offer(client, conn, monkeypatch, prices=())
    assert ev["state"] == "NO_MARKET" and ev["market"] is None
    assert ev["market_note"] == "has no market found for it"
    assert ev["default_vessel_sell"] == "3024.00"
    r = _offer(client, offer_id, "3024.00")
    assert r.status_code == 409 and r.json()["detail"]["needs_accept"] is True
    assert _offer(client, offer_id, "3024.00", accept=True).status_code == 200


@pg
def test_a_want_list_acknowledgement_reaches_the_line(client, monkeypatch, conn):
    """Doug acknowledges a want-list wine at confirm-identity; without that
    reaching seller_line, decision 0038's own check would refuse every
    want-list trade at the share step."""
    offer_id, _ = _priced_offer(client, conn, monkeypatch, want_list=True)
    line = conn.execute("SELECT want_list_ack_by, want_list_ack_at FROM seller_line").fetchone()
    assert line["want_list_ack_by"] is not None and line["want_list_ack_at"] is not None
    assert _offer(client, offer_id, "3150.00").status_code == 200


@pg
def test_a_non_gbp_supplier_price_is_refused_in_plain_english(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch, currency="EUR")
    r = _offer(client, offer_id, "3150.00")
    assert r.status_code == 422
    assert "EUR" in r.json()["detail"]


@pg
def test_confirm_needs_an_offer_and_a_buyer(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    r = client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "Client X"})
    assert r.status_code == 422 and "create the offer first" in r.json()["detail"]
    assert _offer(client, offer_id, "3150.00").status_code == 200
    r = client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "   "})
    assert r.status_code == 422


@pg
def test_confirm_freezes_the_commercial_facts(client, monkeypatch, conn):
    """Buy £8,400, sell £9,450, gross £1,050 — and after CONFIRM neither the
    supplier price nor the sell price can change: not by re-pricing, not by
    re-confirming identity, not by an UPDATE straight to the table."""
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, offer_id, "3150.00", availability="Available now")
    r = client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "Client X"})
    assert r.status_code == 200, r.text
    f = r.json()["fulfilment"]
    assert (f["supplier_name"], f["buyer_name"], f["wine_name"]) == (
        "ABC Wines", "Client X", "Armand Rousseau Clos St Jacques 2015")
    assert (f["supplier_price"], f["vessel_sell_price"], f["gross_total"]) == (
        "2800.00", "3150.00", "1050.00")
    assert (f["quantity"], f["stock_location"], f["bond_status"], f["availability"]) == (
        3, "LCB", "UK IB", "Available now")
    assert f["state"] == "OPEN"

    assert _offer(client, offer_id, "3300.00").status_code == 409
    assert client.post(f"/inbound-offers/{offer_id}/confirm",
                       json={"buyer_name": "Someone"}).status_code == 409
    frozen = conn.execute("SELECT wine_id, supplier_id FROM fulfilment").fetchone()
    again = client.post(f"/inbound-offers/{offer_id}/confirm-identity", json={
        "wine_id": str(frozen["wine_id"]), "vintage": 2015, "bottle_ml": 750, "pack_size": 1,
        "quantity": 6, "supplier_id": str(frozen["supplier_id"])})
    assert again.status_code == 409
    with pytest.raises(psycopg.Error, match="frozen"):
        conn.execute("UPDATE fulfilment SET vessel_sell_price = 3300.00, gross_total = 1500.00")
    with pytest.raises(psycopg.Error, match="cannot be deleted"):
        conn.execute("DELETE FROM fulfilment")
    # reopening shows the agreed trade, never a fresh re-benchmark of it
    runs = conn.execute("SELECT count(*) AS n FROM benchmark_run").fetchone()["n"]
    ev = client.post(f"/inbound-offers/{offer_id}/evaluate").json()
    assert ev["fulfilment"]["vessel_sell_price"] == "3150.00"
    assert conn.execute("SELECT count(*) AS n FROM benchmark_run").fetchone()["n"] == runs


@pg
def test_a_confirmed_trade_completes_once(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, offer_id, "3150.00")
    f = client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "X"}).json()
    fid = f["fulfilment"]["fulfilment_id"]
    r = client.post(f"/fulfilments/{fid}/complete")
    assert r.status_code == 200 and r.json()["state"] == "COMPLETE"
    assert client.post(f"/fulfilments/{fid}/complete").status_code == 409


@pg
def test_changed_details_after_the_offer_block_confirm_until_it_is_recreated(
        client, monkeypatch, conn):
    """The supplier says only two are left: identity re-confirmed at
    quantity 2 after the offer was made at 3. Confirming the stale offer
    would freeze the wrong total."""
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    _offer(client, offer_id, "3150.00")
    row = conn.execute("SELECT * FROM inbound_offer").fetchone()
    r = client.post(f"/inbound-offers/{offer_id}/confirm-identity", json={
        "wine_id": str(row["confirmed_wine_id"]), "vintage": 2015, "bottle_ml": 750,
        "pack_size": 1, "quantity": 2, "supplier_id": str(row["supplier_id"]),
        "asking_price": "2800.00", "asking_currency": "GBP", "asking_basis": "per_bottle"})
    assert r.status_code == 200, r.text
    r = client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "X"})
    assert r.status_code == 409 and "create the offer again" in r.json()["detail"]
    assert _offer(client, offer_id, "3150.00").status_code == 422   # market not re-checked
    ev = client.post(f"/inbound-offers/{offer_id}/evaluate").json()
    assert ev["quantity"] == 2
    assert _offer(client, offer_id, "3150.00").status_code == 200
    f = client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "X"}).json()
    assert f["fulfilment"]["gross_total"] == "700.00"


@pg
def test_trades_list_shows_offers_out_then_confirmed(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch)
    assert client.get("/pocket/trades").json() == []
    _offer(client, offer_id, "3150.00")
    [t] = client.get("/pocket/trades").json()
    assert (t["state"], t["vessel_sell"], t["wine_name"], t["supplier_name"]) == (
        "OFFERED", "3150.00", "Armand Rousseau Clos St Jacques 2015", "ABC Wines")
    client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "Client X"})
    [t] = client.get("/pocket/trades").json()
    assert (t["state"], t["buyer_name"]) == ("CONFIRMED", "Client X")


# ------------------------- decision 0046: a never-searched line, parcel_trade only


@pg
def test_not_searched_is_its_own_state_never_blurred_into_no_market(client, monkeypatch, conn):
    """Production on 30 October 2026 had never collected anything at all:
    every Pocket trade dead-ended at CREATE OFFER. Never searched stays a
    distinct state from searched-and-found-nothing (invariant 10)."""
    _, ev = _priced_offer(client, conn, monkeypatch, nothing_collected=True)
    assert ev["state"] == "NOT_SEARCHED"
    assert ev["market"] is None
    assert ev["market_note"] == "has not been checked against the market"
    assert ev["checked_merchants"] == []
    assert ev["default_vessel_sell"] == "3024.00"


@pg
def test_a_never_searched_parcel_trade_proceeds_only_behind_an_accept(client, monkeypatch, conn):
    offer_id, _ = _priced_offer(client, conn, monkeypatch, nothing_collected=True)
    r = _offer(client, offer_id, "3024.00")
    assert r.status_code == 409 and r.json()["detail"]["needs_accept"] is True
    assert "has not been checked against the market" in r.json()["detail"]["error"]
    assert conn.execute("SELECT count(*) AS n FROM pricing_result").fetchone()["n"] == 0

    r = _offer(client, offer_id, "3024.00", accept=True)
    assert r.status_code == 200, r.text
    assert r.json()["committed"]["accepted"] is True
    row = conn.execute("SELECT state, run_id, uk_floor, requires_acknowledgement "
                       "FROM pricing_result").fetchone()
    assert (row["state"], row["run_id"], row["uk_floor"], row["requires_acknowledgement"]) == (
        "NOT_SEARCHED", None, None, True)
    ack = conn.execute("SELECT state FROM pricing_acknowledgement").fetchone()
    assert ack["state"] == "NOT_SEARCHED"

    f = client.post(f"/inbound-offers/{offer_id}/confirm", json={"buyer_name": "Client X"})
    assert f.status_code == 200, f.text
    assert f.json()["fulfilment"]["gross_total"] == "672.00"


@pg
def test_not_searched_pricing_is_refused_for_every_other_basis(client, monkeypatch, conn):
    """Invariant 10 holds everywhere else, structurally: a cellar line priced
    off the market may never carry a price nobody searched for."""
    offer_id, _ = _priced_offer(client, conn, monkeypatch, nothing_collected=True)
    _offer(client, offer_id, "3024.00", accept=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE pricing_result SET price_basis = 'manual'")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE pricing_result SET state = 'NO_MARKET'")


@pg
def test_once_anything_is_collected_a_never_checked_line_must_be_checked_first(
        client, monkeypatch, conn):
    """Not-searched may proceed only while there is genuinely nothing to
    search against; the moment evidence exists, EVALUATE must run first."""
    offer_id, ev = _priced_offer(client, conn, monkeypatch, nothing_collected=True)
    _seed_offers(conn, wine_id=conn.execute("SELECT wine_id FROM wine").fetchone()["wine_id"],
                 vintage=2015, prices=["3400.00", "3500.00"])
    r = _offer(client, offer_id, "3024.00", accept=True)
    assert r.status_code == 422 and "check the market again" in r.json()["detail"]
    ev = client.post(f"/inbound-offers/{offer_id}/evaluate").json()
    assert ev["state"] == "READY"
    assert _offer(client, offer_id, "3024.00").status_code == 200
