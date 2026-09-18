"""Pre-merge adversarial audit of the operational BFF (G1.6).

Five properties the operator asked to see proven before merge. These are kept as
permanent tests, not one-off probes, so a later change that breaks one fails the
build rather than shipping.

  1. /delegation is unreachable without a valid authenticated session
  2. a cross-site POST cannot mint a delegation
  3. actor identity cannot be supplied via body, query, or header
  4. no token or secret is returned in any response, or written to normal logs
  5. /health exposes no sensitive configuration
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff.app import create_app
from home_bff.store import SessionStore

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "episteck_home"))

from tests.test_app import (  # noqa: E402
    FakeClient,
    complete_login,
    login_and_get_state,
    make_settings,
)

# Every secret the app knows about. None may ever appear in output.
SECRETS = {
    "client_secret": "super-secret",
    "access_token": "at-1",
    "refresh_token": "rt-1",
    "delegation_secret": "bff-delegation-secret",
}


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http, store, client


# ==========================================================================
# 1. /delegation requires a valid authenticated session
# ==========================================================================


def test_delegation_denied_with_no_cookie(ctx):
    http, _, _ = ctx
    assert http.post("/delegation").status_code == 401


def test_delegation_denied_with_forged_cookie(ctx):
    http, _, _ = ctx
    http.cookies.set(sessions.COOKIE_NAME, "forged-session-id", domain="bff.invalid")
    assert http.post("/delegation").status_code == 401


def test_delegation_denied_with_empty_cookie(ctx):
    http, _, _ = ctx
    http.cookies.set(sessions.COOKIE_NAME, "", domain="bff.invalid")
    assert http.post("/delegation").status_code == 401


def test_delegation_denied_after_logout(ctx):
    http, _, _ = ctx
    complete_login(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)
    http.post("/logout")
    http.cookies.set(sessions.COOKIE_NAME, raw, domain="bff.invalid")
    assert http.post("/delegation").status_code == 401


def test_delegation_denied_when_session_expired(ctx):
    http, store, _ = ctx
    complete_login(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)
    with sqlite3.connect(store._path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, raw),
        )
    assert http.post("/delegation").status_code == 401


def test_delegation_denied_for_a_deleted_session(ctx):
    """Server-side revocation denies the very next call."""
    http, store, _ = ctx
    complete_login(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)
    store.delete_session(raw)
    assert http.post("/delegation").status_code == 401


def test_delegation_cannot_be_reached_by_guessing_a_home_session_id(ctx):
    """Knowing the Home session id is not a credential; only the cookie is."""
    http, _, _ = ctx
    http.cookies.set(sessions.COOKIE_NAME, "HDS-0001", domain="bff.invalid")
    assert http.post("/delegation").status_code == 401


def test_delegation_requires_post_not_get(ctx):
    """A GET cannot be triggered by a bare cross-site image/link."""
    http, _, _ = ctx
    complete_login(http)
    assert http.get("/delegation").status_code == 405


# ==========================================================================
# 2. A cross-site POST cannot mint a delegation
# ==========================================================================


def test_samesite_lax_is_declared_on_the_session_cookie(ctx):
    """Lax is what makes a cross-site POST arrive with no cookie at all."""
    http, _, _ = ctx
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert "samesite=lax" in response.headers["set-cookie"].lower()


def test_cross_site_post_arrives_without_the_cookie_and_is_denied(ctx):
    """Simulate the browser's SameSite=Lax behaviour: no cookie on cross-site POST.

    A real browser withholds a Lax cookie on a cross-site POST, so the request
    reaches the app unauthenticated. That is exactly the no-cookie case, and it is
    denied.
    """
    http, _, _ = ctx
    complete_login(http)
    saved = http.cookies.get(sessions.COOKIE_NAME)
    assert saved  # we do have a real session

    http.cookies.clear()
    response = http.post(
        "/delegation",
        headers={
            "Origin": "https://evil.invalid",
            "Referer": "https://evil.invalid/attack.html",
        },
    )
    assert response.status_code == 401


def test_delegation_is_not_reachable_by_simple_form_content_types(ctx):
    """A cross-site HTML form can only send these content types; none are accepted
    as a way to smuggle an actor, and all still require the session."""
    http, _, _ = ctx
    for content_type in (
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        "text/plain",
    ):
        response = http.post(
            "/delegation",
            headers={"Content-Type": content_type, "Origin": "https://evil.invalid"},
            content=b"audience=home-control-plane",
        )
        assert response.status_code == 401, content_type


def test_cookie_is_not_readable_by_script(ctx):
    """HttpOnly: an XSS payload cannot exfiltrate the session to mint delegations."""
    http, _, _ = ctx
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert "httponly" in response.headers["set-cookie"].lower()


def test_delegation_is_denied_at_the_proxy_layer():
    """Defence in depth: nginx returns 404 for /delegation regardless of cookie."""
    vhost = (
        Path(__file__).resolve().parents[3]
        / "deploy"
        / "home-bff"
        / "nginx-home-bff.conf"
    ).read_text(encoding="utf-8")
    assert "location = /delegation" in vhost
    assert "deny all;" in vhost


# ==========================================================================
# 3. Actor identity cannot be supplied through body, query, or header
# ==========================================================================

ACTOR_ATTEMPTS = [
    {"actor_person_id": "PSN-00002"},
    {"actor": "PSN-00002"},
    {"person_id": "PSN-00002"},
    {"human_actor": "PSN-00002"},
    {"sub": "PSN-00002"},
]

ACTOR_HEADERS = [
    {"X-Actor-ID": "PSN-00002"},
    {"X-Episteck-Actor": "PSN-00002"},
    {"X-Human-Actor": "PSN-00002"},
    {"X-Episteck-Delegation": "PSN-00002"},
]


@pytest.mark.parametrize("params", ACTOR_ATTEMPTS)
def test_actor_cannot_be_supplied_in_the_query_string(ctx, params):
    http, _, _ = ctx
    complete_login(http)
    body = http.get("/whoami", params=params).json()
    assert body["actor_person_id"] == "PSN-00001"


@pytest.mark.parametrize("headers", ACTOR_HEADERS)
def test_actor_cannot_be_supplied_in_a_header(ctx, headers):
    http, _, _ = ctx
    complete_login(http)
    body = http.get("/whoami", headers=headers).json()
    assert body["actor_person_id"] == "PSN-00001"


@pytest.mark.parametrize("params", ACTOR_ATTEMPTS)
def test_actor_in_a_body_cannot_steer_the_minted_delegation(ctx, params):
    from tests.test_app import _claims

    http, _, _ = ctx
    complete_login(http)
    response = http.post("/delegation", json=params)
    assert response.status_code == 200
    # Bound to the session's own Home session, not the requested Person.
    assert _claims(response.json()["delegation"]).session_id == "HDS-0001"


@pytest.mark.parametrize("headers", ACTOR_HEADERS)
def test_actor_header_cannot_steer_the_minted_delegation(ctx, headers):
    from tests.test_app import _claims

    http, _, _ = ctx
    complete_login(http)
    response = http.post("/delegation", headers=headers)
    assert response.status_code == 200
    assert _claims(response.json()["delegation"]).session_id == "HDS-0001"


def test_no_route_declares_an_actor_parameter(ctx):
    """Mechanical: the OpenAPI schema must contain no actor input anywhere."""
    http, _, _ = ctx
    schema = http.get("/openapi.json").json()
    forbidden = {
        "actor_person_id",
        "actor",
        "actor_id",
        "human_actor",
        "person_id",
        "access_token",
        "client_secret",
        "token",
    }
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                assert parameter["name"] not in forbidden, f"{method} {path}"


def test_minted_delegation_never_contains_a_person_id(ctx):
    http, _, _ = ctx
    complete_login(http)
    body = http.post("/delegation", json={"actor_person_id": "PSN-00002"}).json()
    assert "PSN-" not in body["delegation"]


# ==========================================================================
# 4. No token or secret in any response, or in normal logs
# ==========================================================================


def _assert_clean(text: str, where: str) -> None:
    for label, value in SECRETS.items():
        assert value not in text, f"{label} leaked in {where}"


def test_no_secret_in_any_successful_response(ctx):
    http, _, _ = ctx
    complete_login(http)
    for method, path in [
        ("GET", "/health"),
        ("GET", "/session"),
        ("GET", "/whoami"),
        ("POST", "/delegation"),
        ("GET", "/openapi.json"),
    ]:
        response = http.request(method, path)
        _assert_clean(response.text, f"{method} {path} body")
        _assert_clean(str(dict(response.headers)), f"{method} {path} headers")


def test_no_secret_in_the_login_redirect(ctx):
    http, _, _ = ctx
    response = http.get("/login", follow_redirects=False)
    _assert_clean(response.headers["location"], "login redirect")
    _assert_clean(response.text, "login body")


def test_no_secret_in_callback_response_or_cookie(ctx):
    http, _, _ = ctx
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    _assert_clean(response.text, "callback body")
    _assert_clean(response.headers["set-cookie"], "callback set-cookie")


def test_no_secret_in_error_responses(ctx):
    """Failure paths are where leaks usually hide."""
    from home_bff.frappe_client import SessionOpenError, TokenExchangeError

    http, _, client = ctx

    client.exchange_error = TokenExchangeError(f"upstream echoed {SECRETS['client_secret']}")
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    _assert_clean(response.text, "token-exchange error body")

    client.exchange_error = None
    client.session_error = SessionOpenError(f"leak {SECRETS['access_token']}")
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    _assert_clean(response.text, "session-open error body")


def test_no_secret_in_logs_on_the_happy_path(ctx, caplog):
    http, _, _ = ctx
    with caplog.at_level(logging.DEBUG):
        complete_login(http)
        http.get("/whoami")
        http.post("/delegation")
        http.post("/logout")
    _assert_clean(caplog.text, "logs (happy path)")


def test_no_secret_in_logs_on_failure_paths(ctx, caplog):
    """The two places we log a warning both carry upstream text — check them."""
    from home_bff.frappe_client import SessionOpenError, TokenExchangeError

    http, _, client = ctx
    with caplog.at_level(logging.DEBUG):
        client.exchange_error = TokenExchangeError(SECRETS["client_secret"])
        state = login_and_get_state(http)
        http.get(f"/callback?code=c&state={state}", follow_redirects=False)

        client.exchange_error = None
        client.session_error = SessionOpenError(SECRETS["access_token"])
        state = login_and_get_state(http)
        http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    _assert_clean(caplog.text, "logs (failure paths)")


def test_access_log_is_disabled_so_query_strings_are_not_recorded():
    """uvicorn access logs would record ?code=... on every callback."""
    source = (
        Path(__file__).resolve().parents[1] / "home_bff" / "__main__.py"
    ).read_text(encoding="utf-8")
    assert "access_log=False" in source


def test_pkce_verifier_never_leaves_the_server(ctx):
    http, store, _ = ctx
    state = login_and_get_state(http)
    transaction = store.consume_transaction(state)
    assert transaction is not None
    store.begin_transaction(
        state=state,
        code_verifier=transaction.code_verifier,
        nonce=transaction.nonce,
        redirect_uri=transaction.redirect_uri,
    )
    response = http.get("/login", follow_redirects=False)
    assert transaction.code_verifier not in response.headers["location"]

    completed = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert transaction.code_verifier not in completed.text


def test_session_response_carries_no_token_fields(ctx):
    http, _, _ = ctx
    complete_login(http)
    body = http.get("/session").json()
    assert set(body) == {"authenticated", "expires_at"}


# ==========================================================================
# 5. /health exposes no sensitive configuration
# ==========================================================================


def test_health_body_is_a_fixed_two_key_shape(ctx):
    http, _, _ = ctx
    body = http.get("/health").json()
    assert body == {"status": "ok", "service": "home-bff"}


def test_health_reveals_no_configuration(ctx):
    http, _, _ = ctx
    text = http.get("/health").text
    for forbidden in (
        "super-secret",
        "bff-delegation-secret",
        "client-abc",
        "home.invalid",
        "bff.invalid/callback",
        "/data/bff.sqlite",
        "9933",
    ):
        assert forbidden not in text, forbidden


def test_health_requires_no_session_and_creates_none(ctx):
    """Health must be usable by a probe without minting state."""
    http, store, _ = ctx
    assert http.get("/health").status_code == 200
    assert http.cookies.get(sessions.COOKIE_NAME) is None
    with sqlite3.connect(store._path) as db:
        assert db.execute("SELECT COUNT(*) FROM bff_session").fetchone()[0] == 0


def test_health_does_not_reach_the_control_plane(ctx):
    """A liveness probe must not depend on, or exercise, upstream credentials."""
    http, _, client = ctx

    def boom(*args, **kwargs):
        raise AssertionError("health must not call upstream")

    client.whoami = boom
    client.open_home_session = boom
    assert http.get("/health").status_code == 200
