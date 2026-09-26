"""Home BFF HTTP surface (G1.6).

These tests drive the real ASGI app with a fake Control Plane, so the login, callback,
session, and logout paths are exercised end to end without touching the network.
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff.app import create_app
from home_bff.config import ConfigError, Settings
from home_bff.frappe_client import SessionOpenError, TokenExchangeError, TokenSet
from home_bff.runtime import RUNTIME_ID, BindResult
from home_bff.store import SessionStore, StoreUnavailableError

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "episteck_home"))
from episteck_home.identity.delegation import verify  # noqa: E402

DELEGATION_SECRET = "bff-delegation-secret"


def make_settings(**overrides) -> Settings:
    base = dict(
        home_base_url="https://home.invalid",
        client_id="client-abc",
        client_secret="super-secret",
        redirect_uri="https://bff.invalid/callback",
        delegation_secret=DELEGATION_SECRET,
        delegation_issuer="episteck-home-bff",
        store_path=":memory:",
        mint_socket_path="/run/episteck/home-bff-mint/mint.sock",
        port=9933,
        scope="all openid",
    )
    base.update(overrides)
    return Settings(**base)


class FakeClient:
    """Stands in for the Frappe Control Plane."""

    authorize_url = "https://home.invalid/api/method/frappe.integrations.oauth2.authorize"

    def __init__(self):
        self.exchange_error: Exception | None = None
        self.session_error: Exception | None = None
        self.seen_verifiers: list[str] = []
        self.closed: list[tuple[str, str]] = []
        self.revoked: list[str] = []
        self.whoami_payload = {
            "actor_person_id": "PSN-00001",
            "principals": {
                "human_actor": "PSN-00001",
                "machine_caller": None,
                "delegated": False,
            },
        }
        self.whoami_error: Exception | None = None

    def exchange_code(self, *, code, redirect_uri, code_verifier):
        self.seen_verifiers.append(code_verifier)
        if self.exchange_error:
            raise self.exchange_error
        return TokenSet(access_token="at-1", refresh_token="rt-1", expires_in=3600)

    def open_home_session(self, access_token, *, client="bff-web"):
        if self.session_error:
            raise self.session_error
        return "HDS-0001"

    def close_home_session(self, access_token, home_session_id):
        self.closed.append((access_token, home_session_id))
        return True

    def revoke_token(self, access_token):
        self.revoked.append(access_token)
        return True

    def whoami(self, access_token):
        if self.whoami_error:
            raise self.whoami_error
        return self.whoami_payload


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(make_settings(), store=store, client=client)
    # base_url https so the Secure cookie is retained by the test client.
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http, store, client


def login_and_get_state(http) -> str:
    response = http.get("/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0]


def complete_login(http) -> str:
    state = login_and_get_state(http)
    response = http.get(
        f"/callback?code=auth-code&state={state}", follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return state


# ------------------------------------------------------------------- health


def test_health_is_ok_and_leaks_nothing(ctx):
    http, _, _ = ctx
    response = http.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "client_secret" not in response.text
    assert set(body) == {"status", "service"}


# -------------------------------------------------------------------- login


def test_login_redirects_with_s256_pkce_and_state(ctx):
    http, _, _ = ctx
    response = http.get("/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]
    assert query["state"][0]
    assert query["code_challenge"][0]
    assert query["nonce"][0]


def test_login_never_exposes_verifier_or_secret(ctx):
    http, _, _ = ctx
    response = http.get("/login", follow_redirects=False)
    location = response.headers["location"]
    assert "code_verifier" not in location
    assert "super-secret" not in location
    assert "client_secret" not in location


def test_login_state_is_unique_per_request(ctx):
    http, _, _ = ctx
    states = {login_and_get_state(http) for _ in range(5)}
    assert len(states) == 5


def test_login_persists_transaction_server_side(ctx):
    http, store, _ = ctx
    state = login_and_get_state(http)
    transaction = store.consume_transaction(state)
    assert transaction is not None
    assert transaction.code_verifier


# ----------------------------------------------------------------- callback


def test_callback_happy_path_sets_opaque_cookie(ctx):
    http, store, client = ctx
    complete_login(http)

    raw = http.cookies.get(sessions.COOKIE_NAME)
    assert raw
    # The cookie is an opaque key, never a token.
    assert raw != "at-1"
    assert store.get_session(raw) is not None


def test_callback_claims_fixed_runtime_and_reports_binding(ctx):
    http, store, _ = ctx

    state = login_and_get_state(http)
    response = http.get(
        f"/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    browser_session = store.get_session(http.cookies.get(sessions.COOKIE_NAME))
    assert browser_session is not None
    assert store.resolve_runtime(RUNTIME_ID) == browser_session


def test_callback_refuses_to_replace_live_runtime_owner(ctx):
    http, store, _ = ctx
    owner = store.create_session(
        home_session_id="HDS-OWNER",
        access_token="owner-token",
        refresh_token=None,
    )
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND

    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert store.resolve_runtime(RUNTIME_ID) == owner
    contender_id = http.cookies.get(sessions.COOKIE_NAME)
    assert contender_id != owner.session_id
    assert store.get_session(contender_id) is not None


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("runtime binding requires a live session"),
        StoreUnavailableError("runtime store unavailable: sqlite detail"),
    ],
    ids=["invalid-candidate", "store-unavailable"],
)
def test_callback_binding_failure_is_a_generic_fail_closed_response(ctx, failure):
    http, store, _ = ctx

    def fail_claim(**kwargs):
        raise failure

    store.create_session_and_claim_runtime = fail_claim
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 503
    assert "location" not in response.headers
    assert sessions.COOKIE_NAME not in response.cookies
    assert "sqlite" not in response.text.lower()
    assert "live session" not in response.text.lower()
    with sqlite3.connect(store._path) as db:
        assert db.execute("SELECT COUNT(*) FROM bff_session").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM runtime_binding").fetchone()[0] == 0


def test_callback_uses_the_verifier_minted_for_that_state(ctx):
    http, store, client = ctx
    response = http.get("/login", follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)
    state, challenge = query["state"][0], query["code_challenge"][0]

    http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    from home_bff.oauth import compute_challenge

    assert compute_challenge(client.seen_verifiers[0]) == challenge


def test_callback_rejects_wrong_state(ctx):
    http, _, _ = ctx
    login_and_get_state(http)
    response = http.get("/callback?code=c&state=not-the-state", follow_redirects=False)
    assert response.status_code == 400


def test_callback_rejects_reused_state(ctx):
    http, _, _ = ctx
    state = login_and_get_state(http)
    first = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert first.status_code == 303
    replay = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert replay.status_code == 400


def test_callback_rejects_missing_code(ctx):
    http, _, _ = ctx
    state = login_and_get_state(http)
    response = http.get(f"/callback?state={state}", follow_redirects=False)
    assert response.status_code == 400


def test_callback_rejects_missing_state(ctx):
    http, _, _ = ctx
    response = http.get("/callback?code=c", follow_redirects=False)
    assert response.status_code == 400


def test_callback_propagates_provider_error(ctx):
    http, _, _ = ctx
    state = login_and_get_state(http)
    response = http.get(
        f"/callback?error=access_denied&state={state}", follow_redirects=False
    )
    assert response.status_code == 400


def test_callback_fails_closed_on_token_exchange_failure(ctx):
    http, store, client = ctx
    client.exchange_error = TokenExchangeError("upstream said no")
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 400
    assert sessions.COOKIE_NAME not in response.cookies


def test_callback_never_echoes_upstream_error_detail(ctx):
    http, _, client = ctx
    client.exchange_error = TokenExchangeError("secret-value-leaked")
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert "secret-value-leaked" not in response.text


@pytest.mark.parametrize(
    "reason",
    ["no linked person", "ambiguous linked_user", "user disabled"],
)
def test_callback_fails_closed_when_control_plane_refuses(ctx, reason):
    """Zero Persons, two Persons, and a disabled User all deny here."""
    http, _, client = ctx
    client.session_error = SessionOpenError(reason)
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 403
    assert sessions.COOKIE_NAME not in response.cookies


def test_session_cookie_flags(ctx):
    http, _, _ = ctx
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header
    assert "path=/" in header


def test_no_token_appears_in_any_callback_response(ctx):
    http, _, _ = ctx
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert "at-1" not in response.text
    assert "rt-1" not in response.text
    assert "super-secret" not in response.text


# ------------------------------------------------------------------ session


def test_session_requires_authentication(ctx):
    http, _, _ = ctx
    assert http.get("/session").status_code == 401


def test_session_reports_authenticated_without_identity(ctx):
    http, _, _ = ctx
    complete_login(http)
    body = http.get("/session").json()
    assert body["authenticated"] is True
    assert "actor_person_id" not in body
    assert "access_token" not in body


def test_expired_session_is_denied(ctx):
    http, store, _ = ctx
    complete_login(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)
    with sqlite3.connect(store._path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, raw),
        )
    assert http.get("/session").status_code == 401


def test_forged_cookie_is_denied(ctx):
    http, _, _ = ctx
    http.cookies.set(sessions.COOKIE_NAME, "totally-made-up", domain="bff.invalid")
    assert http.get("/session").status_code == 401


# ------------------------------------------------------------------- whoami


def test_whoami_returns_actor_resolved_by_control_plane(ctx):
    http, _, _ = ctx
    complete_login(http)
    body = http.get("/whoami").json()
    assert body["actor_person_id"] == "PSN-00001"


def test_whoami_denies_after_upstream_revocation(ctx):
    http, _, client = ctx
    complete_login(http)
    client.whoami_error = SessionOpenError("revoked")
    assert http.get("/whoami").status_code == 403


def test_caller_cannot_choose_actor_via_query_or_body(ctx):
    """There is no actor input. Supplying one changes nothing."""
    http, _, _ = ctx
    complete_login(http)
    body = http.get("/whoami?actor_person_id=PSN-00002").json()
    assert body["actor_person_id"] == "PSN-00001"


def test_actor_header_is_ignored(ctx):
    http, _, _ = ctx
    complete_login(http)
    body = http.get("/whoami", headers={"X-Actor-ID": "PSN-00002"}).json()
    assert body["actor_person_id"] == "PSN-00001"


def test_wrong_session_cannot_become_another_person(ctx):
    """A second browser's cookie resolves to its own session, never a chosen one."""
    http, store, _ = ctx
    complete_login(http)
    other = store.create_session(
        home_session_id="HDS-OTHER", access_token="at-other", refresh_token=None
    )
    http.cookies.set(sessions.COOKIE_NAME, other.session_id, domain="bff.invalid")
    response = http.post(f"/delegation?audience={sessions.AUDIENCE_CONTROL_PLANE}")
    claims = _claims(response.json()["delegation"])
    # Bound to ITS OWN home session, not the one it might have wished for.
    assert claims.session_id == "HDS-OTHER"


# --------------------------------------------------------------- delegation


def _claims(token: str):
    result = verify(
        token,
        secret=DELEGATION_SECRET,
        expected_issuer="episteck-home-bff",
        expected_audience=sessions.AUDIENCE_CONTROL_PLANE,
        now=int(time.time()),
    )
    assert result.valid, result.reason
    return result.context


def test_delegation_requires_a_session(ctx):
    http, _, _ = ctx
    assert http.post("/delegation").status_code == 401


def test_minted_delegation_verifies_at_the_control_plane(ctx):
    http, _, _ = ctx
    complete_login(http)
    token = http.post("/delegation").json()["delegation"]
    assert _claims(token).session_id == "HDS-0001"


def test_delegation_carries_no_person_id(ctx):
    http, _, _ = ctx
    complete_login(http)
    body = http.post("/delegation").json()
    assert "PSN-" not in body["delegation"]
    assert "actor_person_id" not in body


def test_delegation_rejects_unknown_audience(ctx):
    http, _, _ = ctx
    complete_login(http)
    assert http.post("/delegation?audience=some-other-service").status_code == 400


def test_delegation_is_audience_bound(ctx):
    """A Control Plane token must not verify at Nutrition."""
    http, _, _ = ctx
    complete_login(http)
    token = http.post("/delegation").json()["delegation"]
    result = verify(
        token,
        secret=DELEGATION_SECRET,
        expected_issuer="episteck-home-bff",
        expected_audience=sessions.AUDIENCE_NUTRITION,
        now=int(time.time()),
    )
    assert not result.valid


def test_delegation_replay_is_denied_by_the_verifier(ctx):
    http, _, _ = ctx
    complete_login(http)
    token = http.post("/delegation").json()["delegation"]
    seen: set[str] = set()
    first = verify(
        token,
        secret=DELEGATION_SECRET,
        expected_issuer="episteck-home-bff",
        expected_audience=sessions.AUDIENCE_CONTROL_PLANE,
        now=int(time.time()),
        seen_token_ids=seen,
    )
    assert first.valid
    seen.add(first.context.token_id)
    replayed = verify(
        token,
        secret=DELEGATION_SECRET,
        expected_issuer="episteck-home-bff",
        expected_audience=sessions.AUDIENCE_CONTROL_PLANE,
        now=int(time.time()),
        seen_token_ids=seen,
    )
    assert not replayed.valid


# ------------------------------------------------------------------- logout


def test_logout_invalidates_session_and_clears_cookie(ctx):
    http, store, _ = ctx
    complete_login(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)

    response = http.post("/logout")
    assert response.status_code == 200
    assert store.get_session(raw) is None
    assert http.get("/session").status_code == 401


def test_logout_atomically_removes_the_runtime_binding_with_its_session(ctx):
    http, store, _ = ctx
    complete_login(http)
    session_id = http.cookies.get(sessions.COOKIE_NAME)
    assert store.resolve_runtime(RUNTIME_ID).session_id == session_id

    response = http.post("/logout")

    assert response.status_code == 200
    assert store.get_session(session_id) is None
    assert store.resolve_runtime(RUNTIME_ID) is None


def test_logout_revokes_upstream_session_and_token(ctx):
    http, _, client = ctx
    complete_login(http)
    http.post("/logout")
    assert client.closed == [("at-1", "HDS-0001")]
    assert client.revoked == ["at-1"]


def test_old_session_cannot_mint_delegation_after_logout(ctx):
    http, _, _ = ctx
    complete_login(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)
    http.post("/logout")
    http.cookies.set(sessions.COOKIE_NAME, raw, domain="bff.invalid")
    assert http.post("/delegation").status_code == 401


def test_logout_without_session_is_safe(ctx):
    http, _, _ = ctx
    assert http.post("/logout").status_code == 200


def test_logout_survives_upstream_failure(ctx):
    """Local logout must never be blocked by an unreachable Control Plane."""
    http, store, client = ctx
    complete_login(http)
    raw = http.cookies.get(sessions.COOKIE_NAME)

    def boom(*args, **kwargs):
        raise RuntimeError("upstream down")

    client.close_home_session = boom
    client.revoke_token = boom
    assert http.post("/logout").status_code == 200
    assert store.get_session(raw) is None


# ------------------------------------------------------------------- config


def test_config_rejects_plaintext_redirect_uri():
    import os

    env = {
        "HOME_BASE_URL": "https://home.invalid",
        "BFF_CLIENT_ID": "c",
        "BFF_CLIENT_SECRET": "s",
        "BFF_REDIRECT_URI": "http://bff.invalid/callback",
        "HOME_DELEGATION_SECRET": "d",
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        with pytest.raises(ConfigError):
            Settings.from_env()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_config_requires_every_secret():
    import os

    keys = [
        "HOME_BASE_URL",
        "BFF_CLIENT_ID",
        "BFF_CLIENT_SECRET",
        "BFF_REDIRECT_URI",
        "HOME_DELEGATION_SECRET",
    ]
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    try:
        with pytest.raises(ConfigError):
            Settings.from_env()
    finally:
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v


def test_config_requires_an_explicit_mint_socket_path():
    import os

    env = {
        "HOME_BASE_URL": "https://home.invalid",
        "BFF_CLIENT_ID": "c",
        "BFF_CLIENT_SECRET": "s",
        "BFF_REDIRECT_URI": "https://bff.invalid/callback",
        "HOME_DELEGATION_SECRET": "d",
    }
    keys = [*env, "BFF_MINT_SOCKET_PATH"]
    old = {key: os.environ.get(key) for key in keys}
    os.environ.update(env)
    os.environ.pop("BFF_MINT_SOCKET_PATH", None)
    try:
        with pytest.raises(ConfigError, match="BFF_MINT_SOCKET_PATH"):
            Settings.from_env()
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
