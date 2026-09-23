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


class FakeValidationError(Exception):
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
    fake.ValidationError = FakeValidationError
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
    # Home Delegated Session rows, keyed by session id. Shape mirrors
    # test_auth_hook.py's fake.sessions so the reused auth_hook._user_for_session
    # helper works unmodified against this fixture.
    fake.home_delegated_sessions = {
        "sess-actor": {
            "user": "person@example.invalid",
            "status": "Active",
            "expires_at": None,
        },
    }
    fake.loaded_person_ids = []
    fake.get_all_calls = []
    fake.db = FakeDatabase(fake)
    fake.utils = SimpleNamespace(today=lambda: "2026-09-15", now=lambda: "2026-09-15 12:00:00")
    fake.get_request_header = lambda name: None

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

    def _matches(row, filters):
        for key, value in filters.items():
            if isinstance(value, (list, tuple)) and len(value) == 2 and value[0] == "in":
                if row.get(key) not in value[1]:
                    return False
            elif row.get(key) != value:
                return False
        return True

    def get_all(doctype, filters=None, fields=None, **kwargs):
        filters = filters or {}
        fake.get_all_calls.append((doctype, dict(filters)))
        if doctype == "Person":
            fields = fields or ["name"]
            return [
                {field: ({"name": person_id, **person}).get(field) for field in fields}
                for person_id, person in fake.people.items()
                if _matches({"name": person_id, **person}, filters)
            ]
        if doctype == "Circle Membership":
            return [
                {field: row.get(field) for field in fields}
                for row in fake.memberships
                if _matches(row, filters)
            ]
        if doctype == "Care Relationship":
            return [
                {field: row.get(field) for field in fields}
                for row in fake.care_relationships
                if _matches(row, filters)
            ]
        if doctype == "Home Delegated Session":
            row = fake.home_delegated_sessions.get(filters.get("name"))
            if not row or row["status"] != filters.get("status"):
                return []
            return [{"user": row["user"], "expires_at": row["expires_at"]}]
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
        "episteck_home.identity.auth_hook",
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
    "get_home_bootstrap",
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


# --------------------------------------------------------------------------
# get_home_bootstrap: F2a-CP (HOME_HUB_F2_SESSION_BOOTSTRAP_PLAN.md §12, CP-1..CP-12)
#
# session_id is an opaque selector, never identity/authority. The authenticated
# OAuth user (frappe.session.user) is authoritative; the CP verifies the selected
# Home Delegated Session belongs to that user, is Active, unexpired, and its User
# is enabled, reusing auth_hook._user_for_session. It then derives the actor from
# that SAME validated session_user (identity.actor._person_for_user), not from
# resolve_actor()/resolve_principals() (see the security-review regression tests
# below for why), and composes only the existing _circles_for / _care_for
# helpers. No grants, no access evaluation.
# --------------------------------------------------------------------------


@pytest.fixture
def bootstrap_direct_session(home_api):
    """Direct human bearer call: the actor's own session, no delegation header."""
    api, fake = home_api
    fake.session.user = "person@example.invalid"
    fake.local.episteck_delegated_user = None
    fake.local.episteck_machine_caller = None
    return api, fake


def test_own_active_session_returns_viewer_circles_and_care(bootstrap_direct_session):
    """CP-1."""
    api, _ = bootstrap_direct_session
    result = api.get_home_bootstrap("sess-actor")
    assert result == {
        "viewer": {"person_id": "PSN-ACTOR", "display_name": "Synthetic Actor"},
        "circles": [{"circle_id": "CIR-HOME", "display_name": "Synthetic Household"}],
        "care": [
            {
                "person_id": "PSN-SUBJECT",
                "display_name": "Synthetic Subject",
                "relationship_type": "CAREGIVER",
            }
        ],
    }


def test_another_users_session_id_is_denied(bootstrap_direct_session):
    """CP-2: a session that exists but belongs to someone else."""
    api, fake = bootstrap_direct_session
    fake.home_delegated_sessions["sess-other"] = {
        "user": "other@example.invalid",
        "status": "Active",
        "expires_at": None,
    }
    with pytest.raises(FakePermissionError):
        api.get_home_bootstrap("sess-other")


def test_revoked_session_is_denied(bootstrap_direct_session):
    """CP-3."""
    api, fake = bootstrap_direct_session
    fake.home_delegated_sessions["sess-actor"]["status"] = "Revoked"
    with pytest.raises(FakePermissionError):
        api.get_home_bootstrap("sess-actor")


def test_expired_session_is_denied(bootstrap_direct_session):
    """CP-4."""
    api, fake = bootstrap_direct_session
    fake.home_delegated_sessions["sess-actor"]["expires_at"] = "2000-01-01 00:00:00"
    with pytest.raises(FakePermissionError):
        api.get_home_bootstrap("sess-actor")


def test_disabled_user_is_denied(bootstrap_direct_session):
    """CP-5."""
    api, fake = bootstrap_direct_session
    fake.users["person@example.invalid"]["enabled"] = 0
    with pytest.raises(FakePermissionError):
        api.get_home_bootstrap("sess-actor")


def test_unlinked_actor_is_denied(bootstrap_direct_session):
    """CP-6: session itself is valid, but the User has no linked Person."""
    api, fake = bootstrap_direct_session
    fake.people["PSN-ACTOR"]["linked_user"] = None
    with pytest.raises(FakePermissionError):
        api.get_home_bootstrap("sess-actor")


def test_ambiguous_actor_link_is_denied(bootstrap_direct_session):
    """CP-6: two Persons linked to the same User fails closed."""
    api, fake = bootstrap_direct_session
    fake.people["PSN-ACTOR-2"] = {
        "full_name": "Duplicate",
        "external_ref": None,
        "linked_user": "person@example.invalid",
    }
    with pytest.raises(FakePermissionError):
        api.get_home_bootstrap("sess-actor")


def test_missing_session_id_is_denied(bootstrap_direct_session):
    """Unknown session id collapses to the same refusal as revoked/foreign."""
    api, _ = bootstrap_direct_session
    with pytest.raises(FakePermissionError):
        api.get_home_bootstrap("sess-does-not-exist")


def test_get_home_bootstrap_takes_no_actor_parameter(home_api):
    """CP-7: the signature itself is the control."""
    api, _ = home_api
    signature = inspect.signature(api.get_home_bootstrap)
    assert set(signature.parameters) == {"session_id"}


def test_get_home_bootstrap_never_evaluates_policy(bootstrap_direct_session, monkeypatch):
    """CP-8: no grant/access evaluation, and no access-shaped keys in the response."""
    api, _ = bootstrap_direct_session
    calls = []
    monkeypatch.setattr(
        api,
        "_check_access",
        lambda *a, **k: calls.append(a) or {"allow": False, "reason": "unused"},
    )
    result = api.get_home_bootstrap("sess-actor")
    assert calls == []
    assert "access" not in result
    assert "grants" not in result


def test_circle_co_member_without_care_is_not_a_person_context(bootstrap_direct_session):
    """CP-9: a Person who SHARES the actor's Circle but has no active Care
    Relationship with the actor must not appear as a PERSON/care context.
    Circle co-membership alone never grants bootstrap visibility.
    """
    api, fake = bootstrap_direct_session
    fake.people["PSN-COMEMBER"] = {
        "full_name": "Circle Co-member",
        "external_ref": None,
        "linked_user": None,
    }
    fake.memberships.append(
        {"circle": "CIR-HOME", "person": "PSN-COMEMBER", "role_in_circle": "member"}
    )
    # Deliberately no Care Relationship for PSN-COMEMBER.

    result = api.get_home_bootstrap("sess-actor")

    care_ids = {row["person_id"] for row in result["care"]}
    assert "PSN-COMEMBER" not in care_ids
    # The legitimate care subject (also a CIR-HOME co-member, but WITH an active
    # Care Relationship) still appears normally -- co-membership isn't what's
    # being excluded here, the absence of a care relationship is.
    assert "PSN-SUBJECT" in care_ids
    # Circles never carry a member list or any Person expansion at all.
    for circle in result["circles"]:
        assert "members" not in circle
        assert set(circle) == {"circle_id", "display_name"}


def test_care_row_outside_validity_window_is_excluded(bootstrap_direct_session):
    """CP-10."""
    api, fake = bootstrap_direct_session
    fake.people["PSN-EXPIRED"] = {
        "full_name": "Expired Subject",
        "external_ref": None,
        "linked_user": None,
    }
    fake.care_relationships.append(
        {
            "caregiver_person": "PSN-ACTOR",
            "subject_person": "PSN-EXPIRED",
            "relationship_type": "CAREGIVER",
            "valid_from": None,
            "valid_to": "2020-01-01",
        }
    )
    result = api.get_home_bootstrap("sess-actor")
    care_ids = {row["person_id"] for row in result["care"]}
    assert "PSN-EXPIRED" not in care_ids


def test_response_excludes_sensitive_fields(bootstrap_direct_session):
    """CP-11: no external_ref, User.name/email, principals, or validity dates."""
    api, _ = bootstrap_direct_session
    result = api.get_home_bootstrap("sess-actor")
    assert set(result) == {"viewer", "circles", "care"}
    assert set(result["viewer"]) == {"person_id", "display_name"}
    for circle in result["circles"]:
        assert set(circle) == {"circle_id", "display_name"}
    for care_row in result["care"]:
        assert set(care_row) == {"person_id", "display_name", "relationship_type"}


def test_over_fifty_circles_is_a_validation_error(bootstrap_direct_session):
    """CP-12."""
    api, fake = bootstrap_direct_session
    for i in range(51):
        circle_id = f"CIR-{i:03d}"
        fake.circles[circle_id] = {"title": f"Circle {i}", "circle_type": "HOUSEHOLD"}
        fake.memberships.append(
            {"circle": circle_id, "person": "PSN-ACTOR", "role_in_circle": "member"}
        )
    with pytest.raises(FakeValidationError):
        api.get_home_bootstrap("sess-actor")


def test_over_fifty_care_rows_is_a_validation_error(bootstrap_direct_session):
    """CP-12."""
    api, fake = bootstrap_direct_session
    for i in range(51):
        subject_id = f"PSN-CARE-{i:03d}"
        fake.people[subject_id] = {
            "full_name": f"Subject {i}",
            "external_ref": None,
            "linked_user": None,
        }
        fake.care_relationships.append(
            {
                "caregiver_person": "PSN-ACTOR",
                "subject_person": subject_id,
                "relationship_type": "CAREGIVER",
                "valid_from": None,
                "valid_to": None,
            }
        )
    with pytest.raises(FakeValidationError):
        api.get_home_bootstrap("sess-actor")


def test_all_bootstrap_refusals_share_one_message(bootstrap_direct_session):
    """Anti-oracle: foreign session, revoked, expired, disabled user, and
    unlinked/ambiguous Person all raise the identical PermissionError text, so a
    direct caller cannot distinguish any refusal reason from any other.
    """
    api, fake = bootstrap_direct_session

    def refusal_message(mutate):
        local_fake = _make_fake_frappe()
        local_fake.session.user = "person@example.invalid"
        local_fake.local.episteck_delegated_user = None
        local_fake.local.episteck_machine_caller = None
        mutate(local_fake)
        import sys as _sys

        _sys.modules["frappe"] = local_fake
        for mod in (
            "episteck_home.policy.wrappers",
            "episteck_home.identity.actor",
            "episteck_home.identity.auth_hook",
            "episteck_home.api",
        ):
            _sys.modules.pop(mod, None)
        local_api = importlib.import_module("episteck_home.api")
        try:
            local_api.get_home_bootstrap("sess-actor")
        except FakePermissionError as error:
            return str(error)
        raise AssertionError("expected a refusal")

    messages = {
        refusal_message(lambda f: f.home_delegated_sessions.pop("sess-actor")),
        refusal_message(
            lambda f: f.home_delegated_sessions["sess-actor"].__setitem__(
                "status", "Revoked"
            )
        ),
        refusal_message(
            lambda f: f.home_delegated_sessions["sess-actor"].__setitem__(
                "expires_at", "2000-01-01 00:00:00"
            )
        ),
        refusal_message(lambda f: f.users["person@example.invalid"].__setitem__("enabled", 0)),
        refusal_message(lambda f: f.people["PSN-ACTOR"].__setitem__("linked_user", None)),
    }
    assert len(messages) == 1


def test_dangling_care_subject_person_fails_closed_not_with_a_keyerror(
    bootstrap_direct_session,
):
    """A Care Relationship pointing at a Person id that no longer exists must not
    surface as a raw, unhandled KeyError. Every other failure path in this module
    raises a typed, sanitized Frappe exception; this one should too.
    """
    api, fake = bootstrap_direct_session
    fake.care_relationships.append(
        {
            "caregiver_person": "PSN-ACTOR",
            "subject_person": "PSN-GHOST",
            "relationship_type": "CAREGIVER",
            "valid_from": None,
            "valid_to": None,
        }
    )
    # PSN-GHOST is deliberately absent from fake.people (orphaned reference).
    with pytest.raises(FakeDoesNotExistError):
        api.get_home_bootstrap("sess-actor")


def test_bootstrap_ignores_a_stray_delegation_header_and_uses_the_session_owner(
    bootstrap_direct_session,
):
    """A caller who legitimately owns ``sess-actor`` (PSN-ACTOR) but also carries an
    ambient/stray delegation binding to a DIFFERENT person must still get their own
    bootstrap, never the delegated person's. ``session_id`` ownership and the
    returned identity must derive from the SAME validated principal
    (``session_user``), not from two independently-resolved ones.

    Regression for the actor/session-identity mismatch found in code review:
    resolve_actor() prefers frappe.local.episteck_delegated_user over
    frappe.session.user whenever a delegation header was presented, which let a
    stray header substitute a different person's data into this caller's own,
    already-validated session.
    """
    api, fake = bootstrap_direct_session
    # A delegation header was (mis)routed to this request, binding a DIFFERENT
    # person's User than the one that owns sess-actor.
    fake.local.episteck_delegated_user = "other@example.invalid"
    fake.local.episteck_machine_caller = "home-mcp@example.invalid"

    result = api.get_home_bootstrap("sess-actor")

    assert result["viewer"]["person_id"] == "PSN-ACTOR"
