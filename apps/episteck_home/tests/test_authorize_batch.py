"""authorize_batch: the Finance-shaped, positional, no-oracle batch decision (B2).

One HTTP request, one delegation (single-use), one actor resolution, 1..8 requirements
``{subject: "SELF" | "PSN-...", domain: "FINANCE", action}``. The response is positional:
decision i answers requirement i, with the subject echoed exactly as sent.
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys

import pytest

from tests.test_home_api_security import FakePermissionError, _make_fake_frappe


@pytest.fixture
def batch(monkeypatch):
    fake = _make_fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", fake)
    for module in (
        "episteck_home.policy.wrappers",
        "episteck_home.identity.actor",
        "episteck_home.api",
    ):
        sys.modules.pop(module, None)
    api = importlib.import_module("episteck_home.api")

    asked: list[tuple] = []
    allowed: set[tuple] = set()  # (subject, action)

    def fake_check(actor, subject, domain, action):
        asked.append((actor, subject, domain, action))
        if (subject, action) in allowed:
            return {"allow": True, "reason": "grant"}
        # Distinct internal reasons: the endpoint must not leak them.
        reason = "no consent grant (fail closed)" if subject == "PSN-MISSING" \
            else "no matching active grant (fail closed)"
        return {"allow": False, "reason": reason}

    monkeypatch.setattr(api, "_check_access", fake_check)
    return api, fake, asked, allowed


def req(subject="SELF", action="VIEW", domain="FINANCE"):
    return {"subject": subject, "domain": domain, "action": action}


def test_positional_order_and_echo(batch):
    api, _, _, allowed = batch
    allowed |= {("PSN-ACTOR", "VIEW"), ("PSN-SUBJECT", "UPDATE")}
    reqs = [req("PSN-SUBJECT", "UPDATE"), req("SELF", "VIEW"), req("PSN-SUBJECT", "VIEW")]
    out = api.authorize_batch(reqs)
    assert out["actor_person_id"] == "PSN-ACTOR"
    got = [(d["subject"], d["domain"], d["action"], d["allow"]) for d in out["decisions"]]
    assert got == [
        ("PSN-SUBJECT", "FINANCE", "UPDATE", True),
        ("SELF", "FINANCE", "VIEW", True),
        ("PSN-SUBJECT", "FINANCE", "VIEW", False),
    ]
    assert all(set(d) == {"subject", "domain", "action", "allow", "reason"} for d in out["decisions"])


def test_self_resolves_to_actor_server_side(batch):
    api, _, asked, _ = batch
    api.authorize_batch([req("SELF")])
    assert asked == [("PSN-ACTOR", "PSN-ACTOR", "FINANCE", "VIEW")]


def test_one_policy_evaluation_per_requirement(batch):
    api, _, asked, _ = batch
    api.authorize_batch([req("SELF"), req("PSN-SUBJECT"), req("PSN-SUBJECT", "UPDATE")])
    assert len(asked) == 3


def test_actor_resolved_exactly_once(batch, monkeypatch):
    api, _, _, _ = batch
    calls = []
    real = api.resolve_actor
    monkeypatch.setattr(api, "resolve_actor", lambda **kw: calls.append(kw) or real(**kw))
    api.authorize_batch([req("SELF"), req("PSN-SUBJECT")])
    assert len(calls) == 1
    assert calls[0]["accept_audiences"] == api.POLICY_AUDIENCES


def test_missing_and_denied_subjects_are_indistinguishable(batch):
    api, _, _, _ = batch
    out = api.authorize_batch([req("PSN-MISSING"), req("PSN-SUBJECT")])
    missing, denied = out["decisions"]
    assert missing["allow"] is False and denied["allow"] is False
    assert missing["reason"] == denied["reason"]


def test_denials_use_one_uniform_reason_and_hide_internal_text(batch):
    api, _, _, allowed = batch
    allowed.add(("PSN-ACTOR", "VIEW"))
    out = api.authorize_batch([req("SELF", "VIEW"), req("SELF", "UPDATE"), req("PSN-MISSING")])
    assert out["decisions"][0]["allow"] is True
    reasons = {d["reason"] for d in out["decisions"][1:]}
    assert len(reasons) == 1
    assert "grant" not in reasons.pop()


def test_accepts_json_string_body(batch):
    api, _, _, _ = batch
    out = api.authorize_batch(json.dumps([req("SELF")]))
    assert len(out["decisions"]) == 1


BAD = [
    None, "not json", {"subject": "SELF"}, 5, [], [req()] * 9,
    [None], ["SELF"], [req(domain="NUTRITION")], [req(domain="finance")], [req(domain=None)],
    [req(action="DELETE")], [req(action=None)], [req(subject="")], [req(subject=None)],
    [req(subject="someone")], [req(subject=7)], [req(subject="self")],
    [{**req(), "extra": 1}], [{"subject": "SELF", "domain": "FINANCE"}],
    [req(), {"domain": "FINANCE", "action": "VIEW"}],
    [req(), "x"],
]


@pytest.mark.parametrize("bad", BAD, ids=range(len(BAD)))
def test_malformed_input_is_refused_without_decisions(batch, bad):
    api, fake, asked, _ = batch
    with pytest.raises(fake.ValidationError):
        api.authorize_batch(bad)
    assert asked == [], "no policy evaluation on refused input"


def test_eight_is_the_maximum(batch):
    api, _, _, _ = batch
    assert len(api.authorize_batch([req()] * 8)["decisions"]) == 8


def test_wrong_audience_refused(batch):
    api, fake, asked, _ = batch
    fake.local.episteck_delegation_audience = "some-other-audience"
    with pytest.raises(FakePermissionError):
        api.authorize_batch([req()])
    assert asked == []


def test_no_delegation_refused(batch):
    api, fake, asked, _ = batch
    fake.local.episteck_delegated_user = None
    with pytest.raises(FakePermissionError):
        api.authorize_batch([req()])
    assert asked == []


def test_finance_audience_accepted(batch):
    api, fake, _, _ = batch
    fake.local.episteck_delegation_audience = "svc-finance"
    assert api.authorize_batch([req()])["actor_person_id"] == "PSN-ACTOR"


def test_no_actor_token_or_workspace_parameter(batch):
    api = batch[0]
    params = set(inspect.signature(api.authorize_batch).parameters)
    assert params == {"requirements"}
