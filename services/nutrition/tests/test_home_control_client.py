"""Nutrition's Home authorization client — independent actor resolution (G1.6)."""
from __future__ import annotations

import httpx
import pytest

from app.home_control.client import AccessDecision, HomeControlPlaneClient

SESSION = "delegation-token-xyz"


def _client(handler) -> HomeControlPlaneClient:
    return HomeControlPlaneClient(
        "https://home.episteck.com",
        "nutrition-key",
        "nutrition-secret",
        transport=httpx.MockTransport(handler),
    )


# --------------------------------------------------------------------------
# Independent actor resolution
# --------------------------------------------------------------------------


def test_resolve_actor_asks_home_with_its_own_machine_credential():
    """Nutrition asks Home who the human is; it never accepts an asserted answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token nutrition-key:nutrition-secret"
        assert request.headers["X-Episteck-Delegation"] == SESSION
        assert request.url.path.endswith("/episteck_home.api.whoami")
        # Nutrition must not be able to suggest an actor.
        assert "actor_person_id" not in str(request.url)
        return httpx.Response(200, json={"message": {"actor_person_id": "PSN-A"}})

    assert _client(handler).resolve_actor(SESSION) == "PSN-A"


def test_resolve_actor_without_session_makes_no_network_call():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"message": {"actor_person_id": "PSN-A"}})

    assert _client(handler).resolve_actor(None) is None
    assert calls == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": {}}, {"message": {"actor_person_id": ""}}, {"message": None}],
)
def test_resolve_actor_denies_on_malformed_identity(payload):
    assert _client(lambda request: httpx.Response(200, json=payload)).resolve_actor(
        SESSION
    ) is None


def test_resolve_actor_denies_on_revoked_or_expired_session():
    for status in (401, 403, 404):
        assert _client(
            lambda request, s=status: httpx.Response(s)
        ).resolve_actor(SESSION) is None


def test_resolve_actor_denies_when_home_is_unreachable():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    assert _client(timeout).resolve_actor(SESSION) is None


# --------------------------------------------------------------------------
# Authorization decisions
# --------------------------------------------------------------------------


def test_valid_allow_is_accepted_with_machine_auth_and_exact_scope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token nutrition-key:nutrition-secret"
        assert request.headers["X-Episteck-Delegation"] == SESSION
        assert request.url.path.endswith("/episteck_home.api.check_access")
        # The actor is resolved by Home from the session; it is never sent.
        assert dict(request.url.params) == {
            "subject_person_id": "PSN-B",
            "domain": "NUTRITION",
            "action": "VIEW",
        }
        return httpx.Response(
            200,
            json={"message": {"allow": True, "reason": "grant NUTRITION/VIEW"}},
        )

    decision = _client(handler).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW", SESSION
    )
    assert decision == AccessDecision(True, "grant NUTRITION/VIEW")


def test_authoritative_denial_is_preserved():
    decision = _client(
        lambda request: httpx.Response(
            200,
            json={"message": {"allow": False, "reason": "no consent grant"}},
        )
    ).check_access("PSN-A", "PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision == AccessDecision(False, "no consent grant")


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": {}}, {"message": {"allow": "yes"}}, {"message": None}],
)
def test_malformed_decision_denies(payload):
    decision = _client(lambda request: httpx.Response(200, json=payload)).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW", SESSION
    )
    assert decision == AccessDecision(
        False, "authorization indeterminate (fail closed)"
    )


def test_timeout_denies():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    decision = _client(timeout).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW", SESSION
    )
    assert decision.allow is False
    assert decision.reason == "authorization indeterminate (fail closed)"


def test_http_error_denies():
    decision = _client(lambda request: httpx.Response(503)).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW", SESSION
    )
    assert decision.allow is False
    assert decision.reason == "authorization indeterminate (fail closed)"


def test_missing_session_denies_without_network():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"message": {"allow": True}})

    decision = _client(handler).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW", None
    )
    assert decision.allow is False
    assert calls == []


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

    decision = _client(handler).check_access(actor, subject, domain, action, SESSION)
    assert decision.allow is False
    assert calls == 0
