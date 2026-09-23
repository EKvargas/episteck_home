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

from backends.common import AuthorizedSet, ContentAccessLog
from backends.instrumentation import (
    BarrierVerdict,
    layer_a_from_log,
    layer_b_postgres_exact_lookup,
    layer_b_sqlite_exact_lookup,
)
from backends.sqlite_backend import SQLiteKnowledgeBackend

AS_OF = 2_000_000_000


def test_s1_content_barrier_plan_is_index_bounded_over_real_backend(loaded_backend):
    """Over a real loaded backend, the S1 content-lookup plan seeks by index on the
    authorized version IDs -> Layer B PASS (access pattern bounded). Backend-specific plan
    format (SQLite EXPLAIN QUERY PLAN rows vs PostgreSQL EXPLAIN JSON text), same closed-set
    verdict contract on both (correction 12)."""
    backend, corpus = loaded_backend
    p0 = corpus.persons[0]
    planned = backend.plan_metadata(
        partition_id=corpus.partitions[0], subject_person_ids=(p0,),
        domains=("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD"), as_of=AS_OF,
    )
    # Precondition: the query actually produced candidates, else the plan probe is vacuous.
    assert planned.candidate_version_ids, "seed corpus produced no candidates for p0"

    if backend.name.endswith("PostgreSQL"):
        # Condition 1 (Product Architect directive, correction 11): Layer B may only
        # classify PASS if Layer A has ALREADY proved zero unauthorized IDs were requested.
        # Drive the real fetch_content path (not just the EXPLAIN probe) so Layer A is real.
        authz = AuthorizedSet(version_ids=planned.candidate_version_ids)
        log = ContentAccessLog()
        backend.fetch_content(authz, log=log)
        layer_a = layer_a_from_log(log)
        assert layer_a.verdict == BarrierVerdict.PASS, "Layer A must pass before Layer B can"

        plan_text = backend.explain_content_barrier(planned.candidate_version_ids)
        evidence = layer_b_postgres_exact_lookup(plan_text)

        assert evidence.access_pattern_bounded is True, (evidence.note, plan_text)
        assert evidence.verdict == BarrierVerdict.PASS
        return

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


# --- layer_b_postgres_exact_lookup (correction 11, Product Architect directive) -----------
#
# Synthetic EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) fragments, shaped like real output from
# this spike's PostgreSQL 15.8 instance (see backends/postgres_backend.py::
# explain_content_barrier). Unit-level, no live database needed -- mirrors how the existing
# SQLite Layer B unit tests above use synthetic plan strings.

import json as _json  # local import: test-only, keeps the module's real imports minimal


def _pg_plan(plan_node: dict) -> str:
    return _json.dumps([{"Plan": plan_node, "Execution Time": 0.04}])


def test_s1_postgres_seq_scan_with_exact_id_filter_passes():
    """A Seq Scan over assertion_version whose Filter is directly `version_id = ANY(...)` is
    PASS -- planner cost choice, not a security failure (correction 11's core finding: this
    is the actual, repeatable shape PostgreSQL 15.8 produces at C-small/medium/large)."""
    plan = _pg_plan({
        "Node Type": "Seq Scan", "Relation Name": "assertion_version",
        "Filter": "(version_id = ANY ('{LINE-1,LINE-2}'::text[]))",
        "Rows Removed by Filter": 70, "Actual Rows": 30,
    })
    evidence = layer_b_postgres_exact_lookup(plan)
    assert evidence.access_pattern_bounded is True
    assert evidence.verdict == BarrierVerdict.PASS


def test_s1_postgres_index_scan_with_exact_id_filter_passes():
    """An Index/Bitmap scan with an Index Cond directly on version_id is equally PASS -- the
    verdict must not depend on which physical access method the planner happened to choose."""
    plan = _pg_plan({
        "Node Type": "Index Scan", "Relation Name": "assertion_version",
        "Index Cond": "(version_id = ANY ('{LINE-1,LINE-2}'::text[]))",
        "Actual Rows": 2,
    })
    evidence = layer_b_postgres_exact_lookup(plan)
    assert evidence.access_pattern_bounded is True
    assert evidence.verdict == BarrierVerdict.PASS

    bitmap_plan = _pg_plan({
        "Node Type": "Bitmap Heap Scan", "Relation Name": "assertion_version",
        "Filter": "(version_id = ANY ('{LINE-1,LINE-2}'::text[]))",
        "Actual Rows": 2,
    })
    evidence2 = layer_b_postgres_exact_lookup(bitmap_plan)
    assert evidence2.access_pattern_bounded is True
    assert evidence2.verdict == BarrierVerdict.PASS


def test_s1_postgres_missing_or_broadened_id_predicate_is_not_pass():
    """A scan whose predicate does not reference version_id at all cannot confirm the
    restriction is the authorized-ID set -- UNKNOWN, never a guessed PASS. A plan that joins
    in a second relation before restricting (candidate set broadened) is FAIL."""
    no_id_predicate = _pg_plan({
        "Node Type": "Seq Scan", "Relation Name": "assertion_version",
        "Filter": "(lifecycle_state = 'ADMITTED'::text)",
    })
    evidence = layer_b_postgres_exact_lookup(no_id_predicate)
    assert evidence.access_pattern_bounded is None
    assert evidence.verdict == BarrierVerdict.UNKNOWN

    broadened_by_join = _pg_plan({
        "Node Type": "Hash Join",
        "Plans": [
            {"Node Type": "Seq Scan", "Relation Name": "assertion_version"},
            {"Node Type": "Seq Scan", "Relation Name": "assertion_subject",
             "Filter": "(version_id = ANY ('{LINE-1}'::text[]))"},
        ],
    })
    evidence2 = layer_b_postgres_exact_lookup(broadened_by_join)
    assert evidence2.access_pattern_bounded is False
    assert evidence2.verdict == BarrierVerdict.FAIL


def test_s1_postgres_ambiguous_plan_is_unknown():
    """No plan, or a plan shape this function does not confidently recognize (multiple
    relations, unexpected structure), resolves to UNKNOWN -- never inferred as PASS."""
    assert layer_b_postgres_exact_lookup("").verdict == BarrierVerdict.UNKNOWN
    assert layer_b_postgres_exact_lookup("not json").verdict == BarrierVerdict.UNKNOWN

    fts_touching = _pg_plan({
        "Node Type": "Bitmap Heap Scan", "Relation Name": "assertion_version",
        "Filter": "(version_id = ANY ('{LINE-1}'::text[]))",
        "Index Cond": "(content_tsv @@ plainto_tsquery('english', 'x'))",
    })
    evidence = layer_b_postgres_exact_lookup(fts_touching)
    assert evidence.access_pattern_bounded is False
    assert evidence.verdict == BarrierVerdict.FAIL


def test_s1_postgres_layer_b_verdicts_are_closed_set():
    """Every S1-PostgreSQL Layer B verdict is one of the closed-set classifications
    (correction 12), same contract as the SQLite side."""
    allowed = {v for v in BarrierVerdict}
    seq_scan = _pg_plan({
        "Node Type": "Seq Scan", "Relation Name": "assertion_version",
        "Filter": "(version_id = ANY ('{LINE-1}'::text[]))",
    })
    for plan in ("", "not json", seq_scan):
        assert layer_b_postgres_exact_lookup(plan).verdict in allowed
