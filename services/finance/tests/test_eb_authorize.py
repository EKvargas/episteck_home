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
    AuthorizationError, complete_authorization, start_authorization,
)
from app.connectors.eb_jwt import JwtSigner
from app.connectors.enable_banking import EbClient
from tests.support import make_account, make_repo, raw_execute, seed_workspace

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
             "cash_account_type": "CACC"},
            {"identification_hash": "hash-NEW", "uid": UID_NEW, "currency": "EUR",
             "cash_account_type": "CACC"}]
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


def _start(setup, days=365, now=NOW, name="Sparkasse Example"):
    repo, bank, client = setup
    url = start_authorization(client, repo, "ws-1", "conn-1", aspsp_name=name, country="DE",
                              redirect_url="https://bff.example.test/finance/connect/callback",
                              requested_days=days, now=now)
    return url, bank.body("/auth")["state"]


def test_consent_is_capped_at_the_banks_maximum_validity(setup):
    _start(setup, days=365)
    valid_until = datetime.fromisoformat(setup[1].body("/auth")["access"]["valid_until"])
    assert valid_until == NOW + timedelta(seconds=MAX_VALIDITY)


def test_a_shorter_request_is_kept_as_asked(setup):
    _start(setup, days=30)
    valid_until = datetime.fromisoformat(setup[1].body("/auth")["access"]["valid_until"])
    assert valid_until == NOW + timedelta(days=30)


def test_authorization_request_shape_and_returned_url(setup):
    url, state = _start(setup)
    body = setup[1].body("/auth")
    assert url == "https://bank.example.test/authorize?x=1"
    assert body["aspsp"] == {"name": "Sparkasse Example", "country": "DE"}
    assert body["redirect_url"] == "https://bff.example.test/finance/connect/callback"
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


def test_completing_stores_the_session_map_consent_expiry_and_reopens_the_connection(setup):
    repo, bank, client = setup
    _, state = _start(setup)
    result = complete_authorization(client, repo, state, "code-xyz", now=NOW + timedelta(minutes=2))
    assert bank.body("/sessions") == {"code": "code-xyz"}
    assert (result.linked, result.unexpected, result.missing) == (1, 1, 0)
    connection = repo.list_connections("ws-1")[0]
    assert connection.status is domain.ConnectionStatus.OK
    assert connection.consent_expires_at == NOW + timedelta(days=90)  # from the response
    session = repo.load_eb_session("conn-1")
    assert session.session_id == "session-1"
    assert dict(session.accounts) == {"hash-A1": UID_A}  # the unexpected account is NOT linked


def test_an_expected_account_missing_from_the_session_is_reported(setup):
    repo, bank, client = setup
    bank.accounts = [{"identification_hash": "hash-OTHER", "uid": UID_NEW, "currency": "EUR",
                      "cash_account_type": "CACC"}]
    _, state = _start(setup)
    result = complete_authorization(client, repo, state, "c", now=NOW)
    assert (result.linked, result.unexpected, result.missing) == (0, 1, 1)


@pytest.mark.parametrize("scenario", ["replay", "expired", "unknown"])
def test_bad_state_fails_identically_and_never_calls_the_bank(setup, scenario):
    repo, bank, client = setup
    _, state = _start(setup)
    before = len(bank.requests)
    now = NOW + timedelta(minutes=1)
    if scenario == "replay":
        complete_authorization(client, repo, state, "c", now=now)
        before = len(bank.requests)
    elif scenario == "expired":
        now = NOW + timedelta(minutes=16)
    else:
        state = "x" * 43
    with pytest.raises(AuthorizationError) as raised:
        complete_authorization(client, repo, state, "c", now=now)
    assert str(raised.value) == "authorization could not be completed"
    assert len(bank.requests) == before


def test_state_is_consumed_even_if_the_code_exchange_fails(setup):
    repo, bank, client = setup
    bank.session_status = 403
    _, state = _start(setup)
    with pytest.raises(AuthorizationError):
        complete_authorization(client, repo, state, "c", now=NOW)
    bank.session_status = 200
    with pytest.raises(AuthorizationError):
        complete_authorization(client, repo, state, "c", now=NOW)
    assert repo.list_connections("ws-1")[0].status is domain.ConnectionStatus.REAUTH_REQUIRED


def test_reauthorization_replaces_the_previous_session_map(setup):
    repo, bank, client = setup
    _, state = _start(setup)
    complete_authorization(client, repo, state, "c1", now=NOW)
    bank.accounts = [{"identification_hash": "hash-A1", "uid": UID_NEW, "currency": "EUR",
                      "cash_account_type": "CACC"}]
    _, state2 = _start(setup)
    complete_authorization(client, repo, state2, "c2", now=NOW)
    assert dict(repo.load_eb_session("conn-1").accounts) == {"hash-A1": UID_NEW}


def test_logs_never_contain_the_state_or_the_code(setup, caplog):
    caplog.set_level(logging.DEBUG)
    repo, bank, client = setup
    _, state = _start(setup)
    complete_authorization(client, repo, state, "SECRET-CODE-123", now=NOW)
    with pytest.raises(AuthorizationError):
        complete_authorization(client, repo, state, "SECRET-CODE-123", now=NOW)
    assert state not in caplog.text and "SECRET-CODE-123" not in caplog.text
