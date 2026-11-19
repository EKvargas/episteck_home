"""Control Plane calls for the runtime grant (H5)."""
from __future__ import annotations

import httpx
import pytest

from home_bff.frappe_client import (
    AccessRefused,
    ControlPlaneUnreachable,
    HomeOAuthClient,
    SessionOpenError,
)

OPEN = "/api/method/episteck_home.identity.session.open_runtime_grant"
CLOSE = "/api/method/episteck_home.identity.session.close_runtime_grant"


def _client(handler) -> HomeOAuthClient:
    return HomeOAuthClient(
        "https://home.invalid", "cid", "csecret", transport=httpx.MockTransport(handler)
    )


def test_open_sends_runtime_and_days_with_the_humans_bearer_and_no_user():
    seen = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"message": {"session_id": "HDS-9", "expires_at": "x"}})

    assert _client(handle).open_runtime_grant("tok", "home-agent-primary", 90) == "HDS-9"
    assert seen["path"] == OPEN
    assert seen["auth"] == "Bearer tok"
    assert seen["body"] in ("runtime_id=home-agent-primary&ttl_days=90",
                            "ttl_days=90&runtime_id=home-agent-primary")


def test_open_without_session_id_is_refused():
    client = _client(lambda r: httpx.Response(200, json={"message": {}}))
    with pytest.raises(SessionOpenError):
        client.open_runtime_grant("tok", "home-agent-primary", 90)


def test_open_refusal_is_session_open_error_but_not_unreachable():
    client = _client(lambda r: httpx.Response(403, json={}))
    with pytest.raises(SessionOpenError) as caught:
        client.open_runtime_grant("tok", "home-agent-primary", 90)
    assert not isinstance(caught.value, ControlPlaneUnreachable)


def test_open_network_failure_and_5xx_are_unreachable():
    def boom(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ControlPlaneUnreachable):
        _client(boom).open_runtime_grant("tok", "home-agent-primary", 90)
    with pytest.raises(ControlPlaneUnreachable):
        _client(lambda r: httpx.Response(503)).open_runtime_grant("tok", "home-agent-primary", 90)


def test_close_true_false_and_unreachable():
    ok = _client(lambda r: httpx.Response(200, json={"message": {"closed": True}}))
    assert ok.close_runtime_grant("tok", "HDS-1") is True
    no = _client(lambda r: httpx.Response(200, json={"message": {"closed": False}}))
    assert no.close_runtime_grant("tok", "HDS-1") is False

    def boom(request):
        raise httpx.ConnectError("down")

    assert _client(boom).close_runtime_grant("tok", "HDS-1") is None
    assert _client(lambda r: httpx.Response(502)).close_runtime_grant("tok", "HDS-1") is None


def test_close_uses_close_runtime_grant_path():
    seen = {}

    def handle(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"message": {"closed": True}})

    _client(handle).close_runtime_grant("tok", "HDS-1")
    assert seen["path"] == CLOSE


@pytest.mark.parametrize("status", [401, 403])
def test_close_with_a_rejected_token_raises_instead_of_claiming_not_owner(status):
    """An expired access token is not an ownership answer (review fix C2)."""
    client = _client(lambda r: httpx.Response(status, json={}))
    with pytest.raises(AccessRefused):
        client.close_runtime_grant("tok", "HDS-1")


def test_access_refused_is_a_session_open_error_for_existing_handlers():
    assert issubclass(AccessRefused, SessionOpenError)
    assert not issubclass(AccessRefused, ControlPlaneUnreachable)


# ------------------------------------------------- list_grantable_runtimes (Task 5)

GRANTABLE = "/api/method/episteck_home.identity.session.get_grantable_runtimes"


def test_grantable_returns_the_list_via_bare_get():
    seen = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = request.url.query
        seen["body"] = request.content
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"message": {"runtime_ids": ["home-agent-ana"]}})

    assert _client(handle).list_grantable_runtimes("tok") == ["home-agent-ana"]
    assert seen == {
        "method": "GET", "path": GRANTABLE, "query": b"", "body": b"", "auth": "Bearer tok",
    }


def test_grantable_malformed_bodies_are_none():
    for message in ({"runtime_ids": "x"}, {"runtime_ids": [1]}, {}, ["a"], None):
        client = _client(lambda r, m=message: httpx.Response(200, json={"message": m}))
        assert client.list_grantable_runtimes("tok") is None
    assert _client(lambda r: httpx.Response(200, content=b"nope")).list_grantable_runtimes("tok") is None


def test_grantable_unreachable_and_missing_method_are_none():
    def boom(request):
        raise httpx.ConnectError("down")

    assert _client(boom).list_grantable_runtimes("tok") is None
    assert _client(lambda r: httpx.Response(500)).list_grantable_runtimes("tok") is None
    assert _client(lambda r: httpx.Response(404)).list_grantable_runtimes("tok") is None
    assert _client(lambda r: httpx.Response(417)).list_grantable_runtimes("tok") is None


def test_grantable_refusal_raises_access_refused():
    for status in (401, 403):
        with pytest.raises(AccessRefused):
            _client(lambda r, s=status: httpx.Response(s)).list_grantable_runtimes("tok")
