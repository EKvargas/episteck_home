from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import domain
from app.connectors.eb_auth import (
    AuthorizationError, OfferedAccount, complete_authorization, receive_callback,
    start_authorization,
)
from app.connectors.eb_jwt import JwtSigner
from app.connectors.enable_banking import EbClient
from tests.support import count_rows, make_account, make_repo, raw_execute, seed_workspace

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
MAX_VALIDITY = 15552000  # 180 days, as in the documented example
UID_A, UID_NEW = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption())


class Bank:
    """A scripted Enable Banking: records requests, answers /aspsps, /auth, /sessions."""

    def __init__(self, accounts=None, session_status=200, valid_until=None):
        self.requests = []
        self.accounts = accounts if accounts is not None else [
            {"identification_hash": "hash-A1", "uid": UID_A, "currency": "EUR",
             "cash_account_type": "CACC", "product": "Giro"},
            {"identification_hash": "hash-NEW", "uid": UID_NEW, "currency": "EUR",
             "cash_account_type": "SVGS", "product": "Tagesgeld"}]
        self.session_status = session_status
        self.valid_until = valid_until or (NOW + timedelta(days=90)).isoformat()

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if path == "/aspsps":
            return httpx.Response(200, json={"aspsps": [
                {"name": "Sparkasse Example", "country": "DE",
                 "maximum_consent_validity": MAX_VALIDITY}]})
        if path == "/auth":
            return httpx.Response(200, json={"url": "https://bank.example.test/authorize?x=1",
                                             "authorization_id": "auth-1"})
        if path == "/sessions":
            if self.session_status != 200:
                return httpx.Response(self.session_status, json={"error": "ACCESS_DENIED"})
            return httpx.Response(200, json={
                "session_id": "session-1", "accounts": self.accounts,
                "aspsp": {"name": "Sparkasse Example", "country": "DE"},
                "access": {"valid_until": self.valid_until}})
        return httpx.Response(404)

    def body(self, path):
        return json.loads(next(r for r in reversed(self.requests) if r.url.path == path).content)


@pytest.fixture
def setup(tmp_path):
    repo = make_repo(tmp_path)
    seed_workspace(repo)
    repo.add_connection(domain.Connection("conn-1", "ws-1", domain.Provider.ENABLE_BANKING,
                                          "PSN-1", domain.ConnectionStatus.REAUTH_REQUIRED))
    repo.add_account(make_account(aid="acc-1", connection_id="conn-1",
                                  provider_account_ref="hash-A1",
                                  movement_authority=domain.Provider.ENABLE_BANKING))
    bank = Bank()
    client = EbClient(JwtSigner("app-1", _PEM), transport=httpx.MockTransport(bank))
    return repo, bank, client


REDIRECT = "https://bff.example.test/finance/connect/callback"


def _start(setup, days=365, now=NOW, name="Sparkasse Example"):
    repo, bank, client = setup
    started = start_authorization(client, repo, "ws-1", "conn-1", aspsp_name=name, country="DE",
                                  redirect_url=REDIRECT, requested_days=days, now=now)
    return started, bank.body("/auth")["state"]


def _complete(setup, code="code-xyz", now=NOW + timedelta(minutes=2)):
    """Start, the browser returns with a code, the operator's command exchanges it."""
    repo, _, client = setup
    started, state = _start(setup)
    assert receive_callback(repo, state, code=code, error=None, now=now)
    return complete_authorization(client, repo, repo.take_callback(started.state_hash), now=now)


def _status(repo):
    return repo.list_connections("ws-1")[0].status


def test_consent_is_capped_at_the_banks_maximum_validity(setup):
    _start(setup, days=365)
    valid_until = datetime.fromisoformat(setup[1].body("/auth")["access"]["valid_until"])
    assert valid_until == NOW + timedelta(seconds=MAX_VALIDITY)


def test_a_shorter_request_is_kept_as_asked(setup):
    _start(setup, days=30)
    valid_until = datetime.fromisoformat(setup[1].body("/auth")["access"]["valid_until"])
    assert valid_until == NOW + timedelta(days=30)


def test_authorization_request_shape_and_returned_url(setup):
    started, state = _start(setup)
    body = setup[1].body("/auth")
    assert started.url == "https://bank.example.test/authorize?x=1"
    assert state not in started.state_hash
    assert body["aspsp"] == {"name": "Sparkasse Example", "country": "DE"}
    assert body["redirect_url"] == REDIRECT
    assert body["psu_type"] == "personal"
    assert len(state) >= 32
    assert _start(setup)[1] != state


def test_only_a_hash_of_the_state_is_stored(setup):
    _, state = _start(setup)
    dump = repr(raw_execute(setup[0], "SELECT * FROM oauth_state"))
    assert state not in dump


def test_unknown_bank_is_refused_and_leaves_no_state(setup):
    with pytest.raises(AuthorizationError):
        _start(setup, name="No Such Bank")
    assert raw_execute(setup[0], "SELECT COUNT(*) FROM oauth_state")[0][0] == 0


def test_completing_maps_every_returned_account_but_links_none_silently(setup):
    repo, bank, _ = setup
    result = _complete(setup)
    assert bank.body("/sessions") == {"code": "code-xyz"}
    assert (result.linked, result.unexpected, result.missing) == (1, 1, 0)
    connection = repo.list_connections("ws-1")[0]
    assert connection.status is domain.ConnectionStatus.OK
    assert connection.consent_expires_at == NOW + timedelta(days=90)  # from the response
    session = repo.load_eb_session("conn-1")
    assert session.session_id == "session-1"
    # Every uid is kept, so an account linked after the first consent needs no second SCA;
    # linking itself stays the owner's step: no account row appears for hash-NEW.
    assert dict(session.accounts) == {"hash-A1": UID_A, "hash-NEW": UID_NEW}
    assert [a.provider_account_ref for a in repo.list_accounts("ws-1")] == ["hash-A1"]


def test_the_result_lists_the_offered_accounts_for_the_operator(setup):
    assert _complete(setup).accounts == (
        OfferedAccount("hash-A1", "Giro", "EUR", linked=True),
        OfferedAccount("hash-NEW", "Tagesgeld", "EUR", linked=False))


def test_an_expected_account_missing_from_the_session_is_reported(setup):
    setup[1].accounts = [{"identification_hash": "hash-OTHER", "uid": UID_NEW,
                          "currency": "EUR", "cash_account_type": "CACC"}]
    result = _complete(setup, code="c")
    assert (result.linked, result.unexpected, result.missing) == (0, 1, 1)
    assert result.accounts == (OfferedAccount("hash-OTHER", "CACC", "EUR", linked=False),)


@pytest.mark.parametrize("scenario", ["replay", "expired", "unknown"])
def test_a_bad_state_is_refused_identically_and_stores_nothing(setup, scenario):
    repo, bank, _ = setup
    _, state = _start(setup)
    now = NOW + timedelta(minutes=1)
    if scenario == "replay":
        assert receive_callback(repo, state, code="c", error=None, now=now)
    elif scenario == "expired":
        now = NOW + timedelta(minutes=16)
    else:
        state = "x" * 43
    stored, requests = count_rows(repo, "oauth_callback"), len(bank.requests)
    assert receive_callback(repo, state, code="c2", error=None, now=now) is False
    assert count_rows(repo, "oauth_callback") == stored
    assert len(bank.requests) == requests


@pytest.mark.parametrize("code,error", [
    (None, None), ("c", "access_denied"), ("", None), ("c\nx", None), ("c" * 2049, None)])
def test_a_malformed_callback_is_refused_without_consuming_the_state(setup, code, error):
    repo, _, _ = setup
    _, state = _start(setup)
    assert receive_callback(repo, state, code=code, error=error, now=NOW) is False
    assert receive_callback(repo, "s" * 129, code="c", error=None, now=NOW) is False
    assert receive_callback(repo, state, code="ok", error=None, now=NOW) is True


def test_a_refusal_at_the_bank_consumes_the_state_and_never_calls_sessions(setup):
    repo, bank, client = setup
    started, state = _start(setup)
    assert receive_callback(repo, state, code=None, error="access_denied", now=NOW)
    received = repo.take_callback(started.state_hash)
    assert received.code is None
    requests = len(bank.requests)
    with pytest.raises(AuthorizationError):
        complete_authorization(client, repo, received, now=NOW)
    assert len(bank.requests) == requests
    assert receive_callback(repo, state, code="c", error=None, now=NOW) is False
    assert _status(repo) is domain.ConnectionStatus.REAUTH_REQUIRED


def test_a_received_code_is_handed_over_once_and_then_deleted(setup):
    repo, _, _ = setup
    started, state = _start(setup)
    receive_callback(repo, state, code="SECRET-CODE-123", error=None, now=NOW)
    assert repo.take_callback("0" * 64) is None
    received = repo.take_callback(started.state_hash)
    assert (received.connection_id, received.code) == ("conn-1", "SECRET-CODE-123")
    assert repo.take_callback(started.state_hash) is None
    assert count_rows(repo, "oauth_callback") == 0


def test_a_code_nobody_collected_is_purged_when_the_next_authorization_starts(setup):
    repo, _, _ = setup
    _, state = _start(setup)
    receive_callback(repo, state, code="ABANDONED", error=None, now=NOW)
    _start(setup, now=NOW + timedelta(minutes=16))
    assert count_rows(repo, "oauth_callback") == 0


def test_a_failed_code_exchange_keeps_the_connection_closed_and_the_code_gone(setup):
    repo, bank, client = setup
    bank.session_status = 403
    started, state = _start(setup)
    receive_callback(repo, state, code="c", error=None, now=NOW)
    with pytest.raises(AuthorizationError):
        complete_authorization(client, repo, repo.take_callback(started.state_hash), now=NOW)
    assert repo.take_callback(started.state_hash) is None
    assert _status(repo) is domain.ConnectionStatus.REAUTH_REQUIRED


def test_reauthorization_replaces_the_previous_session_map(setup):
    repo, bank, _ = setup
    _complete(setup, code="c1")
    bank.accounts = [{"identification_hash": "hash-A1", "uid": UID_NEW, "currency": "EUR",
                      "cash_account_type": "CACC"}]
    _complete(setup, code="c2")
    assert dict(repo.load_eb_session("conn-1").accounts) == {"hash-A1": UID_NEW}


def test_logs_never_contain_the_state_or_the_code(setup, caplog):
    caplog.set_level(logging.DEBUG)
    repo, _, client = setup
    started, state = _start(setup)
    receive_callback(repo, state, code="SECRET-CODE-123", error=None, now=NOW)
    receive_callback(repo, state, code="SECRET-CODE-123", error=None, now=NOW)  # replay
    complete_authorization(client, repo, repo.take_callback(started.state_hash), now=NOW)
    assert state not in caplog.text and "SECRET-CODE-123" not in caplog.text
