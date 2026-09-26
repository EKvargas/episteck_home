"""Process-safe ownership of the fixed Home Agent runtime."""
from __future__ import annotations

import multiprocessing
import sqlite3
import time
from pathlib import Path

import pytest

from home_bff.runtime import RUNTIME_ID, BindResult
from home_bff.store import SessionStore, StoreUnavailableError


def _make_session(store: SessionStore, suffix: str, *, ttl_seconds: int = 300):
    return store.create_session(
        home_session_id=f"HDS-{suffix}",
        access_token=f"access-{suffix}",
        refresh_token=None,
        ttl_seconds=ttl_seconds,
    )


def _claim_after_barrier(
    path: str,
    session_id: str,
    barrier: multiprocessing.synchronize.Barrier,
    results: multiprocessing.queues.Queue,
) -> None:
    store = SessionStore(path)
    barrier.wait(timeout=10)
    try:
        result = store.claim_runtime(RUNTIME_ID, session_id)
    except Exception as error:  # return child failures to the parent test
        results.put(("error", type(error).__name__, str(error)))
    else:
        results.put(("result", result.value, session_id))


def _resolve_in_process(path: str, results: multiprocessing.queues.Queue) -> None:
    session = SessionStore(path).resolve_runtime(RUNTIME_ID)
    results.put(None if session is None else session.session_id)


def _race_claims(path: Path, session_ids: tuple[str, str]) -> list[tuple[str, ...]]:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_claim_after_barrier,
            args=(str(path), session_id, barrier, results),
        )
        for session_id in session_ids
    ]
    for process in processes:
        process.start()
    collected = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    return collected


def _resolve_from_another_process(path: Path) -> str | None:
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    process = context.Process(target=_resolve_in_process, args=(str(path), results))
    process.start()
    resolved = results.get(timeout=15)
    process.join(timeout=15)
    assert process.exitcode == 0
    return resolved


def _binding_count(path: Path) -> int:
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*) FROM runtime_binding").fetchone()[0]


def _session_count(path: Path) -> int:
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*) FROM bff_session").fetchone()[0]


def _create_and_claim(store: SessionStore):
    return store.create_session_and_claim_runtime(
        home_session_id="HDS-CANDIDATE",
        access_token="candidate-access",
        refresh_token="candidate-refresh",
        runtime_id=RUNTIME_ID,
    )


def test_atomic_create_and_claim_bound_persists_both_rows(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    session, result = _create_and_claim(store)

    assert result is BindResult.BOUND
    assert store.get_session(session.session_id) == session
    assert store.resolve_runtime(RUNTIME_ID) == session
    assert _session_count(path) == 1
    assert _binding_count(path) == 1


def test_atomic_create_and_claim_value_error_rolls_back_candidate(tmp_path, monkeypatch):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))

    def reject(*args):
        raise ValueError("runtime claim rejected")

    monkeypatch.setattr(store, "_claim_runtime_in_transaction", reject)
    with pytest.raises(ValueError, match="runtime claim rejected"):
        _create_and_claim(store)

    assert _session_count(path) == 0
    assert _binding_count(path) == 0


def test_atomic_create_and_claim_requires_controlled_result(tmp_path, monkeypatch):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    monkeypatch.setattr(store, "_claim_runtime_in_transaction", lambda *args: None)

    with pytest.raises(ValueError, match="runtime claim outcome"):
        _create_and_claim(store)

    assert _session_count(path) == 0
    assert _binding_count(path) == 0


def test_atomic_create_and_claim_sqlite_error_rolls_back_partial_binding(
    tmp_path, monkeypatch
):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))

    def partially_claim(db, runtime_id, session_id, now):
        db.execute(
            "INSERT INTO runtime_binding (runtime_id, session_id, bound_at) VALUES (?,?,?)",
            (runtime_id, session_id, now),
        )
        raise sqlite3.OperationalError("injected failure after binding insert")

    monkeypatch.setattr(store, "_claim_runtime_in_transaction", partially_claim)
    with pytest.raises(StoreUnavailableError):
        _create_and_claim(store)

    assert _session_count(path) == 0
    assert _binding_count(path) == 0


def test_atomic_create_and_claim_already_bound_keeps_owner_and_candidate(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    owner = _make_session(store, "owner")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND

    candidate, result = _create_and_claim(store)

    assert result is BindResult.ALREADY_BOUND
    assert store.get_session(candidate.session_id) == candidate
    assert store.resolve_runtime(RUNTIME_ID) == owner
    assert _session_count(path) == 2
    assert _binding_count(path) == 1


def test_atomic_create_and_claim_replaces_stale_owner(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    owner = _make_session(store, "owner")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, owner.session_id),
        )

    candidate, result = _create_and_claim(store)

    assert result is BindResult.REPLACED_STALE
    assert store.get_session(candidate.session_id) == candidate
    assert store.resolve_runtime(RUNTIME_ID) == candidate
    assert _binding_count(path) == 1


def test_fixed_runtime_id_is_not_caller_selected():
    assert RUNTIME_ID == "home-agent-primary"


def test_live_session_claims_empty_binding_and_resolves_from_another_store(tmp_path):
    path = tmp_path / "bff.sqlite"
    writer = SessionStore(str(path))
    session = _make_session(writer, "one")

    assert writer.claim_runtime(RUNTIME_ID, session.session_id) is BindResult.BOUND

    resolved = SessionStore(str(path)).resolve_runtime(RUNTIME_ID)
    assert resolved == session
    assert _binding_count(path) == 1


def test_same_live_session_claim_is_idempotent(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    session = _make_session(store, "one")
    assert store.claim_runtime(RUNTIME_ID, session.session_id) is BindResult.BOUND

    assert store.claim_runtime(RUNTIME_ID, session.session_id) is BindResult.SAME_SESSION


def test_different_live_session_cannot_replace_owner(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    owner = _make_session(store, "owner")
    contender = _make_session(store, "contender")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND

    assert (
        store.claim_runtime(RUNTIME_ID, contender.session_id)
        is BindResult.ALREADY_BOUND
    )
    assert store.resolve_runtime(RUNTIME_ID) == owner


def test_expired_owner_is_replaced_atomically(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    stale = _make_session(store, "stale")
    replacement = _make_session(store, "replacement")
    assert store.claim_runtime(RUNTIME_ID, stale.session_id) is BindResult.BOUND
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, stale.session_id),
        )

    assert (
        store.claim_runtime(RUNTIME_ID, replacement.session_id)
        is BindResult.REPLACED_STALE
    )
    assert store.resolve_runtime(RUNTIME_ID) == replacement


def test_deleted_owner_is_replaced_atomically(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    stale = _make_session(store, "stale")
    replacement = _make_session(store, "replacement")
    assert store.claim_runtime(RUNTIME_ID, stale.session_id) is BindResult.BOUND
    # Simulate a legacy/malformed writer that deleted without enabling foreign keys.
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM bff_session WHERE session_id = ?", (stale.session_id,))

    assert (
        store.claim_runtime(RUNTIME_ID, replacement.session_id)
        is BindResult.REPLACED_STALE
    )
    assert store.resolve_runtime(RUNTIME_ID) == replacement


@pytest.mark.parametrize("expired", [False, True], ids=["absent", "expired"])
def test_non_live_candidate_is_rejected_without_changing_binding(tmp_path, expired):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    owner = _make_session(store, "owner")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND
    if expired:
        candidate_id = _make_session(store, "expired", ttl_seconds=-1).session_id
    else:
        candidate_id = "missing-session"

    with pytest.raises(ValueError, match="live session"):
        store.claim_runtime(RUNTIME_ID, candidate_id)

    assert store.resolve_runtime(RUNTIME_ID) == owner
    assert _binding_count(path) == 1


@pytest.mark.parametrize("expired", [False, True], ids=["absent", "expired"])
def test_non_live_candidate_cannot_create_empty_binding(tmp_path, expired):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    if expired:
        candidate_id = _make_session(store, "expired", ttl_seconds=-1).session_id
    else:
        candidate_id = "missing-session"

    with pytest.raises(ValueError, match="live session"):
        store.claim_runtime(RUNTIME_ID, candidate_id)

    assert store.resolve_runtime(RUNTIME_ID) is None
    assert _binding_count(path) == 0


def test_resolve_removes_expired_binding(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    owner = _make_session(store, "owner")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, owner.session_id),
        )

    assert store.resolve_runtime(RUNTIME_ID) is None
    assert _binding_count(path) == 0


def test_resolve_removes_binding_whose_session_was_deleted(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    owner = _make_session(store, "owner")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND
    # Simulate an older writer that deleted without enabling foreign keys, leaving
    # the orphaned state that resolve_runtime must clean up defensively.
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM bff_session WHERE session_id = ?", (owner.session_id,))
    assert _binding_count(path) == 1

    assert store.resolve_runtime(RUNTIME_ID) is None
    assert _binding_count(path) == 0


def test_clear_runtime_for_session_only_clears_its_binding(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    owner = _make_session(store, "owner")
    other = _make_session(store, "other")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND

    assert store.clear_runtime_for_session(other.session_id) is False
    assert store.clear_runtime_for_session(owner.session_id) is True
    assert store.clear_runtime_for_session(owner.session_id) is False
    assert store.resolve_runtime(RUNTIME_ID) is None


def test_delete_session_cascades_binding_in_the_same_transaction(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    owner = _make_session(store, "owner")
    assert store.claim_runtime(RUNTIME_ID, owner.session_id) is BindResult.BOUND

    assert store.delete_session(owner.session_id) is True

    assert store.resolve_runtime(RUNTIME_ID) is None
    assert _binding_count(path) == 0


def test_locked_runtime_mutation_fails_closed_without_mutation(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    candidate = _make_session(store, "candidate")
    lock = sqlite3.connect(path)
    lock.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RuntimeError, match="runtime store unavailable"):
            store.claim_runtime(RUNTIME_ID, candidate.session_id)
    finally:
        lock.rollback()
        lock.close()

    assert store.resolve_runtime(RUNTIME_ID) is None
    assert _binding_count(path) == 0


def test_two_processes_racing_empty_binding_have_exactly_one_winner(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    contenders = (
        _make_session(store, "one").session_id,
        _make_session(store, "two").session_id,
    )

    results = _race_claims(path, contenders)

    assert sorted(result[1] for result in results) == sorted(
        [BindResult.BOUND.value, BindResult.ALREADY_BOUND.value]
    )
    winner = next(result[2] for result in results if result[1] == BindResult.BOUND)
    assert store.resolve_runtime(RUNTIME_ID).session_id == winner
    assert _resolve_from_another_process(path) == winner
    assert _binding_count(path) == 1


def test_two_processes_racing_stale_binding_have_exactly_one_replacer(tmp_path):
    path = tmp_path / "bff.sqlite"
    store = SessionStore(str(path))
    stale = _make_session(store, "stale")
    assert store.claim_runtime(RUNTIME_ID, stale.session_id) is BindResult.BOUND
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE bff_session SET expires_at = ? WHERE session_id = ?",
            (int(time.time()) - 1, stale.session_id),
        )
    contenders = (
        _make_session(store, "one").session_id,
        _make_session(store, "two").session_id,
    )

    results = _race_claims(path, contenders)

    assert sorted(result[1] for result in results) == sorted(
        [BindResult.REPLACED_STALE.value, BindResult.ALREADY_BOUND.value]
    )
    winner = next(
        result[2] for result in results if result[1] == BindResult.REPLACED_STALE
    )
    assert store.resolve_runtime(RUNTIME_ID).session_id == winner
    assert _binding_count(path) == 1
