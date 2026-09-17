"""Trusted-actor Home business API tests using a small in-memory Frappe boundary.

G1.6: the API has NO ``actor_person_id`` parameter. The actor is derived from
authenticated context only, so actor substitution is unrepresentable rather than
merely rejected.
"""
from __future__ import annotations

import importlib
import inspect
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

    def get_value(self, doctype, filters=None, fieldname=None):
        if doctype == "User":
            user = self.frappe.users.get(filters)
            if user is None:
                return None
            return user.get(fieldname)
        if doctype == "Person":
            linked_user = (filters or {}).get("linked_user")
            for person_id, person in self.frappe.people.items():
                if person.get("linked_user") == linked_user:
                    return person_id
            return None
        raise AssertionError(f"unexpected get_value query: {doctype} {filters}")

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
    # Default: the machine service calls with a delegated human session.
    fake.session = SimpleNamespace(user="home-mcp@example.invalid")
    fake.local = SimpleNamespace(
        episteck_delegated_user="person@example.invalid",
        episteck_machine_caller="home-mcp@example.invalid",
    )
    fake.conf = {}
    fake.users = {
        "person@example.invalid": {"enabled": 1},
        "other@example.invalid": {"enabled": 1},
        "home-mcp@example.invalid": {"enabled": 1},
        "disabled@example.invalid": {"enabled": 0},
    }
    fake.people = {
        "PSN-ACTOR": {
            "full_name": "Synthetic Actor",
            "external_ref": None,
            "linked_user": "person@example.invalid",
        },
        "PSN-SUBJECT": {
            "full_name": "Synthetic Subject",
            "external_ref": None,
            "linked_user": None,
        },
        "PSN-OTHER": {
            "full_name": "Unrelated",
            "external_ref": None,
            "linked_user": "other@example.invalid",
        },
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
        if doctype == "Person":
            return [
                {"name": person_id}
                for person_id, person in fake.people.items()
                if all(person.get(key) == value for key, value in filters.items())
            ]
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

    def parse_json(value):
        import json

        return json.loads(value)

    fake.whitelist = whitelist
    fake.throw = throw
    fake.get_doc = get_doc
    fake.get_all = get_all
    fake.parse_json = parse_json
    fake.log_error = lambda *args, **kwargs: None
    return fake


@pytest.fixture
def home_api(monkeypatch):
    fake = _make_fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", fake)
    for module in (
        "episteck_home.policy.wrappers",
        "episteck_home.identity.actor",
        "episteck_home.api",
    ):
        sys.modules.pop(module, None)
    api = importlib.import_module("episteck_home.api")
    monkeypatch.setattr(
        api,
        "_check_access",
        lambda actor, subject, domain, action: {"allow": False, "reason": "no grant"},
    )
    return api, fake


# --------------------------------------------------------------------------
# T-1 / T-2: actor substitution is UNREPRESENTABLE, not merely rejected
# --------------------------------------------------------------------------

WHITELISTED = [
    "check_access",
    "check_access_many",
    "get_person",
    "list_my_circles",
    "list_circle_members",
    "list_people_i_care_for",
    "get_access_to_person",
    "get_care_dashboard",
    "whoami",
]


@pytest.mark.parametrize("method_name", WHITELISTED)
def test_no_business_method_accepts_an_actor_parameter(home_api, method_name):
    """The strongest guarantee: a caller cannot even express an actor."""
    api, _ = home_api
    signature = inspect.signature(getattr(api, method_name))
    assert "actor_person_id" not in signature.parameters
    assert "actor" not in signature.parameters
    assert "user" not in signature.parameters


def test_supplying_an_actor_is_a_type_error(home_api):
    """An agent that tries the old G1.5 shape fails outright."""
    api, _ = home_api
    with pytest.raises(TypeError):
        api.list_my_circles(actor_person_id="PSN-OTHER")
    with pytest.raises(TypeError):
        api.check_access(
            actor_person_id="PSN-OTHER",
            subject_person_id="PSN-SUBJECT",
            domain="NUTRITION",
            action="VIEW",
        )


def test_actor_comes_from_session_not_from_parameters(home_api):
    api, fake = home_api
    assert api.whoami()["actor_person_id"] == "PSN-ACTOR"
    # Change only the delegated session; the actor must follow it.
    fake.local.episteck_delegated_user = "other@example.invalid"
    assert api.whoami()["actor_person_id"] == "PSN-OTHER"


def test_changing_subject_cannot_change_actor(home_api):
    """Parameter fiddling moves the subject, never the actor.

    Discoverable subjects return the fixed actor; undiscoverable ones are denied.
    Either way the actor never becomes the value the caller supplied.
    """
    api, _ = home_api
    for subject in ("PSN-SUBJECT", "PSN-ACTOR"):
        assert api.get_access_to_person(subject)["actor_person_id"] == "PSN-ACTOR"

    # An undiscoverable subject is denied rather than silently acting as them.
    with pytest.raises(FakeDoesNotExistError):
        api.get_access_to_person("PSN-OTHER")


# --------------------------------------------------------------------------
# T-3 / T-4: service credential alone, and wrong session
# --------------------------------------------------------------------------


def test_machine_credential_alone_cannot_impersonate_a_person(home_api):
    """A stolen service key buys no human's data."""
    api, fake = home_api
    fake.local.episteck_delegated_user = None
    fake.session.user = "home-mcp@example.invalid"
    with pytest.raises(FakePermissionError, match="no human actor"):
        api.list_my_circles()


def test_unauthenticated_request_is_denied(home_api):
    api, fake = home_api
    fake.local.episteck_delegated_user = None
    fake.session.user = "Guest"
    with pytest.raises(FakePermissionError, match="authentication required"):
        api.list_my_circles()


def test_wrong_session_acts_only_as_its_own_person(home_api):
    api, fake = home_api
    fake.local.episteck_delegated_user = "other@example.invalid"
    assert api.get_care_dashboard()["actor_person_id"] == "PSN-OTHER"
    # PSN-OTHER is in a different circle and must not see the household roster.
    with pytest.raises(FakeDoesNotExistError):
        api.list_circle_members("CIR-HOME")


# --------------------------------------------------------------------------
# T-9..T-13: unlinked, disabled, ambiguous bindings
# --------------------------------------------------------------------------


def test_user_without_linked_person_cannot_act(home_api):
    api, fake = home_api
    fake.local.episteck_delegated_user = "nobody@example.invalid"
    with pytest.raises(FakePermissionError, match="no human actor"):
        api.list_my_circles()


def test_unlinking_denies_immediately(home_api):
    api, fake = home_api
    assert api.whoami()["actor_person_id"] == "PSN-ACTOR"
    fake.people["PSN-ACTOR"]["linked_user"] = None
    with pytest.raises(FakePermissionError, match="no human actor"):
        api.whoami()


def test_ambiguous_duplicate_linked_user_fails_closed(home_api):
    """Two Persons for one User must DENY, never guess."""
    api, fake = home_api
    fake.people["PSN-DUPLICATE"] = {
        "full_name": "Duplicate Binding",
        "external_ref": None,
        "linked_user": "person@example.invalid",
    }
    with pytest.raises(FakePermissionError, match="no human actor"):
        api.whoami()


def test_person_without_user_can_be_subject_but_never_actor(home_api):
    """Children/dependents: valid subjects, never actors."""
    api, fake = home_api
    assert fake.people["PSN-SUBJECT"]["linked_user"] is None
    # Valid subject: discoverable through the actor's circle.
    assert api.get_person("PSN-SUBJECT")["full_name"] == "Synthetic Subject"
    # Never an actor: no session can resolve to it.
    fake.local.episteck_delegated_user = None
    fake.session.user = "home-mcp@example.invalid"
    with pytest.raises(FakePermissionError):
        api.whoami()


# --------------------------------------------------------------------------
# Dual principal (A6)
# --------------------------------------------------------------------------


def test_dual_principal_retains_both_identities(home_api):
    api, _ = home_api
    principals = api.whoami()["principals"]
    assert principals["human_actor"] == "PSN-ACTOR"
    assert principals["machine_caller"] == "home-mcp@example.invalid"
    assert principals["delegated"] is True


def test_direct_human_session_has_no_machine_caller(home_api):
    """A human logging in directly is not a delegated call."""
    api, fake = home_api
    fake.local.episteck_delegated_user = None
    fake.session.user = "person@example.invalid"
    principals = api.whoami()["principals"]
    assert principals["human_actor"] == "PSN-ACTOR"
    assert principals["machine_caller"] is None
    assert principals["delegated"] is False


# --------------------------------------------------------------------------
# G1.5 behaviour preserved (discovery, scoping, non-disclosure)
# --------------------------------------------------------------------------


def test_get_person_allows_self(home_api):
    api, _ = home_api
    assert api.get_person("PSN-ACTOR")["full_name"] == "Synthetic Actor"


def test_get_person_allows_shared_circle(home_api):
    api, _ = home_api
    assert api.get_person("PSN-SUBJECT")["full_name"] == "Synthetic Subject"


def test_get_person_denies_unrelated_without_loading_it(home_api):
    api, fake = home_api
    with pytest.raises(FakeDoesNotExistError):
        api.get_person("PSN-OTHER")
    assert "PSN-OTHER" not in fake.loaded_person_ids


def test_list_circle_members_requires_actor_membership(home_api):
    api, _ = home_api
    with pytest.raises(FakeDoesNotExistError):
        api.list_circle_members("CIR-OTHER")


def test_list_people_i_care_for_is_scoped_to_actor(home_api):
    api, _ = home_api
    assert api.list_people_i_care_for() == [
        {"person_id": "PSN-SUBJECT", "relationship_type": "CAREGIVER"}
    ]


def test_get_access_to_person_uses_only_resolved_actor(home_api, monkeypatch):
    api, _ = home_api
    seen = []

    def decision(actor, subject, domain, action):
        seen.append((actor, subject, domain, action))
        return {"allow": domain == "NUTRITION" and action == "VIEW", "reason": "x"}

    monkeypatch.setattr(api, "_check_access", decision)
    result = api.get_access_to_person("PSN-SUBJECT")
    assert result["actor_person_id"] == "PSN-ACTOR"
    assert result["access"] == {"NUTRITION": ["VIEW"]}
    assert {actor for actor, _, _, _ in seen} == {"PSN-ACTOR"}


def test_care_dashboard_contains_only_actor_scoped_queries(home_api):
    api, fake = home_api
    fake.get_all_calls.clear()
    result = api.get_care_dashboard()
    assert result["actor_person_id"] == "PSN-ACTOR"
    for doctype, filters in fake.get_all_calls:
        if doctype == "Circle Membership" and "person" in filters:
            assert filters["person"] == "PSN-ACTOR"
        if doctype == "Care Relationship":
            assert filters["caregiver_person"] == "PSN-ACTOR"


def test_check_access_delegates_subject_and_action_unchanged(home_api, monkeypatch):
    """T-14/T-15: subject and domain/action substitution still go through policy."""
    api, _ = home_api
    seen = []
    monkeypatch.setattr(
        api,
        "_check_access",
        lambda a, s, d, act: seen.append((a, s, d, act)) or {"allow": False, "reason": "no"},
    )
    api.check_access("PSN-OTHER", "MIND", "UPDATE")
    assert seen == [("PSN-ACTOR", "PSN-OTHER", "MIND", "UPDATE")]
