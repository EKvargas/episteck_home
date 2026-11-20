"""The mint serves the runtime the gateway names in X-Runtime-ID, and only that one."""
from __future__ import annotations

import base64
import json
import logging

import pytest
from fastapi.testclient import TestClient

from home_bff import store as store_module
from home_bff.internal_app import MINT_LIMIT_PER_MINUTE, create_internal_app
from home_bff.runtime import PRIMARY_GRANT_AUDIENCES, PRIMARY_RUNTIME_ID
from home_bff.store import SessionStore
from tests.test_app import make_settings

ANA = "home-agent-ana"
ANA_AUDIENCES = frozenset({"home-control-plane"})
HEADER = "X-Runtime-ID"
DAY = 86400


class Clock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _sid(response) -> str:
    body = response.headers["X-Episteck-Delegation"].split(".")[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))["sid"]


def _build(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(store_module, "_now", lambda: int(clock.now))
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    settings = make_settings(
        runtime_ids=(PRIMARY_RUNTIME_ID, ANA), runtime_legacy_binding=False
    )
    app = create_internal_app(settings, store=store, clock=clock)
    store.put_runtime_grant(
        PRIMARY_RUNTIME_ID, "HDS-OWNER", PRIMARY_GRANT_AUDIENCES, ttl_seconds=DAY
    )
    store.put_runtime_grant(ANA, "HDS-ANA", ANA_AUDIENCES, ttl_seconds=DAY)
    return TestClient(app), store


@pytest.fixture
def mint_with_clock(tmp_path, monkeypatch):
    clock = Clock()
    http, store = _build(tmp_path, monkeypatch, clock)
    return http, store, clock


@pytest.fixture
def mint(mint_with_clock):
    http, store, _ = mint_with_clock
    return http, store


@pytest.mark.parametrize(
    "headers",
    [{}, {HEADER: ""}, {HEADER: "home-agent-other"}, {HEADER: "HOME-AGENT-PRIMARY"}],
)
def test_missing_or_unknown_runtime_header_is_401_and_never_the_primary(mint, headers):
    http, _ = mint
    response = http.post("/internal/mint", headers=headers)
    assert response.status_code == 401
    assert "X-Episteck-Delegation" not in response.headers


def test_ana_header_mints_for_anas_grant_only(mint):
    http, _ = mint
    response = http.post("/internal/mint", headers={HEADER: ANA})
    assert response.status_code == 204
    assert _sid(response) == "HDS-ANA"


def test_ana_without_grant_is_401_while_primary_grant_is_live(mint):
    http, store = mint
    store.delete_runtime_grant(ANA)
    assert http.post("/internal/mint", headers={HEADER: ANA}).status_code == 401
    assert (
        http.post("/internal/mint", headers={HEADER: PRIMARY_RUNTIME_ID}).status_code
        == 204
    )


def test_primary_header_mints_for_the_owner_as_before(mint):
    http, _ = mint
    response = http.post("/internal/mint", headers={HEADER: PRIMARY_RUNTIME_ID})
    assert response.status_code == 204
    assert _sid(response) == "HDS-OWNER"


def test_finance_mint_refuses_any_runtime_but_primary(mint):
    http, store = mint
    store.put_runtime_grant(ANA, "HDS-ANA", PRIMARY_GRANT_AUDIENCES, ttl_seconds=DAY)
    assert http.post("/internal/mint_finance", headers={HEADER: ANA}).status_code == 401
    assert http.post("/internal/mint_finance").status_code == 401


def test_finance_mint_for_primary_unchanged(mint):
    http, _ = mint
    response = http.post("/internal/mint_finance", headers={HEADER: PRIMARY_RUNTIME_ID})
    assert response.status_code == 204
    assert _sid(response) == "HDS-OWNER"


def test_each_runtime_has_its_own_rate_limit(mint_with_clock):
    http, _, _ = mint_with_clock
    ana = {HEADER: ANA}
    codes = [http.post("/internal/mint", headers=ana).status_code for _ in range(MINT_LIMIT_PER_MINUTE)]
    assert set(codes) == {204}
    assert http.post("/internal/mint", headers=ana).status_code == 429
    assert (
        http.post("/internal/mint", headers={HEADER: PRIMARY_RUNTIME_ID}).status_code
        == 204
    )


def test_unknown_runtime_log_line_is_static(mint, caplog):
    http, _ = mint
    with caplog.at_level(logging.DEBUG, logger="home_bff"):
        assert http.post("/internal/mint", headers={HEADER: "evil-value"}).status_code == 401
    assert "mint refused: unknown runtime" in caplog.text
    assert "evil-value" not in caplog.text


def test_legacy_row_without_ref_still_mints_for_primary(mint):
    http, store = mint
    store.put_runtime_grant(
        PRIMARY_RUNTIME_ID, "HDS-LEGACY", PRIMARY_GRANT_AUDIENCES, ttl_seconds=DAY
    )
    response = http.post("/internal/mint", headers={HEADER: PRIMARY_RUNTIME_ID})
    assert response.status_code == 204
    assert _sid(response) == "HDS-LEGACY"
