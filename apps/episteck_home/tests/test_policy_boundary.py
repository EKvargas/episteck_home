"""Home policy boundary: a positive decision requires a currently existing subject.

The guard lives in ``policy.wrappers.check_access``, the one function every Home
authorization path calls. A missing subject must be indistinguishable from an existing
subject with no consent, and an orphaned grant must never authorize.
"""
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.test_home_api_security import _make_fake_frappe

NOW = datetime(2026, 10, 6, 12, 0, 0)
NO_GRANT = {"allow": False, "reason": "no consent grant (fail closed)"}


def _grant(actor, subject, domain="NUTRITION", actions="VIEW", state="ACTIVE"):
    return {
        "actor_person": actor,
        "subject_person": subject,
        "domain": domain,
        "actions": actions,
        "state": state,
        "valid_from": None,
        "valid_until": None,
    }


@pytest.fixture
def policy(monkeypatch):
    fake = types.ModuleType("frappe")
    fake.people = {"PSN-ACTOR", "PSN-SUBJECT", "PSN-OTHER"}
    fake.grants = []
    fake.grant_loads = []
    fake.exists_calls = []
    fake.exists_error = None

    class _DB:
        def exists(self, doctype, name):
            assert doctype == "Person"
            fake.exists_calls.append(name)
            if fake.exists_error is not None:
                raise fake.exists_error
            return name if name in fake.people else None

    def get_all(doctype, filters=None, fields=None, **kwargs):
        assert doctype == "Consent Grant"
        fake.grant_loads.append(dict(filters))
        return [
            g for g in fake.grants
            if g["actor_person"] == filters["actor_person"]
            and g["subject_person"] == filters["subject_person"]
        ]

    fake.db = _DB()
    fake.get_all = get_all
    fake.utils = SimpleNamespace(now_datetime=lambda: NOW)
    fake.log_error = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("episteck_home.policy.wrappers", None)
    return importlib.import_module("episteck_home.policy.wrappers"), fake


def test_cross_subject_with_active_grant_allows(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")["allow"] is True


def test_cross_subject_without_grant_denies(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-OTHER", "NUTRITION", "VIEW") == NO_GRANT


def test_missing_subject_with_orphaned_grant_denies_without_loading_grants(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-GONE"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-GONE", "NUTRITION", "VIEW") == NO_GRANT
    assert fake.grant_loads == []


def test_missing_subject_is_indistinguishable_from_no_grant(policy):
    wrappers, _ = policy
    missing = wrappers.check_access("PSN-ACTOR", "PSN-GONE", "NUTRITION", "VIEW")
    existing = wrappers.check_access("PSN-ACTOR", "PSN-OTHER", "NUTRITION", "VIEW")
    assert missing == existing == NO_GRANT


def test_self_access_still_allows(policy):
    wrappers, _ = policy
    assert wrappers.check_access("PSN-ACTOR", "PSN-ACTOR", "NUTRITION", "VIEW")["allow"] is True


def test_subject_deleted_after_bootstrap_denies_on_the_next_check(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")["allow"] is True
    fake.people.discard("PSN-SUBJECT")
    assert wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW") == NO_GRANT


def test_existence_lookup_failure_fails_closed(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    fake.exists_error = RuntimeError("db down")
    decision = wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")
    assert decision == {"allow": False, "reason": "policy error (fail closed)"}


def test_invalid_request_answer_does_not_reveal_existence(policy):
    wrappers, fake = policy
    missing = wrappers.check_access("PSN-ACTOR", "PSN-GONE", "NOT_A_DOMAIN", "VIEW")
    existing = wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NOT_A_DOMAIN", "VIEW")
    assert missing == existing
    assert missing["allow"] is False
    assert fake.exists_calls == []


def test_existence_is_checked_on_every_call(policy):
    wrappers, fake = policy
    wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")
    wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")
    assert fake.exists_calls == ["PSN-SUBJECT", "PSN-SUBJECT"]


# --- API level, with the real wrapper -------------------------------------


@pytest.fixture
def api_real_policy(monkeypatch):
    fake = _make_fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", fake)
    for module in (
        "episteck_home.policy.wrappers",
        "episteck_home.identity.actor",
        "episteck_home.identity.auth_hook",
        "episteck_home.api",
    ):
        sys.modules.pop(module, None)
    return importlib.import_module("episteck_home.api"), fake


def test_api_check_access_missing_subject_matches_no_grant(api_real_policy):
    api, _ = api_real_policy
    missing = api.check_access("PSN-GONE", "NUTRITION", "VIEW")
    existing = api.check_access("PSN-SUBJECT", "NUTRITION", "VIEW")
    assert missing == existing == NO_GRANT


def test_api_batch_missing_subject_has_no_positive_decision(api_real_policy):
    api, _ = api_real_policy
    requirements = [
        {"domain": "NUTRITION", "action": "VIEW"},
        {"domain": "NUTRITION", "action": "CREATE"},
    ]
    missing = api.check_access_many("PSN-GONE", requirements)
    existing = api.check_access_many("PSN-SUBJECT", requirements)
    assert missing["allow"] is False
    assert all(item["allow"] is False for item in missing["decisions"])
    assert missing == existing


def test_api_self_access_still_allows(api_real_policy):
    api, _ = api_real_policy
    assert api.check_access("PSN-ACTOR", "NUTRITION", "VIEW")["allow"] is True
