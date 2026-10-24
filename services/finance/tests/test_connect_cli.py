"""Operator command for PSD2 consent: ``python -m app.connect banks|authorize``."""
from __future__ import annotations

import json
import os
import sys
from datetime import timedelta

import httpx
import pytest

from app import connect, domain
from app.connectors.eb_auth import receive_callback
from app.store.repo import FinanceRepository
from tests.support import make_account, seed_workspace
from tests.test_eb_authorize import _PEM, NOW, Bank

PEPPER = b"connect-test-pepper"


@pytest.fixture
def env(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    _private(secrets / "pepper", PEPPER.decode())
    _private(secrets / "sparkasse.enable_banking", json.dumps(
        {"application_id": "app-1", "private_key_pem": _PEM.decode()}))
    _private(secrets / "bofa.simplefin", "https://u:p@bridge.example.test/simplefin")
    env = {"FINANCE_DB": str(tmp_path / "f.sqlite"), "FINANCE_WORKSPACE_ID": "ws-1",
           "FINANCE_PEPPER_FILE": str(secrets / "pepper"), "FINANCE_SECRETS_DIR": str(secrets)}
    repo = _repo(env)
    seed_workspace(repo)
    for cid, provider in (("sparkasse", domain.Provider.ENABLE_BANKING),
                          ("bofa", domain.Provider.SIMPLEFIN)):
        repo.add_connection(domain.Connection(cid, "ws-1", provider, "PSN-1",
                                              domain.ConnectionStatus.REAUTH_REQUIRED))
    repo.add_account(make_account(aid="acc-1", connection_id="sparkasse",
                                  provider_account_ref="hash-A1",
                                  movement_authority=domain.Provider.ENABLE_BANKING))
    return env


def _private(path, text):
    path.write_text(text)
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def _repo(env):
    return FinanceRepository(env["FINANCE_DB"], pepper=PEPPER)


def _status(env, cid="sparkasse"):
    return next(c.status for c in _repo(env).list_connections("ws-1") if c.id == cid)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Browser:
    """Stands in for the owner: on the first wait it returns from the bank, then it is idle."""

    def __init__(self, env, bank, clock, *, code="code-1", error=None):
        self.env, self.bank, self.clock = env, bank, clock
        self.code, self.error, self.done = code, error, False

    def sleep(self, seconds):
        self.clock.now += timedelta(seconds=seconds)
        if not self.done:
            state = self.bank.body("/auth")["state"]
            assert receive_callback(_repo(self.env), state, code=self.code,
                                    error=self.error, now=self.clock.now)
            self.done = True


def _run(env, *argv, bank, sleep=None, clock=None):
    lines = []
    clock = clock or Clock()
    code = connect.run(list(argv), env, transport=httpx.MockTransport(bank), out=lines.append,
                       sleep=sleep or (lambda s: None), clock=clock)
    return code, lines


AUTHORIZE = ("authorize", "--connection", "sparkasse", "--aspsp", "Sparkasse Example",
             "--country", "DE", "--redirect-url", "https://bff.example.test/finance/connect/callback")


def test_authorize_prints_the_link_then_completes_when_the_browser_returns(env, capsys):
    bank, clock = Bank(), Clock()
    browser = Browser(env, bank, clock)
    code, lines = _run(env, *AUTHORIZE, bank=bank, sleep=browser.sleep, clock=clock)
    assert code == 0
    link = lines.index("https://bank.example.test/authorize?x=1")
    done = next(i for i, line in enumerate(lines) if line.startswith("authorized sparkasse"))
    assert link < done
    assert "linked=1 new=1 missing=0" in lines[done]
    assert "hash-A1 | Giro | EUR | linked" in lines
    assert "hash-NEW | Tagesgeld | EUR | not linked" in lines
    assert _status(env) is domain.ConnectionStatus.OK
    text = "\n".join(lines) + capsys.readouterr().err
    assert bank.body("/auth")["state"] not in text and "code-1" not in text
    assert "PRIVATE KEY" not in text


def test_authorize_times_out_and_changes_nothing(env):
    bank, clock = Bank(), Clock()

    def idle(seconds):
        clock.now += timedelta(seconds=seconds)

    code, lines = _run(env, *AUTHORIZE, bank=bank, sleep=idle, clock=clock)
    assert code == 1
    assert any("timed out" in line for line in lines)
    assert not any(r.url.path == "/sessions" for r in bank.requests)
    assert _status(env) is domain.ConnectionStatus.REAUTH_REQUIRED


def test_a_refusal_in_the_browser_ends_the_command_with_nothing_changed(env, capsys):
    bank, clock = Bank(), Clock()
    browser = Browser(env, bank, clock, code=None, error="access_denied")
    code, _ = _run(env, *AUTHORIZE, bank=bank, sleep=browser.sleep, clock=clock)
    assert code == 1
    assert "not completed" in capsys.readouterr().err
    assert not any(r.url.path == "/sessions" for r in bank.requests)


def test_authorize_refuses_a_connection_that_is_not_enable_banking(env, capsys):
    bank = Bank()
    argv = [a if a != "sparkasse" else "bofa" for a in AUTHORIZE]
    code, _ = _run(env, *argv, bank=bank)
    assert code == 1
    assert "enable banking" in capsys.readouterr().err
    assert bank.requests == []


def test_the_redirect_url_must_be_https(env):
    bank = Bank()
    argv = list(AUTHORIZE[:-1]) + ["http://bff.example.test/finance/connect/callback"]
    assert _run(env, *argv, bank=bank)[0] == 1
    assert bank.requests == []


def test_banks_lists_matching_names_with_their_consent_limit(env):
    code, lines = _run(env, "banks", "--connection", "sparkasse", "--country", "DE",
                       "--match", "sparkasse", bank=Bank())
    assert code == 0
    assert lines == ["Sparkasse Example | consent up to 180 days"]
