from __future__ import annotations

import pytest

from app.store.repo import IdempotencyConflict
from tests.support import count_rows, make_repo, raw_execute, seed_workspace

AUDIT = dict(human_actor="PSN-1", machine_caller="svc-finance", channel="admin")


@pytest.fixture
def repo(tmp_path):
    r = make_repo(tmp_path)
    seed_workspace(r)
    return r


def _effect(repo, counter):
    def effect(conn):
        counter.append(1)
        conn.execute("INSERT INTO workspace_member(workspace_id,person_id,role) "
                     "VALUES('ws-1','PSN-9','MEMBER')")
        return {"added": "PSN-9"}
    return effect


def test_same_key_and_payload_runs_the_effect_once(repo):
    calls: list[int] = []
    first = repo.run_command("ws-1", "k1", "add_member", {"p": "PSN-9"}, _effect(repo, calls), **AUDIT)
    second = repo.run_command("ws-1", "k1", "add_member", {"p": "PSN-9"}, _effect(repo, calls), **AUDIT)
    assert first == second == {"added": "PSN-9"}
    assert len(calls) == 1
    assert count_rows(repo, "workspace_member") == 2


def test_same_key_with_different_payload_is_rejected(repo):
    calls: list[int] = []
    repo.run_command("ws-1", "k1", "add_member", {"p": "PSN-9"}, _effect(repo, calls), **AUDIT)
    with pytest.raises(IdempotencyConflict):
        repo.run_command("ws-1", "k1", "add_member", {"p": "PSN-8"}, _effect(repo, calls), **AUDIT)
    assert len(calls) == 1


def test_payload_key_order_does_not_change_identity(repo):
    calls: list[int] = []
    repo.run_command("ws-1", "k1", "t", {"a": 1, "b": 2}, _effect(repo, calls), **AUDIT)
    repo.run_command("ws-1", "k1", "t", {"b": 2, "a": 1}, _effect(repo, calls), **AUDIT)
    assert len(calls) == 1


def test_effect_and_log_commit_together_or_not_at_all(repo):
    def failing(conn):
        conn.execute("INSERT INTO workspace_member(workspace_id,person_id,role) "
                     "VALUES('ws-1','PSN-9','MEMBER')")
        raise RuntimeError("crash after the effect")

    with pytest.raises(RuntimeError):
        repo.run_command("ws-1", "k1", "t", {}, failing, **AUDIT)
    assert count_rows(repo, "workspace_member") == 1
    assert count_rows(repo, "command_log") == 0


def test_a_retry_after_a_failed_attempt_runs_the_effect(repo):
    calls: list[int] = []

    def flaky(conn):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first attempt dies")
        return {"ok": True}

    with pytest.raises(RuntimeError):
        repo.run_command("ws-1", "k1", "t", {}, flaky, **AUDIT)
    assert repo.run_command("ws-1", "k1", "t", {}, flaky, **AUDIT) == {"ok": True}


def test_audit_fields_are_recorded(repo):
    repo.run_command("ws-1", "k1", "t", {}, lambda c: {}, human_actor=None,
                     machine_caller="sync", channel="sync")
    row = raw_execute(repo, "SELECT human_actor, machine_caller, channel FROM command_log")[0]
    assert tuple(row) == (None, "sync", "sync")


def test_keys_are_scoped_per_workspace(repo):
    seed_workspace(repo, ws="ws-2", owner="PSN-2")
    calls: list[int] = []
    repo.run_command("ws-1", "k", "t", {}, lambda c: calls.append(1) or {}, **AUDIT)
    repo.run_command("ws-2", "k", "t", {}, lambda c: calls.append(1) or {}, **AUDIT)
    assert len(calls) == 2
