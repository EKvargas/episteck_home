from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import domain
from app.connectors.base import ConnectorError, ErrorKind
from app.connectors.eb_jwt import JwtSigner
from app.connectors.enable_banking import (
    EbClient, EnableBankingConnector, RepoBudget, SessionInfo,
)
from tests.connector_contract import ConnectorContract
from tests.support import make_account, make_repo, seed_connection, seed_workspace

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
REF, UID = "hash-A1", "11111111-1111-4111-8111-111111111111"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())


class AllowAll:
    def allow(self, ref):
        return True

    def record(self, ref):
        pass

    def block(self, ref):
        pass


BALANCES = {"balances": [
    {"name": "booked", "balance_amount": {"currency": "EUR", "amount": "1234.50"},
     "balance_type": "CLBD", "last_change_date_time": "2026-10-09T10:00:00Z"},
    {"name": "avail", "balance_amount": {"currency": "EUR", "amount": "1200.00"},
     "balance_type": "CLAV", "reference_date": "2026-10-09"},
    {"name": "other", "balance_amount": {"currency": "EUR", "amount": "9.00"},
     "balance_type": "XPCD"},
]}


def _tx(**over):
    base = {"transaction_id": "tx1", "entry_reference": "e1", "booking_date": "2026-10-08",
            "value_date": "2026-10-08",
            "transaction_amount": {"currency": "EUR", "amount": "12.50"},
            "credit_debit_indicator": "DBIT", "status": "BOOK",
            "creditor": {"name": "Corner Shop"},
            "creditor_account": {"iban": "DE89370400440532013000"},
            "remittance_information": ["Card", "payment"]}
    base.update(over)
    return base


TRANSACTIONS = {"transactions": [
    _tx(),
    _tx(transaction_id="tx2", status="PDNG", credit_debit_indicator="CRDT",
        transaction_amount={"currency": "EUR", "amount": "50.00"},
        debtor={"name": "Laura V"}, debtor_account={"iban": "ES9121000418450200051332"},
        creditor=None, creditor_account=None, remittance_information=["Zelle"]),
    _tx(transaction_id="tx3", status="CNCL"),
], "continuation_key": None}


def _router(seen=None, balances=BALANCES, transactions=TRANSACTIONS):
    def handler(request):
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == f"/accounts/{UID}/balances":
            return httpx.Response(200, json=balances)
        if path == f"/accounts/{UID}/transactions":
            return httpx.Response(200, json=transactions)
        return httpx.Response(404, json={"error": "NOT_FOUND"})
    return handler


def _connector(handler, budget=None):
    client = EbClient(JwtSigner("app-1", _PEM), transport=httpx.MockTransport(handler))
    return EnableBankingConnector(client, SessionInfo("s-1", {REF: UID}), budget or AllowAll(),
                                  clock=lambda: NOW)


class TestEnableBankingContract(ConnectorContract):
    def make(self, scenario):
        handlers = {
            "ok": _router(),
            "auth": lambda r: httpx.Response(401, json={"error": "ACCESS_DENIED", "message": "no"}),
            "rate_limited": lambda r: httpx.Response(
                429, json={"error": "ASPSP_RATE_LIMIT_EXCEEDED", "message": "slow"}),
            "unavailable": lambda r: httpx.Response(503),
            "malformed": lambda r: httpx.Response(200, text="<html>nope</html>"),
        }
        return _connector(handlers[scenario]), REF


# --- request shape -----------------------------------------------------------------
def test_requests_carry_the_jwt_and_never_a_psu_header():
    seen = []
    _connector(_router(seen)).fetch_balances(REF)
    request = seen[0]
    assert request.headers["authorization"].startswith("Bearer ey")
    assert not [h for h in request.headers if h.lower().startswith("psu-")]


def test_session_scoped_uid_is_resolved_from_the_stable_reference():
    seen = []
    _connector(_router(seen)).fetch_balances(REF)
    assert seen[0].url.path == f"/accounts/{UID}/balances"
    with pytest.raises(ConnectorError) as raised:
        _connector(_router()).fetch_balances("hash-not-in-this-session")
    assert raised.value.kind is ErrorKind.AUTH_REQUIRED


# --- balances ----------------------------------------------------------------------
def test_balance_types_map_to_booked_and_available_and_unknown_types_are_skipped():
    balances = {b.kind: b for b in _connector(_router()).fetch_balances(REF)}
    assert set(balances) == {domain.BalanceKind.BOOKED, domain.BalanceKind.AVAILABLE}
    assert balances[domain.BalanceKind.BOOKED].amount_minor == 123450
    assert balances[domain.BalanceKind.BOOKED].as_of == datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
    assert balances[domain.BalanceKind.AVAILABLE].amount_minor == 120000
    assert balances[domain.BalanceKind.AVAILABLE].as_of == datetime(2026, 10, 9, tzinfo=timezone.utc)


def test_preferred_balance_type_wins_when_several_map_to_the_same_kind():
    body = {"balances": [
        {"balance_amount": {"currency": "EUR", "amount": "1.00"}, "balance_type": "OPBD",
         "last_change_date_time": "2026-10-09T10:00:00Z"},
        {"balance_amount": {"currency": "EUR", "amount": "2.00"}, "balance_type": "CLBD",
         "last_change_date_time": "2026-10-09T10:00:00Z"}]}
    booked = [b for b in _connector(_router(balances=body)).fetch_balances(REF)]
    assert [b.amount_minor for b in booked] == [200]


def test_a_balance_without_any_date_falls_back_to_the_fetch_time():
    body = {"balances": [{"balance_amount": {"currency": "EUR", "amount": "5.00"},
                          "balance_type": "CLBD"}]}
    assert _connector(_router(balances=body)).fetch_balances(REF)[0].as_of == NOW


def test_no_usable_balance_is_malformed_and_a_numeric_amount_is_malformed():
    for body in ({"balances": []}, {"balances": [
            {"balance_amount": {"currency": "EUR", "amount": 5.0}, "balance_type": "CLBD"}]}):
        with pytest.raises(ConnectorError) as raised:
            _connector(_router(balances=body)).fetch_balances(REF)
        assert raised.value.kind is ErrorKind.MALFORMED


# --- transactions ------------------------------------------------------------------
def test_debits_are_negative_credits_positive_and_counterparty_follows_direction():
    moves = {m.provider_tx_id: m for m in _connector(_router()).fetch_movements(REF, None)}
    assert set(moves) == {"tx1", "tx2"}  # cancelled is not a fact
    out, inc = moves["tx1"], moves["tx2"]
    assert out.amount_minor == -1250 and out.status is domain.MovementStatus.BOOKED
    assert out.counterparty_name == "Corner Shop" and out.counterparty_iban == "DE89370400440532013000"
    assert out.remittance == "Card payment" and out.booking_date == date(2026, 10, 8)
    assert inc.amount_minor == 5000 and inc.status is domain.MovementStatus.PENDING
    assert inc.counterparty_name == "Laura V"


def test_missing_counterparty_and_remittance_do_not_crash():
    sparse = _tx(creditor=None, creditor_account=None, remittance_information=None)
    sparse.pop("transaction_id")
    body = {"transactions": [sparse], "continuation_key": None}
    move = _connector(_router(transactions=body)).fetch_movements(REF, None)[0]
    assert move.provider_tx_id == "e1"  # falls back to entry_reference
    assert move.counterparty_name == "" and move.remittance == ""


def test_date_from_and_the_continuation_key_are_sent_and_pages_are_followed():
    seen, calls = [], {"n": 0}

    def handler(request):
        seen.append(request)
        calls["n"] += 1
        key = None if calls["n"] == 2 else "page-2"
        return httpx.Response(200, json={"transactions": [_tx(transaction_id=f"p{calls['n']}")],
                                         "continuation_key": key})

    moves = _connector(handler).fetch_movements(REF, date(2026, 9, 1))
    assert [m.provider_tx_id for m in moves] == ["p1", "p2"]
    assert seen[0].url.params["date_from"] == "2026-09-01"
    assert "continuation_key" not in seen[0].url.params
    assert seen[1].url.params["continuation_key"] == "page-2"


def test_paging_stops_at_the_page_cap():
    def handler(request):
        return httpx.Response(200, json={"transactions": [], "continuation_key": "again"})

    seen = []
    connector = _connector(lambda r: (seen.append(r), handler(r))[1])
    connector.fetch_movements(REF, None)
    assert len(seen) == 5


def test_account_level_error_codes_map_to_reauthorization():
    for code, kind in (("EXPIRED_SESSION", ErrorKind.CONSENT_EXPIRED),
                       ("CLOSED_SESSION", ErrorKind.AUTH_REQUIRED),
                       ("REVOKED_SESSION", ErrorKind.AUTH_REQUIRED)):
        handler = lambda r, c=code: httpx.Response(401, json={"error": c, "message": "x"})
        with pytest.raises(ConnectorError) as raised:
            _connector(handler).fetch_balances(REF)
        assert raised.value.kind is kind


def test_a_bank_that_demands_psu_headers_is_unavailable_not_faked():
    handler = lambda r: httpx.Response(429, json={"error": "PSU_HEADER_NOT_PROVIDED", "message": "x"})
    with pytest.raises(ConnectorError) as raised:
        _connector(handler).fetch_balances(REF)
    assert raised.value.kind is ErrorKind.UNAVAILABLE


# --- the PSD2 unattended-access budget -----------------------------------------------
@pytest.fixture
def budget(tmp_path):
    repo = make_repo(tmp_path)
    seed_workspace(repo)
    clock = {"now": NOW}
    return RepoBudget(repo, "ws-1", cap=4, clock=lambda: clock["now"]), clock


def test_the_fifth_data_request_in_24_hours_is_refused_before_sending(budget):
    budget, _ = budget
    seen = []
    connector = _connector(_router(seen), budget)
    for _ in range(4):
        connector.fetch_balances(REF)
    assert len(seen) == 4
    with pytest.raises(ConnectorError) as raised:
        connector.fetch_balances(REF)
    assert raised.value.kind is ErrorKind.RATE_LIMITED
    assert len(seen) == 4  # nothing was sent


def test_the_window_rolls_after_24_hours(budget):
    budget, clock = budget
    connector = _connector(_router(), budget)
    for _ in range(4):
        connector.fetch_balances(REF)
    clock["now"] = NOW + timedelta(hours=24, minutes=1)
    assert connector.fetch_balances(REF)


def test_budgets_are_per_account(budget):
    budget, _ = budget
    for _ in range(4):
        assert budget.allow("a")
        budget.record("a")
    assert not budget.allow("a") and budget.allow("b")


def test_every_attempt_counts_even_when_it_fails(budget):
    budget, _ = budget
    connector = _connector(lambda r: httpx.Response(503), budget)
    for _ in range(4):
        with pytest.raises(ConnectorError):
            connector.fetch_balances(REF)
    with pytest.raises(ConnectorError) as raised:
        connector.fetch_balances(REF)
    assert raised.value.kind is ErrorKind.RATE_LIMITED


def test_a_bank_429_closes_the_window_even_below_the_cap(budget):
    budget, clock = budget
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(429, json={"error": "ASPSP_RATE_LIMIT_EXCEEDED", "message": "x"})

    connector = _connector(handler, budget)
    with pytest.raises(ConnectorError):
        connector.fetch_balances(REF)
    with pytest.raises(ConnectorError) as raised:
        connector.fetch_balances(REF)
    assert raised.value.kind is ErrorKind.RATE_LIMITED and len(seen) == 1
    clock["now"] = NOW + timedelta(hours=24, minutes=1)
    assert budget.allow(REF) is True


def test_transaction_pages_each_count_against_the_budget(budget):
    budget, _ = budget
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"transactions": [], "continuation_key": "more"})

    with pytest.raises(ConnectorError) as raised:
        _connector(handler, budget).fetch_movements(REF, None)
    assert raised.value.kind is ErrorKind.RATE_LIMITED
    assert len(seen) == 4
