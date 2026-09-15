from __future__ import annotations

import httpx

from home_mcp.client import HomeControlPlaneClient

DELEGATION = "delegation-token-abc"


def _client(handler) -> HomeControlPlaneClient:
    return HomeControlPlaneClient(
        "https://home.episteck.com",
        "test-key",
        "test-secret",
        transport=httpx.MockTransport(handler),
    )


def test_call_sends_both_principals_and_no_actor():
    """Dual principal: machine credential AND human delegation, never an actor id."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token test-key:test-secret"
        assert request.headers["X-Episteck-Delegation"] == DELEGATION
        assert request.url.path.endswith("/episteck_home.api.get_person")
        assert request.url.params["person_id"] == "PSN-SUBJECT"
        # The actor must not appear anywhere in the request.
        assert "actor_person_id" not in request.url.params
        assert "actor_person_id" not in str(request.url)
        return httpx.Response(
            200,
            json={"message": {"person_id": "PSN-SUBJECT", "full_name": "Synthetic"}},
        )

    result = _client(handler).get_person("PSN-SUBJECT", DELEGATION)
    assert result == {"person_id": "PSN-SUBJECT", "full_name": "Synthetic"}


def test_circle_members_sends_only_the_circle():
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"circle_id": "CIR-HOME"}
        return httpx.Response(200, json={"message": [{"person_id": "PSN-ACTOR"}]})

    result = _client(handler).list_circle_members("CIR-HOME", DELEGATION)
    assert result == [{"person_id": "PSN-ACTOR"}]


def test_missing_delegation_never_reaches_the_network():
    """No human session means the call is not even attempted."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"message": "should not happen"})

    result = _client(handler).list_my_circles(None)
    assert result == {"ok": False, "error": "no_authenticated_human_session"}
    assert calls == []


def test_expired_or_revoked_session_returns_non_revealing_error():
    """Frappe answers 401/403 once a session is revoked, expired, or unknown."""
    for status in (401, 403):
        result = _client(lambda request, s=status: httpx.Response(s)).list_my_circles(
            DELEGATION
        )
        assert result == {"ok": False, "error": "not_authorized_or_not_found"}


def test_undiscoverable_resource_returns_non_revealing_error():
    result = _client(lambda request: httpx.Response(404)).get_person(
        "PSN-UNRELATED", DELEGATION
    )
    assert result == {"ok": False, "error": "not_authorized_or_not_found"}


def test_transport_failure_returns_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    result = _client(handler).list_my_circles(DELEGATION)
    assert result == {"ok": False, "error": "home_control_plane_unavailable"}


def test_malformed_frappe_response_returns_safe_error():
    result = _client(lambda request: httpx.Response(200, json={})).get_care_dashboard(
        DELEGATION
    )
    assert result == {"ok": False, "error": "invalid_home_control_plane_response"}


def test_check_access_accepts_only_boolean_decisions():
    result = _client(
        lambda request: httpx.Response(200, json={"message": {"allow": "yes"}})
    ).check_access("PSN-SUBJECT", "NUTRITION", "VIEW", DELEGATION)
    assert result == {
        "allow": False,
        "reason": "authorization indeterminate (fail closed)",
    }


def test_check_access_without_session_fails_closed():
    result = _client(
        lambda request: httpx.Response(200, json={"message": {"allow": True}})
    ).check_access("PSN-SUBJECT", "NUTRITION", "VIEW", None)
    assert result["allow"] is False


def test_check_access_preserves_authoritative_denial():
    result = _client(
        lambda request: httpx.Response(
            200,
            json={"message": {"allow": False, "reason": "no matching active grant"}},
        )
    ).check_access("PSN-SUBJECT", "MIND", "VIEW", DELEGATION)
    assert result == {"allow": False, "reason": "no matching active grant"}


def test_check_access_canonicalizes_agent_supplied_domain_and_action():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["domain"] == "NUTRITION"
        assert request.url.params["action"] == "VIEW"
        return httpx.Response(
            200,
            json={"message": {"allow": True, "reason": "grant NUTRITION/VIEW"}},
        )

    result = _client(handler).check_access(
        "PSN-SUBJECT", "nutrition", "view", DELEGATION
    )
    assert result == {"allow": True, "reason": "grant NUTRITION/VIEW"}
