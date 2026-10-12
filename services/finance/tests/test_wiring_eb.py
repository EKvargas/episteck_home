from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import admin, domain
from app.connectors.enable_banking import EnableBankingConnector
from app.store.repo import FinanceRepository
from app.wiring import build_connectors

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PEM = _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()


@pytest.fixture
def env(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    pepper = secrets / "pepper"
    pepper.write_text("test-pepper-not-a-secret")
    if sys.platform != "win32":
        os.chmod(pepper, 0o600)
    return {"FINANCE_DB": str(tmp_path / "f.sqlite"), "FINANCE_WORKSPACE_ID": "ws-1",
            "FINANCE_PEPPER_FILE": str(pepper), "FINANCE_SECRETS_DIR": str(secrets)}


def _write_secret(env, content=None):
    path = os.path.join(env["FINANCE_SECRETS_DIR"], "bank-1.enable_banking")
    with open(path, "w") as handle:
        handle.write(content or json.dumps({"application_id": "app-1", "private_key_pem": _PEM}))
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def _bootstrap(env):
    admin.run(["init-workspace", "--name", "Home", "--owner", "PSN-1"], env)
    _write_secret(env)
    assert admin.run(["add-connection", "--id", "bank-1", "--provider", "enable_banking",
                      "--owner", "PSN-1"], env) == 0
    return FinanceRepository(env["FINANCE_DB"], pepper=b"test-pepper-not-a-secret")


def test_adding_an_enable_banking_connection_requires_its_secret(env):
    admin.run(["init-workspace", "--name", "Home", "--owner", "PSN-1"], env)
    assert admin.run(["add-connection", "--id", "bank-1", "--provider", "enable_banking",
                      "--owner", "PSN-1"], env) != 0


def test_an_unusable_secret_is_refused_when_adding(env):
    admin.run(["init-workspace", "--name", "Home", "--owner", "PSN-1"], env)
    _write_secret(env, content="not json")
    assert admin.run(["add-connection", "--id", "bank-1", "--provider", "enable_banking",
                      "--owner", "PSN-1"], env) != 0


def test_no_connector_until_the_owner_has_authorized_a_session(env):
    repo = _bootstrap(env)
    assert build_connectors(repo, "ws-1", env["FINANCE_SECRETS_DIR"]) == {}


def test_connector_is_built_from_the_secret_and_the_stored_session(env):
    repo = _bootstrap(env)
    now = datetime.now(timezone.utc)
    repo.activate_eb_session("ws-1", "bank-1", "s-1", now + timedelta(days=30), now,
                             {"hash-A1": "uid-1"})
    connector = build_connectors(repo, "ws-1", env["FINANCE_SECRETS_DIR"])["bank-1"]
    assert isinstance(connector, EnableBankingConnector)
    assert "PRIVATE KEY" not in repr(connector)


def test_an_expired_session_builds_no_connector(env):
    repo = _bootstrap(env)
    now = datetime.now(timezone.utc)
    repo.activate_eb_session("ws-1", "bank-1", "s-1", now - timedelta(days=1),
                             now - timedelta(days=90), {"hash-A1": "uid-1"})
    assert build_connectors(repo, "ws-1", env["FINANCE_SECRETS_DIR"]) == {}
