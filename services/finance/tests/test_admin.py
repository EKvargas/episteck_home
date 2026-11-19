"""Operator bootstrap CLI and connector wiring. No HTTP surface exists for any of this."""
from __future__ import annotations

import base64
import io
import logging
import os
import stat
import sys

import httpx
import pytest

from app import admin, domain
from app.config import Settings
from app.connectors.simplefin import SimpleFinConnector
from app.store.receivables_repo import ReceivablesRepository
from app.store.repo import FinanceRepository
from app.sync import main as sync_main
from app.wiring import build_connectors
from tests.support import PEPPER, count_rows, raw_execute

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
ACCESS_URL = "https://demo-user:demo-pass@bridge.example.test/simplefin"


@pytest.fixture
def env(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    pepper = secrets / "pepper"
    pepper.write_text("test-pepper-not-a-secret")
    _private(pepper)
    return {"FINANCE_DB": str(tmp_path / "f.sqlite"), "FINANCE_WORKSPACE_ID": "ws-1",
            "FINANCE_PEPPER_FILE": str(pepper), "FINANCE_SECRETS_DIR": str(secrets)}


def _private(path):
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def _secret(env, name, content=ACCESS_URL):
    path = os.path.join(env["FINANCE_SECRETS_DIR"], name)
    with open(path, "w") as handle:
        handle.write(content)
    _private(path)
    return path


def _repo(env):
    return FinanceRepository(env["FINANCE_DB"], pepper=b"test-pepper-not-a-secret")


def _cmd(env, *argv, transport=None):
    return admin.run(list(argv), env, transport=transport)


def _bootstrap(env):
    assert _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1") == 0
    _secret(env, "conn-1.simplefin")
    assert _cmd(env, "add-connection", "--id", "conn-1", "--provider", "simplefin",
                "--owner", "PSN-1") == 0


LINK = ("link-account", "--id", "acc-1", "--connection", "conn-1", "--provider-ref", "A1",
        "--institution", "Bank", "--type", "CURRENT", "--liquidity", "AVAILABLE",
        "--balance-authority", "PROVIDER", "--currency", "USD", "--owner", "PSN-1")


def test_init_workspace_creates_it_with_the_owner_and_is_idempotent(env):
    assert _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1") == 0
    assert _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1") == 0
    repo = _repo(env)
    assert repo.get_workspace("ws-1").status is domain.WorkspaceStatus.ACTIVE
    assert repo.is_member("ws-1", "PSN-1")
    assert count_rows(repo, "workspace") == 1


def test_add_connection_requires_its_secret_file(env):
    _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1")
    assert _cmd(env, "add-connection", "--id", "conn-1", "--provider", "simplefin",
                "--owner", "PSN-1") != 0
    assert count_rows(_repo(env), "connection") == 0


@posix_only
def test_add_connection_refuses_a_secret_that_others_can_read(env):
    _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1")
    path = _secret(env, "conn-1.simplefin")
    os.chmod(path, 0o644)
    assert _cmd(env, "add-connection", "--id", "conn-1", "--provider", "simplefin",
                "--owner", "PSN-1") != 0


def test_link_account_stores_owners_and_validates_enums(env):
    _bootstrap(env)
    assert _cmd(env, *LINK, "--owner", "PSN-2") == 0
    account = _repo(env).list_accounts("ws-1")[0]
    assert account.owner_person_ids == ("PSN-1", "PSN-2")
    assert account.liquidity is domain.Liquidity.AVAILABLE
    bad = [a if a != "AVAILABLE" else "LIQUID" for a in LINK]
    assert _cmd(env, *bad) != 0


def test_link_account_to_an_unknown_connection_fails(env):
    _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1")
    assert _cmd(env, *LINK) != 0


def test_claim_simplefin_writes_the_access_url_privately_and_never_prints_it(env, capsys):
    token = base64.b64encode(b"https://bridge.example.test/simplefin/claim/ABC").decode()
    token_file = _secret(env, "setup-token", token)
    out = os.path.join(env["FINANCE_SECRETS_DIR"], "conn-1.simplefin")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=ACCESS_URL))
    assert _cmd(env, "claim-simplefin", "--setup-token-file", token_file, "--out", out,
                transport=transport) == 0
    assert open(out).read().strip() == ACCESS_URL
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    captured = capsys.readouterr()
    assert "demo-pass" not in captured.out + captured.err
    assert token not in captured.out + captured.err
    # a second claim must not overwrite the secret
    assert _cmd(env, "claim-simplefin", "--setup-token-file", token_file, "--out", out,
                transport=transport) != 0


def test_list_shows_structure_but_no_secrets_or_balances(env, capsys):
    _bootstrap(env)
    _cmd(env, *LINK)
    capsys.readouterr()
    assert _cmd(env, "list") == 0
    text = capsys.readouterr().out
    assert "conn-1" in text and "acc-1" in text
    assert "demo-pass" not in text and "bridge.example.test" not in text


def _bridge(request):
    """A SimpleFIN bridge answering /accounts with one account and its balance."""
    return httpx.Response(200, json={
        "errlist": [], "connections": [{"conn_id": "CON-1", "name": "Bank of America"}],
        "accounts": [{"id": "ACT-1", "conn_id": "CON-1", "name": "Adv Plus Banking",
                      "currency": "USD", "balance": "4321.09", "available-balance": "4300.00",
                      "balance-date": 1760000000}]})


def test_provider_accounts_lists_references_without_balances_or_secrets(env, capsys):
    _bootstrap(env)
    capsys.readouterr()
    assert _cmd(env, "provider-accounts", "--connection", "conn-1",
                transport=httpx.MockTransport(_bridge)) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["ACT-1 | Adv Plus Banking | USD | Bank of America"]
    text = captured.out + captured.err
    assert "4321" not in text and "4300" not in text
    assert "demo-pass" not in text and "bridge.example.test" not in text


def test_provider_accounts_for_an_unknown_connection_fails(env, capsys):
    _bootstrap(env)
    assert _cmd(env, "provider-accounts", "--connection", "nope",
                transport=httpx.MockTransport(_bridge)) != 0
    assert "unknown connection" in capsys.readouterr().err


def test_provider_accounts_reports_a_provider_failure_by_kind_only(env, capsys):
    _bootstrap(env)
    capsys.readouterr()
    denied = httpx.MockTransport(lambda r: httpx.Response(403, text="detail demo-pass"))
    assert _cmd(env, "provider-accounts", "--connection", "conn-1", transport=denied) != 0
    captured = capsys.readouterr()
    assert captured.err.strip() == "error: ConnectorError: AUTH_REQUIRED"
    assert "demo-pass" not in captured.out + captured.err


def test_provider_accounts_for_enable_banking_points_to_the_authorization_step(env, capsys):
    _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1")
    _repo(env).add_connection(domain.Connection(
        "eb-1", "ws-1", domain.Provider.ENABLE_BANKING, "PSN-1",
        domain.ConnectionStatus.REAUTH_REQUIRED))
    assert _cmd(env, "provider-accounts", "--connection", "eb-1") != 0
    assert "authoriz" in capsys.readouterr().err


def test_admin_commands_are_audited_as_the_admin_channel(env):
    _bootstrap(env)
    rows = raw_execute(_repo(env), "SELECT DISTINCT channel FROM command_log")
    assert [r[0] for r in rows] == ["admin"]


# --- wiring and the timer entrypoint ----------------------------------------------------
def test_build_connectors_creates_simplefin_and_skips_the_unconfigured(env):
    _bootstrap(env)
    repo = _repo(env)
    connectors = build_connectors(repo, "ws-1", env["FINANCE_SECRETS_DIR"])
    assert isinstance(connectors["conn-1"], SimpleFinConnector)
    os.remove(os.path.join(env["FINANCE_SECRETS_DIR"], "conn-1.simplefin"))
    assert build_connectors(repo, "ws-1", env["FINANCE_SECRETS_DIR"]) == {}


def test_the_timer_entrypoint_exits_zero_when_clean_and_nonzero_on_a_missing_secret(env, monkeypatch):
    _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("app.sync._default_ecb", lambda: None)
    assert sync_main() == 0  # nothing configured, nothing failed
    _bootstrap_secretless(env)
    assert sync_main() == 1  # a connection exists but its secret is gone


def _bootstrap_secretless(env):
    _secret(env, "conn-1.simplefin")
    _cmd(env, "add-connection", "--id", "conn-1", "--provider", "simplefin", "--owner", "PSN-1")
    os.remove(os.path.join(env["FINANCE_SECRETS_DIR"], "conn-1.simplefin"))


def test_the_timer_entrypoint_runs_the_matcher_even_when_a_connection_failed(env, monkeypatch,
                                                                             caplog):
    _cmd(env, "init-workspace", "--name", "Home", "--owner", "PSN-1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("app.sync._default_ecb", lambda: None)
    _bootstrap_secretless(env)
    with caplog.at_level(logging.INFO, logger="finance.matcher"):
        assert sync_main() == 1
    assert raw_execute(_repo(env), "SELECT workspace_id FROM matcher_cursor") == [("ws-1",)]
    assert "matcher run: linked=0 waiting=0 asked=0 receipts=0 ignored=0" in caplog.text


# --- I2 operator commands -----------------------------------------------------------------
SYNTHETIC_IBAN = "XX00 SYNTHETIC OWN 0003"


def _own_hashes(env):
    rr = ReceivablesRepository(_repo(env))
    with rr.read() as c:
        return rr.own_hashes(c, "ws-1")


def test_admin_watch_account_turns_watching_on_and_off(env):
    _bootstrap(env)
    assert _cmd(env, *LINK) == 0
    rr = ReceivablesRepository(_repo(env))

    def watched():
        with rr.read() as c:
            return rr.watched_accounts(c, "ws-1")

    for state, expected in (("on", {"acc-1"}), ("off", set()), ("on", {"acc-1"})):
        assert _cmd(env, "watch-account", "acc-1", state) == 0
        assert watched() == expected
    assert _cmd(env, "watch-account", "acc-9", "on") != 0
    assert _cmd(env, "watch-account", "acc-1", "maybe") != 0
    assert watched() == {"acc-1"}


def test_admin_own_iban_stores_hash_only(env, capsys, monkeypatch):
    _bootstrap(env)
    assert _cmd(env, *LINK) == 0
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(SYNTHETIC_IBAN + "\n"))
    assert _cmd(env, "own-iban", "acc-1") == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(SYNTHETIC_IBAN.lower() + "\n"))
    assert _cmd(env, "own-iban", "acc-1") == 0  # the same IBAN again: one row
    repo = _repo(env)
    assert _own_hashes(env) == {repo.hash_iban(SYNTHETIC_IBAN)}
    assert count_rows(repo, "own_identifier") == 1
    captured = capsys.readouterr()
    stored = repr(raw_execute(repo, "SELECT * FROM command_log")) + repr(
        raw_execute(repo, "SELECT * FROM own_identifier"))
    for text in (captured.out, captured.err, stored):
        assert "SYNTHETIC" not in text.upper() and "XX00" not in text.upper()


def test_admin_own_iban_refuses_an_unknown_account_or_a_malformed_iban(env, capsys, monkeypatch):
    _bootstrap(env)
    assert _cmd(env, *LINK) == 0
    for account, line in (("acc-9", SYNTHETIC_IBAN), ("acc-1", "not an iban"), ("acc-1", "")):
        monkeypatch.setattr("sys.stdin", io.StringIO(line + "\n"))
        assert _cmd(env, "own-iban", account) != 0
    assert _own_hashes(env) == set()
    assert "not an iban" not in capsys.readouterr().err
