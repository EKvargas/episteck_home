"""Several requirements, ONE delegated request (G1.6).

WHY THIS EXISTS
---------------
Delegations are single-use: the replay claim is made once per HTTP request, so a
second ``check_access`` on the same token is refused. An operation that genuinely
needs two permissions — ``ate_as_planned`` reads a plan (VIEW) and then creates an
intake (CREATE) — therefore could not authorize itself at all.

The wrong fixes are (a) weaken replay protection, or (b) ask for only one permission
and write data the actor was not allowed to read. ``check_access_many`` is the third
option: one request, one actor resolution, an exact decision per requirement.

WHAT THIS SUITE GUARDS
----------------------
The dangerous failure mode is an overall ``allow`` that covered FEWER requirements
than the caller asked for. Every malformed-input test below therefore asserts both
that the call is refused AND that no decision was fabricated.
"""
from __future__ import annotations

import importlib
import inspect
import sys

import pytest

from tests.test_home_api_security import _make_fake_frappe

SUBJECT = "PSN-SUBJECT"


@pytest.fixture
def api_with_grants(monkeypatch):
    """The API with a controllable policy layer, and a record of what it was asked."""
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
    allowed: set[tuple] = set()

    def fake_check(actor, subject, domain, action):
        asked.append((actor, subject, domain, action))
        if (domain, action) in allowed:
            return {"allow": True, "reason": f"grant {domain}/{action}"}
        return {"allow": False, "reason": "no matching active grant (fail closed)"}

    monkeypatch.setattr(api, "_check_access", fake_check)
    return api, asked, allowed


# ==========================================================================
# The actor is resolved server-side, once, and is never a parameter
# ==========================================================================


def test_takes_no_actor_parameter(api_with_grants):
    """The trusted-actor invariant: a caller cannot express an actor."""
    api, _, _ = api_with_grants
    params = inspect.signature(api.check_access_many).parameters
    assert "actor_person_id" not in params
    assert "actor" not in params
    assert "user" not in params


def test_supplying_an_actor_is_a_type_error(api_with_grants):
    api, _, _ = api_with_grants
    with pytest.raises(TypeError):
        api.check_access_many(
            SUBJECT, [{"domain": "NUTRITION", "action": "VIEW"}], actor_person_id="PSN-OTHER"
        )


def test_actor_is_resolved_once_for_all_requirements(api_with_grants):
    """One resolution, reused — not one per requirement."""
    api, asked, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")}

    api.check_access_many(
        SUBJECT,
        [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "NUTRITION", "action": "CREATE"},
        ],
    )

    actors = {actor for actor, _, _, _ in asked}
    assert actors == {"PSN-ACTOR"}, actors
    assert len(asked) == 2, "each requirement is decided exactly once"


# ==========================================================================
# Overall allow only when EVERY requirement allows
# ==========================================================================


def test_allows_only_when_every_requirement_allows(api_with_grants):
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")}

    result = api.check_access_many(
        SUBJECT,
        [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "NUTRITION", "action": "CREATE"},
        ],
    )

    assert result["allow"] is True
    assert [d["allow"] for d in result["decisions"]] == [True, True]


def test_one_denied_requirement_denies_the_whole_operation(api_with_grants):
    """A VIEW grant must not let a CREATE through."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}  # CREATE deliberately absent

    result = api.check_access_many(
        SUBJECT,
        [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "NUTRITION", "action": "CREATE"},
        ],
    )

    assert result["allow"] is False
    assert [d["allow"] for d in result["decisions"]] == [True, False]
    assert "fail closed" in result["reason"]


def test_per_requirement_decisions_are_exact(api_with_grants):
    """Each decision names the domain and action it answered."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}

    result = api.check_access_many(
        SUBJECT,
        [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "HEALTH", "action": "VIEW"},
        ],
    )

    assert [(d["domain"], d["action"], d["allow"]) for d in result["decisions"]] == [
        ("NUTRITION", "VIEW", True),
        ("HEALTH", "VIEW", False),
    ]


def test_one_domain_never_implies_another(api_with_grants):
    """A NUTRITION grant does not satisfy a HEALTH requirement."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")}

    result = api.check_access_many(
        SUBJECT,
        [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "HEALTH", "action": "CREATE"},
        ],
    )
    assert result["allow"] is False


# ==========================================================================
# Exact validation, bounded count, fail closed on malformed input
# ==========================================================================


@pytest.mark.parametrize(
    "requirements",
    [
        [{"domain": "NOPE", "action": "VIEW"}],
        [{"domain": "NUTRITION", "action": "DESTROY"}],
        [{"domain": "nutrition", "action": "VIEW"}],  # case must match exactly
        [{"domain": "NUTRITION", "action": "view"}],
        [{"domain": "NUTRITION"}],  # missing action
        [{"action": "VIEW"}],  # missing domain
        [{"domain": None, "action": "VIEW"}],
        [{"domain": "NUTRITION", "action": None}],
        ["NUTRITION/VIEW"],  # not a mapping
        [42],
    ],
    ids=[
        "unknown-domain",
        "unknown-action",
        "lowercase-domain",
        "lowercase-action",
        "missing-action",
        "missing-domain",
        "null-domain",
        "null-action",
        "string-requirement",
        "int-requirement",
    ],
)
def test_malformed_requirement_refuses_the_whole_call(api_with_grants, requirements):
    """Never silently skip an entry: refuse, and fabricate no decisions."""
    api, asked, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")}

    result = api.check_access_many(SUBJECT, requirements)

    assert result["allow"] is False
    assert result["decisions"] == []
    assert "fail closed" in result["reason"]


def test_a_malformed_entry_poisons_an_otherwise_valid_list(api_with_grants):
    """The dangerous case: one bad entry among good ones must not be dropped.

    Skipping it would return allow=True having decided fewer requirements than the
    caller asked for — exactly the outcome this API exists to prevent.
    """
    api, asked, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")}

    result = api.check_access_many(
        SUBJECT,
        [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "NUTRITION", "action": "NOT-AN-ACTION"},
            {"domain": "NUTRITION", "action": "CREATE"},
        ],
    )

    assert result["allow"] is False
    assert result["decisions"] == []
    assert asked == [], "nothing is decided when the list is not wholly valid"


@pytest.mark.parametrize(
    "requirements", [[], None, "", {}, "not-json"], ids=["empty", "none", "blank", "dict", "garbage"]
)
def test_empty_or_unusable_requirements_fail_closed(api_with_grants, requirements):
    api, _, _ = api_with_grants
    result = api.check_access_many(SUBJECT, requirements)
    assert result["allow"] is False
    assert result["decisions"] == []


def test_requirement_count_is_bounded(api_with_grants):
    """A caller cannot turn one delegated request into a permission sweep."""
    api, asked, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}

    too_many = [{"domain": "NUTRITION", "action": "VIEW"}] * (api.MAX_REQUIREMENTS + 1)
    result = api.check_access_many(SUBJECT, too_many)

    assert result["allow"] is False
    assert "maximum" in result["reason"]
    assert asked == [], "an over-long list is refused before any decision"


def test_the_bound_itself_is_usable(api_with_grants):
    """Exactly MAX_REQUIREMENTS is allowed; the bound is not off by one."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}

    result = api.check_access_many(
        SUBJECT, [{"domain": "NUTRITION", "action": "VIEW"}] * api.MAX_REQUIREMENTS
    )
    assert result["allow"] is True
    assert len(result["decisions"]) == api.MAX_REQUIREMENTS


def test_json_encoded_requirements_are_accepted(api_with_grants):
    """Frappe may deliver a JSON body as a string."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}

    result = api.check_access_many(SUBJECT, '[{"domain": "NUTRITION", "action": "VIEW"}]')
    assert result["allow"] is True


def test_malformed_json_string_fails_closed(api_with_grants):
    api, _, _ = api_with_grants
    result = api.check_access_many(SUBJECT, '[{"domain": "NUTRITION",')
    assert result["allow"] is False
    assert result["decisions"] == []


def test_missing_subject_denies_every_requirement(api_with_grants):
    """A blank subject must not become an allow."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}

    result = api.check_access_many("", [{"domain": "NUTRITION", "action": "VIEW"}])
    assert result["allow"] is False


# ==========================================================================
# Deterministic, and never cached
# ==========================================================================


def test_decisions_are_deterministic_for_the_same_input(api_with_grants):
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}
    requirements = [
        {"domain": "NUTRITION", "action": "VIEW"},
        {"domain": "NUTRITION", "action": "CREATE"},
    ]

    first = api.check_access_many(SUBJECT, requirements)
    second = api.check_access_many(SUBJECT, requirements)
    assert first == second


def test_duplicate_requirements_are_each_decided(api_with_grants):
    """No de-duplication that could mask a differing decision."""
    api, asked, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}

    result = api.check_access_many(
        SUBJECT,
        [
            {"domain": "NUTRITION", "action": "VIEW"},
            {"domain": "NUTRITION", "action": "VIEW"},
        ],
    )
    assert len(result["decisions"]) == 2
    assert len(asked) == 2


def test_nothing_is_cached_between_calls(api_with_grants):
    """A grant revoked between calls denies the very next one."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}
    requirements = [{"domain": "NUTRITION", "action": "VIEW"}]

    assert api.check_access_many(SUBJECT, requirements)["allow"] is True

    allowed.discard(("NUTRITION", "VIEW"))  # revoked
    assert api.check_access_many(SUBJECT, requirements)["allow"] is False


def test_policy_is_consulted_for_every_requirement_every_time(api_with_grants):
    """Two calls, two requirements each -> four policy evaluations."""
    api, asked, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")}
    requirements = [
        {"domain": "NUTRITION", "action": "VIEW"},
        {"domain": "NUTRITION", "action": "CREATE"},
    ]

    api.check_access_many(SUBJECT, requirements)
    api.check_access_many(SUBJECT, requirements)
    assert len(asked) == 4


# ==========================================================================
# Parity with the single-requirement API
# ==========================================================================


def test_agrees_with_check_access_for_a_single_requirement(api_with_grants):
    """The many-form must never be more permissive than the one-form."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}

    for domain, action in (
        ("NUTRITION", "VIEW"),
        ("NUTRITION", "CREATE"),
        ("HEALTH", "VIEW"),
    ):
        single = api.check_access(SUBJECT, domain, action)
        many = api.check_access_many(SUBJECT, [{"domain": domain, "action": action}])
        assert many["allow"] == single["allow"], (domain, action)


def test_unauthenticated_caller_is_denied(api_with_grants, monkeypatch):
    """No human actor -> no decision at all."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}
    frappe = sys.modules["frappe"]
    frappe.session.user = "Guest"

    with pytest.raises(Exception):
        api.check_access_many(SUBJECT, [{"domain": "NUTRITION", "action": "VIEW"}])


def test_machine_credential_alone_cannot_decide(api_with_grants):
    """A service credential with no delegated human session resolves no actor."""
    api, _, allowed = api_with_grants
    allowed |= {("NUTRITION", "VIEW")}
    frappe = sys.modules["frappe"]
    frappe.local.episteck_delegated_user = None
    frappe.session.user = "home-mcp@example.invalid"

    with pytest.raises(Exception):
        api.check_access_many(SUBJECT, [{"domain": "NUTRITION", "action": "VIEW"}])
