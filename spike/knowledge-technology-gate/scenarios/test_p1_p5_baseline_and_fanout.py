"""P1-P5: baseline, R14 domain isolation, fan-out flat-crossing, source expansion."""
from __future__ import annotations

from home_stub.stub import Grant, HomeStub
from domain_stub.stub import make_domain_stubs, total_domain_call_count
from scenarios.orchestration import run_knowledge_query

AS_OF = 2_000_000_000
DOMAINS = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")


def _full_grants(corpus):
    """CORRECTION 1: a genuinely PERMISSIVE grant set for baseline P1-P5 scenarios
    (these test the ordinary-path plumbing, not denial), so the fixed actor `p0` is
    authorized for EVERY subject the synthetic corpus may name in a multi-subject
    candidate -- not just themselves. Includes KNOWLEDGE scope, required in addition to
    every content domain by default (AuthorizationOperation.include_knowledge_scope).
    A candidate naming subjects {P0, P1} requires authorization for BOTH; a grant set
    that only covers self-access would (correctly) deny the whole compound operation,
    which is exactly what the multi-subject correction exists to catch -- see
    test_negatives.py for the adversarial tests proving that denial path."""
    grants = []
    for actor in corpus.persons:
        for subject in corpus.persons:
            for domain in (*DOMAINS, "KNOWLEDGE"):
                grants.append(Grant(actor, subject, domain, "VIEW", corpus.partitions[0]))
    return tuple(grants)


def test_p1_knowledge_only_baseline(loaded_backend):
    """P1: Knowledge only, single Person. Expected: 2 crossings; planning is one bounded
    query, not per-candidate."""
    backend, corpus = loaded_backend
    home = HomeStub(grants=_full_grants(corpus))
    p0 = corpus.persons[0]

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF,
    )

    assert not result.denied, result.deny_reason
    assert result.home_auth_round_trip_count == 2, "P1 requires exactly 2 Home crossings"
    assert result.bundle is not None
    assert result.barrier_evidence.layer_a.verdict.value == "PASS"


def test_p2_knowledge_plus_one_domain_r14(loaded_backend):
    """P2: Knowledge + one domain. R14 measured, reported separately from authorization.
    Expected: 2 crossings; domain access reported separately."""
    backend, corpus = loaded_backend
    home = HomeStub(grants=_full_grants(corpus))
    p0 = corpus.persons[0]
    domains = make_domain_stubs(1)

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF, domain_stubs=domains,
    )

    assert not result.denied, result.deny_reason
    assert result.home_auth_round_trip_count == 2
    assert result.domain_call_count == 1
    fanout_stage = [t for t in result.timings if t.stage == "domain_fanout"]
    assert fanout_stage, "R14 must be a separately reported stage, not merged into auth"


def test_p3_three_independent_domains_crossings_flat(loaded_backend):
    """P3: Knowledge + 3 independent domains. Expected: 2 crossings (flat); total approx
    slowest domain, not the sum (concurrency real)."""
    backend, corpus = loaded_backend
    home = HomeStub(grants=_full_grants(corpus))
    p0 = corpus.persons[0]
    domains = make_domain_stubs(3, base_latency_ms=10.0)

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF, domain_stubs=domains,
    )

    assert not result.denied, result.deny_reason
    assert result.home_auth_round_trip_count == 2, "crossings must stay flat as domain_call_count grows"
    assert result.domain_call_count == 3
    fanout_ms = next(t.elapsed_ms for t in result.timings if t.stage == "domain_fanout")
    # Concurrent: wall clock should be well under the sum of 3x~10ms sequential (~30ms).
    assert fanout_ms < 25.0, f"fan-out took {fanout_ms}ms; expected concurrency, not serial sum"


def test_p4_five_independent_domains_scaling(loaded_backend):
    """P4: Knowledge + 5 independent domains. Expected: 2 crossings still; total still
    approx slowest domain."""
    backend, corpus = loaded_backend
    home = HomeStub(grants=_full_grants(corpus))
    p0 = corpus.persons[0]
    domains = make_domain_stubs(5, base_latency_ms=10.0)

    result = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF, domain_stubs=domains,
    )

    assert not result.denied, result.deny_reason
    assert result.home_auth_round_trip_count == 2, "crossings must not grow with domain_call_count (decisive test)"
    assert result.domain_call_count == 5
    fanout_ms = next(t.elapsed_ms for t in result.timings if t.stage == "domain_fanout")
    assert fanout_ms < 25.0, f"fan-out took {fanout_ms}ms; expected concurrency"


def _assert_p0_has_reachable_predecessor(backend, corpus):
    """Seed-robustness precondition (correction 3, not the assertion under test): P5's
    3-crossing claim only holds if the query's surviving candidates actually reference a
    reachable SUPERSEDED predecessor. Assert that the backend's own
    `resolve_source_expansion` surfaces at least one predecessor for the exact base query
    the test runs -- so a future corpus/seed change produces a self-explaining failure
    ('no reachable predecessor for p0') rather than a silent pass at 2 crossings that would
    make the source-expansion feature look untested."""
    p0 = corpus.persons[0]
    planned = backend.plan_metadata(
        partition_id=corpus.partitions[0], subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF
    )
    suppressed = backend.suppressed_version_ids(corpus.partitions[0])
    surviving = tuple(sorted(v for v in planned.candidate_version_ids if v not in suppressed))
    expansion = backend.resolve_source_expansion(
        partition_id=corpus.partitions[0], surviving_version_ids=surviving
    )
    assert expansion, (
        "corpus precondition broken: base query for p0 surfaces no surviving candidate "
        "whose replaces_version_id points to a reachable SUPERSEDED predecessor, so source "
        "expansion cannot be exercised (C-small seed=42 is expected to contain such a chain)"
    )
    return expansion


def test_p5_source_expansion_is_lazy_and_separate(loaded_backend):
    """P5: source expansion is a genuinely lazy, separately-authorized step.

    Two properties, both asserted through the SAME `run_knowledge_query` code path P1-P4
    use, differing only by the `expand_sources` flag:

      (a) LAZY: with `expand_sources=False` (the default P1-P4 take), no derivation
          reference is followed, no extra Home crossing is spent, and
          `source_expansion_count == 0`.
      (b) SEPARATE + INDEPENDENTLY AUTHORIZED: with `expand_sources=True`, the orchestrator
          follows the surviving candidates' `replaces_version_id` references to their
          SUPERSEDED predecessors and authorizes disclosing THAT provenance content as an
          INDEPENDENT operation -- one additional RT#1-shaped crossing -- so a full P5 flow
          is base-RT#1 -> expansion-RT#1 -> RT#2 = exactly 3 crossings, with
          `source_expansion_count == 1`. This replaces the prior hand-waved "run the query
          three times against a shared counter" proxy (which the old docstring itself
          admitted could not express an RT#2-only step); the flag makes it one real flow.
    """
    backend, corpus = loaded_backend
    p0 = corpus.persons[0]

    # Precondition: the C-small seed=42 corpus actually contains a reachable predecessor for
    # p0 (self-explaining failure if a future seed change removes it).
    _assert_p0_has_reachable_predecessor(backend, corpus)

    # (a) LAZY: expansion off -> no extra crossing, count stays 0. Same 2-crossing shape as
    # P1-P4, confirming P1-P4 (which never pass expand_sources) also report 0.
    home = HomeStub(grants=_full_grants(corpus))
    base = run_knowledge_query(
        backend=backend, home=home, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF,
    )
    assert not base.denied, base.deny_reason
    assert base.source_expansion_count == 0, "expansion must stay lazy unless explicitly requested"
    assert base.home_auth_round_trip_count == 2, "P1-P4 shape: RT#1 + RT#2, no expansion crossing"

    # (b) SEPARATE: expansion on -> exactly one extra RT#1-shaped crossing, on ONE HomeStub
    # across ONE coherent flow (not summed across separately-counted calls).
    home_x = HomeStub(grants=_full_grants(corpus))
    expanded = run_knowledge_query(
        backend=backend, home=home_x, partition_id=corpus.partitions[0], actor_person_id=p0,
        subject_person_ids=(p0,), domains=DOMAINS, as_of=AS_OF, expand_sources=True,
    )
    assert not expanded.denied, expanded.deny_reason
    assert expanded.source_expansion_count == 1, "one expansion crossing was actually spent"
    assert expanded.home_auth_round_trip_count == 3, (
        "P5 full flow = base RT#1 + expansion RT#1 + RT#2 = 3 crossings (expansion is a real "
        "separate operation, not a free extension of the base grant)"
    )
    # Expansion is additive: the predecessor content is disclosed on top of the base result,
    # never in place of it (the base bundle is still produced).
    assert expanded.bundle is not None
    assert expanded.barrier_evidence.layer_a.verdict.value == "PASS"
