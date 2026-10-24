"""The one public Finance route: the PSD2 redirect at ``GET /connect/callback``."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.connectors.eb_auth import receive_callback
from tests.support import make_repo, seeded_service

NOW = datetime(2026, 10, 24, 18, 0, tzinfo=timezone.utc)
STATE = "S" * 20 + "-state-under-test_" + "0" * 5
CODE = "authorization-code-under-test"


@pytest.fixture
def wired(tmp_path):
    service, authz = seeded_service(tmp_path)
    repo = make_repo(tmp_path)  # the same database file the service uses
    state_hash = hashlib.sha256(STATE.encode()).hexdigest()
    repo.create_oauth_state(state_hash, "ws-1", "conn-1", "PSN-1", NOW + timedelta(minutes=15))

    def handler(state, code, error):
        return receive_callback(repo, state, code=code, error=error, now=NOW)

    return TestClient(create_app(service, callback=handler)), repo, state_hash, authz


def test_a_granted_callback_hands_the_code_over_and_echoes_nothing(wired):
    client, repo, state_hash, _ = wired
    response = client.get("/connect/callback", params={"state": STATE, "code": CODE})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "terminal" in response.text
    assert STATE not in response.text and CODE not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert repo.take_callback(state_hash).code == CODE


def test_a_refusal_at_the_bank_is_acknowledged_and_hands_over_no_code(wired):
    client, repo, state_hash, _ = wired
    response = client.get("/connect/callback", params={
        "state": STATE, "error": "access_denied", "error_description": "Cancelled by user"})
    assert response.status_code == 200
    assert "not completed" in response.text
    assert repo.take_callback(state_hash).code is None


def test_replayed_unknown_and_malformed_callbacks_get_one_generic_400(wired):
    client, _, _, _ = wired
    assert client.get("/connect/callback", params={"state": STATE, "code": CODE}).status_code == 200
    bodies = set()
    for params in ({"state": STATE, "code": CODE}, {"state": "U" * 43, "code": CODE},
                   {"code": CODE}, {"state": STATE}, {}):
        response = client.get("/connect/callback", params=params)
        assert response.status_code == 400
        bodies.add(response.text)
    assert len(bodies) == 1
    assert CODE not in bodies.pop()


def test_the_callback_needs_no_delegation_and_never_calls_home(wired):
    client, _, _, authz = wired
    client.get("/connect/callback", params={"state": STATE, "code": CODE})
    assert authz.calls == []


def test_only_get_is_served_on_the_callback(wired):
    client, _, _, _ = wired
    assert client.post("/connect/callback", params={"state": STATE, "code": CODE}).status_code == 405


def test_the_callback_route_exists_only_when_it_is_wired(tmp_path):
    service, _ = seeded_service(tmp_path)
    client = TestClient(create_app(service))
    assert client.get("/connect/callback", params={"state": STATE, "code": CODE}).status_code == 404
