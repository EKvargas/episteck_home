"""claim_runtime_grant: an atomic grant that never replaces another person's live grant."""
import sqlite3
import threading
import time

import pytest

from home_bff.store import SessionStore

RUNTIME = "home-agent-ana"
AUD = {"home-control-plane"}
REF_A = "a" * 64
REF_B = "b" * 64
DAY = 86400


def _store(tmp_path) -> SessionStore:
    return SessionStore(str(tmp_path / "bff.sqlite"))


def _claim(store, ref, hds="HDS-1"):
    return store.claim_runtime_grant(
        RUNTIME, hds, AUD, ttl_seconds=DAY, grantor_ref=ref
    )


def test_claim_writes_when_no_row(tmp_path):
    store = _store(tmp_path)
    grant = _claim(store, REF_A)
    assert grant is not None and grant.grantor_ref == REF_A
    row = store.resolve_runtime_grant(RUNTIME)
    assert row is not None and row.home_session_id == "HDS-1"
    assert row.grantor_ref == REF_A and row.allowed_audiences == frozenset(AUD)


def test_claim_replaces_own_legacy_and_expired_rows(tmp_path):
    store = _store(tmp_path)
    store.put_runtime_grant(RUNTIME, "OLD", AUD, ttl_seconds=DAY, grantor_ref=REF_A)
    assert _claim(store, REF_A, "NEW-OWN") is not None
    store.put_runtime_grant(RUNTIME, "OLD", AUD, ttl_seconds=DAY, grantor_ref="")
    assert _claim(store, REF_B, "NEW-LEGACY") is not None
    assert store.resolve_runtime_grant(RUNTIME).grantor_ref == REF_B
    store.put_runtime_grant(RUNTIME, "OLD", AUD, ttl_seconds=-5, grantor_ref=REF_A)
    assert _claim(store, REF_B, "NEW-EXPIRED") is not None
    row = store.resolve_runtime_grant(RUNTIME)
    assert row.home_session_id == "NEW-EXPIRED" and row.grantor_ref == REF_B


def test_claim_refuses_another_persons_live_row(tmp_path):
    store = _store(tmp_path)
    store.put_runtime_grant(RUNTIME, "OWNER-HDS", AUD, ttl_seconds=DAY, grantor_ref=REF_A)
    assert _claim(store, REF_B, "INTRUDER") is None
    row = store.resolve_runtime_grant(RUNTIME)
    assert row.home_session_id == "OWNER-HDS" and row.grantor_ref == REF_A


def test_two_people_claiming_at_once_leave_exactly_one_owner(tmp_path):
    path = str(tmp_path / "bff.sqlite")
    stores = [SessionStore(path), SessionStore(path)]
    barrier = threading.Barrier(2)
    outcomes: dict[str, object] = {}

    def run(store, ref):
        barrier.wait()
        try:
            outcomes[ref] = store.claim_runtime_grant(
                RUNTIME, f"HDS-{ref[0]}", AUD, ttl_seconds=DAY, grantor_ref=ref
            )
        except Exception as exc:  # recorded, never swallowed
            outcomes[ref] = exc

    threads = [
        threading.Thread(target=run, args=(stores[0], REF_A)),
        threading.Thread(target=run, args=(stores[1], REF_B)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(outcomes) == {REF_A, REF_B}
    assert not [o for o in outcomes.values() if isinstance(o, BaseException)]
    winners = [ref for ref, o in outcomes.items() if o is not None]
    losers = [ref for ref, o in outcomes.items() if o is None]
    assert len(winners) == 1 and len(losers) == 1
    assert stores[0].resolve_runtime_grant(RUNTIME).grantor_ref == winners[0]


def test_resolving_an_expired_row_never_deletes_a_fresh_claim_made_in_the_gap(tmp_path):
    path = str(tmp_path / "bff.sqlite")
    reader = SessionStore(path)
    other = SessionStore(path)
    reader.put_runtime_grant(RUNTIME, "OLD", AUD, ttl_seconds=-5, grantor_ref=REF_A)
    real_connection = reader._connection
    fired = []

    def connection_then_claim():
        # The read connection closes, then A re-claims before resolve deletes.
        ctx = real_connection()

        class Wrapper:
            def __enter__(self_inner):
                return ctx.__enter__()

            def __exit__(self_inner, *exc):
                result = ctx.__exit__(*exc)
                if not fired:
                    fired.append(True)
                    other.claim_runtime_grant(
                        RUNTIME, "FRESH", AUD, ttl_seconds=DAY, grantor_ref=REF_A
                    )
                return result

        return Wrapper()

    reader._connection = connection_then_claim
    assert reader.resolve_runtime_grant(RUNTIME) is None  # it read the expired row
    reader._connection = real_connection
    row = reader.resolve_runtime_grant(RUNTIME)
    assert row is not None and row.home_session_id == "FRESH"
    assert row.grantor_ref == REF_A


def test_claim_with_an_empty_ref_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        _claim(store, "")
    assert store.resolve_runtime_grant(RUNTIME) is None
