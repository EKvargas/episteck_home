"""Nutrition's Home authorization client — one delegated call per operation (G1.6).

The client sends its OWN machine credential and the opaque delegation, and nothing
else. It has no actor parameter, so no upstream component — and no amount of model
output — can assert an identity to this service.

A previous revision resolved the actor via ``whoami`` before authorizing. Delegations
are single-use, so that second request was replay-denied and every person-sensitive
route broke. These tests now assert the single-request contract directly, by counting
the requests the client actually issues.
"""
from __future__ import annotations

import httpx
import pytest

from app.home_control.client import AccessDecision, HomeControlPlaneClient

SESSION = "delegation-token-xyz"
INDETERMINATE = AccessDecision(False, "authorization indeterminate (fail closed)")


def _client(handler) -> HomeControlPlaneClient:
    return HomeControlPlaneClient(
        "https://home.episteck.com",
        "nutrition-key",
        "nutrition-secret",
        transport=httpx.MockTransport(handler),
    )


class _Counter:
    """Handler wrapper that records every request the client issues."""

    def __init__(self, response_factory):
        self.requests: list[httpx.Request] = []
        self._factory = response_factory

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._factory(request)

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def _allow(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"allow": True, "reason": "grant NUTRITION/VIEW"}}
    )


# ==========================================================================
# The single-call contract
# ==========================================================================


def test_authorization_issues_exactly_one_home_request():
    """One authorization, one delegated request. This is the regression."""
    counter = _Counter(_allow)

    _client(counter).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)

    assert len(counter.requests) == 1, counter.paths
    assert counter.paths[0].endswith("/episteck_home.api.check_access")


def test_authorization_never_calls_whoami():
    """whoami would consume the delegation and leave check_access replay-denied."""
    counter = _Counter(_allow)

    _client(counter).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)

    assert not any("whoami" in p for p in counter.paths), counter.paths


def test_client_exposes_no_actor_resolution_method():
    """The seam that caused the double call is gone, not merely unused."""
    assert not hasattr(HomeControlPlaneClient, "resolve_actor")


def test_check_access_signature_takes_no_actor():
    import inspect

    params = set(inspect.signature(HomeControlPlaneClient.check_access).parameters)
    assert "actor_person_id" not in params
    assert "actor" not in params
    assert params == {"self", "subject_person_id", "domain", "action", "delegation"}


# ==========================================================================
# Request shape
# ==========================================================================


def test_sends_own_machine_credential_and_delegation_only():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token nutrition-key:nutrition-secret"
        assert request.headers["X-Episteck-Delegation"] == SESSION
        assert request.url.path.endswith("/episteck_home.api.check_access")
        # No actor is ever sent: Home derives it from the delegation.
        assert dict(request.url.params) == {
            "subject_person_id": "PSN-B",
            "domain": "NUTRITION",
            "action": "VIEW",
        }
        return _allow(request)

    decision = _client(handler).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision == AccessDecision(True, "grant NUTRITION/VIEW")


def test_no_actor_appears_anywhere_in_the_request():
    counter = _Counter(_allow)
    _client(counter).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)

    raw = str(counter.requests[0].url) + str(dict(counter.requests[0].headers))
    assert "actor" not in raw.lower()


# ==========================================================================
# Decisions and fail-closed behaviour
# ==========================================================================


def test_authoritative_denial_is_preserved():
    decision = _client(
        lambda request: httpx.Response(
            200, json={"message": {"allow": False, "reason": "no consent grant"}}
        )
    ).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision == AccessDecision(False, "no consent grant")


@pytest.mark.parametrize(
    "payload",
    [{}, {"message": {}}, {"message": {"allow": "yes"}}, {"message": None}],
)
def test_malformed_decision_denies(payload):
    decision = _client(
        lambda request: httpx.Response(200, json=payload)
    ).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision == INDETERMINATE


def test_replayed_or_rejected_delegation_denies():
    """A 403 is exactly what a replayed or revoked delegation produces upstream."""
    decision = _client(
        lambda request: httpx.Response(403, json={"exception": "PermissionError"})
    ).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision == INDETERMINATE


def test_timeout_denies():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    assert _client(timeout).check_access(
        "PSN-B", "NUTRITION", "VIEW", SESSION
    ) == INDETERMINATE


def test_http_error_denies():
    assert _client(
        lambda request: httpx.Response(500, text="boom")
    ).check_access("PSN-B", "NUTRITION", "VIEW", SESSION) == INDETERMINATE


def test_unreachable_home_denies():
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    assert _client(unreachable).check_access(
        "PSN-B", "NUTRITION", "VIEW", SESSION
    ) == INDETERMINATE


def test_missing_session_denies_without_network():
    counter = _Counter(_allow)
    decision = _client(counter).check_access("PSN-B", "NUTRITION", "VIEW", None)

    assert decision == AccessDecision(
        False, "no authenticated human session (fail closed)"
    )
    assert counter.requests == [], "a missing session must not reach the network"


@pytest.mark.parametrize(
    "subject,domain,action",
    [("", "NUTRITION", "VIEW"), ("PSN-B", "", "VIEW"), ("PSN-B", "NUTRITION", "")],
)
def test_missing_scope_value_denies_without_network(subject, domain, action):
    counter = _Counter(_allow)
    decision = _client(counter).check_access(subject, domain, action, SESSION)

    assert decision == INDETERMINATE
    assert counter.requests == []
