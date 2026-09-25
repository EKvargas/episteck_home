"""Login-binding cookie primitives (F2a-BFF, B3 / §9)."""
from __future__ import annotations

from home_bff import sessions


def test_login_binding_cookie_name_uses_host_prefix():
    assert sessions.LOGIN_BINDING_COOKIE_NAME == "__Host-episteck_home_login"


def test_login_binding_cookie_flags_have_no_domain():
    flags = sessions.LOGIN_BINDING_COOKIE_FLAGS
    assert flags["httponly"] is True
    assert flags["secure"] is True
    assert flags["samesite"] == "lax"
    assert flags["path"] == "/"
    assert "domain" not in flags


def test_login_binding_max_age_is_ten_minutes():
    assert sessions.LOGIN_BINDING_MAX_AGE_SECONDS == 600


def test_new_login_binding_is_random_and_unique():
    values = {sessions.new_login_binding() for _ in range(10)}
    assert len(values) == 10
    assert all(len(v) >= 32 for v in values)


def test_hash_login_binding_is_sha256_hex():
    import hashlib

    value = "some-binding-value"
    expected = hashlib.sha256(value.encode()).hexdigest()
    assert sessions.hash_login_binding(value) == expected


def test_hash_login_binding_is_deterministic():
    value = sessions.new_login_binding()
    assert sessions.hash_login_binding(value) == sessions.hash_login_binding(value)


def test_different_bindings_hash_differently():
    a, b = sessions.new_login_binding(), sessions.new_login_binding()
    assert sessions.hash_login_binding(a) != sessions.hash_login_binding(b)


# --------------------------------------------------------- BFF-1 .. BFF-6 (HTTP)

import pytest
from fastapi.testclient import TestClient

from home_bff.app import create_app
from home_bff.frappe_client import SessionOpenError, TokenExchangeError
from home_bff.runtime import RUNTIME_ID, BindResult
from home_bff.store import SessionStore, StoreUnavailableError

# Reuse the exact fixtures test_app.py already defines, so both files stay in sync.
from tests.test_app import FakeClient, login_and_get_state, make_settings  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http, store, client


def _binding_cookie(http) -> str | None:
    from home_bff import sessions

    return http.cookies.get(sessions.LOGIN_BINDING_COOKIE_NAME)


def test_login_sets_binding_cookie_with_exact_flags(ctx):
    http, _, _ = ctx
    from home_bff import sessions

    response = http.get("/login", follow_redirects=False)
    header = response.headers.get("set-cookie", "")
    assert sessions.LOGIN_BINDING_COOKIE_NAME in header
    lowered = header.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "domain=" not in lowered
    assert "max-age=600" in lowered


def test_bff1_successful_callback_returns_303_with_flags_and_clears_binding(ctx):
    http, store, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)  # a second /login overwrites the first binding
    # login_and_get_state issues its own /login, so pick up the LATEST binding cookie:
    binding = _binding_cookie(http)
    assert binding

    response = http.get(
        f"/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert response.text == ""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"

    from home_bff import sessions

    session_header = response.headers.get("set-cookie", "")
    assert sessions.COOKIE_NAME in session_header

    binding_after = response.cookies.get(sessions.LOGIN_BINDING_COOKIE_NAME)
    # Cleared: either absent, or present with an expiry in the past / empty value.
    assert not binding_after or binding_after == ""


def test_bff2_malicious_redirect_params_and_spoofed_host_still_redirect_to_app(ctx):
    http, _, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)

    response = http.get(
        f"/callback?code=c&state={state}"
        "&return_to=https://evil.example/steal"
        "&next=/other"
        "&redirect_uri=https://evil.example/cb",
        headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/app"


def test_bff3_replayed_state_is_400_with_no_session_cookie(ctx):
    http, _, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)

    first = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert first.status_code == 303

    replay = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert replay.status_code == 400
    from home_bff import sessions

    assert sessions.COOKIE_NAME not in replay.cookies


def test_bff4_missing_binding_cookie_is_400_transaction_consumed_no_session(ctx):
    http, store, _ = ctx
    state = login_and_get_state(http)
    http.cookies.clear()  # binding cookie never reaches the callback request

    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 400
    from home_bff import sessions

    assert sessions.COOKIE_NAME not in response.cookies
    # Transaction was consumed: a second attempt with the same state also fails.
    replay = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert replay.status_code == 400


def test_bff4_mismatched_binding_cookie_is_400_transaction_consumed_no_session(ctx):
    http, store, _ = ctx
    state = login_and_get_state(http)
    from home_bff import sessions

    http.cookies.set(
        sessions.LOGIN_BINDING_COOKIE_NAME, "wrong-binding-value", domain="bff.invalid"
    )

    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 400
    assert sessions.COOKIE_NAME not in response.cookies
    replay = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert replay.status_code == 400


def test_bff4_second_tab_login_overwrites_first_tabs_binding(ctx):
    """Two /login calls share one binding cookie slot; only the newest matches."""
    from urllib.parse import parse_qs, urlparse

    http, _, _ = ctx
    first_login = http.get("/login", follow_redirects=False)
    first_state = parse_qs(urlparse(first_login.headers["location"]).query)["state"][0]
    login_and_get_state(http)  # this issues a second /login, overwriting the binding

    # The callback for the FIRST tab's state now sees the SECOND tab's binding.
    response = http.get(
        f"/callback?code=c&state={first_state}", follow_redirects=False
    )
    assert response.status_code == 400


def test_bff5_error_param_is_400_no_redirect_no_cookie(ctx):
    http, _, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(
        f"/callback?error=access_denied&state={state}", follow_redirects=False
    )
    assert response.status_code == 400
    assert "location" not in response.headers


def test_bff5_exchange_failure_is_400(ctx):
    http, _, client = ctx
    client.exchange_error = TokenExchangeError("nope")
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 400
    assert "location" not in response.headers


def test_bff5_open_session_refusal_is_403(ctx):
    http, _, client = ctx
    client.session_error = SessionOpenError("no linked person")
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 403
    assert "location" not in response.headers


def test_bff5_runtime_binding_failure_is_503(ctx):
    http, store, _ = ctx
    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)

    def fail_claim(runtime_id, session_id):
        raise StoreUnavailableError("runtime store unavailable")

    store.claim_runtime = fail_claim
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 503
    assert "location" not in response.headers
    from home_bff import sessions

    assert sessions.COOKIE_NAME not in response.cookies


def test_bff6_already_bound_still_returns_303_and_enum_absent(ctx):
    http, store, _ = ctx
    owner = store.create_session(
        home_session_id="HDS-OWNER", access_token="owner-token", refresh_token=None
    )
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND

    http.get("/login", follow_redirects=False)
    state = login_and_get_state(http)
    response = http.get(f"/callback?code=c&state={state}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert BindResult.ALREADY_BOUND.value not in response.text
    assert "runtime_binding" not in response.text
