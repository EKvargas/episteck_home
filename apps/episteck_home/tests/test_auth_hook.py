"""Auth-hook tests: session -> User binding, revocation, and logout (G1.6).

These cover the transport seam that maps a verified delegation to an authenticated
Frappe User. The hook never accepts a Person id from any caller.
"""
from __future__ import annotations

import importlib
import sys
import time
import types
from types import SimpleNamespace

import pytest

from episteck_home.identity.delegation import sign

SECRET = "hook-secret"
ISSUER = "episteck-home-bff"
# The hook derives its clock from real epoch UTC (time.time()), never from the site's
# naive local datetime — see auth_hook TIME IS UTC. So these tokens must be minted
# against real time, not a frozen constant, or every one of them reads as expired.
NOW = int(time.time())


def _claims(**overrides):
    base = {
        "iss": ISSUER,
        "aud": "home-control-plane",
        "iat": NOW,
        "exp": NOW + 120,
        "jti": "tok-1",
        "sid": "sess-1",
    }
    base.update(overrides)
    return base


def _make_fake_frappe():
    fake = types.ModuleType("frappe")
    fake.session = SimpleNamespace(user="home-mcp@example.invalid")
    fake.local = SimpleNamespace()
    fake.conf = {
        "home_delegation_secret": SECRET,
        "home_delegation_issuer": ISSUER,
    }
    fake.headers = {}
    fake.sessions = {
        "sess-1": {"user": "person@example.invalid", "status": "Active", "expires_at": None},
        "sess-revoked": {"user": "person@example.invalid", "status": "Revoked", "expires_at": None},
        "sess-expired": {
            "user": "person@example.invalid",
            "status": "Active",
            "expires_at": "2000-01-01 00:00:00",
        },
        "sess-disabled": {"user": "disabled@example.invalid", "status": "Active", "expires_at": None},
    }
    fake.users = {
        "person@example.invalid": {"enabled": 1},
        "disabled@example.invalid": {"enabled": 0},
    }

    fake.get_request_header = lambda name: fake.headers.get(name)

    def get_all(doctype, filters=None, fields=None, **kwargs):
        assert doctype == "Home Delegated Session"
        row = fake.sessions.get((filters or {}).get("name"))
        if not row or row["status"] != (filters or {}).get("status"):
            return []
        return [{"user": row["user"], "expires_at": row["expires_at"]}]

    class _DB:
        def get_value(self, doctype, name, fieldname):
            assert doctype == "User"
            return fake.users.get(name, {}).get(fieldname)

    fake.get_all = get_all
    fake.db = _DB()
    fake.utils = SimpleNamespace(
        now_datetime=lambda: SimpleNamespace(timestamp=lambda: NOW),
        now=lambda: "2026-09-16 00:00:00",
    )
    return fake


@pytest.fixture
def hook(monkeypatch):
    fake = _make_fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("episteck_home.identity.auth_hook", None)
    module = importlib.import_module("episteck_home.identity.auth_hook")
    return module, fake


def _token(**overrides):
    return sign(_claims(**overrides), SECRET)


def test_valid_delegation_binds_the_session_user(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token()
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user == "person@example.invalid"
    assert fake.local.episteck_machine_caller == "home-mcp@example.invalid"


def test_no_header_leaves_no_delegated_user(hook):
    module, fake = hook
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_anonymous_request_cannot_bootstrap_identity(hook):
    """A delegation header alone, with no authenticated machine caller, is inert."""
    module, fake = hook
    fake.session.user = "Guest"
    fake.headers["X-Episteck-Delegation"] = _token()
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_revoked_session_denies_on_the_next_call(hook):
    """Logout: the token is still cryptographically valid, the session is not."""
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(sid="sess-revoked")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_expired_session_record_denies(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(sid="sess-expired")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_disabled_user_denies_even_with_a_live_session(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(sid="sess-disabled")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_unknown_session_denies(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(sid="sess-does-not-exist")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_forged_signature_denies(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = sign(_claims(), "attacker-secret")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_wrong_audience_denies(hook):
    """A delegation minted for Nutrition must not bind at the Control Plane."""
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(aud="svc-nutrition")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_expired_token_denies(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(iat=NOW - 600, exp=NOW - 1)
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_missing_secret_configuration_fails_closed(hook):
    module, fake = hook
    fake.conf["home_delegation_secret"] = None
    fake.headers["X-Episteck-Delegation"] = _token()
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_a_person_id_in_the_header_is_not_an_identity(hook):
    """Amendment A7: a plain actor header must never work."""
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = "PSN-00001"
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_hook_never_raises_into_the_request_path(hook):
    module, fake = hook

    def explode(*args, **kwargs):
        raise RuntimeError("database down")

    fake.get_all = explode
    fake.headers["X-Episteck-Delegation"] = _token()
    module.establish_delegated_context()  # must not raise
    assert fake.local.episteck_delegated_user is None
