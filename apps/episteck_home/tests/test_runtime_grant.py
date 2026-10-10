"""Agent runtime grant lifecycle (H5).

A grant is a Home Delegated Session whose ``client`` is ``agent-runtime:<id>``. These
tests pin the same self-service property as ``open_session`` (no user parameter, the
authenticated human is the only possible owner) plus the grant-specific controls:
runtime allowlist, grantee allowlist, bounded TTL and rotation.
"""
from __future__ import annotations

import datetime as dt
import importlib
import inspect
import sys
import types
from types import SimpleNamespace

import pytest

OWNER = "owner@example.invalid"
NOW = dt.datetime(2026, 10, 10, 10, 0, 0)


class _PermissionError(Exception):
    pass


class _ValidationError(Exception):
    pass


class FakeDoc:
    def __init__(self, data, fake):
        self.__dict__.update(data)
        self._fake = fake
        self.name = None
        self.ignore = None

    def insert(self, ignore_permissions=False):
        self.ignore = ignore_permissions
        if self._fake.fail_insert:
            raise RuntimeError("insert failed")
        self.name = f"HDS-{len(self._fake.rows) + 1:04d}"
        self._fake.rows[self.name] = {
            "user": self.user,
            "status": self.status,
            "expires_at": self.expires_at,
            "client": self.client,
        }


def _make_fake_frappe(current_user=OWNER, conf=None, linked_people=None):
    fake = types.ModuleType("frappe")
    fake.session = SimpleNamespace(user=current_user)
    fake.PermissionError = _PermissionError
    fake.ValidationError = _ValidationError
    fake.conf = {"home_runtime_grantees": [OWNER]} if conf is None else conf
    fake.local = SimpleNamespace()
    fake.rows = {}
    fake.snapshots = []
    fake.fail_insert = False
    fake.committed = 0
    fake.rolled_back = 0
    fake.enabled_users = {OWNER: True, "other@example.invalid": True}
    if current_user:
        fake.enabled_users.setdefault(current_user, True)
    fake.people_by_user = {OWNER: ["PSN-0001"], "other@example.invalid": ["PSN-0002"]}
    if linked_people is not None:
        fake.people_by_user[current_user] = linked_people

    def throw(message, exc=Exception):
        raise exc(message)

    fake.throw = throw
    fake.whitelist = lambda *a, **k: (lambda fn: fn)
    fake.get_doc = lambda data: FakeDoc(data, fake)

    def get_all(doctype, filters=None, fields=None, **kwargs):
        filters = filters or {}
        if doctype == "Person":
            return [
                {"name": n} for n in fake.people_by_user.get(filters.get("linked_user"), [])
            ]
        assert doctype == "Home Delegated Session"
        return [
            {"name": name}
            for name, row in fake.rows.items()
            if all(row.get(k) == v for k, v in filters.items())
        ]

    fake.get_all = get_all

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

        @staticmethod
        def rollback():
            fake.rolled_back += 1
            # emulate a real rollback: restore the pre-call row state
            if fake.snapshots:
                fake.rows.clear()
                fake.rows.update(fake.snapshots[-1])

    fake.db = DB()

    utils = types.ModuleType("frappe.utils")
    utils.now_datetime = lambda: NOW
    utils.add_to_date = lambda d, days=0, seconds=0: d + dt.timedelta(days=days, seconds=seconds)
    fake.utils = utils
    return fake


@pytest.fixture
def build(monkeypatch):
    def make(**kwargs):
        fake = _make_fake_frappe(**kwargs)
        monkeypatch.setitem(sys.modules, "frappe", fake)
        monkeypatch.setitem(sys.modules, "frappe.utils", fake.utils)
        # actor/session bind `frappe` at import time: reload both against this fake.
        importlib.reload(importlib.import_module("episteck_home.identity.actor"))
        module = importlib.reload(importlib.import_module("episteck_home.identity.session"))
        return module, fake

    yield make
    sys.modules.pop("frappe", None)
    sys.modules.pop("frappe.utils", None)


# ------------------------------------------------------------------- open


def test_open_takes_no_user_parameter(build):
    module, _ = build()
    assert set(inspect.signature(module.open_runtime_grant).parameters) == {
        "runtime_id",
        "ttl_days",
    }


@pytest.mark.parametrize("user", ["Guest", None])
def test_open_denies_unauthenticated(build, user):
    module, fake = build(current_user=user)
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows == {}


def test_open_denies_disabled_user(build):
    module, fake = build()
    fake.enabled_users[OWNER] = False
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows == {}


def test_machine_user_without_person_is_denied(build):
    machine = "home-mcp-service@episteck.invalid"
    module, fake = build(
        current_user=machine, conf={"home_runtime_grantees": [machine]}, linked_people=[]
    )
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows == {}


@pytest.mark.parametrize("people", [[], ["PSN-1", "PSN-2"]])
def test_unlinked_or_ambiguous_person_denied(build, people):
    module, fake = build(linked_people=people)
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows == {}


def test_runtime_id_default_is_home_agent_primary_only(build):
    module, fake = build()
    module.open_runtime_grant("home-agent-primary", 90)
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("other-runtime", 90)
    assert len(fake.rows) == 1


def test_runtime_id_site_config_replaces_default(build):
    module, fake = build(
        conf={"home_runtime_ids": ["rt-2"], "home_runtime_grantees": [OWNER]}
    )
    module.open_runtime_grant("rt-2", 5)
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("home-agent-primary", 5)


@pytest.mark.parametrize("conf", [{}, {"home_runtime_grantees": []},
                                  {"home_runtime_grantees": "owner@example.invalid"}])
def test_grantees_absent_or_empty_denies_everyone(build, conf):
    module, fake = build(conf=conf)
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows == {}


def test_non_grantee_is_denied(build):
    module, fake = build(conf={"home_runtime_grantees": ["other@example.invalid"]})
    with pytest.raises(_PermissionError):
        module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows == {}


@pytest.mark.parametrize("ttl", [0, -1, 91, True, False, "abc", "", 1.5, None, "9 0", "-3"])
def test_ttl_days_rejected_before_any_write(build, ttl):
    module, fake = build()
    with pytest.raises(_ValidationError):
        module.open_runtime_grant("home-agent-primary", ttl)
    assert fake.rows == {}
    assert fake.committed == 0


def test_ttl_days_accepts_http_string(build):
    module, fake = build()
    module.open_runtime_grant("home-agent-primary", "90")
    assert len(fake.rows) == 1


def test_custom_max_days_is_respected(build):
    module, fake = build(
        conf={"home_runtime_grant_max_days": 30, "home_runtime_grantees": [OWNER]}
    )
    module.open_runtime_grant("home-agent-primary", 30)
    with pytest.raises(_ValidationError):
        module.open_runtime_grant("home-agent-primary", 31)


def test_creates_prefixed_row_expiring_in_ttl_days(build):
    module, fake = build()
    result = module.open_runtime_grant("home-agent-primary", 90)
    row = fake.rows[result["session_id"]]
    assert row["client"] == "agent-runtime:home-agent-primary"
    assert row["user"] == OWNER
    assert row["status"] == "Active"
    assert row["expires_at"] == NOW + dt.timedelta(days=90)
    assert result["expires_at"] == str(NOW + dt.timedelta(days=90))
    assert fake.committed == 1


def test_insert_uses_ignore_permissions_for_authenticated_caller_only(build, monkeypatch):
    module, fake = build()
    docs = []
    original = fake.get_doc
    fake.get_doc = lambda data: docs.append(original(data)) or docs[-1]
    module.open_runtime_grant("home-agent-primary", 1)
    assert docs[0].ignore is True
    assert docs[0].user == OWNER


def test_rotation_revokes_previous_active_grant(build):
    module, fake = build()
    first = module.open_runtime_grant("home-agent-primary", 90)
    second = module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows[first["session_id"]]["status"] == "Revoked"
    assert fake.rows[first["session_id"]]["revoked_at"] == NOW
    assert fake.rows[second["session_id"]]["status"] == "Active"


def test_rotation_leaves_other_users_and_browser_sessions_untouched(build):
    module, fake = build()
    fake.rows["HDS-B"] = {"user": OWNER, "status": "Active", "client": "bff-web"}
    fake.rows["HDS-O"] = {
        "user": "other@example.invalid",
        "status": "Active",
        "client": "agent-runtime:home-agent-primary",
    }
    module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows["HDS-B"]["status"] == "Active"
    assert fake.rows["HDS-O"]["status"] == "Active"


def test_failed_insert_rolls_back_rotation(build):
    module, fake = build()
    first = module.open_runtime_grant("home-agent-primary", 90)
    fake.snapshots.append({k: dict(v) for k, v in fake.rows.items()})
    fake.fail_insert = True
    with pytest.raises(RuntimeError):
        module.open_runtime_grant("home-agent-primary", 90)
    assert fake.rolled_back == 1
    assert fake.rows[first["session_id"]]["status"] == "Active"


# ------------------------------------------------------------------ close


def test_close_owner_closes(build):
    module, fake = build()
    sid = module.open_runtime_grant("home-agent-primary", 90)["session_id"]
    assert module.close_runtime_grant(sid) == {"closed": True}
    assert fake.rows[sid]["status"] == "Revoked"
    assert fake.rows[sid]["revoked_at"] == NOW


def test_close_not_owner_and_missing_give_same_answer(build):
    module, fake = build()
    sid = module.open_runtime_grant("home-agent-primary", 90)["session_id"]
    fake.rows[sid]["user"] = "other@example.invalid"
    assert module.close_runtime_grant(sid) == module.close_runtime_grant("HDS-NOPE")
    assert fake.rows[sid]["status"] == "Active"


def test_close_refuses_a_browser_session(build):
    module, fake = build()
    fake.rows["HDS-B"] = {"user": OWNER, "status": "Active", "client": "bff-web"}
    assert module.close_runtime_grant("HDS-B") == {"closed": False}
    assert fake.rows["HDS-B"]["status"] == "Active"


def test_close_allowed_after_user_unlinked_and_not_grantee(build):
    module, fake = build()
    sid = module.open_runtime_grant("home-agent-primary", 90)["session_id"]
    fake.people_by_user[OWNER] = []
    fake.conf["home_runtime_grantees"] = []
    assert module.close_runtime_grant(sid) == {"closed": True}


def test_close_denies_guest_and_requires_id(build):
    module, _ = build(current_user="Guest")
    with pytest.raises(_PermissionError):
        module.close_runtime_grant("HDS-0001")
    module, _ = build()
    with pytest.raises(_ValidationError):
        module.close_runtime_grant("")


# ----------------------------------------------------------------- status

MCP_CALLER = "home-mcp-service@episteck.invalid"


def _delegate(fake, session_id, *, audience="home-control-plane", user=OWNER):
    fake.local.episteck_delegated_user = user
    fake.local.episteck_delegation_audience = audience
    fake.local.episteck_delegated_session_id = session_id


@pytest.fixture
def status(build):
    def make(*, caller=MCP_CALLER, client="agent-runtime:home-agent-primary",
             expires=NOW + dt.timedelta(days=89, hours=5), **delegate):
        module, fake = build(current_user=caller)
        fake.rows["HDS-G"] = {"user": OWNER, "status": "Active", "client": client,
                              "expires_at": expires}
        _delegate(fake, delegate.pop("session_id", "HDS-G"), **delegate)
        return module, fake

    return make


def test_status_reports_expiry_and_days_left_rounded_up(status):
    module, _ = status()
    assert module.get_runtime_grant_status() == {
        "granted": True,
        "expires_at": str(NOW + dt.timedelta(days=89, hours=5)),
        "days_left": 90,
    }


def test_status_days_left_never_negative(status):
    module, _ = status(expires=NOW - dt.timedelta(days=2))
    assert module.get_runtime_grant_status()["days_left"] == 0


def test_status_requires_a_delegation(build):
    module, fake = build(current_user=MCP_CALLER)  # plain machine call, nothing bound
    with pytest.raises(_PermissionError):
        module.get_runtime_grant_status()


def test_status_only_for_the_home_mcp_machine(status):
    module, _ = status(caller="nutrition-auth-service@episteck.invalid")
    with pytest.raises(_PermissionError):
        module.get_runtime_grant_status()


def test_status_rejects_a_nutrition_audience_delegation(status):
    module, _ = status(audience="svc-nutrition")
    with pytest.raises(_PermissionError):
        module.get_runtime_grant_status()


def test_status_without_bound_session_id_is_denied(status):
    module, fake = status()
    fake.local.episteck_delegated_session_id = None
    with pytest.raises(_PermissionError):
        module.get_runtime_grant_status()


def test_status_for_a_browser_session_is_not_a_grant(status):
    module, _ = status(client="bff-web")
    assert module.get_runtime_grant_status() == {"granted": False}


def test_status_returns_no_identifier_or_user(status):
    module, _ = status()
    assert set(module.get_runtime_grant_status()) <= {"granted", "expires_at", "days_left"}


def test_status_denies_when_actor_has_no_person(status):
    module, fake = status()
    fake.people_by_user[OWNER] = []
    with pytest.raises(_PermissionError):
        module.get_runtime_grant_status()
