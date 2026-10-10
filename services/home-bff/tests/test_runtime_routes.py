"""/runtime page, /runtime/grant, /runtime/revoke, /logout/all (H5)."""
from __future__ import annotations

import logging
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from home_bff import csrf, sessions
from home_bff.app import create_app
from home_bff.frappe_client import ControlPlaneUnreachable, SessionOpenError
from home_bff.runtime import RUNTIME_ID
from home_bff.store import SessionStore
from tests.test_app import DELEGATION_SECRET, FakeClient, make_settings

ORIGIN = "https://bff.invalid"
EXPECTED_AUDIENCES = {"home-control-plane", "svc-nutrition", "svc-finance"}


class GrantClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.open_calls: list[tuple] = []
        self.close_calls: list[tuple] = []
        self.open_error: Exception | None = None
        self.close_result: bool | None = True  # True / False / None (unreachable)

    def open_runtime_grant(self, access_token, runtime_id, ttl_days):
        self.open_calls.append((access_token, runtime_id, ttl_days))
        if self.open_error:
            raise self.open_error
        return "HDS-GRANT-SECRET"

    def close_runtime_grant(self, access_token, home_session_id):
        self.close_calls.append((access_token, home_session_id))
        return self.close_result


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = GrantClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url=ORIGIN) as http:
        yield http, store, client, str(tmp_path / "bff.sqlite")


def login(http):
    response = http.get("/login", follow_redirects=False)
    state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
    done = http.get(f"/callback?code=c&state={state}", follow_redirects=False)
    assert done.status_code == 303
    return http.cookies.get(sessions.COOKIE_NAME)


def token(cookie):
    return csrf.token_for(cookie, DELEGATION_SECRET)


def post(http, path, cookie, *, csrf_value="valid", origin=ORIGIN, extra_headers=None):
    value = token(cookie) if csrf_value == "valid" else csrf_value
    headers = {} if origin is None else {"Origin": origin}
    headers.update(extra_headers or {})
    data = {} if value is None else {"csrf": value}
    return http.post(path, data=data, headers=headers, follow_redirects=False)


def age_session(path, seconds):
    db = sqlite3.connect(path)
    db.execute("UPDATE bff_session SET created_at = created_at - ?", (seconds,))
    db.commit()
    db.close()


def put_grant(store, home_session_id="HDS-G"):
    store.put_runtime_grant(RUNTIME_ID, home_session_id, EXPECTED_AUDIENCES, ttl_seconds=86400)


# ------------------------------------------------------------------ GET /runtime


def test_page_without_session_redirects_to_login(ctx):
    http, *_ = ctx
    response = http.get("/runtime", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/runtime"


def test_page_shows_state_csrf_and_no_secrets(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store, "HDS-GRANT-SECRET")
    response = http.get("/runtime")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert token(cookie) in response.text
    for secret in ("HDS-GRANT-SECRET", "at-1", "rt-1", cookie, DELEGATION_SECRET, "super-secret"):
        assert secret not in response.text
    assert "puede actuar" in response.text


def test_page_without_grant_says_so(ctx):
    http, *_ = ctx
    login(http)
    assert "no tiene permiso" in http.get("/runtime").text


# ----------------------------------------------------------------- POST grant


def test_grant_requires_a_session(ctx):
    http, _, client, _ = ctx
    response = http.post("/runtime/grant", data={"csrf": "x"}, headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert client.open_calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"csrf_value": None},
        {"csrf_value": "wrong"},
        {"origin": "https://evil.example"},
        {"origin": None},
        {"origin": None, "extra_headers": {"Sec-Fetch-Site": "cross-site"}},
    ],
)
def test_grant_rejects_bad_csrf_without_calling_home(ctx, kwargs):
    http, store, client, _ = ctx
    cookie = login(http)
    response = post(http, "/runtime/grant", cookie, **kwargs)
    assert response.status_code == 403
    assert client.open_calls == []
    assert store.resolve_runtime_grant(RUNTIME_ID) is None


def test_grant_accepts_same_origin_fetch_metadata_without_origin(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    response = post(http, "/runtime/grant", cookie, origin=None,
                    extra_headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 303
    assert len(client.open_calls) == 1


def test_grant_with_stale_login_redirects_to_login_without_calling_home(ctx):
    http, store, client, path = ctx
    cookie = login(http)
    age_session(path, 601)
    response = post(http, "/runtime/grant", cookie)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/runtime"
    assert client.open_calls == []


def test_grant_with_recent_login_stores_pointer(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    response = post(http, "/runtime/grant", cookie)
    assert response.status_code == 303
    assert response.headers["location"] == "/runtime"
    assert client.open_calls == [("at-1", RUNTIME_ID, 90)]
    grant = store.resolve_runtime_grant(RUNTIME_ID)
    assert grant.home_session_id == "HDS-GRANT-SECRET"
    assert grant.allowed_audiences == EXPECTED_AUDIENCES
    assert 89 * 86400 < grant.expires_at - grant.granted_at <= 90 * 86400


def test_grant_refused_by_home_keeps_existing_row(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store, "HDS-OWNERS")
    client.open_error = SessionOpenError("Control Plane refused the session (HTTP 403)")
    response = post(http, "/runtime/grant", cookie)
    assert response.status_code == 403
    assert store.resolve_runtime_grant(RUNTIME_ID).home_session_id == "HDS-OWNERS"


def test_grant_with_home_unreachable_is_503_and_keeps_row(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store, "HDS-OWNERS")
    client.open_error = ControlPlaneUnreachable("Control Plane unreachable")
    response = post(http, "/runtime/grant", cookie)
    assert response.status_code == 503
    assert store.resolve_runtime_grant(RUNTIME_ID).home_session_id == "HDS-OWNERS"


# ---------------------------------------------------------------- POST revoke


def test_revoke_rejects_bad_csrf(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store)
    assert post(http, "/runtime/revoke", cookie, csrf_value="bad").status_code == 403
    assert client.close_calls == []
    assert store.resolve_runtime_grant(RUNTIME_ID) is not None


def test_revoke_confirmed_by_home_deletes_row(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store)
    assert post(http, "/runtime/revoke", cookie).status_code == 303
    assert client.close_calls == [("at-1", "HDS-G")]
    assert store.resolve_runtime_grant(RUNTIME_ID) is None


def test_revoke_with_home_down_still_deletes_row_and_logs_static_warning(ctx, caplog):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store)
    client.close_result = None
    with caplog.at_level(logging.WARNING, logger="home_bff"):
        assert post(http, "/runtime/revoke", cookie).status_code == 303
    assert store.resolve_runtime_grant(RUNTIME_ID) is None
    assert "runtime grant revoke: control plane unreachable" in caplog.text
    assert "HDS-G" not in caplog.text


def test_revoke_refused_by_home_keeps_row(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store)
    client.close_result = False
    assert post(http, "/runtime/revoke", cookie).status_code == 409
    assert store.resolve_runtime_grant(RUNTIME_ID) is not None


def test_revoke_without_grant_is_idempotent(ctx):
    http, _, client, _ = ctx
    cookie = login(http)
    assert post(http, "/runtime/revoke", cookie).status_code == 303
    assert client.close_calls == []


# ---------------------------------------------------------------- logout paths


def test_plain_logout_keeps_the_grant(ctx):
    http, store, client, _ = ctx
    login(http)
    put_grant(store)
    assert http.post("/logout").status_code == 200
    assert store.resolve_runtime_grant(RUNTIME_ID) is not None
    assert client.close_calls == []


@pytest.mark.parametrize(
    "close_result,row_kept,label",
    [(True, False, "revoked"), (None, False, "revoked"), (False, True, "kept")],
)
def test_logout_all_revokes_grant_and_session(ctx, close_result, row_kept, label):
    http, store, client, _ = ctx
    cookie = login(http)
    put_grant(store)
    client.close_result = close_result
    response = post(http, "/logout/all", cookie)
    assert response.status_code == 200
    assert response.json() == {"status": "logged out", "runtime_grant": label}
    assert (store.resolve_runtime_grant(RUNTIME_ID) is not None) is row_kept
    assert store.get_session(cookie) is None
    assert client.revoked == ["at-1"]
    assert ("at-1", "HDS-G") in client.close_calls


def test_logout_all_without_grant_reports_none(ctx):
    http, *_ = ctx
    cookie = login(http)
    assert post(http, "/logout/all", cookie).json()["runtime_grant"] == "none"


def test_logout_all_requires_csrf(ctx):
    http, store, client, _ = ctx
    cookie = login(http)
    assert post(http, "/logout/all", cookie, csrf_value="bad").status_code == 403
    assert store.get_session(cookie) is not None


# -------------------------------------------------------------------- hygiene


def test_logs_never_contain_credentials(ctx, caplog):
    http, store, client, _ = ctx
    with caplog.at_level(logging.DEBUG):
        cookie = login(http)
        post(http, "/runtime/grant", cookie)
        post(http, "/runtime/grant", cookie, csrf_value="bad")
        client.close_result = None
        post(http, "/runtime/revoke", cookie)
        post(http, "/logout/all", cookie)
    for secret in ("at-1", "rt-1", cookie, token(cookie), "HDS-GRANT-SECRET", DELEGATION_SECRET):
        assert secret not in caplog.text
