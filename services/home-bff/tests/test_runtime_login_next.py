"""Login with next=/runtime, and the runtime claim flag at /callback (H5)."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff.app import create_app
from home_bff.runtime import RUNTIME_ID
from home_bff.store import SessionStore
from tests.test_app import FakeClient, make_settings


def build(tmp_path, **settings):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    app = create_app(make_settings(**settings), store=store, client=FakeClient())
    return TestClient(app, base_url="https://bff.invalid"), store


def start_login(http, query: str = "") -> str:
    response = http.get(f"/login{query}", follow_redirects=False)
    assert response.status_code == 302
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def finish(http, state):
    return http.get(f"/callback?code=c&state={state}", follow_redirects=False)


def test_callback_claims_runtime_when_flag_on(tmp_path):
    http, store = build(tmp_path)
    assert finish(http, start_login(http)).status_code == 303
    assert store.resolve_runtime(RUNTIME_ID) is not None


def test_callback_does_not_claim_when_flag_off(tmp_path):
    http, store = build(tmp_path, runtime_legacy_binding=False)
    response = finish(http, start_login(http))
    assert response.status_code == 303
    assert sessions.COOKIE_NAME in response.headers["set-cookie"]
    assert store.resolve_runtime(RUNTIME_ID) is None


def test_login_next_runtime_sets_next_cookie(tmp_path):
    http, _ = build(tmp_path)
    response = http.get("/login?next=/runtime", follow_redirects=False)
    assert sessions.NEXT_COOKIE_NAME in response.headers.get_list("set-cookie")[-1] + "".join(
        response.headers.get_list("set-cookie")
    )


@pytest.mark.parametrize("value", ["//evil.example", "/app", "https://x.example", "", "/runtime/grant", "/runtime?x=1"])
def test_login_ignores_every_other_next_value(tmp_path, value):
    http, _ = build(tmp_path)
    response = http.get("/login", params={"next": value}, follow_redirects=False)
    assert sessions.NEXT_COOKIE_NAME not in "".join(response.headers.get_list("set-cookie"))


def test_callback_redirects_to_runtime_and_clears_next_cookie(tmp_path):
    http, _ = build(tmp_path)
    response = finish(http, start_login(http, "?next=/runtime"))
    assert response.status_code == 303
    assert response.headers["location"] == "/runtime"
    cleared = [c for c in response.headers.get_list("set-cookie") if sessions.NEXT_COOKIE_NAME in c]
    assert cleared and "Max-Age=0" in cleared[0]


def test_callback_default_redirect_is_app(tmp_path):
    http, _ = build(tmp_path)
    assert finish(http, start_login(http)).headers["location"] == "/app"


def test_next_cookie_is_ignored_when_login_fails(tmp_path):
    http, _ = build(tmp_path)
    state = start_login(http, "?next=/runtime")
    response = http.get(f"/callback?state={state}", follow_redirects=False)  # no code
    assert response.status_code == 400
    assert "location" not in response.headers
    assert any(sessions.NEXT_COOKIE_NAME in c for c in response.headers.get_list("set-cookie"))
