"""The synthetic pre-LLM orchestration pipeline every P-scenario exercises.

Implements the accepted B6 sequence (Phase-1 doc, mission brief "AUTHORIZED-SET
EXECUTION BARRIER"):

    trusted request context
    -> protected security-metadata planning (backend, content NEVER read)
    -> compile the COMPLETE union (subject, domain) requirement set across every
       surviving candidate (correction 1)
    -> Home RT#1 authorization (ONE compound, all-or-nothing Knowledge operation)
    -> ONLY THEN content access, bounded to the authorized set
    -> optional domain fan-out (concurrent, R14 measured separately)
    -> ranking/selection (trivial here -- no scoring beyond presence, SS4.2)
    -> Home RT#2 final revalidation (fresh re-evaluation of the SAME logical operation)
    -> ContextBundle-shaped result, constructed ephemeral, never persisted (H10)

This is the ONE orchestration function scenarios call so P1-P13 exercise identical
plumbing and only vary inputs/assertions.

CORRECTION 1 (Product Architect review of PR #33): the previous version authorized only
`domains[0]` -- a single domain -- even when multiple domains were requested or a
candidate spanned multiple subjects/domains. This version compiles the COMPLETE union
requirement set from `PlannedMetadata.union_requirement_pairs()` (which itself reflects
each candidate's full subject/domain membership, not just the requested slice) into ONE
`AuthorizationOperation`, and grants candidacy only if Home authorizes ALL of it. No
candidate-by-candidate authorization; no partial salvage if any required pair is denied.

CORRECTION 2: `authorization_operation_count` now reflects logical operations (see
home_stub/stub.py); this orchestration submits exactly ONE logical operation per query
(re-evaluated at RT#1 and RT#2), so `authorization_operation_count == 1` for an ordinary
query with revalidation, and `authorization_evaluation_count == 2`.
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
    authorization_evaluation_count: int
    domain_call_count: int
    source_expansion_count: int
    barrier_evidence: BarrierEvidence | None
    missing_requirement: tuple[str, str] | None = None  # for adversarial-test visibility


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
    surviving_ids = frozenset(v for v in planned.candidate_version_ids if v not in suppressed)
    surviving_requirements = tuple(r for r in planned.candidate_requirements if r.version_id in surviving_ids)
    timings.append(StageTiming("suppression_filter", (time.monotonic() - t0) * 1000.0))

    # CORRECTION 1: compile the COMPLETE union (subject, domain) requirement set across
    # every surviving candidate -- not just the requested slice, and not just domains[0].
    union_pairs: list[tuple[str, str]] = []
    for req in surviving_requirements:
        for s in req.subject_person_ids:
            for d in req.domains:
                union_pairs.append((s, d))
    union_pairs = list(dict.fromkeys(union_pairs))
    union_subjects = tuple(dict.fromkeys(s for s, _ in union_pairs)) or subject_person_ids
    union_domains = tuple(dict.fromkeys(d for _, d in union_pairs)) or domains

    # Stage: Home RT#1 -- ONE compound, all-or-nothing operation over the complete union.
    op_id = f"op-{uuid.uuid4().hex[:8]}"
    operation = AuthorizationOperation(
        operation_id=op_id, actor_person_id=actor_person_id, subject_person_ids=union_subjects,
        domains=union_domains, action="VIEW", partition_id=partition_id,
    )
    t0 = time.monotonic()
    try:
        decision = home.evaluate_plan(
            (operation,), version_pool={op_id: surviving_ids}
        )
    except RuntimeError as e:
        timings.append(StageTiming("home_rt1", (time.monotonic() - t0) * 1000.0))
        return OrchestrationResult(
            None, True, str(e), timings, home.home_auth_round_trip_count,
            home.authorization_operation_count, home.authorization_evaluation_count, 0, 0, None,
        )
    timings.append(StageTiming("home_rt1", decision.elapsed_ms))

    if not decision.all_allowed():
        missing = decision.decisions[0].missing_requirement if decision.decisions else None
        return OrchestrationResult(
            None, True, "denied by Home RT#1 (incomplete requirement set)", timings,
            home.home_auth_round_trip_count, home.authorization_operation_count,
            home.authorization_evaluation_count, 0, 0, None, missing,
        )

    authorized = AuthorizedSet(version_ids=tuple(decision.decisions[0].granted_version_ids))

    # Stage: content access -- ONLY authorized IDs, fully logged (H3 barrier evidence).
    t0 = time.monotonic()
    log = ContentAccessLog()
    content = backend.fetch_content(authorized, log=log)
    timings.append(StageTiming("content_access", (time.monotonic() - t0) * 1000.0))
    barrier = BarrierEvidence(layer_a=layer_a_from_log(log), layer_b=None)

    # Stage: domain fan-out (synthetic fan-out topology latency -- NOT R14; see
    # domain_stub/stub.py and correction 5 for why this is not a real domain measurement).
    domain_call_count = 0
    if domain_stubs:
        from domain_stub.stub import fan_out_concurrent, total_domain_call_count

        t0 = time.monotonic()
        fan_out_concurrent(domain_stubs)
        timings.append(StageTiming("domain_fanout", (time.monotonic() - t0) * 1000.0))
        domain_call_count = total_domain_call_count(domain_stubs)

    # Stage: Home RT#2 -- fresh re-evaluation of the SAME logical operation, not a TTL
    # check. Re-submitting the same operation_id does NOT increment
    # authorization_operation_count (correction 2); it does increment
    # authorization_evaluation_count and home_auth_round_trip_count.
    if revalidate:
        t0 = time.monotonic()
        try:
            revalidation = home.evaluate_plan(
                (operation,), version_pool={op_id: surviving_ids}
            )
        except RuntimeError as e:
            timings.append(StageTiming("home_rt2", (time.monotonic() - t0) * 1000.0))
            return OrchestrationResult(
                None, True, str(e), timings, home.home_auth_round_trip_count,
                home.authorization_operation_count, home.authorization_evaluation_count,
                domain_call_count, 0, barrier,
            )
        timings.append(StageTiming("home_rt2", revalidation.elapsed_ms))
        if not revalidation.all_allowed():
            return OrchestrationResult(
                None, True, "denied by Home RT#2 revalidation", timings,
                home.home_auth_round_trip_count, home.authorization_operation_count,
                home.authorization_evaluation_count, domain_call_count, 0, barrier,
            )

    t0 = time.monotonic()
    bundle = EphemeralContextBundle(
        actor_person_id=actor_person_id, subject_person_ids=subject_person_ids, content=tuple(content),
    )
    timings.append(StageTiming("bundle_construction", (time.monotonic() - t0) * 1000.0))

    return OrchestrationResult(
        bundle, False, "", timings, home.home_auth_round_trip_count,
        home.authorization_operation_count, home.authorization_evaluation_count,
        domain_call_count, 0, barrier,
    )
