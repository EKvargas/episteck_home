from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from tests.support import FakeAuthorizer, seeded_service

HEADER = "X-Episteck-Delegation"


def _client(tmp_path, authorizer=None):
    service, authz = seeded_service(tmp_path, authorizer)
    return TestClient(create_app(service)), authz


def _walk(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def test_health_is_public(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}


def test_overview_without_a_delegation_is_401_and_never_calls_home(tmp_path):
    client, authz = _client(tmp_path)
    response = client.get("/overview")
    assert response.status_code == 401
    assert response.json() == {"detail": "SESSION_INVALID"}
    assert authz.calls == []


def test_overview_returns_subtotals_with_source_and_date(tmp_path):
    client, authz = _client(tmp_path)
    response = client.get("/overview", headers={HEADER: "  tok  "})
    assert response.status_code == 200
    body = response.json()
    assert body["subtotals"][0]["amount"] == "1234.56"
    assert body["accounts"][0]["source"] == "SIMPLEFIN"
    assert authz.calls[0][0] == "tok"
    assert not any(isinstance(v, float) for v in _walk(body))


@pytest.mark.parametrize("kwargs,status,detail", [
    (dict(mode="session_invalid"), 401, "SESSION_INVALID"),
    (dict(mode="unavailable"), 503, "SERVICE_UNAVAILABLE"),
    (dict(allow={"SELF": False}), 403, "ACCESS_DENIED"),
])
def test_refusals_use_fixed_bodies_without_homes_reason(tmp_path, kwargs, status, detail):
    client, _ = _client(tmp_path, FakeAuthorizer(**kwargs))
    response = client.get("/overview", headers={HEADER: "tok"})
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert "scripted" not in response.text


def test_paused_workspace_is_409_feature_off(tmp_path):
    service, _ = seeded_service(tmp_path)
    with service._repo.connection() as conn:  # noqa: SLF001 - fixture surgery
        conn.execute("UPDATE workspace SET status='PAUSED'")
    response = TestClient(create_app(service)).get("/overview", headers={HEADER: "tok"})
    assert response.status_code == 409
    assert response.json() == {"detail": "FEATURE_OFF"}


def test_actor_and_workspace_query_parameters_are_ignored(tmp_path):
    client, authz = _client(tmp_path)
    response = client.get("/overview?actor=PSN-9&workspace=ws-2&actor_person_id=PSN-9",
                          headers={HEADER: "tok"})
    assert response.status_code == 200
    subjects = {r.subject for r in authz.calls[0][1]}
    assert "PSN-9" not in subjects


def test_valuation_is_requested_explicitly_and_only_eur_is_supported(tmp_path):
    client, _ = _client(tmp_path)
    ok = client.get("/overview?valuation_currency=EUR", headers={HEADER: "tok"})
    assert ok.status_code == 200 and ok.json()["valuation"]["currency"] == "EUR"
    bad = client.get("/overview?valuation_currency=USD", headers={HEADER: "tok"})
    assert bad.status_code == 400
    assert bad.json() == {"detail": "UNSUPPORTED_VALUATION_CURRENCY"}


def test_logs_never_contain_amounts_ids_or_the_delegation(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    client, _ = _client(tmp_path)
    client.get("/overview", headers={HEADER: "secret-token-xyz"})
    other = tmp_path / "denied"
    other.mkdir()
    denied, _ = _client(other, FakeAuthorizer(allow={"SELF": False}))
    denied.get("/overview", headers={HEADER: "secret-token-xyz"})
    text = caplog.text
    for forbidden in ("secret-token-xyz", "1234.56", "123456", "PSN-", "acc-1"):
        assert forbidden not in text
