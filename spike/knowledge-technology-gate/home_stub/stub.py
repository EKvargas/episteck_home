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


@dataclass
class Grant:
    actor_person_id: str
    subject_person_id: str
    domain: str
    action: str
    partition_id: str


@dataclass
class AuthorizationOperation:
    """One independently-complete authorization operation within a Plan (B6 SS8.3.1)."""

    operation_id: str
    actor_person_id: str
    subject_person_ids: tuple[str, ...]
    domain: str
    action: str
    partition_id: str


@dataclass(frozen=True)
class OperationDecision:
    operation_id: str
    allowed: bool
    granted_version_ids: frozenset[str] = field(default_factory=frozenset)


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
        self.authorization_operation_count = 0
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
        """
        start = time.monotonic()
        if self._unavailable:
            self._sleep_calibrated()
            raise RuntimeError("Home stub unavailable (fail closed)")

        decisions = []
        for op in operations:
            allowed = self._check(op)
            granted = version_pool.get(op.operation_id, frozenset()) if allowed else frozenset()
            decisions.append(OperationDecision(op.operation_id, allowed, granted))
        self._sleep_calibrated()
        elapsed = (time.monotonic() - start) * 1000.0

        self.home_auth_round_trip_count += 1
        self.authorization_operation_count += len(operations)
        return PlanDecision(decisions=tuple(decisions), elapsed_ms=elapsed)

    def _check(self, op: AuthorizationOperation) -> bool:
        for subject in op.subject_person_ids:
            found = any(
                g.actor_person_id == op.actor_person_id
                and g.subject_person_id == subject
                and g.domain == op.domain
                and g.partition_id == op.partition_id
                and (g.action == op.action or g.action == "MANAGE")
                for g in self._grants
            )
            if not found:
                return False  # ALL subjects must be authorized -- conservative intersection (B1)
        return True

    def reset_counters(self) -> None:
        self.home_auth_round_trip_count = 0
        self.authorization_operation_count = 0
