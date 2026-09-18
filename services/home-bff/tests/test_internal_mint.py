"""Internal-only delegation mint app and Unix listener boundary."""
from __future__ import annotations

import os
import socket
import stat
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_bff import sessions
from home_bff import internal_main
from home_bff.app import create_app
from home_bff.internal_app import create_internal_app
from home_bff.internal_main import create_mint_socket
from home_bff.runtime import RUNTIME_ID, BindResult
from home_bff.store import SessionStore, StoreUnavailableError
from tests.test_app import DELEGATION_SECRET, FakeClient, make_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "episteck_home"))
from episteck_home.identity.delegation import verify  # noqa: E402


@pytest.fixture
def mint_ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    app = create_internal_app(make_settings(), store=store)
    with TestClient(app) as http:
        yield http, store, app


def _bind_session(store: SessionStore, *, suffix: str = "BOUND"):
    session = store.create_session(
        home_session_id=f"HDS-{suffix}",
        access_token=f"access-{suffix}",
        refresh_token=None,
    )
    assert store.claim_runtime(RUNTIME_ID, session.session_id) is BindResult.BOUND
    return session


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


def test_public_app_structurally_lacks_internal_mint(tmp_path):
    store = SessionStore(str(tmp_path / "public.sqlite"))
    app = create_app(make_settings(), store=store, client=FakeClient())

    with TestClient(app, base_url="https://bff.invalid") as http:
        assert http.post("/internal/mint").status_code == 404

    assert "/internal/mint" not in app.openapi()["paths"]
    assert all(route.path != "/internal/mint" for route in app.routes)


def test_internal_openapi_contains_only_mint_and_no_browser_routes(mint_ctx):
    _, _, app = mint_ctx

    paths = app.openapi()["paths"]

    assert set(paths) == {"/internal/mint"}
    assert set(paths["/internal/mint"]) == {"post"}
    for browser_path in {
        "/login",
        "/callback",
        "/logout",
        "/session",
        "/whoami",
        "/delegation",
    }:
        assert browser_path not in paths


def test_internal_mint_declares_no_request_selected_inputs(mint_ctx):
    _, _, app = mint_ctx

    operation = app.openapi()["paths"]["/internal/mint"]["post"]

    assert operation.get("parameters", []) == []
    assert "requestBody" not in operation
    assert "security" not in operation


def test_internal_mint_requires_a_live_runtime_binding(mint_ctx):
    http, _, _ = mint_ctx

    response = http.post("/internal/mint")

    assert response.status_code == 401
    assert "X-Episteck-Delegation" not in response.headers


def test_internal_mint_rejects_and_removes_a_stale_binding(mint_ctx):
    http, store, _ = mint_ctx
    owner = _bind_session(store)
    import sqlite3

    with sqlite3.connect(store._path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, owner.session_id),
        )

    response = http.post("/internal/mint")

    assert response.status_code == 401
    assert store.resolve_runtime(RUNTIME_ID) is None


def test_internal_mint_returns_empty_204_with_fixed_audience(mint_ctx):
    http, store, _ = mint_ctx
    owner = _bind_session(store)

    response = http.post(
        "/internal/mint?runtime_id=attacker&audience=svc-nutrition",
        json={"session_id": "attacker", "actor_person_id": "PSN-ATTACKER"},
        headers={"Cookie": "episteck_home_session=attacker"},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    claims = _claims(response.headers["X-Episteck-Delegation"])
    assert claims.session_id == owner.home_session_id


def test_each_successful_internal_mint_has_a_fresh_jti(mint_ctx):
    http, store, _ = mint_ctx
    _bind_session(store)

    first = http.post("/internal/mint")
    second = http.post("/internal/mint")

    assert first.status_code == second.status_code == 204
    first_claims = _claims(first.headers["X-Episteck-Delegation"])
    second_claims = _claims(second.headers["X-Episteck-Delegation"])
    assert first.headers["X-Episteck-Delegation"] != second.headers[
        "X-Episteck-Delegation"
    ]
    assert first_claims.token_id != second_claims.token_id


def test_internal_mint_store_failure_is_generic_and_fail_closed(mint_ctx):
    http, store, _ = mint_ctx

    def unavailable(runtime_id):
        raise StoreUnavailableError("runtime store unavailable: sqlite detail")

    store.resolve_runtime = unavailable
    response = http.post("/internal/mint")

    assert response.status_code == 503
    assert "X-Episteck-Delegation" not in response.headers
    assert "sqlite" not in response.text.lower()


def test_internal_main_hands_only_the_prebound_socket_to_uvicorn(monkeypatch):
    settings = make_settings(mint_socket_path="/run/test/mint.sock")
    internal_app = object()
    calls = {}

    class FakeSocket:
        closed = False

        def close(self):
            self.closed = True

    fake_socket = FakeSocket()

    def fake_create_socket(path, *, expected_uid):
        calls["create_socket"] = (path, expected_uid)
        return fake_socket

    class FakeServer:
        def __init__(self, config):
            calls["server_config"] = config

        def run(self, *, sockets):
            calls["sockets"] = sockets

    monkeypatch.setattr(internal_main.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(internal_main.os, "getuid", lambda: 1234, raising=False)
    monkeypatch.setattr(internal_main, "create_mint_socket", fake_create_socket)
    monkeypatch.setattr(
        internal_main, "create_internal_app", lambda configured: internal_app
    )
    monkeypatch.setattr(
        internal_main.uvicorn,
        "Config",
        lambda app, access_log: (app, access_log),
    )
    monkeypatch.setattr(internal_main.uvicorn, "Server", FakeServer)

    internal_main.main()

    assert calls["create_socket"] == (Path(settings.mint_socket_path), 1234)
    assert calls["server_config"] == (internal_app, False)
    assert calls["sockets"] == [fake_socket]
    assert fake_socket.closed is True


pytestmark_socket = pytest.mark.skipif(
    os.name == "nt", reason="requires real Unix socket ownership and mode semantics"
)


@pytestmark_socket
def test_create_mint_socket_has_exact_type_owner_and_mode(tmp_path):
    path = tmp_path / "mint.sock"

    sock = create_mint_socket(path, expected_uid=os.getuid())
    try:
        metadata = path.lstat()
        assert isinstance(sock, socket.socket)
        assert stat.S_ISSOCK(metadata.st_mode)
        assert metadata.st_uid == os.getuid()
        assert stat.S_IMODE(metadata.st_mode) == 0o660
    finally:
        sock.close()


@pytestmark_socket
def test_create_mint_socket_restores_the_process_umask(tmp_path):
    path = tmp_path / "mint.sock"
    original = os.umask(0o027)
    sock = None
    try:
        sock = create_mint_socket(path, expected_uid=os.getuid())
        observed = os.umask(0o077)
        os.umask(observed)
        assert observed == 0o027
    finally:
        if sock is not None:
            sock.close()
        os.umask(original)


@pytestmark_socket
def test_create_mint_socket_replaces_owned_stale_socket(tmp_path):
    path = tmp_path / "mint.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()

    sock = create_mint_socket(path, expected_uid=os.getuid())
    try:
        assert stat.S_ISSOCK(path.lstat().st_mode)
        assert stat.S_IMODE(path.lstat().st_mode) == 0o660
    finally:
        sock.close()


@pytest.mark.parametrize("kind", ["symlink", "directory", "regular-file"])
@pytestmark_socket
def test_create_mint_socket_refuses_non_socket_stale_paths(tmp_path, kind):
    path = tmp_path / "mint.sock"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_text("keep", encoding="utf-8")
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    else:
        path.write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing"):
        create_mint_socket(path, expected_uid=os.getuid())

    assert path.exists() or path.is_symlink()


@pytestmark_socket
def test_create_mint_socket_refuses_wrong_owner_socket_without_unlinking(tmp_path):
    path = tmp_path / "mint.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(path))
    stale.close()
    inode = path.lstat().st_ino

    with pytest.raises(RuntimeError, match="owner"):
        create_mint_socket(path, expected_uid=os.getuid() + 1)

    assert path.lstat().st_ino == inode
    assert stat.S_ISSOCK(path.lstat().st_mode)
