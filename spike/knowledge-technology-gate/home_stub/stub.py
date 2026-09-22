"""Stubbed Home Control Plane (Phase-1 SS16.2, "On stubbing Home").

Not a network client. Not connected to production home.episteck.com. Evaluates a bounded
Authorization Plan against SYNTHETIC grants held in-process, with injected latency
calibrated to E7 (measured Home check_access: 111.57ms median / 119.88ms p95, persistent
client -- Phase-1 doc SS2.3 table). This isolates the variable under test (how many
crossings, and whether authority changes between RT#1 and RT#2) from Home's own response
time, which is already measured separately and not what this spike is testing.

RT#1: evaluate a bounded Authorization Plan (independently complete operations).
RT#2: freshly RE-EVALUATE all operations contributing to disclosure -- not a TTL check.
       Scenarios may mutate authority state between RT#1 and RT#2 (e.g. P8's grant
       revocation) to prove RT#2 is a real re-evaluation.

CORRECTION 1 (Product Architect review of PR #33): a Knowledge authorization operation
must require EVERY Person subject AND EVERY required content domain, all-or-nothing. An
assertion with subjects {P1, P2} and domains {NUTRITION, HEALTH} must not become
addressable merely because (P1, NUTRITION) was authorized -- B1's conservative
intersection requires the WHOLE requirement set. `AuthorizationOperation` now carries
`subject_person_ids` AND `domains` (plural, both complete sets) plus an explicit
`include_knowledge_scope` flag (B1/B6 require a Knowledge-scope authorization in addition
to per-domain authorization), and `_check()` verifies every (subject, domain, action)
pair in the full cross product, never just the first domain.

CORRECTION 2: `authorization_operation_count` now means the number of independently
complete LOGICAL operations submitted in a Plan -- NOT the number of times operations are
evaluated across RT#1 + RT#2. A separate `authorization_evaluation_count` tracks how many
times operations were evaluated (RT#1 + RT#2 re-evaluations of the same logical set).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# Calibrated from Phase-1 doc E7 (G1_5_VALIDATION SS6): 111.57ms median / 119.88ms p95 for
# a persistent client. We inject the median as the deterministic per-call cost; p95/p99
# spread is a property of the REAL network Home measurement, not something a stub should
# invent -- the spike reports crossing COUNT precisely and composes it with this
# calibrated constant, rather than trying to reproduce a distribution it did not measure.
CALIBRATED_HOME_CROSSING_MS = 111.57

KNOWLEDGE_SCOPE_DOMAIN = "KNOWLEDGE"


@dataclass
class Grant:
    actor_person_id: str
    subject_person_id: str
    domain: str
    action: str
    partition_id: str


@dataclass
class AuthorizationOperation:
    """One independently-complete authorization operation within a Plan (B6 SS8.3.1).

    CORRECTION 1: `subject_person_ids` and `domains` are BOTH complete sets. The
    operation is granted only if the actor holds `action` (or MANAGE) for EVERY
    (subject, domain) pair in their cross product, AND -- if `include_knowledge_scope`
    is True (the default, per B1/B6's accepted requirement that Knowledge scope
    authorization is required in addition to per-domain authorization) -- for
    (subject, KNOWLEDGE, action) as well, for every subject.

    This operation is all-or-nothing: `HomeStub._check` returns a single bool for the
    whole cross product, never a partial/candidate-by-candidate result.
    """

    operation_id: str
    actor_person_id: str
    subject_person_ids: tuple[str, ...]
    domains: tuple[str, ...]
    action: str
    partition_id: str
    include_knowledge_scope: bool = True

    def required_pairs(self) -> tuple[tuple[str, str], ...]:
        """The complete (subject, domain) requirement set this operation demands,
        including the Knowledge-scope requirement per subject unless disabled."""
        pairs = [(s, d) for s in self.subject_person_ids for d in self.domains]
        if self.include_knowledge_scope:
            pairs.extend((s, KNOWLEDGE_SCOPE_DOMAIN) for s in self.subject_person_ids)
        return tuple(dict.fromkeys(pairs))  # de-duplicate, preserve order


@dataclass(frozen=True)
class OperationDecision:
    operation_id: str
    allowed: bool
    granted_version_ids: frozenset[str] = field(default_factory=frozenset)
    missing_requirement: tuple[str, str] | None = None  # (subject, domain) that failed, for test/debug visibility only


@dataclass(frozen=True)
class PlanDecision:
    decisions: tuple[OperationDecision, ...]
    elapsed_ms: float

    def allowed_operation_ids(self) -> frozenset[str]:
        return frozenset(d.operation_id for d in self.decisions if d.allowed)

    def all_allowed(self) -> bool:
        return all(d.allowed for d in self.decisions)


class HomeStub:
    """One in-process stub instance = one synthetic Home for one scenario run."""

    def __init__(self, *, grants: tuple[Grant, ...] = (), inject_latency: bool = True):
        self._grants: list[Grant] = list(grants)
        self._inject_latency = inject_latency
        self.home_auth_round_trip_count = 0
        # CORRECTION 2: logical operation count -- how many DISTINCT complete operations
        # have ever been submitted across the whole scenario. Evaluating the SAME logical
        # operation again at RT#2 does not add to this count.
        self.authorization_operation_count = 0
        # New: how many times operations were EVALUATED (RT#1 + RT#2 both count).
        self.authorization_evaluation_count = 0
        self._seen_operation_ids: set[str] = set()
        self._unavailable = False

    def mutate_authority(self, *, revoke: tuple[Grant, ...] = (), add: tuple[Grant, ...] = ()) -> None:
        """Test seam: scenarios (e.g. P8) mutate authority between RT#1 and RT#2."""
        for g in revoke:
            self._grants = [
                x for x in self._grants
                if not (
                    x.actor_person_id == g.actor_person_id
                    and x.subject_person_id == g.subject_person_id
                    and x.domain == g.domain
                    and x.action == g.action
                )
            ]
        self._grants.extend(add)

    def set_unavailable(self, unavailable: bool) -> None:
        """Test seam for negative scenarios: Home outage must deny, not silently pass."""
        self._unavailable = unavailable

    def _sleep_calibrated(self) -> None:
        if self._inject_latency:
            time.sleep(CALIBRATED_HOME_CROSSING_MS / 1000.0)

    def evaluate_plan(
        self, operations: tuple[AuthorizationOperation, ...], *, version_pool: dict[str, frozenset[str]],
    ) -> PlanDecision:
        """RT#1 or RT#2 -- one network round trip evaluating N independently-complete
        operations. `version_pool` maps operation_id -> candidate version IDs (already
        narrowed by protected-metadata planning); Home only decides allow/deny per op and,
        on allow, which of those candidate IDs are actually granted.

        Raises RuntimeError if Home is marked unavailable (fail-closed caller obligation:
        caller must deny, never treat an exception as "no restriction").

        CORRECTION 2: `authorization_operation_count` increments only for operation_ids
        not previously seen by this HomeStub instance (new logical operations).
        `authorization_evaluation_count` increments by len(operations) every call,
        counting RT#1 and RT#2 re-evaluations of the same logical set separately.
        """
        start = time.monotonic()
        if self._unavailable:
            self._sleep_calibrated()
            raise RuntimeError("Home stub unavailable (fail closed)")

        decisions = []
        for op in operations:
            allowed, missing = self._check(op)
            granted = version_pool.get(op.operation_id, frozenset()) if allowed else frozenset()
            decisions.append(OperationDecision(op.operation_id, allowed, granted, missing))
            if op.operation_id not in self._seen_operation_ids:
                self._seen_operation_ids.add(op.operation_id)
                self.authorization_operation_count += 1
        self._sleep_calibrated()
        elapsed = (time.monotonic() - start) * 1000.0

        self.home_auth_round_trip_count += 1
        self.authorization_evaluation_count += len(operations)
        return PlanDecision(decisions=tuple(decisions), elapsed_ms=elapsed)

    def _check(self, op: AuthorizationOperation) -> tuple[bool, tuple[str, str] | None]:
        """CORRECTION 1: check the COMPLETE (subject, domain) cross product, including
        the Knowledge-scope requirement. All-or-nothing: the first missing pair fails
        the whole operation; no partial/candidate-by-candidate salvage."""
        for subject, domain in op.required_pairs():
            found = any(
                g.actor_person_id == op.actor_person_id
                and g.subject_person_id == subject
                and g.domain == domain
                and g.partition_id == op.partition_id
                and (g.action == op.action or g.action == "MANAGE")
                for g in self._grants
            )
            if not found:
                return False, (subject, domain)
        return True, None

    def reset_counters(self) -> None:
        self.home_auth_round_trip_count = 0
        self.authorization_operation_count = 0
        self.authorization_evaluation_count = 0
        self._seen_operation_ids.clear()
