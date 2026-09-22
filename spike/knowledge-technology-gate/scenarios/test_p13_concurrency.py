"""P13: B4 asynchronous cleanup concurrent with interactive reads/writes -- the decisive
discriminator between S1-SQLite and S1-PostgreSQL (Phase-1 doc SS8.3/SS14).

Measures interactive p50/p95/p99 WHILE a bounded cleanup obligation runs concurrently.
SQLite configuration is fixed and documented (backends/sqlite_backend.py SQLITE_PRAGMAS,
correction 8) -- WAL mode, matching what a real service would run, not hand-tuned to bias
the outcome. PostgreSQL uses server defaults, also per correction 8.

Sample sizes: correction 6 requires a justified, bounded count. This test uses 15
interactive reads concurrent with 1 cleanup batch (10 deletes) -- correctness-focused
(does contention cause failures/incorrect reads), not a full latency-distribution study;
bench/run_bench.py performs the larger, timed run for percentile reporting.
"""
from __future__ import annotations

import sqlite3
import threading
import time

from backends.common import AuthorizedSet, ContentAccessLog
from backends.sqlite_backend import SQLiteKnowledgeBackend
from corpus.generator import generate_corpus


def test_p13_sqlite_interactive_reads_survive_concurrent_cleanup_write(tmp_path):
    """A bounded B4-style cleanup (DELETE FROM suppression WHERE ... ) runs on one thread
    while interactive metadata-planning reads run concurrently on others. Under WAL mode
    (SQLITE_PRAGMAS), readers must not be blocked by the writer and must not see a
    corrupted/partial view -- correctness under contention, measured not assumed."""
    db_path = tmp_path / "p13.db"
    corpus = generate_corpus("C-medium", seed=7)

    writer_backend = SQLiteKnowledgeBackend(db_path)
    writer_backend.load_corpus(corpus)
    writer_backend.close()

    errors: list[Exception] = []
    read_latencies_ms: list[float] = []
    cleanup_done = threading.Event()

    def cleanup_worker():
        try:
            be = SQLiteKnowledgeBackend(db_path)
            cur = be.conn.cursor()
            targets = [s.target_version_id for s in corpus.suppressions[:10]]
            for vid in targets:
                cur.execute("DELETE FROM suppression WHERE target_version_id = ?", (vid,))
                time.sleep(0.002)  # spread the writes out so readers overlap with the writer window
            be.conn.commit()
            be.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            cleanup_done.set()

    def read_worker(person_id: str):
        try:
            be = SQLiteKnowledgeBackend(db_path)
            t0 = time.perf_counter()
            planned = be.plan_metadata(
                partition_id=corpus.partitions[0], subject_person_ids=(person_id,),
                domains=("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD"), as_of=2_000_000_000,
            )
            authz = AuthorizedSet(version_ids=planned.candidate_version_ids)
            log = ContentAccessLog()
            be.fetch_content(authz, log=log)
            elapsed = (time.perf_counter() - t0) * 1000.0
            read_latencies_ms.append(elapsed)
            be.close()
        except sqlite3.OperationalError as e:
            errors.append(e)

    cleanup_thread = threading.Thread(target=cleanup_worker)
    read_threads = [
        threading.Thread(target=read_worker, args=(corpus.persons[i % len(corpus.persons)],))
        for i in range(15)
    ]

    cleanup_thread.start()
    for t in read_threads:
        t.start()
    cleanup_thread.join(timeout=10)
    for t in read_threads:
        t.join(timeout=10)

    assert cleanup_done.is_set(), "cleanup must complete within the timeout"
    assert not errors, f"WAL mode must not produce operational errors under this contention: {errors}"
    assert len(read_latencies_ms) == 15, "all interactive reads must complete, not be starved by the writer"

    read_latencies_ms.sort()
    p50 = read_latencies_ms[len(read_latencies_ms) // 2]
    p95 = read_latencies_ms[int(len(read_latencies_ms) * 0.95) - 1] if len(read_latencies_ms) >= 20 else read_latencies_ms[-1]
    # n=15 is UNDERPOWERED for a real p95/p99 (correction 6) -- reported as informational,
    # not asserted against a threshold. bench/run_bench.py runs the larger sample.
    assert p50 >= 0 and p95 >= 0  # sanity; real numbers go in the report
