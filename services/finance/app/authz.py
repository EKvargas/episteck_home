"""Authorization port shaped like the proposed Home H2 ``authorize_batch``.

ONE request per operation (delegations are single-use). Finance never supplies an actor:
Home resolves it from the delegation and returns it. The answer is accepted only if it
proves it decided exactly the requirements we sent, in order; anything else is
UNAVAILABLE and the caller must read nothing.

    request : delegation (opaque, transport header) + 1..8 requirements
              {subject: "SELF" | "PSN-...", domain: "FINANCE", action}
    response: {actor_person_id, decisions: [{subject, domain, action, allow, reason}]}
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

SELF = "SELF"
DOMAIN = "FINANCE"
MAX_REQUIREMENTS = 8

# ANSWERED means the response is complete and trustworthy; individual decisions may
# still be denials. Only ``is_allowed`` grants anything.
ANSWERED = "ANSWERED"
SESSION_INVALID = "SESSION_INVALID"
UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Requirement:
    subject: str
    action: str
    domain: str = DOMAIN


@dataclass(frozen=True)
class Decision:
    subject: str
    domain: str
    action: str
    allow: bool
    reason: str


@dataclass(frozen=True)
class BatchDecision:
    outcome: str
    actor_person_id: str | None = None
    decisions: tuple[Decision, ...] = ()

    def is_allowed(self, subject: str, action: str = "VIEW") -> bool:
        if self.outcome != ANSWERED:
            return False
        return any(
            d.allow and d.subject == subject and d.action == action for d in self.decisions
        )


class Authorizer(Protocol):
    def authorize(
        self, delegation: str | None, requirements: Sequence[Requirement]
    ) -> BatchDecision: ...


def check_requirements(requirements: Sequence[Requirement]) -> None:
    if not requirements or len(requirements) > MAX_REQUIREMENTS:
        raise ValueError(f"between 1 and {MAX_REQUIREMENTS} requirements are required")


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_batch(sent: Sequence[Requirement], payload: object) -> BatchDecision:
    """Turn a raw Home answer into a BatchDecision, failing closed on any mismatch."""
    check_requirements(sent)
    if not isinstance(payload, dict):
        return BatchDecision(UNAVAILABLE)
    actor = payload.get("actor_person_id")
    raw = payload.get("decisions")
    if not _non_empty_str(actor) or not isinstance(raw, list) or len(raw) != len(sent):
        return BatchDecision(UNAVAILABLE)
    decisions: list[Decision] = []
    for want, item in zip(sent, raw):
        if not isinstance(item, dict):
            return BatchDecision(UNAVAILABLE)
        if (item.get("subject"), item.get("domain"), item.get("action")) != (
            want.subject, want.domain, want.action
        ):
            return BatchDecision(UNAVAILABLE)
        if type(item.get("allow")) is not bool or not _non_empty_str(item.get("reason")):
            return BatchDecision(UNAVAILABLE)
        decisions.append(
            Decision(want.subject, want.domain, want.action, item["allow"], item["reason"])
        )
    return BatchDecision(ANSWERED, actor, tuple(decisions))
