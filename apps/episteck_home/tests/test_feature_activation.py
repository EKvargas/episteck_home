"""Feature Activation (B3): bootstrap listing, scoped machine read, DocType sanity.

Finance in I1 does NOT consult this DocType (ADR-0012). These tests guard the Hub
and later-domain surface: only ACTIVE rows, only the actor's own scope, and a
uniform refusal for anything else (no oracle).
"""
from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

from tests.test_home_api_security import (
    FakePermissionError,
    FakeValidationError,
    _make_fake_frappe,
)

DOCTYPE_JSON = (
    Path(__file__).resolve().parents[1]
    / "episteck_home/episteck_home/doctype/feature_activation/feature_activation.json"
)


def _row(feature, scope_type, scope, state="ACTIVE"):
    return {"feature": feature, "scope_type": scope_type, "scope": scope, "state": state}


@pytest.fixture
def api_fa(monkeypatch):
    fake = _make_fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", fake)
    for module in (
        "episteck_home.policy.wrappers",
        "episteck_home.identity.actor",
        "episteck_home.identity.auth_hook",
        "episteck_home.api",
    ):
        sys.modules.pop(module, None)
    api = importlib.import_module("episteck_home.api")
    fake.feature_activations = [
        _row("finance", "Person", "PSN-ACTOR"),
        _row("hub-widgets", "Circle", "CIR-HOME"),
        _row("paused-one", "Person", "PSN-ACTOR", "PAUSED"),
        _row("others-person", "Person", "PSN-OTHER"),
        _row("others-circle", "Circle", "CIR-OTHER"),
    ]
    return api, fake


@pytest.fixture
def human(api_fa):
    """Direct human bearer call, as for get_home_bootstrap."""
    api, fake = api_fa
    fake.session.user = "person@example.invalid"
    fake.local.episteck_delegated_user = None
    fake.local.episteck_machine_caller = None
    return api, fake


# ---------------------------------------------------------------- bootstrap


def test_bootstrap_lists_only_active_features_in_own_scope(human):
    api, _ = human
    result = api.get_home_bootstrap("sess-actor")
    assert sorted(result["features"], key=lambda r: r["feature"]) == [
        _row("finance", "Person", "PSN-ACTOR"),
        _row("hub-widgets", "Circle", "CIR-HOME"),
    ]


def test_bootstrap_features_expose_only_minimal_fields(human):
    api, fake = human
    fake.feature_activations[0]["activated_by"] = "PSN-SECRET"
    result = api.get_home_bootstrap("sess-actor")
    for row in result["features"]:
        assert set(row) == {"feature", "scope_type", "scope", "state"}


def test_bootstrap_features_empty_without_activations(human):
    api, fake = human
    fake.feature_activations = []
    assert api.get_home_bootstrap("sess-actor")["features"] == []


def test_bootstrap_features_bounded_fails_closed(human):
    api, fake = human
    fake.feature_activations = [
        _row(f"f{i}", "Person", "PSN-ACTOR") for i in range(api.MAX_BOOTSTRAP_ROWS + 1)
    ]
    with pytest.raises(FakeValidationError):
        api.get_home_bootstrap("sess-actor")


# ----------------------------------------------------------- get_feature_state


def test_get_feature_state_takes_no_actor_parameter(api_fa):
    api, _ = api_fa
    params = inspect.signature(api.get_feature_state).parameters
    assert list(params) == ["feature", "scope_type", "scope"]


def test_state_active_for_own_person(human):
    api, _ = human
    assert api.get_feature_state("finance", "Person", "PSN-ACTOR") == {
        "state": "ACTIVE",
        "scope_type": "Person",
        "scope": "PSN-ACTOR",
    }


def test_state_active_for_own_circle(human):
    api, _ = human
    assert api.get_feature_state("hub-widgets", "Circle", "CIR-HOME")["state"] == "ACTIVE"


def test_paused_record_reports_paused(human):
    api, _ = human
    assert api.get_feature_state("paused-one", "Person", "PSN-ACTOR")["state"] == "PAUSED"


def test_missing_record_reports_paused_for_permitted_scope(human):
    api, _ = human
    assert api.get_feature_state("never-set", "Person", "PSN-ACTOR") == {
        "state": "PAUSED",
        "scope_type": "Person",
        "scope": "PSN-ACTOR",
    }


@pytest.mark.parametrize(
    "scope_type,scope",
    [
        ("Person", "PSN-OTHER"),  # another person
        ("Person", "PSN-SUBJECT"),  # shares a circle, still not self
        ("Circle", "CIR-OTHER"),  # circle the actor is not in
        ("Circle", "CIR-DOES-NOT-EXIST"),  # same refusal as a foreign one
    ],
)
def test_foreign_scope_is_refused_uniformly(human, scope_type, scope):
    api, _ = human
    with pytest.raises(FakePermissionError) as exc:
        api.get_feature_state("others-person", scope_type, scope)
    assert str(exc.value) == "feature scope not found"


@pytest.mark.parametrize(
    "feature,scope_type,scope",
    [
        ("finance", "Workspace", "PSN-ACTOR"),
        ("finance", "person", "PSN-ACTOR"),
        ("finance", None, "PSN-ACTOR"),
        ("finance", ["Person"], "PSN-ACTOR"),
        ("", "Person", "PSN-ACTOR"),
        (None, "Person", "PSN-ACTOR"),
        ("finance", "Person", ""),
        ("finance", "Person", None),
        ("finance", "Person", 7),
    ],
)
def test_invalid_input_is_rejected(human, feature, scope_type, scope):
    api, _ = human
    with pytest.raises(FakePermissionError):
        api.get_feature_state(feature, scope_type, scope)


def test_machine_with_delegation_can_query(api_fa):
    """Default fixture: machine caller + delegated human, accepted audience."""
    api, _ = api_fa
    assert api.get_feature_state("finance", "Person", "PSN-ACTOR")["state"] == "ACTIVE"


def test_machine_with_policy_audience_can_query(api_fa):
    api, fake = api_fa
    fake.local.episteck_delegation_audience = "svc-nutrition"
    assert api.get_feature_state("finance", "Person", "PSN-ACTOR")["state"] == "ACTIVE"


def test_unaccepted_audience_is_refused(api_fa):
    api, fake = api_fa
    fake.local.episteck_delegation_audience = "some-other-audience"
    with pytest.raises(FakePermissionError):
        api.get_feature_state("finance", "Person", "PSN-ACTOR")


def test_machine_without_delegation_is_refused(api_fa):
    api, fake = api_fa
    fake.local.episteck_delegated_user = None
    with pytest.raises(FakePermissionError):
        api.get_feature_state("finance", "Person", "PSN-ACTOR")


def test_guest_is_refused(api_fa):
    api, fake = api_fa
    fake.session.user = "Guest"
    fake.local.episteck_delegated_user = None
    with pytest.raises(FakePermissionError):
        api.get_feature_state("finance", "Person", "PSN-ACTOR")


# ------------------------------------------------------------- DocType sanity


def _doctype():
    return json.loads(DOCTYPE_JSON.read_text(encoding="utf-8"))


def test_doctype_fields_and_requirements():
    fields = {f["fieldname"]: f for f in _doctype()["fields"]}
    assert set(fields) == {
        "feature", "scope_type", "scope", "state",
        "activated_by", "activated_at", "deactivated_at",
    }
    for name in ("feature", "scope_type", "scope", "state"):
        assert fields[name]["reqd"] == 1
    assert fields["scope_type"]["options"] == "Person\nCircle"
    assert fields["scope"]["fieldtype"] == "Dynamic Link"
    assert fields["scope"]["options"] == "scope_type"
    assert fields["state"]["options"] == "ACTIVE\nPAUSED"
    assert fields["state"]["default"] == "PAUSED"
    assert fields["activated_by"]["options"] == "Person"


def test_doctype_permissions_are_admin_only():
    perms = _doctype()["permissions"]
    assert [p["role"] for p in perms] == ["System Manager"]


def test_doctype_json_is_utf8_without_bom():
    assert not DOCTYPE_JSON.read_bytes().startswith(b"\xef\xbb\xbf")
