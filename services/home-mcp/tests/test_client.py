from __future__ import annotations

import httpx

from home_mcp.client import HomeControlPlaneClient


def _client(handler) -> HomeControlPlaneClient:
    return HomeControlPlaneClient(
        "https://home.episteck.com",
        "test-key",
        "test-secret",
        transport=httpx.MockTransport(handler),
    )


def test_get_person_sends_machine_auth_and_actor_parameters():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "token test-key:test-secret"
        assert request.url.path.endswith("/episteck_home.api.get_person")
        assert request.url.params["actor_person_id"] == "PSN-ACTOR"
        assert request.url.params["person_id"] == "PSN-SUBJECT"
        return httpx.Response(
            200,
            json={"message": {"person_id": "PSN-SUBJECT", "full_name": "Synthetic"}},
        )

    result = _client(handler).get_person("PSN-ACTOR", "PSN-SUBJECT")
    assert result == {"person_id": "PSN-SUBJECT", "full_name": "Synthetic"}


def test_circle_members_sends_actor_before_requesting_roster():
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {
            "actor_person_id": "PSN-ACTOR",
            "circle_id": "CIR-HOME",
        }
        return httpx.Response(200, json={"message": [{"person_id": "PSN-ACTOR"}]})

    result = _client(handler).list_circle_members("PSN-ACTOR", "CIR-HOME")
    assert result == [{"person_id": "PSN-ACTOR"}]


def test_undiscoverable_resource_returns_non_revealing_error():
    result = _client(lambda request: httpx.Response(404)).get_person(
        "PSN-ACTOR", "PSN-UNRELATED"
    )
    assert result == {"ok": False, "error": "not_authorized_or_not_found"}


def test_transport_failure_returns_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    result = _client(handler).list_my_circles("PSN-ACTOR")
    assert result == {"ok": False, "error": "home_control_plane_unavailable"}


def test_malformed_frappe_response_returns_safe_error():
    result = _client(lambda request: httpx.Response(200, json={})).get_care_dashboard(
        "PSN-ACTOR"
    )
    assert result == {"ok": False, "error": "invalid_home_control_plane_response"}


def test_check_access_accepts_only_boolean_decisions():
    result = _client(
        lambda request: httpx.Response(200, json={"message": {"allow": "yes"}})
    ).check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")
    assert result == {
        "allow": False,
        "reason": "authorization indeterminate (fail closed)",
    }


def test_check_access_preserves_authoritative_denial():
    result = _client(
        lambda request: httpx.Response(
            200,
            json={"message": {"allow": False, "reason": "no matching active grant"}},
        )
    ).check_access("PSN-ACTOR", "PSN-SUBJECT", "MIND", "VIEW")
    assert result == {"allow": False, "reason": "no matching active grant"}
