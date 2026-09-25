"""Server-side store: single-use transactions, durability, expiry (G1.6)."""
from __future__ import annotations

import sqlite3
import time

from home_bff.store import SessionStore


def make_store(tmp_path) -> SessionStore:
    return SessionStore(str(tmp_path / "bff.sqlite"))


def test_transaction_round_trip(tmp_path):
    store = make_store(tmp_path)
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://b/cb",
        login_binding_hash="test-hash",
    )
    transaction = store.consume_transaction("s1")
    assert transaction is not None
    assert transaction.code_verifier == "v1"


def test_transaction_is_single_use(tmp_path):
    store = make_store(tmp_path)
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://b/cb",
        login_binding_hash="test-hash",
    )
    assert store.consume_transaction("s1") is not None
    assert store.consume_transaction("s1") is None


def test_unknown_state_returns_nothing(tmp_path):
    assert make_store(tmp_path).consume_transaction("never-issued") is None


def test_empty_state_returns_nothing(tmp_path):
    assert make_store(tmp_path).consume_transaction("") is None


def test_expired_transaction_is_denied_and_spent(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = make_store(tmp_path)
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://b/cb",
        login_binding_hash="test-hash",
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE oauth_transaction SET expires_at = ? WHERE state = 's1'",
            (int(time.time()) - 1,),
        )
    assert store.consume_transaction("s1") is None
    # Still consumed: a stale state can never be retried.
    assert store.consume_transaction("s1") is None


def test_session_round_trip(tmp_path):
    store = make_store(tmp_path)
    created = store.create_session(
        home_session_id="HDS-1", access_token="at", refresh_token="rt"
    )
    fetched = store.get_session(created.session_id)
    assert fetched is not None
    assert fetched.home_session_id == "HDS-1"


def test_session_ids_are_unique_and_opaque(tmp_path):
    store = make_store(tmp_path)
    ids = {
        store.create_session(
            home_session_id="HDS-1", access_token="at", refresh_token=None
        ).session_id
        for _ in range(10)
    }
    assert len(ids) == 10
    assert all(len(i) >= 32 and "HDS-1" not in i for i in ids)


def test_expired_session_is_denied_and_removed(tmp_path):
    store = make_store(tmp_path)
    created = store.create_session(
        home_session_id="HDS-1", access_token="at", refresh_token=None, ttl_seconds=-1
    )
    assert store.get_session(created.session_id) is None
    assert store.delete_session(created.session_id) is False


def test_delete_session(tmp_path):
    store = make_store(tmp_path)
    created = store.create_session(
        home_session_id="HDS-1", access_token="at", refresh_token=None
    )
    assert store.delete_session(created.session_id) is True
    assert store.get_session(created.session_id) is None


def test_missing_session_id_is_denied(tmp_path):
    assert make_store(tmp_path).get_session(None) is None


def test_purge_expired_removes_both_tables(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = make_store(tmp_path)
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://b/cb",
        login_binding_hash="test-hash",
    )
    store.create_session(
        home_session_id="HDS-1", access_token="at", refresh_token=None, ttl_seconds=-1
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE oauth_transaction SET expires_at = ?", (int(time.time()) - 1,)
        )
    assert store.purge_expired() == 2


def test_sessions_survive_reopening_the_database(tmp_path):
    """A service restart must not log everyone out."""
    path = str(tmp_path / "bff.sqlite")
    store = SessionStore(path)
    created = store.create_session(
        home_session_id="HDS-1", access_token="at", refresh_token=None
    )
    store.close()

    reopened = SessionStore(path)
    assert reopened.get_session(created.session_id) is not None


def test_transaction_persists_login_binding_hash(tmp_path):
    from home_bff.store import SessionStore

    store = SessionStore(str(tmp_path / "bff.sqlite"))
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://bff.invalid/callback",
        login_binding_hash="hash-of-binding",
    )
    transaction = store.consume_transaction("s1")
    assert transaction is not None
    assert transaction.login_binding_hash == "hash-of-binding"


def test_migration_adds_login_binding_hash_column_to_existing_db(tmp_path):
    """A store created before this column existed must upgrade in place."""
    import sqlite3

    from home_bff.store import SessionStore, _SCHEMA_PRE_LOGIN_BINDING

    path = str(tmp_path / "legacy.sqlite")
    with sqlite3.connect(path) as db:
        db.executescript(_SCHEMA_PRE_LOGIN_BINDING)
        db.commit()

    store = SessionStore(path)
    store.begin_transaction(
        state="s1",
        code_verifier="v1",
        nonce="n1",
        redirect_uri="https://bff.invalid/callback",
        login_binding_hash="hash-1",
    )
    transaction = store.consume_transaction("s1")
    assert transaction.login_binding_hash == "hash-1"


def test_migration_is_idempotent_across_repeated_init(tmp_path):
    import sqlite3

    from home_bff.store import SessionStore

    path = str(tmp_path / "bff.sqlite")
    SessionStore(path)
    SessionStore(path)
    SessionStore(path)

    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(oauth_transaction)")]
    assert columns.count("login_binding_hash") == 1


def test_migration_survives_concurrent_store_construction(tmp_path):
    """Simulates the public app and the mint process starting at the same time."""
    import threading

    from home_bff.store import SessionStore

    path = str(tmp_path / "bff.sqlite")
    errors: list[Exception] = []

    def build():
        try:
            SessionStore(path)
        except Exception as error:  # pragma: no cover - failure path under test
            errors.append(error)

    threads = [threading.Thread(target=build) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    import sqlite3

    with sqlite3.connect(path) as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(oauth_transaction)")]
    assert columns.count("login_binding_hash") == 1
