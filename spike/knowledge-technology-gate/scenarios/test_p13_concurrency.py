"""P13: B4 asynchronous cleanup concurrent with interactive work -- the DECISIVE
discriminator between S1-SQLite and S1-PostgreSQL (Phase-1 doc SS8.3/SS16.5).

Correction 4 (Product Architect review of PR #33), with the PA's methodological refinement:
the first P13 wiring used 200 pure-Python reader threads and produced a ~20s p50/p95/p99
cluster that was a CPython GIL serialization ARTIFACT, not SQLite writer contention. The PA
replaced that design with a TWO-PHASE, sequential-foreground methodology (see
`bench/contention.py` for the full rationale):

  * NO hundreds of reader threads. The interactive workload is a sequential foreground loop
    (one worker, one connection) timing each operation individually.
  * ONE background bounded B4 cleanup writer, batched (begin->delete bounded batch->commit->
    optional inter-batch sleep OUTSIDE the txn), confirmed live via an Event before the
    foreground begins measuring, kept active until the foreground stops it.
  * TWO phases -- P13-R (interactive reads during cleanup) and P13-W (interactive writes
    during cleanup, where two writers genuinely contend for SQLite's single write lock) --
    each measured BOTH baseline (no cleanup) and cleanup-active, so the report states the
    delta/ratio attributable to contention, not an absolute number.
  * P13 invents NO new pass/fail threshold. The empirical numbers ARE the result; these
    tests assert only that a VALID two-phase measurement was obtained (classification PASS =
    measurement validity, not a technology verdict), and record busy/timeout/error counts as
    evidence. No technology is selected here.

Both backends run the IDENTICAL logical workload via the ONE shared harness so the SQLite
arm, the PostgreSQL arm, and the bench-runner timed run exercise the same contention shape
rather than drifting copies. SQLite is MEASURED against a real on-disk WAL database (a
`:memory:` db is per-connection, so multi-connection contention needs a shared file).
PostgreSQL runs the identical workload IF a disposable instance is reachable (detect, never
provision -- correction 5); otherwise it is recorded NOT EXECUTED - ENVIRONMENT BLOCKED via
pytest.skip with the named prerequisite, never fabricated (correction 12).
"""
from __future__ import annotations

import sqlite3

import pytest

from bench.contention import run_two_phase_contention
from backends.postgres_env import detect_postgres
from backends.sqlite_backend import SQLITE_PRAGMAS, SQLiteKnowledgeBackend
from corpus.generator import generate_corpus

# C-medium seed=7: 5,000 assertions and 344 suppression rows -- ample real work for the
# foreground reads and a suppression register large enough that the bounded cleanup writer's
# own dedicated pool never collides with corpus rows. Same corpus for both backends so the
# arms are comparable (correction 9).
P13_CORPUS_SIZE = "C-medium"
P13_CORPUS_SEED = 7
# Keep the pytest run tractable: a smaller-but-still-non-underpowered sample proves the
# harness works end to end and produces both phases; the bench runner (bench/run_bench.py)
# collects the full INTERACTIVE_SAMPLE_COUNT numbers for the report.
P13_TEST_SAMPLE_COUNT = 60


def _assert_valid_two_phase(result) -> None:
    """The shared assertions both arms make: a VALID two-phase contention measurement was
    obtained (all four runs completed, both cleanup-active runs saw a confirmed-live writer,
    nothing underpowered). This is measurement validity, NOT a technology verdict."""
    assert result.classification == "PASS", (
        f"{result.backend_name} P13 must obtain a valid two-phase measurement: "
        f"{result.classification} -- {result.note}"
    )
    # All four foreground runs present with real percentiles.
    for phase in (
        result.read_baseline, result.read_cleanup_active,
        result.write_baseline, result.write_cleanup_active,
    ):
        assert phase is not None
        assert phase.samples_completed == phase.samples_requested, (
            f"{phase.label}: only {phase.samples_completed}/{phase.samples_requested} completed"
        )
        assert phase.p50_ms is not None and phase.p95_ms is not None and phase.p99_ms is not None
        assert not phase.underpowered
    # Both cleanup-active runs overlapped a confirmed-live bounded cleanup writer that
    # actually committed batches (proof the measured window was genuinely contended).
    for ev in (result.read_cleanup_evidence, result.write_cleanup_evidence):
        assert ev is not None
        assert ev.confirmed_active, "cleanup writer never confirmed active before measurement"
        assert ev.batches_committed > 0, "cleanup writer committed no batches"
    # Deltas/ratios (the reported contention signal) are computed.
    assert result.read_p95_delta_ms is not None and result.read_p95_ratio is not None
    assert result.write_p95_delta_ms is not None and result.write_p95_ratio is not None


def test_p13_sqlite_two_phase_contention_measurement(tmp_path):
    """SQLite arm, MEASURED. One connection loads the corpus into a real on-disk WAL database
    and closes; the shared harness then opens fresh connections for the sequential foreground
    loops and the background bounded cleanup writer against that SAME file. Under WAL
    (SQLITE_PRAGMAS, correction 8) the two-phase measurement must complete cleanly for both
    interactive reads and interactive writes, baseline and cleanup-active -- classification
    PASS means a valid contention measurement was obtained (not that SQLite 'won' anything;
    P13 selects no technology)."""
    db_path = tmp_path / "p13.db"
    corpus = generate_corpus(P13_CORPUS_SIZE, seed=P13_CORPUS_SEED)

    loader = SQLiteKnowledgeBackend(db_path)
    loader.load_corpus(corpus)
    loader.close()

    result = run_two_phase_contention(
        backend_name="S1-SQLite",
        open_backend=lambda: SQLiteKnowledgeBackend(db_path),
        partition_id=corpus.partitions[0],
        persons=corpus.persons,
        concurrency_config=dict(SQLITE_PRAGMAS),
        sample_count=P13_TEST_SAMPLE_COUNT,
        # SQLITE_BUSY under contention is the operational contention signal (vs a harness
        # bug); it is recorded as busy_count evidence, never hidden by an unbounded retry.
        is_operational_error=lambda e: isinstance(e, sqlite3.OperationalError),
    )

    _assert_valid_two_phase(result)


def test_p13_postgres_two_phase_contention_measurement():
    """PostgreSQL arm, IDENTICAL logical workload -- MEASURED only if a disposable Postgres
    is already reachable, otherwise NOT EXECUTED - ENVIRONMENT BLOCKED.

    Detect, never provision (correction 5): if `detect_postgres()` reports unavailable this
    test SKIPS with the named missing prerequisite -- a reportable NOT EXECUTED status, not a
    pass and not a silent gap. When a DSN is reachable, one owner connection loads the corpus
    into the disposable spike schema, then the harness opens `connect_existing` sessions for
    the foreground loops and the cleanup writer against that SAME loaded schema (never
    dropping it out from under peers), running the same two-phase contention shape as the
    SQLite arm."""
    availability = detect_postgres()
    if not availability.available:
        pytest.skip(
            "S1-PostgreSQL P13 NOT EXECUTED - ENVIRONMENT BLOCKED: "
            f"{availability.reason} (set {availability!r} prerequisite; detect-never-provision)"
        )

    from backends.postgres_backend import PostgresKnowledgeBackend

    corpus = generate_corpus(P13_CORPUS_SIZE, seed=P13_CORPUS_SEED)

    owner = PostgresKnowledgeBackend(availability.dsn)
    try:
        owner.load_corpus(corpus)
        result = run_two_phase_contention(
            backend_name="S1-PostgreSQL",
            open_backend=lambda: PostgresKnowledgeBackend.connect_existing(
                availability.dsn, schema_name=owner.schema_name
            ),
            partition_id=corpus.partitions[0],
            persons=corpus.persons,
            concurrency_config={"session": "autocommit=False, server defaults (correction 8)"},
            sample_count=P13_TEST_SAMPLE_COUNT,
        )
    finally:
        owner.close()  # drops the disposable schema at the very end (correction 4)

    _assert_valid_two_phase(result)
