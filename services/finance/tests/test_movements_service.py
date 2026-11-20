"""MovementsService: authorization first, validation, loading and shaping (synthetic data)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app import domain
from app.movements.service import MovementsService
from app.service import AccessDenied, PolicyUnavailable, SessionInvalid
from tests.support import (
    FakeAuthorizer, SpyRepo, make_account, make_balance, make_repo, seed_connection,
    seed_workspace,
)

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
DELEG = "deleg"
DATA_READS = {"list_accounts", "latest_balance", "current_movements", "list_connections",
              "latest_fx_rates", "is_member", "connection"}


class Env:
    """EUR A, EUR B and USD C owned by the owner; EUR H (optional) owned by someone else."""

    def __init__(self, tmp_path, authorizer=None, hidden=False):
        self.base = make_repo(tmp_path)
        seed_workspace(self.base)
        seed_connection(self.base)
        for aid, cur, bank in (("acc-a", "EUR", "Bank A"), ("acc-b", "EUR", "Bank B"),
                               ("acc-c", "USD", "Bank C")):
            self.base.add_account(make_account(aid=aid, currency=cur, institution=bank))
        if hidden:
            self.base.add_account(make_account(aid="acc-h", institution="Bank H",
                                               owner_person_ids=("PSN-2",)))
        self.authz = authorizer or FakeAuthorizer()
        self.svc = MovementsService(self.base, self.authz, "ws-1", clock=lambda: NOW)
        self.n = 0

    def add(self, acc, amount, day, name="", text="", cur=None,
            status=domain.MovementStatus.BOOKED):
        self.n += 1
        cur = cur or ("USD" if acc == "acc-c" else "EUR")
        self.base.insert_movement(domain.Movement(
            f"m{self.n}", "ws-1", acc, f"tx{self.n}", f"fp{self.n}", status, day, day,
            amount, cur, name, None, text))

    def ago(self, days):
        return TODAY - timedelta(days=days)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.mark.parametrize("mode,error", [
    ("session_invalid", SessionInvalid), ("unavailable", PolicyUnavailable),
    ("malformed", PolicyUnavailable), ("raise", PolicyUnavailable),
    ("denied", AccessDenied),
])
@pytest.mark.parametrize("operation", ["movements", "summary"])
def test_refusals_read_no_movement_data(tmp_path, mode, error, operation):
    authz = (FakeAuthorizer(allow={"SELF": False}) if mode == "denied"
             else FakeAuthorizer(mode=mode))
    e = Env(tmp_path, authz)
    spy = SpyRepo(e.base)
    svc = MovementsService(spy, authz, "ws-1", clock=lambda: NOW)
    with pytest.raises(error):
        getattr(svc, operation)(DELEG)
    assert len(authz.calls) == 1
    assert not set(spy.calls) & DATA_READS  # every receivables read opens a connection


def test_no_delegation_calls_nothing(tmp_path):
    authz = FakeAuthorizer()
    e = Env(tmp_path, authz)
    with pytest.raises(SessionInvalid):
        e.svc.movements(None)
    assert authz.calls == []


def test_non_owner_member_is_denied(tmp_path):
    e = Env(tmp_path, FakeAuthorizer(actor="PSN-2"))
    e.base.add_member("ws-1", "PSN-2", "MEMBER")
    spy = SpyRepo(e.base)
    svc = MovementsService(spy, e.authz, "ws-1", clock=lambda: NOW)
    for operation in (svc.movements, svc.summary):
        with pytest.raises(AccessDenied):
            operation(DELEG)
    # the role read needs a connection; no account, balance or link is read for a refusal
    assert not set(spy.calls) & {"list_accounts", "list_connections", "latest_balance"}


def test_hidden_account_is_absent_and_does_not_pair(tmp_path):
    e = Env(tmp_path, hidden=True)
    e.add("acc-a", -5000, e.ago(2), "Destino")
    e.add("acc-h", 5000, e.ago(2), "Origen")
    result = e.svc.movements(DELEG)
    assert [m["amount_minor"] for m in result["movements"]] == [-5000]
    assert result["movements"][0]["kind"] == "OWN"  # the hidden side cannot pair it
    assert {a["id"] for a in result["accounts"]} == {"acc-a", "acc-b", "acc-c"}
    summary = e.svc.summary(DELEG)
    assert summary["hidden_accounts"] == 1 and "hidden_accounts" in summary["incomplete_reasons"]
    assert "acc-h" not in str(summary)


def test_visible_transfer_pairs_across_the_range_edge(env):
    env.add("acc-a", -7000, env.ago(90), "Salida")  # on the first day of the window
    env.add("acc-b", 7000, env.ago(91), "Entrada")  # one day before it
    result = env.svc.movements(DELEG)
    assert [m["kind"] for m in result["movements"]] == ["OWN_TRANSFER"]


@pytest.mark.parametrize("kwargs,code", [
    ({"text": "a"}, "bad_text"), ({"text": "x" * 61}, "bad_text"), ({"text": " a "}, "bad_text"),
    ({"amount": "abc"}, "bad_amount"), ({"amount": "12.505"}, "bad_amount"),
    ({"direction": "sideways"}, "bad_direction"),
    ({"since": "2026-13-01"}, "bad_date"), ({"until": "20261101"}, "bad_date"),
    ({"since": "2026-11-20", "until": "2026-11-01"}, "bad_range"),
    ({"since": "2025-01-01"}, "bad_range"),
    ({"until": "0001-02-01"}, "bad_range"),
    ({"since": "9999-12-30", "until": "9999-12-31"}, "bad_range"),
    ({"since": "0001-01-01", "until": "0001-01-02"}, "bad_range"),
    ({"limit": 0}, "bad_limit"), ({"limit": 51}, "bad_limit"), ({"limit": True}, "bad_limit"),
    ({"limit": "5"}, "bad_limit"),
    ({"account": "nowhere"}, "unknown_account"),
])
def test_validation_errors(tmp_path, kwargs, code):
    e = Env(tmp_path, hidden=True)
    result = e.svc.movements(DELEG, **kwargs)
    assert result["ok"] is False and result["error"] == code
    if code == "unknown_account":
        assert result["accounts"] == [
            {"id": "acc-a", "institution": "Bank A"}, {"id": "acc-b", "institution": "Bank B"},
            {"id": "acc-c", "institution": "Bank C"}]


@pytest.mark.parametrize("period,code", [
    ("abc", "bad_period"), ("9999-12", "bad_period"), ("9999", "bad_period"), ("2026-13", "bad_period"), ("2026-12", "bad_period"),
    ("2027", "bad_period"), ("2024-10", "bad_period"), ("2024", "bad_period"),
    ("2024-11", None), ("2026", None), ("2026-11", None), (None, None),
])
def test_summary_period_validation(env, period, code):
    result = env.svc.summary(DELEG, period)
    assert (result.get("error") if not result["ok"] else None) == code


def test_amount_accepts_comma_and_rejects_extra_decimals(env):
    env.add("acc-a", -1250, env.ago(1), "Tienda")
    env.add("acc-a", -1251, env.ago(1), "Otra")
    for spelled in ("12,50", "12.50", "-12.50", " 12.5 "):
        found = env.svc.movements(DELEG, amount=spelled)
        assert [m["amount_minor"] for m in found["movements"]] == [-1250], spelled
    assert env.svc.movements(DELEG, amount="12.505") == {"ok": False, "error": "bad_amount"}


def test_amount_matches_only_the_currency_it_parses_in(env):
    env.add("acc-c", -1250, env.ago(1), "Zelle")
    env.add("acc-a", -1250, env.ago(1), "Tienda")
    found = env.svc.movements(DELEG, amount="12,50")
    assert sorted(m["currency"] for m in found["movements"]) == ["EUR", "USD"]


def test_defaults_window_limit_and_newest_first(env):
    for i in range(30):
        env.add("acc-a", -(1000 + i), env.ago(i), f"Tienda {i}")
    env.add("acc-a", -9001, env.ago(90), "Borde")
    env.add("acc-a", -9002, env.ago(91), "Fuera")
    result = env.svc.movements(DELEG)
    assert result["since"] == env.ago(90).isoformat() and result["until"] == TODAY.isoformat()
    assert result["total_matches"] == 31 and result["truncated"] is True
    dates = [m["date"] for m in result["movements"]]
    assert len(dates) == 20 and dates == sorted(dates, reverse=True)
    assert dates[0] == TODAY.isoformat()
    bigger = env.svc.movements(DELEG, limit=50)
    assert len(bigger["movements"]) == 31 and bigger["truncated"] is False
    assert bigger["movements"][-1]["date"] == env.ago(90).isoformat()


def test_same_day_orders_by_insertion_newest_first(env):
    env.add("acc-a", -1001, env.ago(1), "Primera")
    env.add("acc-a", -1002, env.ago(1), "Segunda")
    got = env.svc.movements(DELEG)["movements"]
    assert [m["amount_minor"] for m in got] == [-1002, -1001]


def test_filters_account_direction_and_text_without_accents(env):
    env.add("acc-a", -1001, env.ago(1), "Cafetería Sol")
    env.add("acc-a", 2000, env.ago(1), "Nómina")
    env.add("acc-b", -3000, env.ago(1), "Cafeteria Sol")
    assert len(env.svc.movements(DELEG, text="cafeteria sol")["movements"]) == 2
    only_b = env.svc.movements(DELEG, text="cafeteria", account="BANK b")
    assert [a["id"] for a in only_b["accounts"]] == ["acc-b"]
    assert [m["amount_minor"] for m in only_b["movements"]] == [-3000]
    assert [m["amount_minor"] for m in env.svc.movements(DELEG, direction="in")["movements"]] == [2000]
    assert len(env.svc.movements(DELEG, account="acc-a", direction="out")["movements"]) == 1


def test_search_finds_text_hidden_from_display(env):
    env.add("acc-a", -4500, env.ago(2), "Tienda", "Pago factura 302-1234567 Local")
    found = env.svc.movements(DELEG, text="302-1234567")["movements"]
    assert len(found) == 1
    assert "302-1234567" not in found[0]["text"] and "302-1234567" not in str(found[0])


def test_result_never_carries_ids_or_hashes(env):
    env.add("acc-a", -4500, env.ago(2), "Tienda")
    blob = str(env.svc.movements(DELEG)) + str(env.svc.summary(DELEG))
    for forbidden in ("m1", "tx1", "fp1", "iban", "provider_tx_id", "hash"):
        assert forbidden not in blob, forbidden


def test_accounts_report_sync_history_and_staleness(env):
    old = NOW - timedelta(days=10)
    env.base.record_balance(make_balance("o1", aid="acc-a", as_of=old, observed_at=old))
    env.add("acc-a", -1000, env.ago(40), "Antigua")
    rows = {a["id"]: a for a in env.svc.movements(DELEG)["accounts"]}
    assert rows["acc-a"]["stale"] is True and rows["acc-a"]["history_from"] == env.ago(40).isoformat()
    assert rows["acc-b"]["stale"] is False and rows["acc-b"]["history_from"] is None
    assert set(rows["acc-a"]) == {"id", "institution", "currency", "synced_at",
                                  "history_from", "stale"}


def test_summary_figures_and_complete_past_month(env):
    for acc in ("acc-a", "acc-b", "acc-c"):
        env.add(acc, -100, date(2026, 9, 1), "Antiguo")
    env.add("acc-a", 100000, date(2026, 10, 5), "Empresa")
    env.add("acc-a", -2000, date(2026, 10, 6), "Tienda")
    result = env.svc.summary(DELEG, "2026-10")
    assert result["complete"] is True and result["incomplete_reasons"] == []
    assert (result["from"], result["to"], result["period"]) == ("2026-10-01", "2026-10-31", "2026-10")
    eur = next(c for c in result["currencies"] if c["currency"] == "EUR")
    assert eur["income"]["amount_minor"] == 100000
    assert eur["spending"]["bank"]["amount_minor"] == 2000
    assert eur["net"]["amount_minor"] == 98000
    assert [c["currency"] for c in result["currencies"]] == ["EUR", "USD"]


def test_summary_completeness_reasons(tmp_path):
    e = Env(tmp_path, hidden=True)
    old = NOW - timedelta(days=10)
    e.base.record_balance(make_balance("o1", aid="acc-a", as_of=old, observed_at=old))
    e.add("acc-a", -100, date(2026, 9, 1), "Antiguo")
    e.add("acc-b", -100, date(2026, 11, 10), "Tarde")  # history starts after the period start
    result = e.svc.summary(DELEG)
    assert result["period"] == "2026-11" and result["complete"] is False
    assert result["incomplete_reasons"] == [
        "in_progress", "history_starts_late", "account_stale", "hidden_accounts"]


def test_summary_flags_partner_payment_without_split(env):
    iban = "XX00 SYNTHETIC PARTNER 0001"
    from app.receivables.model import Counterparty, CounterpartyKind
    from app.store.receivables_repo import ReceivablesRepository

    rx = ReceivablesRepository(env.base)
    with rx.tx() as c:
        rx.insert_counterparty(c, Counterparty("p", "ws-1", CounterpartyKind.EXCHANGE_PARTNER,
                                               "Socio", "ACTIVE"), ["Socio"])
        rx.add_partner_identifier(c, "ws-1", rx.hash_key(iban), "p")
        env.base.insert_movement_in_tx(c, domain.Movement(
            "mp", "ws-1", "acc-a", "txp", "fpp", domain.MovementStatus.BOOKED,
            date(2026, 10, 7), date(2026, 10, 7), -9000, "EUR", "Socio", rx.hash_key(iban), "x"))
    result = env.svc.summary(DELEG, "2026-10")
    assert "exchanges_without_split" in result["incomplete_reasons"]


@pytest.mark.parametrize("operation", ["movements", "summary"])
def test_query_count_does_not_grow_with_movements(tmp_path, monkeypatch, operation):
    from app.store import db

    counts = []
    for size in (10, 200):
        (tmp_path / f"n{size}").mkdir()
        e = Env(tmp_path / f"n{size}")
        for i in range(size):
            e.add("acc-a" if i % 2 else "acc-c", -(1000 + i), e.ago(i % 25), f"Tienda {i}")
        statements: list[str] = []
        real = db.connect

        def traced(path, _real=real, _sink=statements):
            conn = _real(path)
            conn.set_trace_callback(_sink.append)
            return conn

        monkeypatch.setattr(db, "connect", traced)
        assert getattr(e.svc, operation)(DELEG)["ok"] is True
        counts.append(len(statements))
        monkeypatch.setattr(db, "connect", real)
    assert counts[0] == counts[1], counts


def _past(e, accounts=("acc-a", "acc-b", "acc-c")):
    for acc in accounts:
        e.add(acc, -100, date(2026, 9, 1), "Antiguo")


def test_m13_history_starts_late_when_an_empty_account_never_synced(env):
    _past(env, ("acc-a", "acc-b"))  # acc-c has no stored movement and the link never synced
    result = env.svc.summary(DELEG, "2026-10")
    assert result["complete"] is False
    assert result["incomplete_reasons"] == ["history_starts_late"]


def test_m13_dormant_account_that_syncs_is_not_flagged(env):
    env.base.set_connection_status("ws-1", "conn-1", domain.ConnectionStatus.OK,
                                   NOW - timedelta(days=1))
    result = env.svc.summary(DELEG, "2026-10")  # no movement stored anywhere
    assert result["complete"] is True and result["incomplete_reasons"] == []


def test_m13_reauth_required_connection_makes_the_month_stale_without_a_balance(env):
    _past(env)
    env.base.set_connection_status("ws-1", "conn-1", domain.ConnectionStatus.REAUTH_REQUIRED)
    result = env.svc.summary(DELEG, "2026-10")  # no balance observation: status NO_DATA
    assert result["incomplete_reasons"] == ["account_stale"]
    assert all(a["stale"] for a in result["accounts"])
    assert all(a["stale"] for a in env.svc.movements(DELEG)["accounts"])


def test_m13_expired_consent_is_stale(env):
    _past(env)
    env.base.set_connection_status("ws-1", "conn-1", domain.ConnectionStatus.OK, NOW)
    with env.base.connection() as c:
        c.execute("UPDATE connection SET consent_expires_at=? WHERE id='conn-1'",
                  ((NOW - timedelta(days=1)).isoformat(),))
    assert env.svc.summary(DELEG, "2026-10")["incomplete_reasons"] == ["account_stale"]


def test_m13_in_progress_and_hidden_accounts(tmp_path):
    e = Env(tmp_path, hidden=True)
    e.base.set_connection_status("ws-1", "conn-1", domain.ConnectionStatus.OK,
                                 NOW - timedelta(days=1))
    result = e.svc.summary(DELEG, "2026-11")
    assert result["incomplete_reasons"] == ["in_progress", "hidden_accounts"]
