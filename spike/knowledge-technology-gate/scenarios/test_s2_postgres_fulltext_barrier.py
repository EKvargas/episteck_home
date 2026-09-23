"""S2 (native full-text) PostgreSQL barrier evidence -- correction (Product Architect
directive, closure item 1): the approved PostgreSQL correction includes the native
full-text comparison the original report's §11/§15 explicitly could not produce (SQLite
FTS5 tested and FAILED; PostgreSQL was NOT EXECUTED). This exercises the SAME
authorization-barrier semantics as SQLite S2 -- explicit 3-step (resolve authorized IDs ->
bounded temp table -> full-text match ONLY against that temp table) -- against a live
PostgreSQL tsvector/GIN realization. The barrier design is NOT changed to make PostgreSQL
pass; this test reports whatever the real plan shows.
"""
from __future__ import annotations

import pytest

import json as _json

from backends.common import AuthorizedSet, ContentAccessLog
from backends.instrumentation import (
    BarrierVerdict,
    layer_a_from_log,
    layer_b_postgres,
    layer_b_postgres_exact_lookup,
)
from backends.postgres_env import detect_postgres

AS_OF = 2_000_000_000
DOMAINS = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")
SEARCH_TERM = "prefers-cuisine"  # one of corpus/generator.py's _TOPICS -- matches a bounded, real subset


def _postgres_backend():
    availability = detect_postgres()
    if not availability.available:
        pytest.skip(f"S1/S2-PostgreSQL NOT EXECUTED - ENVIRONMENT BLOCKED: {availability.reason}")
    from backends.postgres_backend import PostgresKnowledgeBackend

    return PostgresKnowledgeBackend(availability.dsn)


def test_s2_postgres_fulltext_barrier_over_real_backend():
    """Drive the real 3-step S2 barrier query against a live PostgreSQL instance:
    1. plan_metadata() resolves the authorized candidate set (never content_text).
    2. fetch_content_fulltext() materializes that set into a bounded temp table and joins
       tsvector @@ plainto_tsquery ONLY against it (backends/postgres_backend.py, unchanged
       -- this test does not alter the barrier's query shape).
    3. Layer A (mandatory) + Layer B (EXPLAIN ANALYZE, corroboration only) are both
       recorded, and this test asserts nothing beyond what those two layers actually show.
    """
    from corpus.generator import generate_corpus

    be = _postgres_backend()
    try:
        corpus = generate_corpus("C-medium", seed=42)
        be.load_corpus(corpus)
        p0 = corpus.persons[0]

        planned = be.plan_metadata(
            partition_id=corpus.partitions[0], subject_person_ids=(p0,),
            domains=DOMAINS, as_of=AS_OF,
        )
        assert planned.candidate_version_ids, "seed corpus produced no candidates for p0"
        authorized = AuthorizedSet(version_ids=planned.candidate_version_ids)

        # Layer A: the REAL fetch_content_fulltext call, fully logged.
        log = ContentAccessLog()
        results = be.fetch_content_fulltext(authorized, query=SEARCH_TERM, log=log)
        layer_a = layer_a_from_log(log)

        print(f"\n--- S2-PostgreSQL Layer A ---")
        print(f"authorized candidate count: {len(authorized.version_ids)}")
        print(f"matched+returned rows: {len(results)}")
        print(f"logical_content_ids_requested: {layer_a.logical_content_ids_requested}")
        print(f"unauthorized_logical_content_ids_requested: "
              f"{layer_a.unauthorized_logical_content_ids_requested}")
        print(f"Layer A verdict: {layer_a.verdict.value}")

        # Every returned row must be inside the authorized set -- the mandatory,
        # application-boundary check independent of what the backend did internally.
        authorized_set = set(authorized.version_ids)
        for r in results:
            assert r["version_id"] in authorized_set, (
                f"S2-PostgreSQL returned an unauthorized version_id: {r['version_id']}"
            )
        assert layer_a.verdict == BarrierVerdict.PASS, (
            "Layer A must pass: the application must never have requested/received an "
            "unauthorized ID, regardless of what Layer B's plan shows"
        )

        # Layer B: real EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) on the identical barrier
        # query shape (temp table -> tsvector @@ plainto_tsquery joined against it).
        plan_text = be.explain_fulltext_barrier(SEARCH_TERM, authorized.version_ids)
        layer_b = layer_b_postgres(plan_text)

        print(f"\n--- S2-PostgreSQL Layer B (corroboration only) ---")
        print(f"plan: {plan_text}")
        print(f"access_pattern_bounded: {layer_b.access_pattern_bounded}")
        print(f"Layer B verdict: {layer_b.verdict.value}")
        print(f"Layer B note: {layer_b.note}")

        combined = (
            BarrierVerdict.FAIL if layer_a.verdict == BarrierVerdict.FAIL
            else BarrierVerdict.FAIL if layer_b.verdict == BarrierVerdict.FAIL
            else BarrierVerdict.UNKNOWN if layer_b.verdict == BarrierVerdict.UNKNOWN
            else BarrierVerdict.PASS
        )
        print(f"\n--- S2-PostgreSQL combined verdict: {combined.value} ---")

        # Both verdicts drawn from the closed set (correction 12).
        assert layer_a.verdict in set(BarrierVerdict)
        assert layer_b.verdict in set(BarrierVerdict)

        # Expected, verified result (Product Architect directive, S2-PostgreSQL closure):
        # Layer A PASS, Layer B FAIL. Confirmed structurally -- the full-text predicate on
        # assertion_version drives the join (evaluated against the whole content table)
        # and the authorized-scope relation only restricts the result afterward, the same
        # "correct final results, wrong internal ordering" failure as SQLite FTS5 (SS11).
        # This assertion documents the expected, already-verified outcome; a future
        # PostgreSQL version or planner change that produces a genuinely different plan
        # shape should make this test fail loudly rather than silently drift.
        assert layer_a.verdict == BarrierVerdict.PASS
        assert layer_b.verdict == BarrierVerdict.FAIL
        assert combined == BarrierVerdict.FAIL
    finally:
        be.close()


def test_s2_postgres_forced_gin_index_still_drives_from_content_table():
    """Corroboration (Product Architect directive): repeat the same barrier query with
    `enable_seqscan = off`, forcing the planner toward the GIN index. This is NOT a barrier
    design change -- it only toggles a planner setting to observe whether the drive-order
    finding is a Seq-Scan-specific planner choice or structural. It is neither: even the
    GIN/Bitmap-driven plan still scans assertion_version (content) first and joins the
    authorized-scope relation second."""
    from corpus.generator import generate_corpus

    be = _postgres_backend()
    try:
        corpus = generate_corpus("C-medium", seed=42)
        be.load_corpus(corpus)
        p0 = corpus.persons[0]
        planned = be.plan_metadata(
            partition_id=corpus.partitions[0], subject_person_ids=(p0,),
            domains=DOMAINS, as_of=AS_OF,
        )
        with be.conn.cursor() as cur:
            cur.execute(f"SET search_path TO {be.schema_name}")
            cur.execute("SET enable_seqscan = off")
            cur.execute("DROP TABLE IF EXISTS pg_temp.probe_forced")
            cur.execute("CREATE TEMP TABLE probe_forced (version_id TEXT PRIMARY KEY)")
            cur.executemany(
                "INSERT INTO pg_temp.probe_forced VALUES (%s)",
                [(v,) for v in planned.candidate_version_ids],
            )
            cur.execute(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT av.version_id FROM assertion_version av
                JOIN pg_temp.probe_forced sc ON sc.version_id = av.version_id
                WHERE av.content_tsv @@ plainto_tsquery('english', %s)
                """,
                (SEARCH_TERM,),
            )
            (plan,) = cur.fetchone()
            cur.execute("SET enable_seqscan = on")  # restore default for any later use of this connection

        evidence = layer_b_postgres(_json.dumps(plan))
        # Structural finding: forcing the GIN index does not change which side drives.
        assert evidence.access_pattern_bounded is False, evidence.note
        assert evidence.verdict == BarrierVerdict.FAIL
    finally:
        be.close()


# --- layer_b_postgres (S2) unit tests: drive-order classification -------------------------
#
# Synthetic EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) fragments, shaped like real output
# captured from the live test above. Per the Product Architect directive: a join merely
# existing is NOT sufficient for PASS -- the classifier must determine which side drives.


def _pg_join_plan(*, outer: dict, inner: dict, join_type: str = "Nested Loop") -> str:
    outer_full = {"Parent Relationship": "Outer", **outer}
    inner_full = {"Parent Relationship": "Inner", **inner}
    return _json.dumps([{
        "Plan": {"Node Type": join_type, "Plans": [outer_full, inner_full]},
        "Execution Time": 5.0,
    }])


def test_s2_postgres_content_seqscan_drives_before_authorized_join_is_fail():
    """Case 1: content Seq Scan (with the FTS predicate) is the OUTER/driving side,
    authorized-scope relation joined afterward -> FAIL. This is the exact shape verified
    against the live PostgreSQL instance."""
    plan = _pg_join_plan(
        outer={
            "Node Type": "Seq Scan", "Relation Name": "assertion_version",
            "Filter": "(content_tsv @@ 'x'::tsquery)",
            "Actual Rows": 474, "Rows Removed by Filter": 4526,
        },
        inner={
            "Node Type": "Index Only Scan", "Relation Name": "authorized_scope_probe",
            "Index Cond": "(version_id = av.version_id)", "Actual Rows": 67,
        },
    )
    evidence = layer_b_postgres(plan)
    assert evidence.access_pattern_bounded is False
    assert evidence.verdict == BarrierVerdict.FAIL


def test_s2_postgres_content_gin_bitmap_drives_before_authorized_join_is_fail():
    """Case 2: content Bitmap Heap Scan using the GIN index is the OUTER/driving side --
    still FAIL, because using the GIN index does not change WHICH side drives (matches the
    forced enable_seqscan=off observation against the live instance)."""
    plan = _pg_join_plan(
        outer={
            "Node Type": "Bitmap Heap Scan", "Relation Name": "assertion_version",
            "Recheck Cond": "(content_tsv @@ 'x'::tsquery)",
            "Actual Rows": 474,
            "Plans": [{
                "Node Type": "Bitmap Index Scan", "Index Name": "idx_av_fts",
                "Index Cond": "(content_tsv @@ 'x'::tsquery)",
            }],
        },
        inner={
            "Node Type": "Index Only Scan", "Relation Name": "authorized_scope_probe",
            "Index Cond": "(version_id = av.version_id)", "Actual Rows": 67,
        },
    )
    evidence = layer_b_postgres(plan)
    assert evidence.access_pattern_bounded is False
    assert evidence.verdict == BarrierVerdict.FAIL


def test_s2_postgres_authorized_scope_drives_content_lookup_second_is_pass():
    """Case 3: the authorized-scope relation is the OUTER/driving side; the full-text
    predicate on assertion_version only ever runs on the INNER side, bounded to rows the
    outer side already restricted to -> PASS. This is the shape the barrier design intends
    but which this PostgreSQL instance's planner never actually chose (see the live test
    above) -- included so the classifier is proven capable of recognizing PASS, not just
    FAIL, and does not always return FAIL regardless of input."""
    plan = _pg_join_plan(
        outer={
            "Node Type": "Seq Scan", "Relation Name": "authorized_scope_probe",
            "Actual Rows": 844,
        },
        inner={
            "Node Type": "Index Scan", "Relation Name": "assertion_version",
            "Index Cond": "(version_id = sc.version_id)",
            "Filter": "(content_tsv @@ 'x'::tsquery)",
            "Actual Rows": 67,
        },
    )
    evidence = layer_b_postgres(plan)
    assert evidence.access_pattern_bounded is True
    assert evidence.verdict == BarrierVerdict.PASS


def test_s2_postgres_ambiguous_join_shape_is_unknown():
    """Case 4: a join node present, but neither side is recognizable (missing Parent
    Relationship labels, or neither side names assertion_version/authorized_scope) ->
    UNKNOWN, never inferred as PASS or FAIL. Also: no plan at all -> UNKNOWN."""
    assert layer_b_postgres("").verdict == BarrierVerdict.UNKNOWN
    assert layer_b_postgres("not json").verdict == BarrierVerdict.UNKNOWN

    unlabeled = _json.dumps([{
        "Plan": {
            "Node Type": "Hash Join",
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "assertion_version"},  # no Parent Relationship
                {"Node Type": "Seq Scan", "Relation Name": "authorized_scope_probe"},
            ],
        },
        "Execution Time": 1.0,
    }])
    evidence = layer_b_postgres(unlabeled)
    assert evidence.verdict == BarrierVerdict.UNKNOWN


def test_s2_postgres_s1_exact_lookup_classifier_is_unaffected():
    """Case 5: the S1 exact-lookup classifier (layer_b_postgres_exact_lookup, correction 11)
    is a SEPARATE function and must be unaffected by this S2 drive-order fix -- its own
    no-join, single-relation PASS case still classifies correctly."""
    plan = _json.dumps([{
        "Plan": {
            "Node Type": "Seq Scan", "Relation Name": "assertion_version",
            "Filter": "(version_id = ANY ('{LINE-1}'::text[]))",
        },
        "Execution Time": 1.0,
    }])
    evidence = layer_b_postgres_exact_lookup(plan)
    assert evidence.access_pattern_bounded is True
    assert evidence.verdict == BarrierVerdict.PASS
