"""The synthetic pre-LLM orchestration pipeline every P-scenario exercises.

Implements the accepted B6 sequence (Phase-1 doc, mission brief "AUTHORIZED-SET
EXECUTION BARRIER"):

    trusted request context
    -> protected security-metadata planning (backend, content NEVER read)
    -> compile N independently-complete authorization operations: one KNOWLEDGE-scope
       operation (every subject touched by any surviving candidate) plus one operation
       per requested content domain (every subject whose candidate requires that domain)
       (correction 1 + correction 2's exact expected operation-count table)
    -> Home RT#1 authorization (ALL operations submitted together, ONE round trip)
    -> ONLY THEN content access, bounded to the intersection of every operation's
       granted set (a candidate is addressable only if EVERY operation covering it
       was granted -- no partial salvage)
    -> optional domain fan-out (concurrent, R14 measured separately)
    -> ranking/selection (trivial here -- no scoring beyond presence, SS4.2)
    -> Home RT#2 final revalidation (fresh re-evaluation of the SAME logical operations)
    -> ContextBundle-shaped result, constructed ephemeral, never persisted (H10)

This is the ONE orchestration function scenarios call so P1-P13 exercise identical
plumbing and only vary inputs/assertions.

CORRECTION 1 (Product Architect review of PR #33): the previous version authorized only
`domains[0]` -- a single domain -- even when multiple domains were requested or a
candidate spanned multiple subjects/domains. This version compiles the COMPLETE
per-operation requirement sets from `PlannedMetadata.candidate_requirements` (each
candidate's full subject/domain membership, not just the requested slice). A candidate
is addressable only if it is covered and GRANTED by every operation whose requirement it
falls under -- no candidate-by-candidate authorization, no partial salvage.

CORRECTION 2: exact expected operation-count shape, verbatim from the Product Architect's
review:

    P1 Knowledge only:         authorization_operation_count = 1
    P2 Knowledge + 1 domain:   authorization_operation_count = 2
    P3 Knowledge + 3 domains:  authorization_operation_count = 4
    P4 Knowledge + 5 domains:  authorization_operation_count = 6

Realized here as: ONE KNOWLEDGE-scope operation (every subject touched by any surviving
candidate, domain=KNOWLEDGE, include_knowledge_scope=False to avoid double-requiring it)
PLUS one operation per requested content domain (every subject whose candidate requires
that domain). All operations share ONE RT#1 round trip and ONE RT#2 round trip
(`home_auth_round_trip_count` stays 2 regardless of operation count -- B6's "several
independently complete operations share one crossing").
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from backends.common import AuthorizedSet, ContentAccessLog, KnowledgeBackend, PlannedMetadata
from backends.instrumentation import BarrierEvidence, layer_a_from_log
from home_stub.stub import KNOWLEDGE_SCOPE_DOMAIN, AuthorizationOperation, HomeStub


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


def _compile_operations(
    *, planned: PlannedMetadata, surviving_ids: frozenset[str], requested_domains: tuple[str, ...],
    actor_person_id: str, partition_id: str,
) -> list[AuthorizationOperation]:
    """CORRECTION 2: ONE KNOWLEDGE-scope operation + one operation per requested domain,
    each all-or-nothing over the complete subject set that operation's requirement
    covers. A candidate whose complete subject set is {P1, P2} contributes P1 and P2 to
    EVERY operation for a domain it requires -- so a per-domain operation still enforces
    the full multi-subject correctness correction 1 established, just distributed across
    N operations instead of compiled into one.
    """
    surviving = [r for r in planned.candidate_requirements if r.version_id in surviving_ids]

    # KNOWLEDGE-scope operation: every subject touched by any surviving candidate.
    knowledge_subjects: list[str] = []
    for req in surviving:
        for s in req.subject_person_ids:
            if s not in knowledge_subjects:
                knowledge_subjects.append(s)

    operations: list[AuthorizationOperation] = []
    knowledge_op_id = f"op-knowledge-{uuid.uuid4().hex[:8]}"
    operations.append(
        AuthorizationOperation(
            operation_id=knowledge_op_id, actor_person_id=actor_person_id,
            subject_person_ids=tuple(knowledge_subjects), domains=(KNOWLEDGE_SCOPE_DOMAIN,),
            action="VIEW", partition_id=partition_id, include_knowledge_scope=False,
        )
    )

    for domain in requested_domains:
        domain_subjects: list[str] = []
        for req in surviving:
            if domain in req.domains:
                for s in req.subject_person_ids:
                    if s not in domain_subjects:
                        domain_subjects.append(s)
        if not domain_subjects:
            continue  # no surviving candidate requires this domain; nothing to authorize
        op_id = f"op-{domain.lower()}-{uuid.uuid4().hex[:8]}"
        operations.append(
            AuthorizationOperation(
                operation_id=op_id, actor_person_id=actor_person_id,
                subject_person_ids=tuple(domain_subjects), domains=(domain,),
                action="VIEW", partition_id=partition_id, include_knowledge_scope=False,
            )
        )

    return operations


def _candidate_ids_covered_by(op: AuthorizationOperation, requirements) -> frozenset[str]:
    """Which candidate version_ids this operation's requirement set covers -- used to
    intersect grants across operations so a candidate is addressable only if EVERY
    covering operation was granted."""
    covered = set()
    for req in requirements:
        if op.domains[0] == KNOWLEDGE_SCOPE_DOMAIN:
            if any(s in op.subject_person_ids for s in req.subject_person_ids):
                covered.add(req.version_id)
        elif op.domains[0] in req.domains and any(s in op.subject_person_ids for s in req.subject_person_ids):
            covered.add(req.version_id)
    return frozenset(covered)


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

    if not surviving_ids:
        # Nothing to authorize -- an empty Plan is a legitimate no-content outcome, not
        # a denial (correction 8 distinguishes "denied" from "genuinely no content").
        t0 = time.monotonic()
        bundle = EphemeralContextBundle(actor_person_id=actor_person_id, subject_person_ids=subject_person_ids, content=())
        timings.append(StageTiming("bundle_construction", (time.monotonic() - t0) * 1000.0))
        return OrchestrationResult(
            bundle, False, "", timings, home.home_auth_round_trip_count,
            home.authorization_operation_count, home.authorization_evaluation_count, 0, 0, None,
        )

    # CORRECTION 2: compile N independently-complete operations (1 KNOWLEDGE-scope + 1
    # per requested domain), all submitted together in ONE Plan.
    operations = _compile_operations(
        planned=planned, surviving_ids=surviving_ids, requested_domains=domains,
        actor_person_id=actor_person_id, partition_id=partition_id,
    )
    version_pool = {op.operation_id: surviving_ids for op in operations}

    t0 = time.monotonic()
    try:
        decision = home.evaluate_plan(tuple(operations), version_pool=version_pool)
    except RuntimeError as e:
        timings.append(StageTiming("home_rt1", (time.monotonic() - t0) * 1000.0))
        return OrchestrationResult(
            None, True, str(e), timings, home.home_auth_round_trip_count,
            home.authorization_operation_count, home.authorization_evaluation_count, 0, 0, None,
        )
    timings.append(StageTiming("home_rt1", decision.elapsed_ms))

    if not decision.all_allowed():
        first_denied = next(d for d in decision.decisions if not d.allowed)
        return OrchestrationResult(
            None, True, "denied by Home RT#1 (incomplete requirement set)", timings,
            home.home_auth_round_trip_count, home.authorization_operation_count,
            home.authorization_evaluation_count, 0, 0, None, first_denied.missing_requirement,
        )

    # A candidate is addressable only if it is covered by EVERY operation whose
    # requirement it falls under, and ALL of those operations were granted (no partial
    # salvage: since decision.all_allowed() already confirmed every operation passed,
    # this intersection is simply "every surviving candidate", but computed explicitly
    # rather than assumed, so a future partial-grant model cannot silently regress this).
    addressable = set(surviving_ids)
    for op, dec in zip(operations, decision.decisions):
        covered = _candidate_ids_covered_by(op, surviving_requirements)
        if not dec.allowed:
            addressable -= covered
    authorized = AuthorizedSet(version_ids=tuple(sorted(addressable)))

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

    # Stage: Home RT#2 -- fresh re-evaluation of the SAME logical operations, not a TTL
    # check. Re-submitting the same operation_ids does NOT increment
    # authorization_operation_count (correction 2); it does increment
    # authorization_evaluation_count and home_auth_round_trip_count.
    if revalidate:
        t0 = time.monotonic()
        try:
            revalidation = home.evaluate_plan(tuple(operations), version_pool=version_pool)
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
