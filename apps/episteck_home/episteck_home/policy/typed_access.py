"""Pure KAP-2 typed decision over a trusted Home snapshot.

Disconnected from Frappe wrappers and endpoints. The future loader must prove
actor/service binding, target completeness, issuer evidence and dependencies;
caller-supplied values or legacy DocTypes are not a trusted snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .access import ACTIONS, DOMAINS, Decision


RESOURCE_TYPES = frozenset({"PERSON", "CIRCLE"})


@dataclass(frozen=True)
class Actor:
    partition_id: str
    person_id: str


@dataclass(frozen=True)
class TypedTarget:
    partition_id: str
    resource_type: str
    resource_id: str
    active: bool = True


@dataclass(frozen=True)
class AccessRequirement:
    resource_type: str
    resource_id: str
    domain: str
    action: str


@dataclass(frozen=True)
class TypedGrant:
    partition_id: str
    actor_person_id: str
    resource_type: str
    resource_id: str
    domain: str
    actions: frozenset[str]
    state: str
    issuer_verified: bool
    dependency_current: bool
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    legacy: bool = False
    legacy_reauthorized: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", frozenset(self.actions))


def _valid_time(value: datetime | None) -> bool:
    return value is None or (isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None)


def _grant_covers(
    grant: TypedGrant, requirement: AccessRequirement, partition_id: str, actor_person_id: str, now: datetime
) -> bool:
    if not isinstance(grant, TypedGrant):
        return False
    if (
        grant.partition_id != partition_id
        or grant.actor_person_id != actor_person_id
        or grant.resource_type != requirement.resource_type
        or grant.resource_id != requirement.resource_id
        or grant.domain != requirement.domain
        or grant.state != "ACTIVE"
        or not grant.actions
        or not grant.actions.issubset(ACTIONS)
        or grant.issuer_verified is not True
        or grant.dependency_current is not True
        or (grant.legacy is True and grant.legacy_reauthorized is not True)
        or not _valid_time(grant.valid_from)
        or not _valid_time(grant.valid_until)
    ):
        return False
    if grant.valid_from is not None and now < grant.valid_from:
        return False
    if grant.valid_until is not None and now > grant.valid_until:
        return False
    return requirement.action in grant.actions or "MANAGE" in grant.actions


def evaluate_operation(
    *,
    partition_id: str,
    actor: Actor,
    requirements: Iterable[AccessRequirement],
    targets: Iterable[TypedTarget],
    grants: Iterable[TypedGrant],
    now: datetime,
) -> Decision:
    """Allow only when every typed requirement is proven by current authority."""
    deny = Decision(False, "unverified typed authority")
    if not partition_id or not isinstance(actor, Actor) or actor.partition_id != partition_id or not actor.person_id:
        return deny
    if not _valid_time(now) or now is None:
        return deny
    try:
        required, resources, rows = tuple(requirements), tuple(targets), tuple(grants)
    except (TypeError, ValueError):
        return deny
    if not required:
        return deny
    target_index: dict[tuple[str, str], TypedTarget] = {}
    for target in resources:
        if not isinstance(target, TypedTarget) or target.resource_type not in RESOURCE_TYPES or not target.resource_id:
            return deny
        key = (target.resource_type, target.resource_id)
        if key in target_index:
            return deny
        target_index[key] = target
    for requirement in required:
        if (
            not isinstance(requirement, AccessRequirement)
            or requirement.resource_type not in RESOURCE_TYPES
            or not requirement.resource_id
            or requirement.domain not in DOMAINS
            or requirement.action not in ACTIONS
        ):
            return deny
        target = target_index.get((requirement.resource_type, requirement.resource_id))
        if target is None or target.partition_id != partition_id or target.active is not True:
            return deny
        if requirement.resource_type == "PERSON" and requirement.resource_id == actor.person_id:
            continue
        if not any(_grant_covers(row, requirement, partition_id, actor.person_id, now) for row in rows):
            return deny
    return Decision(True, "all typed requirements authorized")
