"""Home Delegated Session lifecycle (G1.6).

The security property under test: ``open_session`` and ``close_session`` take **no
user parameter**, so the BFF can only ever open a session for the human whose token
Frappe just validated. Possession of a session id is likewise not enough to revoke
someone else's session.
"""
from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pytest


class _PermissionError(Exception):
    pass


class _ValidationError(Exception):
    pass


class FakeDoc:
    def __init__(self, data, store):
        self.__dict__.update(data)
        self._store = store
        self.name = None
        self.inserted_with_ignore = None

    def insert(self, ignore_permissions=False):
        self.inserted_with_ignore = ignore_permissions
        self.name = f"HDS-{len(self._store) + 1:04d}"
        self._store[self.name] = {
            "user": self.user,
            "status": self.status,
            "expires_at": self.expires_at,
            "client": self.client,
        }


def _make_fake_frappe(current_user="person@example.invalid", enabled=True):
    fake = types.ModuleType("frappe")
    fake.session = SimpleNamespace(user=current_user)
    fake.PermissionError = _PermissionError
    fake.ValidationError = _ValidationError
    fake.rows = {}
    fake.enabled_users = {current_user: enabled} if current_user else {}
    fake.committed = 0

    def throw(message, exc=Exception):
        raise exc(message)

    def whitelist(*args, **kwargs):
        def decorate(fn):
            return fn

        return decorate

    fake.throw = throw
    fake.whitelist = whitelist
    fake.get_doc = lambda data: FakeDoc(data, fake.rows)

    class DB:
        @staticmethod
        def get_value(doctype, name, field):
            if doctype == "User":
                return 1 if fake.enabled_users.get(name) else 0
            row = fake.rows.get(name)
            return row.get(field) if row else None

        @staticmethod
        def set_value(doctype, name, values, update_modified=True):
            fake.rows[name].update(values)

        @staticmethod
        def commit():
            fake.committed += 1

    fake.db = DB()

    utils = types.ModuleType("frappe.utils")
    utils.now_datetime = lambda: "2026-09-16 10:00:00"
    utils.add_to_date = lambda dt, seconds=0: "2026-09-16 22:00:00"
    fake.utils = utils
    return fake


@pytest.fixture
def session_module(monkeypatch):
    def build(**kwargs):
        fake = _make_fake_frappe(**kwargs)
        monkeypatch.setitem(sys.modules, "frappe", fake)
        monkeypatch.setitem(sys.modules, "frappe.utils", fake.utils)
        module = importlib.reload(
            importlib.import_module("episteck_home.identity.session")
        )
        return module, fake

    yield build
    sys.modules.pop("frappe", None)
    sys.modules.pop("frappe.utils", None)


# ------------------------------------------------------------------- open


def test_open_session_binds_the_authenticated_user(session_module):
    module, fake = session_module()
    result = module.open_session()
    assert fake.rows[result["session_id"]]["user"] == "person@example.invalid"


def test_open_session_takes_no_user_parameter(session_module):
    """The signature itself is the control: an actor cannot be expressed."""
    import inspect

    module, _ = session_module()
    params = set(inspect.signature(module.open_session).parameters)
    assert params == {"client"}
    assert "user" not in params
    assert "actor_person_id" not in params


def test_open_session_denies_guest(session_module):
    module, _ = session_module(current_user="Guest")
    with pytest.raises(_PermissionError):
        module.open_session()


def test_open_session_denies_missing_user(session_module):
    module, _ = session_module(current_user=None)
    with pytest.raises(_PermissionError):
        module.open_session()


def test_open_session_denies_disabled_user(session_module):
    module, _ = session_module(enabled=False)
    with pytest.raises(_PermissionError):
        module.open_session()


def test_open_session_is_active_with_an_expiry(session_module):
    module, fake = session_module()
    row = fake.rows[module.open_session()["session_id"]]
    assert row["status"] == "Active"
    assert row["expires_at"]


def test_open_session_records_the_client(session_module):
    module, fake = session_module()
    row = fake.rows[module.open_session(client="bff-tablet")["session_id"]]
    assert row["client"] == "bff-tablet"


def test_open_session_truncates_oversized_client(session_module):
    module, fake = session_module()
    row = fake.rows[module.open_session(client="x" * 500)["session_id"]]
    assert len(row["client"]) == 140


def test_session_ids_are_distinct(session_module):
    module, _ = session_module()
    assert module.open_session()["session_id"] != module.open_session()["session_id"]


# ------------------------------------------------------------------ close


def test_close_session_revokes_own_session(session_module):
    module, fake = session_module()
    session_id = module.open_session()["session_id"]
    assert module.close_session(session_id) == {"closed": True}
    assert fake.rows[session_id]["status"] == "Revoked"
    assert fake.rows[session_id]["revoked_at"]


def test_close_session_refuses_another_users_session(session_module):
    """Holding a session id must not be enough to revoke it."""
    module, fake = session_module()
    session_id = module.open_session()["session_id"]
    fake.rows[session_id]["user"] = "someone-else@example.invalid"

    assert module.close_session(session_id) == {"closed": False}
    assert fake.rows[session_id]["status"] == "Active"


def test_close_session_does_not_reveal_existence(session_module):
    """Unknown and not-yours return the same answer, so this is no oracle."""
    module, fake = session_module()
    session_id = module.open_session()["session_id"]
    fake.rows[session_id]["user"] = "someone-else@example.invalid"

    assert module.close_session("HDS-DOES-NOT-EXIST") == module.close_session(session_id)


def test_close_session_denies_guest(session_module):
    module, _ = session_module(current_user="Guest")
    with pytest.raises(_PermissionError):
        module.close_session("HDS-0001")


def test_close_session_requires_a_session_id(session_module):
    module, _ = session_module()
    with pytest.raises(_ValidationError):
        module.close_session("")
