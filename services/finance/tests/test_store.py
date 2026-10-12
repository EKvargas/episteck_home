from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import domain
from tests.support import (
    T0, column_names, count_rows, make_account, make_balance, make_movement, make_repo,
    pragma, raw_execute, seed_connection, seed_workspace, table_names,
)

# Reference data that is intentionally global (no tenant).
GLOBAL_TABLES = {"fx_rate"}


@pytest.fixture
def repo(tmp_path):
    r = make_repo(tmp_path)
    seed_workspace(r)
    seed_connection(r)
    r.add_account(make_account())
    return r


def test_pragmas_are_durable_and_safe(repo):
    assert pragma(repo, "journal_mode") == "wal"
    assert pragma(repo, "synchronous") == 2  # FULL
    assert pragma(repo, "foreign_keys") == 1
    assert pragma(repo, "busy_timeout") > 0


def test_every_tenant_table_carries_workspace_id(repo):
    names = table_names(repo)
    assert {"workspace", "workspace_member", "account", "connection", "balance_observation",
            "movement", "command_log", "fx_rate", "sync_run", "access_log"} <= set(names)
    for table in set(names) - GLOBAL_TABLES:
        cols = column_names(repo, table)
        assert "workspace_id" in cols or table == "workspace", table


@pytest.mark.parametrize("table", ["balance_observation", "movement"])
def test_facts_cannot_be_updated_or_deleted(repo, table):
    repo.record_balance(make_balance())
    repo.insert_movement(make_movement())
    with pytest.raises(sqlite3.IntegrityError):
        raw_execute(repo, f"UPDATE {table} SET currency='USD'")
    with pytest.raises(sqlite3.IntegrityError):
        raw_execute(repo, f"DELETE FROM {table}")


def test_provider_tx_id_is_unique_per_account(repo):
    assert repo.insert_movement(make_movement("m1", tx="tx-1", fp="a")) is True
    assert repo.insert_movement(make_movement("m2", tx="tx-1", fp="b")) is False
    assert len(repo.current_movements("ws-1", "acc-1")) == 1


def test_fingerprint_is_unique_only_when_there_is_no_provider_id(repo):
    assert repo.insert_movement(make_movement("m1", tx=None, fp="same")) is True
    assert repo.insert_movement(make_movement("m2", tx=None, fp="same")) is False
    # with a provider id, the same fingerprint may repeat (two identical payments)
    assert repo.insert_movement(make_movement("m3", tx="t3", fp="same")) is True
    assert repo.insert_movement(make_movement("m4", tx="t4", fp="same")) is True


def test_booked_supersedes_pending_without_editing_or_duplicating(repo):
    repo.insert_movement(make_movement("p1", tx="p-1", fp="x", status=domain.MovementStatus.PENDING))
    repo.insert_movement(make_movement("b1", tx="b-1", fp="x", supersedes="p1"))
    current = repo.current_movements("ws-1", "acc-1")
    assert [m.id for m in current] == ["b1"]
    assert current[0].status is domain.MovementStatus.BOOKED
    assert count_rows(repo, "movement") == 2  # the pending fact is kept, not edited


def test_latest_balance_is_the_newest_as_of(repo):
    repo.record_balance(make_balance("o1", amount=100, as_of=T0, source_ref="s1"))
    repo.record_balance(make_balance("o2", amount=300, as_of=T0 + timedelta(days=1), source_ref="s2"))
    repo.record_balance(make_balance("o3", amount=200, as_of=T0 - timedelta(days=1), source_ref="s3"))
    assert repo.latest_balance("ws-1", "acc-1", domain.BalanceKind.BOOKED).amount_minor == 300


def test_same_observation_twice_is_recorded_once(repo):
    assert repo.record_balance(make_balance("o1")) is True
    assert repo.record_balance(make_balance("o2")) is False
    assert count_rows(repo, "balance_observation") == 1


def test_balance_kinds_are_kept_apart(repo):
    repo.record_balance(make_balance("o1", amount=500, kind=domain.BalanceKind.BOOKED))
    repo.record_balance(make_balance("o2", amount=450, kind=domain.BalanceKind.AVAILABLE))
    assert repo.latest_balance("ws-1", "acc-1", domain.BalanceKind.AVAILABLE).amount_minor == 450
    assert repo.latest_balance("ws-1", "acc-1", domain.BalanceKind.VALUATION) is None


def test_other_workspace_sees_nothing(repo):
    repo.record_balance(make_balance())
    repo.insert_movement(make_movement())
    seed_workspace(repo, ws="ws-2", owner="PSN-2")
    assert repo.latest_balance("ws-2", "acc-1", domain.BalanceKind.BOOKED) is None
    assert repo.current_movements("ws-2", "acc-1") == []
    assert repo.list_accounts("ws-2") == []


def test_cannot_attach_a_balance_to_an_account_of_another_workspace(repo):
    seed_workspace(repo, ws="ws-2", owner="PSN-2")
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_balance(make_balance("o9", ws="ws-2", aid="acc-1"))


def test_accounts_round_trip_with_all_owners(repo):
    repo.add_account(make_account(aid="acc-2", owner_person_ids=("PSN-1", "PSN-2")))
    accounts = {a.id: a for a in repo.list_accounts("ws-1")}
    assert accounts["acc-2"].owner_person_ids == ("PSN-1", "PSN-2")
    assert accounts["acc-1"].currency == "EUR"


def test_iban_hash_is_keyed_and_normalised(repo, tmp_path):
    a = repo.hash_iban("DE89 3704 0044 0532 0130 00")
    assert a == repo.hash_iban("de89370400440532013000")
    other = make_repo(tmp_path, "other.sqlite")
    other._pepper = b"different"  # noqa: SLF001
    assert other.hash_iban("DE89370400440532013000") != a
    assert "DE89" not in a and len(a) == 64


def test_pepper_is_not_a_default():
    from app.store.repo import FinanceRepository
    with pytest.raises(ValueError):
        FinanceRepository(":memory:", pepper=b"")
