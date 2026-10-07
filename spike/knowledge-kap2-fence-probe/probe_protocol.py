"""Disposable synthetic KAP-2 journal protocol probe; no network or real identities."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import dataclass


PREFIX = "home-auth/v1/partitions/synthetic-partition"


def slot_key(sequence: int) -> str:
    return f"{PREFIX}/slots/{sequence:020d}.json"


def outcome_key(sequence: int) -> str:
    return f"{PREFIX}/outcomes/{sequence:020d}.json"


def encoded(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class Conflict(Exception):
    pass


class SyntheticStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self.available = True

    def create(self, key: str, value: dict) -> bytes:
        if not self.available:
            raise ConnectionError("synthetic journal unavailable")
        data = encoded(value)
        with self.lock:
            if key in self.objects:
                raise Conflict(key)
            self.objects[key] = data
        return data

    def get(self, key: str) -> dict | None:
        if not self.available:
            raise ConnectionError("synthetic journal unavailable")
        data = self.objects.get(key)
        return json.loads(data) if data is not None else None


@dataclass
class Local:
    sequence: int = 0
    epoch: int = 1
    grant_state: str = "ACTIVE"
    ready_flag_from_backup: bool = True  # Deliberately ignored by authorize().


def scan(store: SyntheticStore) -> tuple[int, int, str, str]:
    """Derive the head from contiguous immutable slots/outcomes, never a pointer."""
    sequence, epoch, state, previous = 0, 1, "ACTIVE", "GENESIS"
    while True:
        slot = store.get(slot_key(sequence + 1))
        outcome = store.get(outcome_key(sequence + 1))
        if slot is None:
            if outcome is not None or any(
                key.startswith(PREFIX + "/slots/") and key > slot_key(sequence + 1)
                for key in store.objects
            ):
                return sequence, epoch, state, "BROKEN"
            return sequence, epoch, state, "READY"
        if outcome is None:
            return sequence, epoch, state, "PENDING"
        next_epoch = epoch + 1 if slot["kind"] == "EPOCH" else epoch
        if slot["previous"] != previous or slot["epoch"] != next_epoch:
            return sequence, epoch, state, "BROKEN"
        if outcome["slot_sha256"] != digest(encoded(slot)):
            return sequence, epoch, state, "BROKEN"
        if outcome["decision"] not in {"COMMIT", "UNCERTAIN_DENY"}:
            return sequence, epoch, state, "BROKEN"
        if outcome["decision"] == "UNCERTAIN_DENY" and slot["after"] == "ACTIVE":
            state = "REVOKED"
        else:
            state = slot["after"]
        sequence += 1
        epoch = next_epoch
        previous = digest(encoded(outcome))


def authorize(store: SyntheticStore, local: Local) -> tuple[bool, str]:
    try:
        sequence, epoch, state, status = scan(store)
    except ConnectionError:
        return False, "UNAVAILABLE"
    if status != "READY" or (local.sequence, local.epoch, local.grant_state) != (
        sequence, epoch, state
    ):
        return False, "UNVERIFIED"
    return state == "ACTIVE", "READY"


def reserve(store: SyntheticStore, local: Local, kind: str, after: str) -> dict:
    sequence, epoch, state, status = scan(store)
    if status != "READY" or (local.sequence, local.epoch, local.grant_state) != (
        sequence, epoch, state
    ):
        raise Conflict("writer has no verified head")
    previous = "GENESIS" if sequence == 0 else digest(encoded(store.get(outcome_key(sequence))))
    slot = {
        "sequence": sequence + 1,
        "epoch": epoch + (kind == "EPOCH"),
        "kind": kind,
        "previous": previous,
        "before": state,
        "after": after,
        "event_id": f"synthetic-event-{sequence + 1}",
    }
    store.create(slot_key(sequence + 1), slot)  # GCS: ifGenerationMatch=0.
    return slot


def commit_db(local: Local, slot: dict) -> None:
    local.sequence = slot["sequence"]
    local.epoch = slot["epoch"]
    local.grant_state = slot["after"]


def publish(store: SyntheticStore, slot: dict, decision: str = "COMMIT") -> None:
    store.create(
        outcome_key(slot["sequence"]),
        {"slot_sha256": digest(encoded(slot)), "decision": decision},
    )  # GCS: ifGenerationMatch=0.


def commit_gap_read() -> None:
    store, local = SyntheticStore(), Local(grant_state="REVOKED")
    # Genesis for a restrictive local state is represented by an epoch transition.
    local.grant_state = "ACTIVE"
    revoke = reserve(store, local, "REVOKE", "REVOKED")
    commit_db(local, revoke)
    assert authorize(store, local) == (False, "UNVERIFIED")
    publish(store, revoke)
    assert authorize(store, local) == (False, "READY")

    grant = reserve(store, local, "GRANT", "ACTIVE")
    commit_db(local, grant)
    assert authorize(store, local) == (False, "UNVERIFIED")
    publish(store, grant)
    assert authorize(store, local) == (True, "READY")


def competing_writers() -> None:
    store = SyntheticStore()
    barrier = threading.Barrier(2)
    results: list[str] = []

    def writer(name: str) -> None:
        barrier.wait()
        try:
            store.create(
                slot_key(1),
                {"sequence": 1, "epoch": 1, "kind": "REVOKE", "writer": name},
            )
            results.append("won")
        except Conflict:
            results.append("lost")

    threads = [threading.Thread(target=writer, args=(name,)) for name in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["lost", "won"]
    assert authorize(store, Local())[0] is False  # A reserved slot is not an allow.


def restore_before_revocation() -> None:
    store, local = SyntheticStore(), Local()
    backup = copy.deepcopy(local)
    revoke = reserve(store, local, "REVOKE", "REVOKED")
    commit_db(local, revoke)
    publish(store, revoke)
    assert authorize(store, local) == (False, "READY")
    restored = copy.deepcopy(backup)
    assert restored.ready_flag_from_backup
    assert authorize(store, restored) == (False, "UNVERIFIED")
    commit_db(restored, revoke)  # Restrictive committed event is replayed.
    assert authorize(store, restored) == (False, "READY")


def uncertain_commit_and_lost_ack() -> None:
    store, local = SyntheticStore(), Local()
    revoke = reserve(store, local, "REVOKE", "REVOKED")
    # A lost create acknowledgement is resolved only by exact-key/byte readback.
    assert store.get(slot_key(1)) == revoke
    try:
        store.create(slot_key(1), revoke)
    except Conflict:
        pass
    else:
        raise AssertionError("duplicate reservation accepted")
    assert authorize(store, local) == (False, "UNVERIFIED")
    # DB commit is uncertain: conservative resolution cannot publish an allow.
    publish(store, revoke, "UNCERTAIN_DENY")
    commit_db(local, revoke)
    assert authorize(store, local) == (False, "READY")


def writer_takeover() -> None:
    store, local = SyntheticStore(), Local()
    stale = copy.deepcopy(local)
    epoch = reserve(store, local, "EPOCH", "ACTIVE")
    commit_db(local, epoch)
    publish(store, epoch)
    assert authorize(store, stale) == (False, "UNVERIFIED")
    try:
        reserve(store, stale, "REVOKE", "REVOKED")
    except Conflict:
        pass
    else:
        raise AssertionError("stale epoch was accepted")
    # A bypassing stale writer can occupy a slot but not form an authoritative chain.
    store.create(
        slot_key(2),
        {"sequence": 2, "epoch": 1, "kind": "REVOKE", "previous": "forged", "after": "REVOKED"},
    )
    store.create(outcome_key(2), {"slot_sha256": "forged", "decision": "COMMIT"})
    assert authorize(store, local) == (False, "UNVERIFIED")


def journal_outage() -> None:
    store, local = SyntheticStore(), Local()
    store.available = False
    assert authorize(store, local) == (False, "UNAVAILABLE")


def main() -> None:
    cases = [
        commit_gap_read,
        competing_writers,
        restore_before_revocation,
        uncertain_commit_and_lost_ack,
        writer_takeover,
        journal_outage,
    ]
    results = {}
    for case in cases:
        try:
            case()
            results[case.__name__] = "PASS"
        except Exception as exc:
            results[case.__name__] = f"FAIL: {type(exc).__name__}: {exc}"
    print(json.dumps({"probe": "synthetic_journal", "results": results}, sort_keys=True))
    if any(result != "PASS" for result in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
