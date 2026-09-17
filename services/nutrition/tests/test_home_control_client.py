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


# ==========================================================================
# Several requirements, still ONE delegated request
# ==========================================================================

VIEW_CREATE = [("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")]


def _allow_many(request: httpx.Request) -> httpx.Response:
    import json

    requirements = json.loads(request.content)["requirements"]
    return httpx.Response(
        200,
        json={
            "message": {
                "allow": True,
                "reason": "all requirements allowed",
                "decisions": [
                    {
                        "domain": r["domain"],
                        "action": r["action"],
                        "allow": True,
                        "reason": "grant",
                    }
                    for r in requirements
                ],
            }
        },
    )


def test_many_requirements_issue_exactly_one_request():
    """THE POINT: two permissions, one delegated request."""
    counter = _Counter(_allow_many)

    decision = _client(counter).check_access_many("PSN-B", VIEW_CREATE, SESSION)

    assert decision.allow is True
    assert len(counter.requests) == 1
    assert counter.paths == ["/api/method/episteck_home.api.check_access_many"]


def test_the_request_carries_the_delegation_and_no_actor():
    import json

    counter = _Counter(_allow_many)
    _client(counter).check_access_many("PSN-B", VIEW_CREATE, SESSION)

    request = counter.requests[0]
    assert request.headers["X-Episteck-Delegation"] == SESSION
    body = json.loads(request.content)
    assert body == {
        "subject_person_id": "PSN-B",
        "requirements": [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "NUTRITION", "action": "CREATE"},
        ],
    }
    assert "actor" not in request.content.decode().lower()


def test_any_denied_requirement_denies_overall():
    def mixed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "allow": False,
                    "reason": "no matching active grant (fail closed)",
                    "decisions": [
                        {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"},
                        {"domain": "NUTRITION", "action": "CREATE", "allow": False, "reason": "n"},
                    ],
                }
            },
        )

    decision = _client(mixed).check_access_many("PSN-B", VIEW_CREATE, SESSION)
    assert decision.allow is False


def test_an_allow_contradicted_by_its_own_decisions_is_refused():
    """Defence in depth: a summary flag never overrides a listed denial."""

    def contradictory(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "allow": True,  # claims allow
                    "reason": "all requirements allowed",
                    "decisions": [
                        {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"},
                        {"domain": "NUTRITION", "action": "CREATE", "allow": False, "reason": "n"},
                    ],
                }
            },
        )

    decision = _client(contradictory).check_access_many("PSN-B", VIEW_CREATE, SESSION)
    assert decision.allow is False


def test_an_allow_covering_fewer_requirements_than_asked_is_refused():
    """The dangerous shape: allow=True with one decision for a two-permission ask."""

    def short(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "allow": True,
                    "reason": "all requirements allowed",
                    "decisions": [
                        {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"}
                    ],
                }
            },
        )

    assert _client(short).check_access_many("PSN-B", VIEW_CREATE, SESSION) == INDETERMINATE


# --------------------------------------------------------------------------
# EXACT response coverage: the right COUNT is not the right PERMISSIONS
# --------------------------------------------------------------------------


def _many(allow, decisions, reason="all requirements allowed"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"allow": allow, "reason": reason, "decisions": decisions}},
        )

    return handler


def test_right_count_but_wrong_permissions_is_refused():
    """THE HARDENING: two decisions for permissions we never asked about.

    Counting alone would accept this. The requested pair was
    (NUTRITION/VIEW, NUTRITION/CREATE); the response allows two entirely different
    permissions, so it proves nothing about the operation being authorized.
    """
    handler = _many(
        True,
        [
            {"domain": "HEALTH", "action": "VIEW", "allow": True, "reason": "g"},
            {"domain": "HEALTH", "action": "CREATE", "allow": True, "reason": "g"},
        ],
    )
    assert _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION) == INDETERMINATE


@pytest.mark.parametrize(
    "decisions",
    [
        [
            {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"},
            {"domain": "HEALTH", "action": "CREATE", "allow": True, "reason": "g"},
        ],
        [
            {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"},
            {"domain": "NUTRITION", "action": "UPDATE", "allow": True, "reason": "g"},
        ],
        [
            {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"},
            {"domain": "NUTRITION", "action": "MANAGE", "allow": True, "reason": "g"},
        ],
    ],
    ids=["wrong-domain", "weaker-action-substituted", "different-action"],
)
def test_a_substituted_permission_is_refused(decisions):
    """One correct entry does not license a substituted second entry."""
    assert (
        _client(_many(True, decisions)).check_access_many("PSN-B", VIEW_CREATE, SESSION)
        == INDETERMINATE
    )


def test_a_reordered_response_is_refused():
    """Ordering is part of the contract; a swap is refused, not re-sorted."""
    handler = _many(
        True,
        [
            {"domain": "NUTRITION", "action": "CREATE", "allow": True, "reason": "g"},
            {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"},
        ],
    )
    assert _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION) == INDETERMINATE


def test_an_exactly_matching_response_is_allowed():
    """The positive control: correct permissions, correct order -> allow."""
    handler = _many(
        True,
        [
            {"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"},
            {"domain": "NUTRITION", "action": "CREATE", "allow": True, "reason": "g"},
        ],
    )
    decision = _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION)
    assert decision.allow is True


@pytest.mark.parametrize(
    "item",
    ["NUTRITION/VIEW", 42, None, ["NUTRITION", "VIEW"], True],
    ids=["string", "int", "null", "list", "bool"],
)
def test_a_non_dict_decision_item_is_a_controlled_denial(item):
    """A non-dict must not raise AttributeError out of the client.

    ``item.get(...)`` on a string would raise, and AttributeError was not in the
    caught set, so it would have escaped as an unhandled exception instead of a
    fail-closed decision.
    """
    handler = _many(
        True,
        [{"domain": "NUTRITION", "action": "VIEW", "allow": True, "reason": "g"}, item],
    )
    decision = _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION)
    assert decision == INDETERMINATE


def test_every_decision_item_non_dict_is_a_controlled_denial():
    handler = _many(True, ["nope", "also-nope"])
    assert _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION) == INDETERMINATE


@pytest.mark.parametrize(
    "decisions",
    [
        [
            {"action": "VIEW", "allow": True},
            {"domain": "NUTRITION", "action": "CREATE", "allow": True},
        ],
        [
            {"domain": "NUTRITION", "allow": True},
            {"domain": "NUTRITION", "action": "CREATE", "allow": True},
        ],
        [
            {"domain": None, "action": None, "allow": True},
            {"domain": "NUTRITION", "action": "CREATE", "allow": True},
        ],
    ],
    ids=["missing-domain", "missing-action", "null-both"],
)
def test_a_decision_item_without_its_permission_is_refused(decisions):
    """An item that does not say WHAT it decided cannot corroborate an allow."""
    assert (
        _client(_many(True, decisions)).check_access_many("PSN-B", VIEW_CREATE, SESSION)
        == INDETERMINATE
    )


def test_a_denial_needs_no_corroboration():
    """Refusing is always safe: a denial stands even with an unusable detail list."""
    handler = _many(False, "not-a-list", reason="no matching active grant (fail closed)")
    decision = _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION)
    assert decision.allow is False
    assert "fail closed" in decision.reason


def test_a_single_requirement_is_covered_exactly_too():
    """The check is not specific to multi-permission asks."""
    ok = _many(True, [{"domain": "NUTRITION", "action": "VIEW", "allow": True}])
    wrong = _many(True, [{"domain": "NUTRITION", "action": "CREATE", "allow": True}])
    one = [("NUTRITION", "VIEW")]

    assert _client(ok).check_access_many("PSN-B", one, SESSION).allow is True
    assert _client(wrong).check_access_many("PSN-B", one, SESSION) == INDETERMINATE


def test_an_allow_with_no_decisions_cannot_be_verified():
    def bare(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"allow": True, "reason": "ok"}})

    assert _client(bare).check_access_many("PSN-B", VIEW_CREATE, SESSION) == INDETERMINATE


@pytest.mark.parametrize(
    "payload",
    [
        {"message": {"allow": "yes", "decisions": []}},
        {"message": {"reason": "no allow key"}},
        {"message": "not-a-mapping"},
        {"unexpected": "shape"},
    ],
    ids=["non-bool-allow", "missing-allow", "not-a-mapping", "wrong-envelope"],
)
def test_malformed_many_response_denies(payload):
    handler = lambda request: httpx.Response(200, json=payload)  # noqa: E731
    assert _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION) == INDETERMINATE


def test_unreachable_home_denies_many():
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    assert (
        _client(unreachable).check_access_many("PSN-B", VIEW_CREATE, SESSION)
        == INDETERMINATE
    )


def test_http_error_denies_many():
    handler = lambda request: httpx.Response(500, json={})  # noqa: E731
    assert _client(handler).check_access_many("PSN-B", VIEW_CREATE, SESSION) == INDETERMINATE


def test_many_without_session_denies_without_network():
    counter = _Counter(_allow_many)
    decision = _client(counter).check_access_many("PSN-B", VIEW_CREATE, None)

    assert decision == AccessDecision(
        False, "no authenticated human session (fail closed)"
    )
    assert counter.requests == [], "a missing session must not reach the network"


@pytest.mark.parametrize(
    "subject,requirements",
    [
        ("", VIEW_CREATE),
        ("PSN-B", []),
        ("PSN-B", [("", "VIEW")]),
        ("PSN-B", [("NUTRITION", "")]),
    ],
    ids=["no-subject", "no-requirements", "blank-domain", "blank-action"],
)
def test_malformed_many_input_denies_without_network(subject, requirements):
    counter = _Counter(_allow_many)
    decision = _client(counter).check_access_many(subject, requirements, SESSION)

    assert decision == INDETERMINATE
    assert counter.requests == []
