"""S1 backend plan evidence -- Layer B corroboration for the exact-version content barrier
(correction 10, Product Architect review of PR #33).

The earlier PR gave S1 only Layer A (application-boundary subset) evidence while S2 already
carried both layers. Correction 10 requires S1 to also present the backend plan evidence:
the content barrier's EXPLAIN QUERY PLAN must show an index-bounded seek on the authorized
version IDs (`SEARCH assertion_version USING INDEX ... (version_id=?)`), not a global
`SCAN assertion_version`. This is corroboration only (correction 1.B) -- Layer A stays
authoritative -- and every verdict is drawn from the closed set (correction 12).
"""
from __future__ import annotations

from backends.instrumentation import BarrierVerdict, layer_b_sqlite_exact_lookup
from backends.sqlite_backend import SQLiteKnowledgeBackend

AS_OF = 2_000_000_000


def test_s1_content_barrier_plan_is_index_bounded_over_real_backend(loaded_backend):
    """Over a real loaded backend, the S1 content-lookup plan seeks by index on the
    authorized version IDs -> Layer B PASS (access pattern bounded)."""
    backend, corpus = loaded_backend
    p0 = corpus.persons[0]
    planned = backend.plan_metadata(
        partition_id=corpus.partitions[0], subject_person_ids=(p0,),
        domains=("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD"), as_of=AS_OF,
    )
    # Precondition: the query actually produced candidates, else the plan probe is vacuous.
    assert planned.candidate_version_ids, "seed corpus produced no candidates for p0"

    plan_rows = backend.explain_content_barrier(planned.candidate_version_ids)
    evidence = layer_b_sqlite_exact_lookup(plan_rows)

    assert evidence.access_pattern_bounded is True, plan_rows
    assert evidence.verdict == BarrierVerdict.PASS
    assert any("SEARCH assertion_version" in row for row in plan_rows), plan_rows
    assert not any(
        "SCAN assertion_version" in row and "SEARCH" not in row for row in plan_rows
    ), "content barrier must not fall back to a full table scan"


def test_s1_layer_b_flags_a_full_scan_as_fail():
    """A plan that shows a bare SCAN of assertion_version (unbounded content access) must be
    Layer B FAIL -- never silently promoted to PASS."""
    scan_plan = ["(2, 0, 0, 'SCAN assertion_version')"]
    evidence = layer_b_sqlite_exact_lookup(scan_plan)
    assert evidence.access_pattern_bounded is False
    assert evidence.verdict == BarrierVerdict.FAIL


def test_s1_layer_b_reports_unknown_when_plan_absent_or_unrecognized():
    """No plan, or a plan shape that is neither a recognized bounded seek nor an unbounded
    scan, resolves to UNKNOWN -- the honest classification, not a guessed PASS."""
    assert layer_b_sqlite_exact_lookup([]).verdict == BarrierVerdict.UNKNOWN
    unrecognized = ["(9, 0, 0, 'USE TEMP B-TREE FOR SOMETHING UNEXPECTED')"]
    assert layer_b_sqlite_exact_lookup(unrecognized).verdict == BarrierVerdict.UNKNOWN


def test_s1_empty_authorized_set_probe_still_plans_bounded():
    """Even with an empty authorized set, the plan PROBE uses a placeholder so SQLite still
    plans the IN-list lookup form -- the probe reports the access PATTERN of the barrier
    query, independent of whether any ID happens to be authorized this call."""
    be = SQLiteKnowledgeBackend()
    try:
        # No corpus loaded is fine: EXPLAIN QUERY PLAN does not require rows, only the schema.
        from corpus.generator import generate_corpus
        be.load_corpus(generate_corpus("C-small", seed=42))
        plan_rows = be.explain_content_barrier(())
        evidence = layer_b_sqlite_exact_lookup(plan_rows)
        assert evidence.verdict == BarrierVerdict.PASS, plan_rows
    finally:
        be.close()


def test_s1_layer_b_verdicts_are_closed_set():
    """Every S1 Layer B verdict is one of the five closed-set classifications (correction 12)."""
    allowed = {v for v in BarrierVerdict}
    for plan in ([], ["(2, 0, 0, 'SCAN assertion_version')"],
                 ["(3, 0, 0, 'SEARCH assertion_version USING INDEX x (version_id=?)')"]):
        assert layer_b_sqlite_exact_lookup(plan).verdict in allowed
