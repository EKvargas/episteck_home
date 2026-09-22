"""The synthetic pre-LLM orchestration pipeline every P-scenario exercises.

Implements the accepted B6 sequence (Phase-1 doc, mission brief "AUTHORIZED-SET
EXECUTION BARRIER"):

    trusted request context
    -> protected security-metadata planning (backend, content NEVER read)
    -> Home RT#1 authorization (bounded Authorization Plan)
    -> ONLY THEN content access, bounded to the authorized set
    -> optional domain fan-out (concurrent, R14 measured separately)
    -> ranking/selection (trivial here -- no scoring beyond presence, SS4.2)
    -> Home RT#2 final revalidation (fresh re-evaluation)
    -> ContextBundle-shaped result, constructed ephemeral, never persisted (H10)

This is the ONE orchestration function scenarios call so P1-P13 exercise identical
plumbing and only vary inputs/assertions.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from backends.common import AuthorizedSet, ContentAccessLog, KnowledgeBackend, PlannedMetadata
from backends.instrumentation import BarrierEvidence, layer_a_from_log
from home_stub.stub import AuthorizationOperation, HomeStub


@dataclass
class StageTiming:
    stage: str
    elapsed_ms: float


@dataclass
class EphemeralContextBundle:
    """Request-local only. Never written to disk/db. Asserting its non-persistence is a
    P-scenario negative check (H10) -- this class simply has no save()/to_disk() method
    and callers must not add one."""

    actor_person_id: str
    subject_person_ids: tuple[str, ...]
    content: tuple[dict, ...]
    built_at: float = field(default_factory=time.monotonic)


@dataclass
class OrchestrationResult:
    bundle: EphemeralContextBundle | None
    denied: bool
    deny_reason: str
    timings: list[StageTiming]
    home_auth_round_trip_count: int
    authorization_operation_count: int
    domain_call_count: int
    source_expansion_count: int
    barrier_evidence: BarrierEvidence | None


def run_knowledge_query(
    *, backend: KnowledgeBackend, home: HomeStub, partition_id: str, actor_person_id: str,
    subject_person_ids: tuple[str, ...], domains: tuple[str, ...], as_of: int,
    grants_for_actor: tuple[str, ...] = (),  # unused here; home already has grants preloaded
    domain_stubs: tuple = (), revalidate: bool = True,
) -> OrchestrationResult:
    timings: list[StageTiming] = []

    # Stage: protected security-metadata planning -- content NEVER read here.
    t0 = time.monotonic()
    planned: PlannedMetadata = backend.plan_metadata(
        partition_id=partition_id, subject_person_ids=subject_person_ids, domains=domains, as_of=as_of,
    )
    timings.append(StageTiming("metadata_planning", (time.monotonic() - t0) * 1000.0))

    # Stage: suppression before candidacy (H5) -- filter candidates against the suppression
    # register BEFORE Home is even asked, so a suppressed record is never presented as a
    # candidate for authorization either.
    t0 = time.monotonic()
    suppressed = backend.suppressed_version_ids(partition_id)
    surviving_candidates = tuple(v for v in planned.candidate_version_ids if v not in suppressed)
    timings.append(StageTiming("suppression_filter", (time.monotonic() - t0) * 1000.0))

    # Stage: Home RT#1.
    op_id = f"op-{uuid.uuid4().hex[:8]}"
    operation = AuthorizationOperation(
        operation_id=op_id, actor_person_id=actor_person_id, subject_person_ids=subject_person_ids,
        domain=domains[0] if domains else "KNOWLEDGE", action="VIEW", partition_id=partition_id,
    )
    t0 = time.monotonic()
    try:
        decision = home.evaluate_plan(
            (operation,), version_pool={op_id: frozenset(surviving_candidates)}
        )
    except RuntimeError as e:
        timings.append(StageTiming("home_rt1", (time.monotonic() - t0) * 1000.0))
        return OrchestrationResult(
            None, True, str(e), timings, home.home_auth_round_trip_count,
            home.authorization_operation_count, 0, 0, None,
        )
    timings.append(StageTiming("home_rt1", decision.elapsed_ms))

    if not decision.all_allowed():
        return OrchestrationResult(
            None, True, "denied by Home RT#1", timings, home.home_auth_round_trip_count,
            home.authorization_operation_count, 0, 0, None,
        )

    authorized = AuthorizedSet(version_ids=tuple(decision.decisions[0].granted_version_ids))

    # Stage: content access -- ONLY authorized IDs, fully logged (H3 barrier evidence).
    t0 = time.monotonic()
    log = ContentAccessLog()
    content = backend.fetch_content(authorized, log=log)
    timings.append(StageTiming("content_access", (time.monotonic() - t0) * 1000.0))
    barrier = BarrierEvidence(layer_a=layer_a_from_log(log), layer_b=None)

    # Stage: domain fan-out (R14, concurrent).
    domain_call_count = 0
    if domain_stubs:
        from domain_stub.stub import fan_out_concurrent, total_domain_call_count

        t0 = time.monotonic()
        fan_out_concurrent(domain_stubs)
        timings.append(StageTiming("domain_fanout", (time.monotonic() - t0) * 1000.0))
        domain_call_count = total_domain_call_count(domain_stubs)

    # Stage: Home RT#2 -- fresh re-evaluation, not a TTL check.
    if revalidate:
        t0 = time.monotonic()
        try:
            revalidation = home.evaluate_plan(
                (operation,), version_pool={op_id: frozenset(surviving_candidates)}
            )
        except RuntimeError as e:
            timings.append(StageTiming("home_rt2", (time.monotonic() - t0) * 1000.0))
            return OrchestrationResult(
                None, True, str(e), timings, home.home_auth_round_trip_count,
                home.authorization_operation_count, domain_call_count, 0, barrier,
            )
        timings.append(StageTiming("home_rt2", revalidation.elapsed_ms))
        if not revalidation.all_allowed():
            return OrchestrationResult(
                None, True, "denied by Home RT#2 revalidation", timings,
                home.home_auth_round_trip_count, home.authorization_operation_count,
                domain_call_count, 0, barrier,
            )

    t0 = time.monotonic()
    bundle = EphemeralContextBundle(
        actor_person_id=actor_person_id, subject_person_ids=subject_person_ids, content=tuple(content),
    )
    timings.append(StageTiming("bundle_construction", (time.monotonic() - t0) * 1000.0))

    return OrchestrationResult(
        bundle, False, "", timings, home.home_auth_round_trip_count,
        home.authorization_operation_count, domain_call_count, 0, barrier,
    )
