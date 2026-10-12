"""authorize_batch: multi-subject, SELF-resolving authorization (H2).

Finance needs the actor's identity AND decisions about themselves and others in
ONE delegated request (delegations are single-use). The actor is never a parameter.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys

import pytest

from tests.test_home_api_security import _make_fake_frappe

ACTOR = "PSN-ACTOR"
SUBJECT = "PSN-SUBJECT"
MISSING = "PSN-GONE"
SELF_REQ = {"subject": "SELF", "domain": "FINANCE", "action": "VIEW"}


@pytest.fixture
def home_api(monkeypatch):
    fake = _make_fake_frappe()
    before = set(sys.modules)
    monkeypatch.setitem(sys.modules, "frappe", fake)
    for module in [m for m in sys.modules if m.startswith("episteck_home.")]:
        monkeypatch.delitem(sys.modules, module)
    yield importlib.import_module("episteck_home.api"), fake
    # Do not leak modules bound to the fake frappe into other test files.
    for module in set(sys.modules) - before:
        if module.startswith("episteck_home."):
            del sys.modules[module]


def test_self_resolves_to_actor_and_allows_self_access(home_api):
    api, _ = home_api
    result = api.authorize_batch([SELF_REQ])
    assert result["actor_person_id"] == ACTOR
    assert result["decisions"] == [
        {"subject": "SELF", "domain": "FINANCE", "action": "VIEW",
         "allow": True, "reason": "self-access"}
    ]


def test_person_subject_without_grant_denies(home_api):
    api, _ = home_api
    result = api.authorize_batch([{**SELF_REQ, "subject": SUBJECT}])
    assert result["actor_person_id"] == ACTOR
    assert result["decisions"][0]["allow"] is False
    assert result["decisions"][0]["subject"] == SUBJECT


def test_missing_subject_denies_identically_to_no_grant(home_api):
    api, _ = home_api
    missing = api.authorize_batch([{**SELF_REQ, "subject": MISSING}])["decisions"][0]
    no_grant = api.authorize_batch([{**SELF_REQ, "subject": SUBJECT}])["decisions"][0]
    assert missing["allow"] is False
    assert missing["reason"] == no_grant["reason"]


def test_decisions_keep_request_order(home_api):
    api, _ = home_api
    result = api.authorize_batch([SELF_REQ, {**SELF_REQ, "subject": SUBJECT}])
    assert [d["subject"] for d in result["decisions"]] == ["SELF", SUBJECT]


@pytest.mark.parametrize(
    "requirements",
    [
        [SELF_REQ] * 9,
        [{**SELF_REQ, "domain": "TELEPATHY"}],
        [{**SELF_REQ, "action": "TELEPORT"}],
        [{**SELF_REQ, "subject": ""}],
        ["not-a-dict"],
        [],
        None,
        "not json",
    ],
)
def test_malformed_requirements_refuse_the_whole_call(home_api, requirements):
    api, _ = home_api
    result = api.authorize_batch(requirements)
    assert result["actor_person_id"] is None
    assert result["decisions"] == []
    assert "fail closed" in result["reason"]


def test_accepts_json_string_requirements(home_api):
    api, _ = home_api
    result = api.authorize_batch(json.dumps([SELF_REQ]))
    assert result["actor_person_id"] == ACTOR
    assert result["decisions"][0]["allow"] is True


def test_has_no_actor_parameter(home_api):
    api, _ = home_api
    params = inspect.signature(api.authorize_batch).parameters
    assert list(params) == ["requirements"]
