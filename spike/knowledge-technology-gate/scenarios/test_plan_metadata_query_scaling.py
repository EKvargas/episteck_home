"""Regression test for correction 13 (Product Architect directive, PR #33 review).

The original `plan_metadata()` issued one subject query + one domain query PER CANDIDATE
(N+1) -- 20,201 SQL statements for 10,100 candidates at C-large, and the dominant cost in
both the C-large metadata-planning benchmark (previously misread as index-absence /
corpus-size-driven storage cost) and P13's C-medium read phase (1,723 statements for 861
candidates, previously misread as a SQLite-vs-PostgreSQL performance difference). Both
backends now batch subject/domain lookups via `backends.common.chunk_ids` (fixed batch
size, correction 13). This test proves query count grows O(number of batches), NOT
O(number of candidates) -- it must FAIL if the N+1 pattern ever returns.
"""
from __future__ import annotations

from backends.common import METADATA_BATCH_SIZE
from backends.postgres_env import detect_postgres
from backends.sqlite_backend import SQLiteKnowledgeBackend
from corpus.generator import generate_corpus

AS_OF = 2_000_000_000
DOMAINS = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")


def _expected_max_queries(candidate_count: int) -> int:
    """1 query for the candidate-ID lookup itself, plus 2 queries (subjects, domains) PER
    BATCH -- not per candidate. A tiny constant is added for margin/rounding; this is a
    ceiling, not an exact count, so the test cannot become flaky on off-by-one batch edges."""
    import math

    batches = max(1, math.ceil(candidate_count / METADATA_BATCH_SIZE))
    return 1 + (2 * batches) + 2


def test_sqlite_plan_metadata_query_count_scales_with_batches_not_candidates():
    """SQLite: trace every SQL statement plan_metadata() issues (correction 3's
    set_trace_callback mechanism, already built into SQLiteKnowledgeBackend) and assert the
    count is bounded by batch count, not candidate count. C-large produces ~10,100
    candidates but must NOT produce anywhere near 10,100 subject/domain queries."""
    be = SQLiteKnowledgeBackend()
    try:
        corpus = generate_corpus("C-large", seed=42)
        be.load_corpus(corpus)
        p0 = corpus.persons[0]

        be.enable_trace()
        planned = be.plan_metadata(
            partition_id=corpus.partitions[0], subject_person_ids=(p0,),
            domains=DOMAINS, as_of=AS_OF,
        )
        query_count = len(be._query_log)  # noqa: SLF001 -- test-only introspection
        be.disable_trace()

        candidate_count = len(planned.candidate_version_ids)
        # Precondition: this corpus size must actually produce a large candidate set,
        # else the O(candidates) vs O(batches) distinction this test exists to catch is
        # never exercised.
        assert candidate_count > METADATA_BATCH_SIZE, (
            f"C-large produced only {candidate_count} candidates; test cannot "
            "distinguish O(batches) from O(candidates) without a candidate set larger "
            "than one batch"
        )

        ceiling = _expected_max_queries(candidate_count)
        assert query_count <= ceiling, (
            f"plan_metadata issued {query_count} SQL statements for {candidate_count} "
            f"candidates (expected <= {ceiling} under O(batches) batching) -- the N+1 "
            "per-candidate pattern appears to have returned"
        )
        # And the inverse: prove it is NOT O(candidates) -- if the N+1 pattern were
        # present, query_count would be >= 2 * candidate_count.
        assert query_count < 2 * candidate_count, (
            f"plan_metadata issued {query_count} SQL statements for {candidate_count} "
            "candidates -- this is O(candidates)-shaped, the exact N+1 pattern correction "
            "13 removed"
        )
    finally:
        be.close()


def test_postgres_plan_metadata_query_count_scales_with_batches_not_candidates():
    """PostgreSQL: count cursor.execute() calls plan_metadata() issues (psycopg has no
    stdlib-equivalent trace callback, so this counts at the Python call-site instead of
    relying on server-side tracing) and assert the same O(batches) bound. Same corpus, same
    logical assertion as the SQLite test above -- one shared regression, two backends."""
    availability = detect_postgres()
    if not availability.available:
        import pytest

        pytest.skip(f"S1-PostgreSQL NOT EXECUTED - ENVIRONMENT BLOCKED: {availability.reason}")

    from backends.postgres_backend import PostgresKnowledgeBackend

    be = PostgresKnowledgeBackend(availability.dsn)
    try:
        corpus = generate_corpus("C-large", seed=42)
        be.load_corpus(corpus)
        p0 = corpus.persons[0]

        real_cursor_factory = be.conn.cursor
        call_count = {"n": 0}

        class _CountingCursor:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, *a, **kw):
                call_count["n"] += 1
                return self._inner.execute(*a, **kw)

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._inner.close()
                return False

        be.conn.cursor = lambda *a, **kw: _CountingCursor(real_cursor_factory(*a, **kw))
        try:
            planned = be.plan_metadata(
                partition_id=corpus.partitions[0], subject_person_ids=(p0,),
                domains=DOMAINS, as_of=AS_OF,
            )
        finally:
            be.conn.cursor = real_cursor_factory

        candidate_count = len(planned.candidate_version_ids)
        assert candidate_count > METADATA_BATCH_SIZE, (
            f"C-large produced only {candidate_count} candidates; test cannot "
            "distinguish O(batches) from O(candidates) without a candidate set larger "
            "than one batch"
        )

        query_count = call_count["n"]
        ceiling = _expected_max_queries(candidate_count)
        assert query_count <= ceiling, (
            f"plan_metadata issued {query_count} SQL statements for {candidate_count} "
            f"candidates (expected <= {ceiling} under O(batches) batching) -- the N+1 "
            "per-candidate pattern appears to have returned"
        )
        assert query_count < 2 * candidate_count, (
            f"plan_metadata issued {query_count} SQL statements for {candidate_count} "
            "candidates -- this is O(candidates)-shaped, the exact N+1 pattern correction "
            "13 removed"
        )
    finally:
        be.close()
