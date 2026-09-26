"""Upstream error classification for the bootstrap CP call (§6)."""
from __future__ import annotations

import httpx
import pytest

from home_bff.frappe_client import (
    HomeOAuthClient,
    UpstreamMalformed,
    UpstreamRefused,
    UpstreamUnavailable,
)

BOOTSTRAP_PATH = "/api/method/episteck_home.api.get_home_bootstrap"


def _client(handler) -> HomeOAuthClient:
    transport = httpx.MockTransport(handler)
    return HomeOAuthClient(
        "https://home.invalid", "client-id", "client-secret", transport=transport
    )


def _handler(status_code: int, json_body=None, raise_connect_error=False):
    def handle(request: httpx.Request) -> httpx.Response:
        if raise_connect_error:
            raise httpx.ConnectError("connection refused")
        if json_body is None:
            return httpx.Response(status_code, text="not json{{{")
        return httpx.Response(status_code, json=json_body)

    return handle


@pytest.mark.parametrize("status_code", [401, 403])
def test_cp_401_403_raise_upstream_refused(status_code):
    client = _client(_handler(status_code, {"exc_type": "PermissionError"}))
    with pytest.raises(UpstreamRefused):
        client.get_home_bootstrap("token", "HDS-1")


def test_connect_error_raises_upstream_unavailable():
    client = _client(_handler(200, raise_connect_error=True))
    with pytest.raises(UpstreamUnavailable):
        client.get_home_bootstrap("token", "HDS-1")


def test_timeout_raises_upstream_unavailable():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = _client(handle)
    with pytest.raises(UpstreamUnavailable):
        client.get_home_bootstrap("token", "HDS-1")


@pytest.mark.parametrize("status_code", [404, 417, 429, 500, 502, 503])
def test_cp_404_417_429_5xx_raise_upstream_unavailable(status_code):
    client = _client(_handler(status_code, {"exc_type": "MethodNotFoundError"}))
    with pytest.raises(UpstreamUnavailable):
        client.get_home_bootstrap("token", "HDS-1")


def test_cp_200_non_json_raises_upstream_malformed():
    client = _client(_handler(200, json_body=None))
    with pytest.raises(UpstreamMalformed):
        client.get_home_bootstrap("token", "HDS-1")


def test_cp_200_json_returns_message_payload():
    payload = {
        "message": {
            "viewer": {"person_id": "PSN-00001", "display_name": "Erick"},
            "circles": [],
            "care": [],
        }
    }
    client = _client(_handler(200, json_body=payload))
    result = client.get_home_bootstrap("token", "HDS-1")
    assert result == payload["message"]


def test_cp_200_json_missing_message_key_raises_upstream_malformed():
    client = _client(_handler(200, json_body={"unexpected": "shape"}))
    with pytest.raises(UpstreamMalformed):
        client.get_home_bootstrap("token", "HDS-1")


def test_no_access_token_raises_upstream_refused():
    client = _client(_handler(200, json_body={"message": {}}))
    with pytest.raises(UpstreamRefused):
        client.get_home_bootstrap("", "HDS-1")
