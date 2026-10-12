from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime, timezone

import httpx
import pytest

from app import domain
from app.connectors.base import ConnectorError, ErrorKind
from app.connectors.simplefin import SimpleFinConnector, TokenAlreadyClaimed, claim
from tests.connector_contract import ConnectorContract

ACCESS_URL = "https://demo-user:demo-pass@bridge.example.test/simplefin"
EPOCH = int(datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp())


def _payload(**over):
    body = {
        "errlist": [],
        "connections": [{"conn_id": "c1", "name": "Bank of Example", "org_id": "o1",
                         "sfin_url": "https://bank.example.test"}],
        "accounts": [{
            "id": "A1", "name": "Checking", "conn_id": "c1", "currency": "USD",
            "balance": "1234.56", "available-balance": "1200.00", "balance-date": EPOCH,
            "transactions": [
                {"id": "t1", "posted": EPOCH, "amount": "-12.50",
                 "description": "COFFEE  SHOP\x07", "transacted_at": EPOCH},
                {"id": "t2", "posted": 0, "amount": "50.00", "pending": True,
                 "description": "Zelle payment from X", "transacted_at": EPOCH},
            ],
        }],
    }
    body.update(over)
    return body


def _connector(handler):
    return SimpleFinConnector(ACCESS_URL, transport=httpx.MockTransport(handler))


def _ok(request):
    return httpx.Response(200, json=_payload())


class TestSimpleFinContract(ConnectorContract):
    def make(self, scenario):
        handlers = {
            "ok": _ok,
            "auth": lambda r: httpx.Response(403, text="forbidden demo-pass"),
            "rate_limited": lambda r: httpx.Response(429),
            "unavailable": lambda r: httpx.Response(503),
            "malformed": lambda r: httpx.Response(200, text="<html>not json</html>"),
        }
        return _connector(handlers[scenario]), "A1"


# --- claim ---------------------------------------------------------------------------
def test_claim_posts_to_the_decoded_url_and_returns_the_access_url():
    seen = {}

    def handler(request):
        seen["method"], seen["url"] = request.method, str(request.url)
        return httpx.Response(200, text=ACCESS_URL)

    token = base64.b64encode(b"https://bridge.example.test/simplefin/claim/ABC123").decode()
    assert claim(token, transport=httpx.MockTransport(handler)) == ACCESS_URL
    assert seen == {"method": "POST", "url": "https://bridge.example.test/simplefin/claim/ABC123"}


def test_claim_403_is_a_distinct_error_and_does_not_echo_the_token(caplog):
    caplog.set_level(logging.DEBUG)
    token = base64.b64encode(b"https://bridge.example.test/claim/SUPERSECRET").decode()
    with pytest.raises(TokenAlreadyClaimed) as raised:
        claim(token, transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    assert "SUPERSECRET" not in str(raised.value) and token not in str(raised.value)
    assert "SUPERSECRET" not in caplog.text and token not in caplog.text


def test_claim_rejects_a_token_that_is_not_an_https_url():
    for bad in ("!!!notbase64!!!", base64.b64encode(b"http://insecure.example.test/c").decode(),
                base64.b64encode(b"not a url").decode()):
        with pytest.raises(ValueError):
            claim(bad, transport=httpx.MockTransport(_ok))


# --- credentials ---------------------------------------------------------------------
def test_basic_auth_comes_from_the_access_url_and_is_not_in_the_request_url(caplog):
    caplog.set_level(logging.DEBUG)
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_payload())

    _connector(handler).fetch_balances("A1")
    expected = "Basic " + base64.b64encode(b"demo-user:demo-pass").decode()
    assert seen["auth"] == expected
    assert "demo-pass" not in seen["url"] and "demo-pass" not in caplog.text


def test_access_url_must_be_https_with_credentials():
    for bad in ("http://u:p@h.example.test/x", "https://h.example.test/x"):
        with pytest.raises(ValueError):
            SimpleFinConnector(bad, transport=httpx.MockTransport(_ok))


def test_connector_repr_does_not_show_the_access_url():
    assert "demo-pass" not in repr(_connector(_ok))


# --- parsing -------------------------------------------------------------------------
def test_balance_and_available_balance_are_separate_kinds():
    balances = {b.kind: b for b in _connector(_ok).fetch_balances("A1")}
    assert balances[domain.BalanceKind.BOOKED].amount_minor == 123456
    assert balances[domain.BalanceKind.AVAILABLE].amount_minor == 120000
    assert balances[domain.BalanceKind.BOOKED].as_of == datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


def test_only_balances_are_requested_for_balance_polls():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_payload())

    _connector(handler).fetch_balances("A1")
    assert seen["version"] == "2" and seen["balances-only"] == "1" and seen["account"] == "A1"


def test_movements_request_pending_and_the_start_date():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_payload())

    _connector(handler).fetch_movements("A1", date(2026, 9, 1))
    assert seen["pending"] == "1" and "balances-only" not in seen
    assert seen["start-date"] == str(int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()))


def test_pending_and_posted_movements_are_distinguished_and_sanitised():
    moves = {m.provider_tx_id: m for m in _connector(_ok).fetch_movements("A1", None)}
    assert moves["t1"].status is domain.MovementStatus.BOOKED
    assert moves["t1"].amount_minor == -1250
    assert moves["t1"].remittance == "COFFEE SHOP"  # control char removed, spaces collapsed
    assert moves["t1"].booking_date == date(2026, 10, 9)
    assert moves["t2"].status is domain.MovementStatus.PENDING
    assert moves["t2"].booking_date is None or moves["t2"].booking_date == date(2026, 10, 9)
    assert moves["t2"].amount_minor == 5000


def test_text_fields_are_length_capped():
    body = _payload()
    body["accounts"][0]["transactions"][0]["description"] = "x" * 5000
    move = _connector(lambda r: httpx.Response(200, json=body)).fetch_movements("A1", None)[0]
    assert len(move.remittance) <= 500


def test_a_custom_currency_url_is_malformed_not_guessed():
    body = _payload()
    body["accounts"][0]["currency"] = "https://example.test/custom-currency"
    with pytest.raises(ConnectorError) as raised:
        _connector(lambda r: httpx.Response(200, json=body)).fetch_balances("A1")
    assert raised.value.kind is ErrorKind.MALFORMED


def test_missing_balance_date_is_malformed():
    body = _payload()
    del body["accounts"][0]["balance-date"]
    with pytest.raises(ConnectorError) as raised:
        _connector(lambda r: httpx.Response(200, json=body)).fetch_balances("A1")
    assert raised.value.kind is ErrorKind.MALFORMED


def test_amount_with_float_or_locale_format_is_malformed():
    for bad in (12.5, "1,234.50"):
        body = _payload()
        body["accounts"][0]["balance"] = bad
        with pytest.raises(ConnectorError) as raised:
            _connector(lambda r: httpx.Response(200, json=body)).fetch_balances("A1")
        assert raised.value.kind is ErrorKind.MALFORMED


# --- errlist / http errors -----------------------------------------------------------
def test_connection_auth_error_requires_reauthorization_for_that_account():
    body = _payload(errlist=[{"code": "con.auth", "msg": "login failed", "conn_id": "c1"}])
    with pytest.raises(ConnectorError) as raised:
        _connector(lambda r: httpx.Response(200, json=body)).fetch_balances("A1")
    assert raised.value.kind is ErrorKind.AUTH_REQUIRED


def test_an_error_on_another_connection_does_not_block_this_account():
    body = _payload(errlist=[{"code": "con.auth", "msg": "x", "conn_id": "OTHER"}])
    assert _connector(lambda r: httpx.Response(200, json=body)).fetch_balances("A1")


def test_unknown_account_is_malformed_and_402_needs_the_owner():
    with pytest.raises(ConnectorError) as raised:
        _connector(_ok).fetch_balances("NOPE")
    assert raised.value.kind is ErrorKind.MALFORMED
    with pytest.raises(ConnectorError) as raised:
        _connector(lambda r: httpx.Response(402)).fetch_balances("A1")
    assert raised.value.kind is ErrorKind.AUTH_REQUIRED


def test_timeouts_and_network_errors_are_unavailable():
    def boom(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ConnectorError) as raised:
        _connector(boom).fetch_balances("A1")
    assert raised.value.kind is ErrorKind.UNAVAILABLE


def test_list_accounts_skips_unsupported_currencies_and_names_the_institution():
    body = _payload()
    body["accounts"].append({"id": "A2", "name": "Odd", "conn_id": "c1",
                             "currency": "https://example.test/c", "balance": "1",
                             "balance-date": EPOCH})
    accounts = _connector(lambda r: httpx.Response(200, json=body)).list_accounts()
    assert [(a.ref, a.currency, a.institution) for a in accounts] == [
        ("A1", "USD", "Bank of Example")]
