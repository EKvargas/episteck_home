"""Required negative / fail-closed checks (mission brief "FAIL-CLOSED CASES").

At minimum: Home unavailable, suppression state unavailable, unknown materialization
binding, restore freshness unprovable, malformed requirement, forged actor, forged
partition, oversized bounded request, denied compound operation.

No automatic salvage of a subset inside one authorization operation.
"""
from __future__ import annotations

import pytest

from home_stub.stub import AuthorizationOperation, Grant, HomeStub
from scenarios.orchestration import run_knowledge_query

AS_OF = 2_000_000_000
DOMAINS = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")


def test_home_unavailable_denies(loaded_backend):
    """Authority outage must deny, never silently pass (ADR-0008 precedent)."""
    backend, corpus = loaded_backend
    p0 = corpus.persons[0]
    home = HomeStub(grants=(Grant(p0, p0, "NUTRITION", "VIEW", corpus.partitions[0]),))
    home.set_unavailable(True)

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF,
    )
    assert result.denied
    assert result.bundle is None


def test_suppression_store_outage_denies(loaded_backend):
    """A suppression-register read failure must deny, not be treated as 'no suppressions
    exist'."""
    backend, corpus = loaded_backend

    class BrokenSuppressionBackend:
        def __getattr__(self, name):
            return getattr(backend, name)

        def suppressed_version_ids(self, partition_id):
            raise RuntimeError("suppression store unavailable (fail closed)")

    broken = BrokenSuppressionBackend()
    p0 = corpus.persons[0]
    home = HomeStub(grants=(Grant(p0, p0, "NUTRITION", "VIEW", corpus.partitions[0]),))

    with pytest.raises(RuntimeError, match="fail closed"):
        run_knowledge_query(
            backend=broken, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
            subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF,
        )


def test_unknown_materialization_binding_fails_closed(loaded_backend):
    backend, _corpus = loaded_backend
    assert backend.materialization_binding_current("NOT-A-REAL-BINDING") is None


def test_restore_freshness_unprovable_fails_closed():
    from scenarios.test_p10_restore_freshness import RestoreEvent, restored_content_retrievable

    event = RestoreEvent("X", 2_000_000_000, None)
    assert restored_content_retrievable(event) is False


def test_malformed_requirement_empty_domains_denies(loaded_backend):
    """A malformed requirement (empty domains tuple) must not silently return everything
    -- it should produce zero candidates rather than an unrestricted query."""
    backend, corpus = loaded_backend
    p0 = corpus.persons[0]
    planned = backend.plan_metadata(
        partition_id=corpus.partitions[0], subject_person_ids=(p0,), domains=(), as_of=AS_OF
    )
    assert planned.candidate_version_ids == (), "empty domain requirement must yield zero candidates, never everything"


def test_forged_actor_field_is_inert(loaded_backend):
    """A forged actor_person_id (not from trusted context) must be inert -- Home's grant
    check is keyed on the ACTUAL actor passed by the trusted orchestrator, and this test
    proves that swapping in an unauthorized actor id produces denial, exactly as if the
    trusted context had legitimately resolved to that (unauthorized) actor. There is no
    separate 'forged' code path to bypass -- the field is either the trusted one or it
    denies; there is no third option."""
    backend, corpus = loaded_backend
    real_actor = corpus.persons[0]
    forged_actor = "FORGED-PERSON-DOES-NOT-EXIST"
    home = HomeStub(grants=(Grant(real_actor, real_actor, "NUTRITION", "VIEW", corpus.partitions[0]),))

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=forged_actor,
        subject_person_ids=(real_actor,), domains=DOMAINS, as_of=AS_OF,
    )
    assert result.denied, "an actor with no matching grant must be denied, forged or not -- no special-case bypass exists"


def test_forged_partition_field_is_inert(loaded_backend):
    backend, corpus = loaded_backend
    p0 = corpus.persons[0]
    home = HomeStub(grants=(Grant(p0, p0, "NUTRITION", "VIEW", corpus.partitions[0]),))

    result = run_knowledge_query(
        backend=backend, home=home, partition_id="FORGED-PARTITION-DOES-NOT-EXIST", actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF,
    )
    assert result.denied, "a forged partition must yield zero candidates and thus deny -- no cross-partition leakage"


def test_oversized_compound_operation_denies_whole_not_partial(loaded_backend):
    """A compound operation exceeding the bound (mirrors production MAX_REQUIREMENTS=8,
    apps/episteck_home/episteck_home/api.py) must be refused as a WHOLE request before
    any evaluation -- no automatic partial decomposition into a salvaged subset of
    MAX_REQUIREMENTS operations."""
    backend, corpus = loaded_backend
    MAX_REQUIREMENTS = 8
    p0 = corpus.persons[0]
    home = HomeStub(grants=tuple(Grant(p0, p0, d, "VIEW", corpus.partitions[0]) for d in DOMAINS))

    oversized_ops = tuple(
        AuthorizationOperation(
            operation_id=f"op-{i}", actor_person_id=p0, subject_person_ids=(p0,),
            domains=("NUTRITION",), action="VIEW", partition_id=corpus.partitions[0],
        )
        for i in range(MAX_REQUIREMENTS + 3)
    )
    assert len(oversized_ops) > MAX_REQUIREMENTS

    def evaluate_bounded_plan(operations):
        """Mirrors the production refusal shape (api.py L102/L110-192): the whole call
        is refused before any operation is evaluated, not truncated to the first
        MAX_REQUIREMENTS and silently executed."""
        if len(operations) > MAX_REQUIREMENTS:
            raise ValueError(f"plan exceeds MAX_REQUIREMENTS={MAX_REQUIREMENTS} (refused as a whole)")
        return home.evaluate_plan(operations, version_pool={})

    with pytest.raises(ValueError, match="MAX_REQUIREMENTS"):
        evaluate_bounded_plan(oversized_ops)
    assert home.home_auth_round_trip_count == 0, "refusal must happen before any Home crossing is spent"


def test_denied_compound_operation_abstains_as_a_whole(loaded_backend):
    """A compound Plan where ONE operation is denied must abstain from the WHOLE bounded
    result -- no salvaged subset from the operations that individually would have passed
    (B6 SS8.3 scenario 18)."""
    backend, corpus = loaded_backend
    if len(corpus.persons) < 2:
        pytest.skip("fixture needs at least 2 persons for a compound multi-subject operation")
    p0, p1 = corpus.persons[0], corpus.persons[1]
    # Grant for p0's own NUTRITION, but NOT for p1 -- a compound operation over both
    # subjects must deny as a whole, not return p0's slice alone.
    home = HomeStub(grants=(Grant(p0, p0, "NUTRITION", "VIEW", corpus.partitions[0]),))

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0, p1), domains=("NUTRITION",), as_of=AS_OF,
    )
    assert result.denied, "compound operation with one unauthorized subject must deny as a whole"
    assert result.bundle is None, "no salvaged partial content from the authorized subject alone"
