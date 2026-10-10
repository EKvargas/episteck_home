"""Current-incarnation activation overlay for the reviewed typed evaluator.

Inputs must come from a guarded Home snapshot, not a runtime request. In
particular, a legacy Consent Grant never supplies its own activation evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from episteck_home.policy.access import Decision
from episteck_home.policy.typed_access import (
    AccessRequirement, Actor, TypedGrant, TypedTarget, evaluate_operation,
)


class WitnessReader(Protocol):
    def authorize(self, partition: str, incarnation: str, revision: int, digest: str) -> bool: ...


@dataclass(frozen=True)
class GrantEvidence:
    grant_id: str
    issuer_person_id: str
    grant: TypedGrant


@dataclass(frozen=True)
class Activation:
    incarnation: str
    partition_id: str
    actor_person_id: str
    resource_type: str
    resource_id: str
    domain: str
    actions: frozenset[str]
    source_grant_id: str
    issuer_person_id: str
    event_id: str


@dataclass(frozen=True)
class SelfActivation:
    incarnation: str
    partition_id: str
    person_id: str
    domain: str
    action: str
    event_id: str


@dataclass(frozen=True)
class KnowledgeSnapshot:
    partition_id: str
    incarnation: str
    revision: int
    digest: str
    actor: Actor
    requirements: tuple[AccessRequirement, ...]
    targets: tuple[TypedTarget, ...]
    grants: tuple[GrantEvidence, ...]
    activations: tuple[Activation, ...]
    self_activations: tuple[SelfActivation, ...]
    now: datetime


def _activation_matches(activation: Activation, evidence: GrantEvidence,
                        snapshot: KnowledgeSnapshot) -> bool:
    grant = evidence.grant
    return (
        isinstance(activation, Activation)
        and type(activation.incarnation) is str and activation.incarnation == snapshot.incarnation
        and type(activation.partition_id) is str and activation.partition_id == snapshot.partition_id
        and type(activation.actor_person_id) is str and activation.actor_person_id == snapshot.actor.person_id
        and type(activation.resource_type) is str and activation.resource_type == grant.resource_type
        and type(activation.resource_id) is str and activation.resource_id == grant.resource_id
        and type(activation.domain) is str and activation.domain == grant.domain
        and type(activation.actions) is frozenset and bool(activation.actions)
        and all(type(action) is str for action in activation.actions)
        and activation.actions.issubset(grant.actions)
        and type(activation.source_grant_id) is str and activation.source_grant_id == evidence.grant_id
        and type(activation.issuer_person_id) is str and activation.issuer_person_id == evidence.issuer_person_id
        and (grant.resource_type != "PERSON" or activation.issuer_person_id == grant.resource_id)
        and type(activation.event_id) is str and bool(activation.event_id)
    )


def _valid_activation(row: Activation) -> bool:
    return (
        isinstance(row, Activation)
        and all(type(value) is str and bool(value) for value in (
            row.incarnation, row.partition_id, row.actor_person_id,
            row.resource_type, row.resource_id, row.domain,
            row.source_grant_id, row.issuer_person_id, row.event_id))
        and type(row.actions) is frozenset and bool(row.actions)
        and all(type(action) is str for action in row.actions)
    )


def _valid_self_activation(row: SelfActivation) -> bool:
    return (
        isinstance(row, SelfActivation)
        and all(type(value) is str and bool(value) for value in (
            row.incarnation, row.partition_id, row.person_id,
            row.domain, row.action, row.event_id))
    )


def evaluate_current(snapshot: KnowledgeSnapshot, witness: WitnessReader) -> Decision:
    """One fresh witness read, then whole-operation typed policy over active rows."""
    deny = Decision(False, "unverified Knowledge incarnation or activation")
    if (
        not isinstance(snapshot, KnowledgeSnapshot)
        or type(snapshot.partition_id) is not str or not snapshot.partition_id
        or type(snapshot.incarnation) is not str or not snapshot.incarnation
        or type(snapshot.revision) is not int or snapshot.revision < 0
        or type(snapshot.digest) is not str or not snapshot.digest
        or not isinstance(snapshot.actor, Actor)
        or type(snapshot.requirements) is not tuple or not snapshot.requirements
        or type(snapshot.targets) is not tuple or type(snapshot.grants) is not tuple
        or type(snapshot.activations) is not tuple or type(snapshot.self_activations) is not tuple
    ):
        return deny
    if (not all(_valid_activation(row) for row in snapshot.activations)
            or not all(_valid_self_activation(row) for row in snapshot.self_activations)):
        return deny
    try:
        if witness.authorize(snapshot.partition_id, snapshot.incarnation,
                             snapshot.revision, snapshot.digest) is not True:
            return deny
    except Exception:
        return deny
    for requirement in snapshot.requirements:
        if not isinstance(requirement, AccessRequirement):
            return deny
        if requirement.resource_type == "PERSON" and requirement.resource_id == snapshot.actor.person_id:
            if not any(
                isinstance(row, SelfActivation)
                and type(row.incarnation) is str and row.incarnation == snapshot.incarnation
                and type(row.partition_id) is str and row.partition_id == snapshot.partition_id
                and type(row.person_id) is str and row.person_id == snapshot.actor.person_id
                and type(row.domain) is str and row.domain == requirement.domain
                and type(row.action) is str and row.action == requirement.action
                and type(row.event_id) is str and bool(row.event_id)
                for row in snapshot.self_activations
            ):
                return deny
    active_grants: list[TypedGrant] = []
    for evidence in snapshot.grants:
        if (
            not isinstance(evidence, GrantEvidence)
            or type(evidence.grant_id) is not str or not evidence.grant_id
            or type(evidence.issuer_person_id) is not str or not evidence.issuer_person_id
            or not isinstance(evidence.grant, TypedGrant)
        ):
            return deny
        for activation in snapshot.activations:
            if _activation_matches(activation, evidence, snapshot):
                active_grants.append(replace(evidence.grant, actions=activation.actions,
                                             legacy_reauthorized=True))
    return evaluate_operation(partition_id=snapshot.partition_id, actor=snapshot.actor,
                              requirements=snapshot.requirements, targets=snapshot.targets,
                              grants=active_grants, now=snapshot.now)
