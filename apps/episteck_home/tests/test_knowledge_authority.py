"""Disconnected Knowledge activation tests; no Frappe endpoint is registered."""

from dataclasses import replace
from datetime import datetime, timezone

from episteck_home.knowledge_authority.policy import (
    Activation, GrantEvidence, KnowledgeSnapshot, SelfActivation, evaluate_current,
)
from episteck_home.policy.typed_access import (
    AccessRequirement, Actor, TypedGrant, TypedTarget,
)


NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


class Witness:
    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.calls = []

    def authorize(self, partition, incarnation, revision, digest):
        self.calls.append((partition, incarnation, revision, digest))
        return self.allowed


def snapshot():
    grant = TypedGrant(
        partition_id="p1", actor_person_id="actor", resource_type="PERSON",
        resource_id="subject", domain="KNOWLEDGE", actions=frozenset({"VIEW"}),
        state="ACTIVE", issuer_verified=True, dependency_current=True, legacy=True,
    )
    return KnowledgeSnapshot(
        partition_id="p1", incarnation="inc-new", revision=1, digest="digest-1",
        actor=Actor("p1", "actor"),
        requirements=(AccessRequirement("PERSON", "subject", "KNOWLEDGE", "VIEW"),),
        targets=(TypedTarget("p1", "PERSON", "subject"),),
        grants=(GrantEvidence("grant-1", "subject", grant),),
        activations=(), self_activations=(), now=NOW,
    )


def activation(incarnation="inc-new"):
    return Activation(
        incarnation=incarnation, partition_id="p1", actor_person_id="actor",
        resource_type="PERSON", resource_id="subject", domain="KNOWLEDGE",
        actions=frozenset({"VIEW"}), source_grant_id="grant-1",
        issuer_person_id="subject", event_id="event-1",
    )


def test_old_grants_are_quarantined_until_current_authenticated_reauthorization():
    old = snapshot()
    witness = Witness()
    assert not evaluate_current(old, witness).allow
    assert witness.calls == [("p1", "inc-new", 1, "digest-1")]
    assert not evaluate_current(replace(old, activations=(activation("inc-old"),)), Witness()).allow
    assert evaluate_current(replace(old, activations=(activation(),)), Witness()).allow


def test_issuer_dependency_and_source_grant_invalidation():
    valid = replace(snapshot(), activations=(activation(),))
    assert not evaluate_current(replace(valid, activations=(replace(activation(), issuer_person_id="other"),)), Witness()).allow
    assert not evaluate_current(replace(valid, grants=(replace(valid.grants[0], issuer_person_id="other"),)), Witness()).allow
    assert not evaluate_current(replace(valid, grants=(replace(valid.grants[0], grant=replace(valid.grants[0].grant, dependency_current=False)),)), Witness()).allow
    assert not evaluate_current(replace(valid, grants=(replace(valid.grants[0], grant=replace(valid.grants[0].grant, state="REVOKED")),)), Witness()).allow
    assert not evaluate_current(replace(valid, grants=(replace(valid.grants[0], grant_id="different"),)), Witness()).allow


def test_partition_binding_and_whole_operation_and_semantics():
    valid = replace(snapshot(), activations=(activation(),))
    assert not evaluate_current(replace(valid, actor=Actor("p2", "actor")), Witness()).allow
    assert not evaluate_current(replace(valid, targets=(TypedTarget("p2", "PERSON", "subject"),)), Witness()).allow
    assert not evaluate_current(replace(valid, activations=(replace(activation(), partition_id="p2"),)), Witness()).allow
    extra = AccessRequirement("CIRCLE", "circle", "KNOWLEDGE", "VIEW")
    both = replace(valid, requirements=valid.requirements + (extra,),
                   targets=valid.targets + (TypedTarget("p1", "CIRCLE", "circle"),))
    assert not evaluate_current(both, Witness()).allow


def test_person_self_activation_only_and_no_circle_self_inference():
    own = replace(snapshot(),
                  requirements=(AccessRequirement("PERSON", "actor", "KNOWLEDGE", "VIEW"),),
                  targets=(TypedTarget("p1", "PERSON", "actor"),), grants=(), activations=())
    assert not evaluate_current(own, Witness()).allow
    active = SelfActivation("inc-new", "p1", "actor", "KNOWLEDGE", "VIEW", "event-self")
    assert evaluate_current(replace(own, self_activations=(active,)), Witness()).allow
    assert not evaluate_current(replace(own, self_activations=(replace(active, incarnation="old"),)), Witness()).allow
    circle = replace(own, requirements=(AccessRequirement("CIRCLE", "actor", "KNOWLEDGE", "VIEW"),),
                     targets=(TypedTarget("p1", "CIRCLE", "actor"),))
    assert not evaluate_current(replace(circle, self_activations=(active,)), Witness()).allow


def test_witness_denial_or_malformed_snapshot_fails_closed():
    valid = replace(snapshot(), activations=(activation(),))
    assert not evaluate_current(valid, Witness(False)).allow
    assert not evaluate_current(replace(valid, revision=True), Witness()).allow
    assert not evaluate_current(replace(valid, activations=(replace(activation(), actions=["VIEW"]),)), Witness()).allow
    assert not evaluate_current(replace(valid, activations=(activation(), object())), Witness()).allow
    self_row = SelfActivation("inc-new", "p1", "actor", "KNOWLEDGE", "VIEW", "event-self")
    assert not evaluate_current(replace(valid, self_activations=(self_row, object())), Witness()).allow
