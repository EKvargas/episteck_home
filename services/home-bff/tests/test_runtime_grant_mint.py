"""/internal/mint resolves the runtime grant before the browser binding (H5)."""
from __future__ import annotations

import base64
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff import store as store_module
from home_bff.internal_app import create_internal_app
from home_bff.runtime import RUNTIME_ID, BindResult
from home_bff.store import SessionStore
from tests.test_app import make_settings

AUDIENCES = frozenset({"home-control-plane", "svc-nutrition", "svc-finance"})
DAY = 86400


class Clock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(store_module, "_now", lambda: int(c.now))
    return c


def build(tmp_path, clock, **settings):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    app = create_internal_app(make_settings(**settings), store=store, clock=clock)
    return TestClient(app), store


def _sid(response) -> str:
    token = response.headers["X-Episteck-Delegation"]
    body = token.split(".")[0]
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    return claims["sid"], claims


def _browser_binding(store, suffix="BROWSER"):
    session = store.create_session(
        home_session_id=f"HDS-{suffix}", access_token="tok", refresh_token=None
    )
    assert store.claim_runtime(RUNTIME_ID, session.session_id) is BindResult.BOUND


def test_mint_prefers_grant_over_browser_binding(tmp_path, clock):
    http, store = build(tmp_path, clock)
    _browser_binding(store)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=DAY)
    response = http.post("/internal/mint")
    assert response.status_code == 204
    assert _sid(response)[0] == "HDS-GRANT"


def test_mint_uses_grant_when_no_browser_session_exists(tmp_path, clock):
    http, store = build(tmp_path, clock, runtime_legacy_binding=False)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=90 * DAY)
    clock.now += 40 * DAY  # long after any 12 h browser session
    assert http.post("/internal/mint").status_code == 204


def test_mint_falls_back_to_legacy_binding_when_flag_on(tmp_path, clock):
    http, store = build(tmp_path, clock)
    _browser_binding(store)
    assert _sid(http.post("/internal/mint"))[0] == "HDS-BROWSER"


def test_mint_denies_without_grant_when_flag_off_even_with_binding(tmp_path, clock):
    http, store = build(tmp_path, clock, runtime_legacy_binding=False)
    _browser_binding(store)
    assert http.post("/internal/mint").status_code == 401


def test_mint_denies_expired_grant_even_if_home_session_still_active(tmp_path, clock):
    http, store = build(tmp_path, clock, runtime_legacy_binding=False)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=DAY)
    clock.now += DAY
    assert http.post("/internal/mint").status_code == 401


def test_mint_denies_when_control_plane_not_in_allowed_audiences(tmp_path, clock):
    http, store = build(tmp_path, clock, runtime_legacy_binding=False)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", frozenset({"svc-finance"}), ttl_seconds=DAY)
    assert http.post("/internal/mint").status_code == 401


def test_mint_after_revoke_is_401(tmp_path, clock):
    http, store = build(tmp_path, clock, runtime_legacy_binding=False)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=DAY)
    assert http.post("/internal/mint").status_code == 204
    store.delete_runtime_grant(RUNTIME_ID)
    assert http.post("/internal/mint").status_code == 401


def test_delegation_claims_are_unchanged_and_carry_no_person_id(tmp_path, clock):
    http, store = build(tmp_path, clock)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=DAY)
    _, claims = _sid(http.post("/internal/mint"))
    assert set(claims) == {"iss", "aud", "iat", "exp", "jti", "sid"}
    assert claims["aud"] == sessions.AUDIENCE_CONTROL_PLANE


def test_rate_limit_601st_in_a_minute_is_429_with_static_log(tmp_path, clock, caplog):
    http, store = build(tmp_path, clock)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=DAY)
    for _ in range(600):
        assert http.post("/internal/mint").status_code == 204
    with caplog.at_level(logging.WARNING, logger="home_bff"):
        response = http.post("/internal/mint")
    assert response.status_code == 429
    assert "X-Episteck-Delegation" not in response.headers
    assert [r.getMessage() for r in caplog.records] == ["mint rate limit exceeded"]


def test_rate_limit_window_resets_next_minute(tmp_path, clock):
    http, store = build(tmp_path, clock)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=DAY)
    for _ in range(601):
        http.post("/internal/mint")
    clock.now += 60
    assert http.post("/internal/mint").status_code == 204


def test_mint_records_last_use_once_per_minute(tmp_path, clock):
    http, store = build(tmp_path, clock)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", AUDIENCES, ttl_seconds=DAY)
    assert store.resolve_runtime_grant(RUNTIME_ID).last_mint_at is None
    http.post("/internal/mint")
    first = store.resolve_runtime_grant(RUNTIME_ID).last_mint_at
    assert first == int(clock.now) - int(clock.now) % 60
    clock.now += 61
    http.post("/internal/mint")
    assert store.resolve_runtime_grant(RUNTIME_ID).last_mint_at == first + 60
