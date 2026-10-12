"""runtime_grant table: a pointer to a Home grant session, never a credential (H5)."""
from __future__ import annotations

import sqlite3

import pytest

from home_bff import store as store_module
from home_bff.store import RuntimeGrant, SessionStore

AUDIENCES = frozenset({"home-control-plane", "svc-nutrition", "svc-finance"})
DAY = 86400


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 1_800_000_000}
    monkeypatch.setattr(store_module, "_now", lambda: state["now"])
    return state


def make_store(tmp_path) -> SessionStore:
    return SessionStore(str(tmp_path / "bff.sqlite"))


def test_table_has_no_token_columns(tmp_path):
    store = make_store(tmp_path)
    db = sqlite3.connect(str(tmp_path / "bff.sqlite"))
    columns = {row[1] for row in db.execute("PRAGMA table_info(runtime_grant)")}
    assert columns == {
        "runtime_id", "home_session_id", "allowed_audiences",
        "granted_at", "expires_at", "last_mint_at",
    }


def test_put_then_resolve(tmp_path, clock):
    store = make_store(tmp_path)
    put = store.put_runtime_grant("rt", "HDS-G1", AUDIENCES, ttl_seconds=90 * DAY)
    assert put == RuntimeGrant(
        runtime_id="rt", home_session_id="HDS-G1", allowed_audiences=AUDIENCES,
        granted_at=clock["now"], expires_at=clock["now"] + 90 * DAY, last_mint_at=None,
    )
    assert store.resolve_runtime_grant("rt") == put


def test_put_replaces_existing(tmp_path, clock):
    store = make_store(tmp_path)
    store.put_runtime_grant("rt", "HDS-OLD", AUDIENCES, ttl_seconds=DAY)
    store.put_runtime_grant("rt", "HDS-NEW", AUDIENCES, ttl_seconds=DAY)
    assert store.resolve_runtime_grant("rt").home_session_id == "HDS-NEW"


def test_unknown_runtime_resolves_none(tmp_path):
    assert make_store(tmp_path).resolve_runtime_grant("nope") is None


def test_expired_grant_resolves_none_and_is_deleted(tmp_path, clock):
    store = make_store(tmp_path)
    store.put_runtime_grant("rt", "HDS-G1", AUDIENCES, ttl_seconds=DAY)
    clock["now"] += DAY
    assert store.resolve_runtime_grant("rt") is None
    db = sqlite3.connect(str(tmp_path / "bff.sqlite"))
    assert db.execute("SELECT COUNT(*) FROM runtime_grant").fetchone()[0] == 0


def test_delete(tmp_path, clock):
    store = make_store(tmp_path)
    store.put_runtime_grant("rt", "HDS-G1", AUDIENCES, ttl_seconds=DAY)
    assert store.delete_runtime_grant("rt") is True
    assert store.delete_runtime_grant("rt") is False
    assert store.resolve_runtime_grant("rt") is None


def test_touch_updates_at_most_once_per_minute(tmp_path, clock):
    store = make_store(tmp_path)
    store.put_runtime_grant("rt", "HDS-G1", AUDIENCES, ttl_seconds=DAY)
    store.touch_runtime_grant("rt")
    first = store.resolve_runtime_grant("rt").last_mint_at
    assert first == clock["now"] - clock["now"] % 60
    clock["now"] += 30
    store.touch_runtime_grant("rt")
    clock["now"] = first + 61
    store.touch_runtime_grant("rt")
    assert store.resolve_runtime_grant("rt").last_mint_at == (first + 61) - (first + 61) % 60


def test_touch_unknown_runtime_is_a_noop(tmp_path):
    make_store(tmp_path).touch_runtime_grant("nope")


def test_existing_store_file_gains_table_without_data_loss(tmp_path):
    path = str(tmp_path / "bff.sqlite")
    store_module_schema = store_module._SCHEMA_PRE_LOGIN_BINDING
    db = sqlite3.connect(path)
    db.executescript(store_module_schema)
    db.execute(
        "INSERT INTO bff_session VALUES ('s1','HDS-1','tok',NULL,1,4102444800)"
    )
    db.commit()
    db.close()
    store = SessionStore(path)
    assert store.get_session("s1") is not None
    assert store.resolve_runtime_grant("rt") is None


def test_second_store_on_same_file_is_harmless(tmp_path, clock):
    first = make_store(tmp_path)
    first.put_runtime_grant("rt", "HDS-G1", AUDIENCES, ttl_seconds=DAY)
    second = make_store(tmp_path)
    assert second.resolve_runtime_grant("rt").home_session_id == "HDS-G1"


def test_session_exposes_created_at(tmp_path, clock):
    store = make_store(tmp_path)
    created = store.create_session(home_session_id="H", access_token="a", refresh_token=None)
    assert created.created_at == clock["now"]
    assert store.get_session(created.session_id).created_at == clock["now"]
