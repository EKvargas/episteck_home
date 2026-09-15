"""Actor-aware Home business API tests using a small in-memory Frappe boundary."""
from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pytest


class FakePermissionError(Exception):
    pass


class FakeDoesNotExistError(Exception):
    pass


class FakeDatabase:
    def __init__(self, frappe_module):
        self.frappe = frappe_module

    def get_value(self, doctype, filters, fieldname):
        assert doctype == "Person"
        assert fieldname == "name"
        linked_user = filters.get("linked_user")
        for person_id, person in self.frappe.people.items():
            if person.get("linked_user") == linked_user:
                return person_id
        return None

    def exists(self, doctype, filters):
        if doctype == "Person":
            return filters in self.frappe.people
        if doctype == "Circle Membership":
            return any(
                membership["circle"] == filters["circle"]
                and membership["person"] == filters["person"]
                for membership in self.frappe.memberships
            )
        raise AssertionError(f"unexpected exists query: {doctype} {filters}")


def _make_fake_frappe():
    fake = types.ModuleType("frappe")
    fake.PermissionError = FakePermissionError
    fake.DoesNotExistError = FakeDoesNotExistError
    fake.session = SimpleNamespace(user="home-mcp@example.invalid")
    fake.conf = {"home_control_plane_service_users": ["home-mcp@example.invalid"]}
    fake.people = {
        "PSN-ACTOR": {"full_name": "Synthetic Actor", "external_ref": None, "linked_user": None},
        "PSN-SUBJECT": {"full_name": "Synthetic Subject", "external_ref": None, "linked_user": None},
        "PSN-OTHER": {"full_name": "Unrelated", "external_ref": None, "linked_user": None},
    }
    fake.memberships = [
        {"circle": "CIR-HOME", "person": "PSN-ACTOR", "role_in_circle": "member"},
        {"circle": "CIR-HOME", "person": "PSN-SUBJECT", "role_in_circle": "member"},
        {"circle": "CIR-OTHER", "person": "PSN-OTHER", "role_in_circle": "member"},
    ]
    fake.circles = {
        "CIR-HOME": {"title": "Synthetic Household", "circle_type": "HOUSEHOLD"},
        "CIR-OTHER": {"title": "Other", "circle_type": "HOUSEHOLD"},
    }
    fake.care_relationships = [
        {
            "caregiver_person": "PSN-ACTOR",
            "subject_person": "PSN-SUBJECT",
            "relationship_type": "CAREGIVER",
            "valid_from": None,
            "valid_to": None,
        }
    ]
    fake.loaded_person_ids = []
    fake.get_all_calls = []
    fake.db = FakeDatabase(fake)
    fake.utils = SimpleNamespace(today=lambda: "2026-09-15")

    def whitelist(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda function: function

    def throw(message, exception=None):
        raise (exception or RuntimeError)(message)

    def get_doc(doctype, name):
        if doctype == "Person":
            fake.loaded_person_ids.append(name)
            person = fake.people[name]
            return SimpleNamespace(name=name, **person)
        if doctype == "Circle":
            circle = fake.circles[name]
            return SimpleNamespace(name=name, **circle)
        raise AssertionError(f"unexpected document load: {doctype} {name}")

    def get_all(doctype, filters=None, fields=None, **kwargs):
        filters = filters or {}
        fake.get_all_calls.append((doctype, dict(filters)))
        if doctype == "Circle Membership":
            return [
                {field: row.get(field) for field in fields}
                for row in fake.memberships
                if all(row.get(key) == value for key, value in filters.items())
            ]
        if doctype == "Care Relationship":
            return [
                {field: row.get(field) for field in fields}
                for row in fake.care_relationships
                if all(row.get(key) == value for key, value in filters.items())
            ]
        if doctype == "Consent Grant":
            return []
        raise AssertionError(f"unexpected get_all query: {doctype} {filters}")

    fake.whitelist = whitelist
    fake.throw = throw
    fake.get_doc = get_doc
    fake.get_all = get_all
    fake.log_error = lambda *args, **kwargs: None
    return fake


@pytest.fixture
def home_api(monkeypatch):
    fake = _make_fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("episteck_home.policy.wrappers", None)
    sys.modules.pop("episteck_home.api", None)
    api = importlib.import_module("episteck_home.api")
    monkeypatch.setattr(
        api,
        "_check_access",
        lambda actor, subject, domain, action: {"allow": False, "reason": "no grant"},
    )
    return api, fake


def test_machine_actor_requires_allowlisted_unlinked_user(home_api):
    api, fake = home_api
    fake.session.user = "unknown-service@example.invalid"
    with pytest.raises(FakePermissionError, match="actor binding required"):
        api.list_my_circles(actor_person_id="PSN-ACTOR")


def test_linked_human_cannot_claim_another_actor(home_api):
    api, fake = home_api
    fake.session.user = "person@example.invalid"
    fake.people["PSN-ACTOR"]["linked_user"] = fake.session.user
    with pytest.raises(FakePermissionError, match="actor mismatch"):
        api.list_my_circles(actor_person_id="PSN-SUBJECT")


def test_get_person_allows_self(home_api):
    api, fake = home_api
    result = api.get_person("PSN-ACTOR", actor_person_id="PSN-ACTOR")
    assert result["full_name"] == "Synthetic Actor"
    assert fake.loaded_person_ids == ["PSN-ACTOR"]


def test_get_person_allows_shared_circle_context(home_api):
    api, fake = home_api
    result = api.get_person("PSN-SUBJECT", actor_person_id="PSN-ACTOR")
    assert result["person_id"] == "PSN-SUBJECT"
    assert fake.loaded_person_ids == ["PSN-SUBJECT"]


def test_get_person_denies_unrelated_before_loading_person(home_api):
    api, fake = home_api
    with pytest.raises(FakeDoesNotExistError, match="Person not found"):
        api.get_person("PSN-OTHER", actor_person_id="PSN-ACTOR")
    assert fake.loaded_person_ids == []


def test_list_circle_members_requires_actor_membership_before_member_query(home_api):
    api, fake = home_api
    with pytest.raises(FakeDoesNotExistError, match="Circle not found"):
        api.list_circle_members("CIR-OTHER", actor_person_id="PSN-ACTOR")
    assert ("Circle Membership", {"circle": "CIR-OTHER"}) not in fake.get_all_calls


def test_list_people_i_care_for_is_scoped_to_actor(home_api):
    api, _ = home_api
    assert api.list_people_i_care_for(actor_person_id="PSN-ACTOR") == [
        {"person_id": "PSN-SUBJECT", "relationship_type": "CAREGIVER"}
    ]


def test_get_access_to_person_uses_only_resolved_actor(home_api, monkeypatch):
    api, _ = home_api
    seen = []

    def decision(actor, subject, domain, action):
        seen.append((actor, subject, domain, action))
        return {"allow": domain == "NUTRITION" and action == "VIEW", "reason": "synthetic"}

    monkeypatch.setattr(api, "_check_access", decision)
    result = api.get_access_to_person("PSN-SUBJECT", actor_person_id="PSN-ACTOR")
    assert result["actor_person_id"] == "PSN-ACTOR"
    assert result["access"] == {"NUTRITION": ["VIEW"]}
    assert all(call[0] == "PSN-ACTOR" for call in seen)


def test_care_dashboard_contains_only_actor_scoped_queries(home_api):
    api, fake = home_api
    result = api.get_care_dashboard(actor_person_id="PSN-ACTOR")
    assert result["actor_person_id"] == "PSN-ACTOR"
    assert result["caring_for"] == [
        {"person_id": "PSN-SUBJECT", "relationship_type": "CAREGIVER"}
    ]
    assert all(
        filters.get("person") == "PSN-ACTOR" or filters.get("caregiver_person") == "PSN-ACTOR"
        for doctype, filters in fake.get_all_calls
        if doctype in {"Circle Membership", "Care Relationship"}
    )
