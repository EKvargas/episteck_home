"""A4 (duplicates) and A13 (replay and restart) for the sync engine."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import domain
from app.connectors.base import ConnectorError, ErrorKind
from app.sync import SyncEngine
from tests.support import (
    T0, FakeConnector, count_rows, make_account, make_repo, raw_balance, raw_move, raw_execute,
    seed_connection, seed_workspace,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
PENDING, BOOKED = domain.MovementStatus.PENDING, domain.MovementStatus.BOOKED


@pytest.fixture
def repo(tmp_path):
    r = make_repo(tmp_path)
    seed_workspace(r)
    seed_connection(r)
    r.add_account(make_account(aid="acc-1", connection_id="conn-1", provider_account_ref="A1"))
    return r


def _engine(repo, connectors, ecb=None):
    return SyncEngine(repo, connectors, ecb=ecb, clock=lambda: NOW)


def _run(repo, connector, ecb=None):
    return _engine(repo, {"conn-1": connector}, ecb).run("ws-1")


def _conn_status(repo):
    return raw_execute(repo, "SELECT status FROM connection WHERE id='conn-1'")[0][0]


# --- duplicates (A4) ---------------------------------------------------------------
def test_the_same_movement_in_two_syncs_is_one_row(repo):
    fake = FakeConnector(balances={"A1": [raw_balance()]}, movements={"A1": [raw_move("t1")]})
    _run(repo, fake)
    _run(repo, fake)
    assert count_rows(repo, "movement") == 1
    assert count_rows(repo, "balance_observation") == 1


def test_pending_then_booked_with_the_same_id_is_one_current_movement(repo):
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]},
                             movements={"A1": [raw_move("t1", status=PENDING, day=None)]}))
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]},
                             movements={"A1": [raw_move("t1", status=BOOKED)]}))
    current = repo.current_movements("ws-1", "acc-1")
    assert [m.status for m in current] == [BOOKED]
    assert count_rows(repo, "movement") == 2  # the pending fact is kept


def test_pending_then_booked_with_a_new_id_links_when_the_match_is_unique(repo):
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]},
                             movements={"A1": [raw_move("p-1", amount=-999, status=PENDING, day=None)]}))
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]},
                             movements={"A1": [raw_move("b-9", amount=-999, status=BOOKED)]}))
    assert [m.provider_tx_id for m in repo.current_movements("ws-1", "acc-1")] == ["b-9"]


def test_an_ambiguous_pending_match_is_not_linked(repo):
    pending = [raw_move("p-1", amount=-500, status=PENDING, day=None),
               raw_move("p-2", amount=-500, status=PENDING, day=None)]
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]}, movements={"A1": pending}))
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]},
                             movements={"A1": [raw_move("b-1", amount=-500, status=BOOKED)]}))
    assert len(repo.current_movements("ws-1", "acc-1")) == 3  # nothing guessed


def test_without_provider_ids_the_fingerprint_dedupes_and_keeps_identical_payments(repo):
    twins = [raw_move(None, amount=-300, remittance="bus"), raw_move(None, amount=-300, remittance="bus")]
    fake = FakeConnector(balances={"A1": [raw_balance()]}, movements={"A1": twins})
    _run(repo, fake)
    _run(repo, fake)
    assert count_rows(repo, "movement") == 2  # two real payments, not four


# --- replay and restart (A13) ---------------------------------------------------------
def test_an_interrupted_movement_ingest_leaves_nothing_partial_and_the_rerun_completes(repo, monkeypatch):
    moves = [raw_move("t1"), raw_move("t2", amount=-200), raw_move("t3", amount=-300)]
    fake = FakeConnector(balances={"A1": [raw_balance()]}, movements={"A1": moves})
    original = repo.insert_movement_in_tx
    calls = {"n": 0}

    def flaky(conn, movement):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("process killed")
        return original(conn, movement)

    monkeypatch.setattr(repo, "insert_movement_in_tx", flaky)
    report = _run(repo, fake)
    assert report.any_failed
    assert count_rows(repo, "movement") == 0
    assert raw_execute(repo, "SELECT status FROM sync_run")[0][0] == "FAILED"
    monkeypatch.undo()
    assert not _run(repo, fake).any_failed
    assert count_rows(repo, "movement") == 3
    _run(repo, fake)
    assert count_rows(repo, "movement") == 3


def test_a_balance_is_recorded_once_per_provider_observation(repo):
    fake = FakeConnector(balances={"A1": [raw_balance(777)]})
    _run(repo, fake)
    _run(repo, fake)
    assert count_rows(repo, "balance_observation") == 1
    _run(repo, FakeConnector(balances={"A1": [raw_balance(888, as_of=T0 + timedelta(hours=6))]}))
    assert count_rows(repo, "balance_observation") == 2


# --- failures never write zero --------------------------------------------------------
@pytest.mark.parametrize("kind,status", [
    (ErrorKind.AUTH_REQUIRED, "REAUTH_REQUIRED"),
    (ErrorKind.CONSENT_EXPIRED, "REAUTH_REQUIRED"),
    (ErrorKind.UNAVAILABLE, "FAILING"),
    (ErrorKind.MALFORMED, "FAILING"),
])
def test_a_failed_fetch_writes_no_balance_and_marks_the_connection(repo, kind, status):
    fake = FakeConnector(balances={"A1": ConnectorError(kind)})
    report = _run(repo, fake)
    assert report.any_failed
    assert count_rows(repo, "balance_observation") == 0
    assert _conn_status(repo) == status


def test_rate_limit_stops_that_account_without_changing_the_connection(repo):
    fake = FakeConnector(balances={"A1": ConnectorError(ErrorKind.RATE_LIMITED)})
    report = _run(repo, fake)
    assert count_rows(repo, "balance_observation") == 0
    assert _conn_status(repo) == "OK"
    assert not report.any_failed  # a budget stop is expected, not a failure
    assert fake.calls == [("balances", "A1")]  # no retry, no movements call


def test_success_after_failing_restores_ok_and_stamps_last_success(repo):
    _run(repo, FakeConnector(balances={"A1": ConnectorError(ErrorKind.UNAVAILABLE)}))
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]}))
    assert _conn_status(repo) == "OK"
    assert raw_execute(repo, "SELECT last_success_at FROM connection")[0][0] == NOW.isoformat()


def test_one_failing_connection_does_not_block_another(repo):
    seed_connection(repo, cid="conn-2")
    repo.add_account(make_account(aid="acc-2", connection_id="conn-2", provider_account_ref="B1"))
    bad = FakeConnector(balances={"A1": ConnectorError(ErrorKind.AUTH_REQUIRED)})
    good = FakeConnector(balances={"B1": [raw_balance(4242)]})
    report = SyncEngine(repo, {"conn-1": bad, "conn-2": good}, clock=lambda: NOW).run("ws-1")
    assert report.any_failed
    assert repo.latest_balance("ws-1", "acc-2", domain.BalanceKind.BOOKED).amount_minor == 4242


def test_one_failing_account_does_not_block_another_on_the_same_connection(repo):
    repo.add_account(make_account(aid="acc-3", connection_id="conn-1", provider_account_ref="A3"))
    fake = FakeConnector(balances={"A1": ConnectorError(ErrorKind.UNAVAILABLE),
                                   "A3": [raw_balance(55)]})
    _run(repo, fake)
    assert repo.latest_balance("ws-1", "acc-3", domain.BalanceKind.BOOKED).amount_minor == 55
    assert repo.latest_balance("ws-1", "acc-1", domain.BalanceKind.BOOKED) is None


# --- pausing and audit ------------------------------------------------------------------
def test_paused_connection_and_paused_workspace_are_skipped(repo):
    fake = FakeConnector(balances={"A1": [raw_balance()]})
    raw_execute(repo, "UPDATE connection SET status='PAUSED'")
    _run(repo, fake)
    assert fake.calls == []
    raw_execute(repo, "UPDATE connection SET status='OK'")
    raw_execute(repo, "UPDATE workspace SET status='PAUSED'")
    _run(repo, fake)
    assert fake.calls == []


def test_a_connection_with_no_connector_is_reported_not_crashed(repo):
    report = SyncEngine(repo, {}, clock=lambda: NOW).run("ws-1")
    assert report.any_failed


def test_sync_run_is_audited_as_the_sync_channel(repo):
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]}))
    row = raw_execute(repo, "SELECT channel, machine_caller, status FROM sync_run")[0]
    assert tuple(row) == ("sync", "svc-finance-sync", "OK")


# --- reference rates --------------------------------------------------------------------
class _Ecb:
    def __init__(self, ok):
        self.ok, self.called = ok, 0

    def fetch(self):
        self.called += 1
        if not self.ok:
            raise ConnectorError(ErrorKind.UNAVAILABLE)
        return date(2026, 10, 9), {"USD": Decimal("1.08")}


def test_rates_are_refreshed_and_a_failing_feed_never_fails_the_run(repo):
    ok = _Ecb(True)
    _run(repo, FakeConnector(balances={"A1": [raw_balance()]}), ecb=ok)
    assert ok.called == 1 and repo.latest_fx_rates().per_eur["USD"] == Decimal("1.08")
    broken = _Ecb(False)
    report = _run(repo, FakeConnector(balances={"A1": [raw_balance()]}), ecb=broken)
    assert not report.any_failed
