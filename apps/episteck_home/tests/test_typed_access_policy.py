"""KAP-2 pure evaluator: trusted snapshots only, no Frappe or endpoint wiring."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from episteck_home.policy.typed_access import (
    AccessRequirement,
    Actor,
    TypedGrant,
    TypedTarget,
    evaluate_operation,
)


NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
PERSON = TypedTarget("partition-a", "PERSON", "p1")
CIRCLE = TypedTarget("partition-a", "CIRCLE", "c1")


def req(kind="PERSON", identity="p1", domain="KNOWLEDGE", action="VIEW"):
    return AccessRequirement(kind, identity, domain, action)


def grant(kind="PERSON", identity="p1", **changes):
    row = TypedGrant(
        partition_id="partition-a",
        actor_person_id="actor",
        resource_type=kind,
        resource_id=identity,
        domain="KNOWLEDGE",
        actions=frozenset({"VIEW"}),
        state="ACTIVE",
        issuer_verified=True,
        dependency_current=True,
    )
    return replace(row, **changes)


def decide(requirements, *, actor=Actor("partition-a", "actor"), targets=(PERSON, CIRCLE), grants=()):
    return evaluate_operation(
        partition_id="partition-a",
        actor=actor,
        requirements=requirements,
        targets=targets,
        grants=grants,
        now=NOW,
    )


def test_person_self_access_requires_existing_same_partition_target():
    own = TypedTarget("partition-a", "PERSON", "actor")
    assert decide((req(identity="actor"),), targets=(own,)).allow
    assert not decide((req(identity="actor"),), targets=()).allow
    assert not decide((req(identity="actor"),), targets=(replace(own, partition_id="partition-b"),)).allow


def test_circle_same_id_never_self_authorizes_and_membership_care_are_not_inputs():
    circle = TypedTarget("partition-a", "CIRCLE", "actor")
    assert not decide((req("CIRCLE", "actor"),), targets=(circle,)).allow
    assert not decide((req("CIRCLE", "c1"),), grants=()).allow


def test_explicit_current_grant_is_scoped_to_actor_target_domain_action_and_partition():
    assert decide((req(),), grants=(grant(),)).allow
    assert not decide((req(action="UPDATE"),), grants=(grant(),)).allow
    assert not decide((req(domain="HEALTH"),), grants=(grant(),)).allow
    assert not decide((req(identity="p2"),), targets=(PERSON, TypedTarget("partition-a", "PERSON", "p2")), grants=(grant(),)).allow
    assert not decide((req(),), grants=(grant(actor_person_id="someone-else"),)).allow
    assert not decide((req(),), grants=(grant(partition_id="partition-b"),)).allow
    assert not decide((req(),), actor=Actor("partition-b", "actor"), grants=(grant(),)).allow


def test_unproven_issuer_legacy_and_ended_dependency_are_quarantined():
    for row in (
        grant(issuer_verified=False),
        grant(dependency_current=False),
        grant(legacy=True),
        grant(state="REVOKED"),
        grant(valid_from=NOW + timedelta(seconds=1)),
        grant(valid_until=NOW - timedelta(seconds=1)),
    ):
        assert not decide((req(),), grants=(row,)).allow
    assert decide((req(),), grants=(grant(legacy=True, legacy_reauthorized=True),)).allow


def test_circle_stewardship_grant_is_explicit_and_dependency_bound():
    steward = grant("CIRCLE", "c1", actions=frozenset({"MANAGE"}))
    assert decide((req("CIRCLE", "c1", action="VIEW"),), grants=(steward,)).allow
    assert not decide((req("CIRCLE", "c1", action="VIEW"),), grants=(replace(steward, dependency_current=False),)).allow
    assert not decide((req("CIRCLE", "c1", domain="HEALTH"),), grants=(steward,)).allow


def test_whole_operation_requires_every_resource_and_domain_tuple():
    requirements = (req("CIRCLE", "c1"), req("PERSON", "p1"), req("PERSON", "p1", "HEALTH"))
    rows = (grant("CIRCLE", "c1"), grant("PERSON", "p1"), grant("PERSON", "p1", domain="HEALTH"))
    assert decide(requirements, grants=rows).allow
    assert not decide(requirements, grants=rows[:-1]).allow
    assert not decide(requirements, grants=rows[:-1] + (grant("PERSON", "p1", domain="HEALTH", state="REVOKED"),)).allow


def test_malformed_or_ambiguous_trusted_snapshot_fails_closed():
    assert not decide((), grants=(grant(),)).allow
    assert not decide((req(kind="DOCUMENT"),), grants=(grant(),)).allow
    assert not decide((req(domain="UNKNOWN"),), grants=(grant(),)).allow
    assert not decide((req(),), targets=(PERSON, PERSON), grants=(grant(),)).allow
    assert not decide((req(),), targets=(replace(PERSON, active=False),), grants=(grant(),)).allow
    assert not decide((req(),), grants=(grant(actions=frozenset({"MANAGE", "UNKNOWN"})),)).allow


def test_non_boolean_legacy_values_never_bypass_quarantine():
    for malformed in (1, 0, "false", None):
        assert not decide((req(),), grants=(grant(legacy=malformed),)).allow
        assert not decide((req(),), grants=(grant(legacy=malformed, legacy_reauthorized=True),)).allow
        assert not decide((req(),), grants=(grant(legacy=True, legacy_reauthorized=malformed),)).allow
    assert not decide((req(),), grants=(grant(issuer_verified=1),)).allow
    assert not decide((req(),), grants=(grant(dependency_current=1),)).allow


def test_malformed_snapshot_values_deny_without_exception():
    malformed_cases = (
        {"actor": Actor("partition-a", [])},
        {"actor": Actor([], "actor")},
        {"targets": (replace(PERSON, resource_type=[]),)},
        {"targets": (replace(PERSON, resource_id=[]),)},
        {"requirements": (req(domain=[]),)},
        {"requirements": (req(identity=[]),)},
        {"grants": (grant(actions=1),)},
        {"grants": (grant(actions=[["VIEW"]]),)},
        {"grants": (grant(valid_from="yesterday"),)},
    )
    for changes in malformed_cases:
        options = {"actor": Actor("partition-a", "actor"), "targets": (PERSON,), "grants": (grant(),)}
        options.update(changes)
        requirements = options.pop("requirements", (req(),))
        assert not decide(requirements, **options).allow
