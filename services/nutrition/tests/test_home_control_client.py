from __future__ import annotations

import httpx
import pytest

from app.home_control.client import AccessDecision, HomeControlPlaneClient


def _client(handler) -> HomeControlPlaneClient:
    return HomeControlPlaneClient(
        "https://home.episteck.com",
        "nutrition-key",
        "nutrition-secret",
        transport=httpx.MockTransport(handler),
    )


def test_valid_allow_is_accepted_with_machine_auth_and_exact_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token nutrition-key:nutrition-secret"
        assert request.url.path.endswith("/episteck_home.api.check_access")
        assert dict(request.url.params) == {
            "actor_person_id": "PSN-A",
            "subject_person_id": "PSN-B",
            "domain": "NUTRITION",
            "action": "VIEW",
        }
        return httpx.Response(
            200,
            json={"message": {"allow": True, "reason": "grant NUTRITION/VIEW"}},
        )

    decision = _client(handler).check_access("PSN-A", "PSN-B", "NUTRITION", "VIEW")
    assert decision == AccessDecision(True, "grant NUTRITION/VIEW")


def test_authoritative_denial_is_preserved():
    decision = _client(
        lambda request: httpx.Response(
            200,
            json={"message": {"allow": False, "reason": "no consent grant"}},
        )
    ).check_access("PSN-A", "PSN-B", "NUTRITION", "VIEW")
    assert decision == AccessDecision(False, "no consent grant")


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": {}}, {"message": {"allow": "yes"}}, {"message": None}],
)
def test_malformed_decision_denies(payload):
    decision = _client(lambda request: httpx.Response(200, json=payload)).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW"
    )
    assert decision == AccessDecision(
        False, "authorization indeterminate (fail closed)"
    )


def test_timeout_denies():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    decision = _client(timeout).check_access("PSN-A", "PSN-B", "NUTRITION", "VIEW")
    assert decision.allow is False
    assert decision.reason == "authorization indeterminate (fail closed)"


def test_http_error_denies():
    decision = _client(lambda request: httpx.Response(503)).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW"
    )
    assert decision.allow is False
    assert decision.reason == "authorization indeterminate (fail closed)"


@pytest.mark.parametrize(
    ("actor", "subject", "domain", "action"),
    [
        ("", "PSN-B", "NUTRITION", "VIEW"),
        ("PSN-A", "", "NUTRITION", "VIEW"),
        ("PSN-A", "PSN-B", "", "VIEW"),
        ("PSN-A", "PSN-B", "NUTRITION", ""),
    ],
)
def test_missing_scope_value_denies_without_network(actor, subject, domain, action):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"message": {"allow": True}})

    decision = _client(handler).check_access(actor, subject, domain, action)
    assert decision.allow is False
    assert calls == 0
