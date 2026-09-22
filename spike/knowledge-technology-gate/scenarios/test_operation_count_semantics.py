"""CORRECTION 2 (Product Architect review of PR #33): `authorization_operation_count`
must mean the number of independently complete LOGICAL authorization operations in the
retrieval plan, NOT the number of times those operations are evaluated across RT#1+RT#2.

Exact expected operation-count table (verbatim from the Product Architect's review),
proven here:

  P1 Knowledge only:        authorization_operation_count = 1
  P2 Knowledge + 1 domain:  authorization_operation_count = 2
  P3 Knowledge + 3 domains: authorization_operation_count = 4
  P4 Knowledge + 5 domains: authorization_operation_count = 6

Realized as: ONE KNOWLEDGE-scope operation + ONE operation per requested content domain
(orchestration.py's `_compile_operations`), all submitted together in a single RT#1/RT#2
round-trip pair, so `home_auth_round_trip_count` stays 2 regardless of operation count.

`authorization_evaluation_count` is the separate internal counter distinguishing RT#1
from RT#2 re-evaluations of the same logical operations (home_stub/stub.py).
"""
from __future__ import annotations

from backends.common import CandidateRequirement, PlannedMetadata
from domain_stub.stub import make_domain_stubs
from home_stub.stub import KNOWLEDGE_SCOPE_DOMAIN, AuthorizationOperation, Grant, HomeStub
from scenarios.orchestration import _compile_operations, run_knowledge_query
from scenarios.test_p1_p5_baseline_and_fanout import _full_grants

AS_OF = 2_000_000_000
DOMAINS_ALL = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")


def _run(backend, corpus, n_domains, n_stub_domains=0):
    home = HomeStub(grants=_full_grants(corpus))
    p0 = corpus.persons[0]
    domains = DOMAINS_ALL[:n_domains]
    stubs = make_domain_stubs(n_stub_domains, base_latency_ms=1.0) if n_stub_domains else ()
    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=domains, as_of=AS_OF, domain_stubs=stubs,
    )
    return result, home


def test_p1_knowledge_only_one_operation():
    """P1: Knowledge only -- exactly 1 logical operation (the KNOWLEDGE-scope operation).

    This is the true "Knowledge only" endpoint of the Product Architect's operation-count
    table: NO content domain is requested at all. It is proven at the `_compile_operations`
    level (not through `run_knowledge_query`) because this harness's `plan_metadata`
    structurally requires at least one requested content domain to surface any candidate
    (the assertion_domain join) -- so a whole-flow "Knowledge only" query would return zero
    candidates and take the no-content path (0 operations), never the 1-operation shape.

    `_compile_operations` is the exact function `run_knowledge_query` calls to build the
    Plan, so proving it here proves the same production-shaped code path P2/P3/P4 exercise,
    just fed the degenerate "no content domain requested" input directly."""
    # A surviving candidate that carries only the KNOWLEDGE scope conceptually (its content
    # domain is irrelevant because the query requested none), so exactly the single
    # KNOWLEDGE-scope operation is compiled and no per-domain operation is added.
    planned = PlannedMetadata(
        partition_id="PART-1",
        candidate_version_ids=("v1",),
        candidate_requirements=(
            CandidateRequirement(version_id="v1", subject_person_ids=("P1",), domains=("NUTRITION",)),
        ),
        rows_returned=1,
    )
    operations = _compile_operations(
        planned=planned, surviving_ids=frozenset({"v1"}), requested_domains=(),
        actor_person_id="P1", partition_id="PART-1",
    )

    assert len(operations) == 1, "Knowledge only -> exactly 1 logical operation"
    assert operations[0].domains == (KNOWLEDGE_SCOPE_DOMAIN,)
    assert operations[0].subject_person_ids == ("P1",)


def test_p2_one_domain_two_operations(loaded_backend):
    """P2: Knowledge + 1 domain -- exactly 2 logical operations (KNOWLEDGE + 1 domain
    op), still 2 Home crossings. Run through the full `run_knowledge_query` flow because
    n_domains=1 surfaces candidates and compiles KNOWLEDGE + one NUTRITION operation."""
    backend, corpus = loaded_backend
    result, home = _run(backend, corpus, n_domains=1)
    assert not result.denied, result.deny_reason
    assert result.authorization_operation_count == 2, "KNOWLEDGE-scope operation + 1 domain operation"
    assert result.authorization_evaluation_count == 4
    assert result.home_auth_round_trip_count == 2


def _assert_all_requested_domains_carried(backend, corpus, n_domains):
    """Seed-robustness precondition (not the assertion under test): a per-domain operation
    is only compiled for a requested domain that a SURVIVING candidate actually carries, so
    the P3=4/P4=6 counts only hold if the (seed=42) corpus surfaces candidates spanning
    every requested domain. Assert that precondition explicitly so a future corpus/seed
    change produces a self-explaining failure ('domain X not carried') rather than a bare
    count mismatch."""
    p0 = corpus.persons[0]
    domains = DOMAINS_ALL[:n_domains]
    planned = backend.plan_metadata(
        partition_id=corpus.partitions[0], subject_person_ids=(p0,), domains=domains, as_of=AS_OF
    )
    surviving = frozenset(planned.candidate_version_ids)
    carried = {d for r in planned.candidate_requirements if r.version_id in surviving for d in r.domains}
    for d in domains:
        assert d in carried, f"corpus precondition broken: no surviving candidate carries requested domain {d}"


def test_p3_three_domains_four_operations(loaded_backend):
    """P3: Knowledge + 3 domains -- exactly 4 logical operations (KNOWLEDGE + 3 domain
    ops), still 2 Home crossings (the decisive B6 SS18A.10 test)."""
    backend, corpus = loaded_backend
    _assert_all_requested_domains_carried(backend, corpus, n_domains=3)
    result, home = _run(backend, corpus, n_domains=3, n_stub_domains=3)

    assert not result.denied, result.deny_reason
    assert result.authorization_operation_count == 4, "KNOWLEDGE-scope + 3 domain operations"
    assert result.home_auth_round_trip_count == 2, "crossings stay flat regardless of operation count"


def test_p4_five_domains_six_operations(loaded_backend):
    """P4: Knowledge + 5 domains -- exactly 6 logical operations, still 2 crossings."""
    backend, corpus = loaded_backend
    _assert_all_requested_domains_carried(backend, corpus, n_domains=5)
    result, home = _run(backend, corpus, n_domains=5, n_stub_domains=5)

    assert not result.denied, result.deny_reason
    assert result.authorization_operation_count == 6, "KNOWLEDGE-scope + 5 domain operations"
    assert result.home_auth_round_trip_count == 2


def test_reevaluating_same_operation_does_not_grow_operation_count():
    """Direct HomeStub-level proof: submitting the SAME operation_id twice (RT#1 then
    RT#2) increments authorization_evaluation_count by 2 total but
    authorization_operation_count by only 1."""
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", "PART-1"),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", "PART-1"),
    ))
    op = AuthorizationOperation(
        operation_id="same-op", actor_person_id="P1", subject_person_ids=("P1",),
        domains=("NUTRITION",), action="VIEW", partition_id="PART-1",
    )

    home.evaluate_plan((op,), version_pool={"same-op": frozenset({"v1"})})
    assert home.authorization_operation_count == 1
    assert home.authorization_evaluation_count == 1

    home.evaluate_plan((op,), version_pool={"same-op": frozenset({"v1"})})
    assert home.authorization_operation_count == 1, "re-evaluating the SAME logical operation adds no new operation"
    assert home.authorization_evaluation_count == 2, "but each evaluation still counts"
    assert home.home_auth_round_trip_count == 2


def test_distinct_operation_ids_grow_operation_count():
    """Control: submitting two DIFFERENT operation_ids in the same call is 2 logical
    operations in 1 round trip (evaluation count = 2, operation count = 2, RTT = 1)."""
    home = HomeStub(grants=(
        Grant("P1", "P1", "NUTRITION", "VIEW", "PART-1"),
        Grant("P1", "P1", "KNOWLEDGE", "VIEW", "PART-1"),
        Grant("P1", "P1", "HEALTH", "VIEW", "PART-1"),
    ))
    op_a = AuthorizationOperation(
        operation_id="op-a", actor_person_id="P1", subject_person_ids=("P1",),
        domains=("NUTRITION",), action="VIEW", partition_id="PART-1",
    )
    op_b = AuthorizationOperation(
        operation_id="op-b", actor_person_id="P1", subject_person_ids=("P1",),
        domains=("HEALTH",), action="VIEW", partition_id="PART-1",
    )

    home.evaluate_plan((op_a, op_b), version_pool={"op-a": frozenset({"v1"}), "op-b": frozenset({"v2"})})
    assert home.authorization_operation_count == 2
    assert home.authorization_evaluation_count == 2
    assert home.home_auth_round_trip_count == 1
