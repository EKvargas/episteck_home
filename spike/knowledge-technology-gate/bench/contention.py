"""P13 shared contention harness -- two-phase methodology (correction 4, Product Architect
refinement of the PR #33 review).

P13 is the DECISIVE S1-SQLite vs S1-PostgreSQL discriminator (Phase-1 SS8.3/SS16.5): a B4
asynchronous cleanup obligation runs concurrently with interactive work, and SQLite's
single-writer behavior "either contends measurably or does not -- this is measured, not
predicted." The FIRST wiring of this harness used 200 pure-Python reader threads and
produced a ~20s p50/p95/p99 cluster that was a CPython GIL serialization ARTIFACT, not
SQLite writer contention -- exactly the benchmark misconfiguration correction 8 warns
against. The Product Architect's refinement replaces that design entirely:

  * NO hundreds of Python reader threads. The interactive workload is a SEQUENTIAL
    foreground loop (one worker, one connection) issuing >= INTERACTIVE_SAMPLE_COUNT
    operations back-to-back and timing each individually. Thread scheduling never enters
    the measured path.
  * ONE background bounded cleanup WRITER thread, running batched transactions:
    begin -> delete/insert a bounded batch -> commit -> optional inter-batch sleep ->
    next transaction. It NEVER sleeps while holding a transaction merely to keep cleanup
    active (benchmark hygiene). To keep the writer active for the whole measurement window
    without artificially lengthening lock ownership, it operates on its OWN dedicated pool
    of suppression rows and loops delete->reinsert in bounded committed batches until the
    foreground signals it has collected enough samples.
  * SYNCHRONIZATION: the foreground measurement starts only after the cleanup writer has
    confirmed (via an Event) that it has actually begun committing batches, and the writer
    keeps running until the foreground sets a stop Event -- so the measured window is
    genuinely cleanup-active, verified, not assumed.
  * TWO PHASES, because Phase-1 is meant to discriminate concurrent reads AND writes, and
    a read-only WAL test may not exercise SQLite's single-writer constraint:
      - P13-R: interactive READS (metadata-planning + bounded content fetch) during cleanup.
      - P13-W: interactive WRITES (a small representative suppression-register write) during
        cleanup -- two writers now genuinely contend for SQLite's single write lock.
    Each phase is measured BOTH baseline (no cleanup active) AND cleanup-active, so the
    report can state the delta/ratio attributable to contention rather than an absolute
    number.
  * NO new pass/fail threshold is invented. P13's job is empirical evidence: report
    baseline vs cleanup-active p50/p95/p99, delta/ratio, and busy/timeout/error counts for
    each phase. SQLITE_BUSY / timeout is recorded as evidence, never hidden with unbounded
    retries.

This module is pure orchestration over backends the CALLER constructs and tears down; it
never provisions, installs, or configures a database (correction 5). SQLite is MEASURED
against a real on-disk WAL file (a `:memory:` db is per-connection, so multi-connection
contention needs a shared file). A PostgreSQL caller passes factories that open connections
to an ALREADY-reachable disposable instance; if none is reachable the caller records
NOT EXECUTED - ENVIRONMENT BLOCKED and never invokes the workload.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from backends.common import AuthorizedSet, ContentAccessLog, KnowledgeBackend

# --- Fixed, justified sample sizes (correction 6), set BEFORE the run --------------------
# The interactive foreground loop issues INTERACTIVE_SAMPLE_COUNT sequential operations and
# times each. 200 >= the correction-6 non-underpowered threshold (30) with plenty of margin,
# so the reported p95/p99 index is a real observation, not the max. Each op is a local
# backend operation (no injected ~112ms Home crossing in the P13 path), so 200 sequential
# ops over a C-medium corpus complete in well under a minute per measured run.
INTERACTIVE_SAMPLE_COUNT = 200

# --- The B4 cleanup obligation (the background writer) -----------------------------------
# The writer owns a dedicated pool of suppression rows keyed `P13_CLEANUP_KEY_PREFIX*` so it
# never deletes corpus rows out from under the foreground and never collides with the
# foreground writer's own row keys. It deletes them in bounded batches of
# CLEANUP_BATCH_SIZE per committed transaction, reinserting a batch when the pool is empty,
# and loops until the foreground stops it. CLEANUP_INTER_BATCH_SLEEP_S is the ONLY sleep and
# it is OUTSIDE any transaction (commit-then-sleep), so lock ownership is never artificially
# lengthened -- the sleep only paces batch cadence so the writer's active window comfortably
# spans the foreground's measurement window.
P13_CLEANUP_KEY_PREFIX = "_P13CLEANUP_"
CLEANUP_POOL_SIZE = 200
CLEANUP_BATCH_SIZE = 10
CLEANUP_INTER_BATCH_SLEEP_S = 0.001

# The foreground interactive WRITE (P13-W): a small representative write against the same
# suppression register the cleanup writer touches -- one INSERT of a dedicated
# `P13_WRITE_KEY_PREFIX*` row, then a DELETE of it, each its own committed transaction, so
# the two writers genuinely contend for SQLite's single write lock while the corpus itself
# is left unmutated across samples.
P13_WRITE_KEY_PREFIX = "_P13WRITE_"

JOIN_TIMEOUT_S = 120.0
CLEANUP_START_TIMEOUT_S = 30.0
DOMAINS_ALL = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")
AS_OF = 2_000_000_000
UNDERPOWERED_THRESHOLD = 30  # mirrors bench/run_bench.py; kept local to avoid an import cycle


@dataclass
class PhaseMeasurement:
    """One measured foreground run: baseline OR cleanup-active, reads OR writes.

    Percentiles are MEASURED backend-local latencies (correction 7 MEASURED); never composed
    with the calibrated Home crossing. `busy_count`/`timeout_count`/`error_count` are the
    contention-signal evidence: recorded, never hidden by unbounded retries.
    """

    label: str  # e.g. "baseline_read", "cleanup_active_read", "baseline_write", ...
    cleanup_active: bool
    operation: str  # "read" | "write"
    samples_requested: int
    samples_completed: int = 0  # set by _finalize once the loop has run
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    busy_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    underpowered: bool = False


@dataclass
class CleanupEvidence:
    """What the background B4 cleanup writer actually did during a cleanup-active run --
    proof the measured window was genuinely contended, plus the exact transaction/batch
    shape the report must state."""

    confirmed_active: bool = False
    batches_committed: int = 0
    rows_deleted: int = 0
    duration_s: float | None = None
    batch_size: int = CLEANUP_BATCH_SIZE
    inter_batch_sleep_s: float = CLEANUP_INTER_BATCH_SLEEP_S
    transaction_shape: str = (
        "begin -> DELETE bounded batch of suppression rows -> COMMIT -> "
        "inter-batch sleep (OUTSIDE txn) -> repeat; reinsert pool when drained"
    )
    errors: list[str] = field(default_factory=list)


@dataclass
class ContentionResult:
    """Closed-set-classified (correction 12) P13 two-phase contention outcome for ONE backend.

    `classification` is exactly one of PASS / FAIL / UNKNOWN - INSUFFICIENT EVIDENCE /
    NOT EXECUTED - ENVIRONMENT BLOCKED / N/A. P13 invents NO new pass/fail threshold: the
    empirical numbers (baseline vs cleanup-active percentiles, deltas, busy/timeout counts)
    ARE the result. `classification` here reflects only whether the measurement itself ran
    cleanly and collected a non-underpowered sample -- PASS means "a valid contention
    measurement was obtained for both phases, both baseline and cleanup-active", FAIL means
    the harness could not obtain the measurement (errors, starvation, cleanup never
    confirmed active), UNKNOWN means underpowered. The technology comparison is left to the
    report; no technology is selected here.
    """

    backend_name: str
    classification: str
    concurrency_config: dict
    read_baseline: PhaseMeasurement | None = None
    read_cleanup_active: PhaseMeasurement | None = None
    write_baseline: PhaseMeasurement | None = None
    write_cleanup_active: PhaseMeasurement | None = None
    read_cleanup_evidence: CleanupEvidence | None = None
    write_cleanup_evidence: CleanupEvidence | None = None
    read_p95_delta_ms: float | None = None
    read_p95_ratio: float | None = None
    write_p95_delta_ms: float | None = None
    write_p95_ratio: float | None = None
    note: str = ""


def _percentiles(samples: list[float]) -> tuple[float, float, float]:
    s = sorted(samples)
    n = len(s)
    return s[n // 2], s[min(n - 1, int(n * 0.95))], s[min(n - 1, int(n * 0.99))]


# --- Backend-specific SQL, kept in ONE tiny symmetric place so the arms stay comparable ---

def _cleanup_delete_batch(backend: KnowledgeBackend, target_version_ids: list[str]) -> int:
    """Delete a bounded batch of suppression rows in ONE committed transaction. Returns the
    number of rows the batch removed. The ONLY backend-specific DELETE spot; same logical
    statement and same targets for both arms."""
    conn = backend.conn  # type: ignore[attr-defined]
    if backend.name.endswith("SQLite"):
        cur = conn.cursor()
        deleted = 0
        for vid in target_version_ids:
            cur.execute("DELETE FROM suppression WHERE target_version_id = ?", (vid,))
            deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
        return deleted
    else:  # PostgreSQL
        schema = getattr(backend, "schema_name", None)
        deleted = 0
        with conn.cursor() as cur:
            if schema:
                cur.execute(f"SET search_path TO {schema}")
            for vid in target_version_ids:
                cur.execute("DELETE FROM suppression WHERE target_version_id = %s", (vid,))
                deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
        return deleted


def _insert_suppression_batch(
    backend: KnowledgeBackend, partition_id: str, target_version_ids: list[str]
) -> None:
    """Insert a batch of suppression rows in ONE committed transaction (used to seed and to
    reinsert the cleanup writer's dedicated pool, and for the P13-W foreground write). Same
    logical statement for both arms."""
    conn = backend.conn  # type: ignore[attr-defined]
    now = AS_OF
    if backend.name.endswith("SQLite"):
        cur = conn.cursor()
        for vid in target_version_ids:
            cur.execute(
                "INSERT OR REPLACE INTO suppression "
                "(target_version_id, partition_id, reason_family, effective_at) VALUES (?,?,?,?)",
                (vid, partition_id, "P13_SYNTHETIC", now),
            )
        conn.commit()
    else:  # PostgreSQL
        schema = getattr(backend, "schema_name", None)
        with conn.cursor() as cur:
            if schema:
                cur.execute(f"SET search_path TO {schema}")
            for vid in target_version_ids:
                cur.execute(
                    "INSERT INTO suppression "
                    "(target_version_id, partition_id, reason_family, effective_at) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT (target_version_id) DO NOTHING",
                    (vid, partition_id, "P13_SYNTHETIC", now),
                )
        conn.commit()


def _delete_suppression_one(backend: KnowledgeBackend, target_version_id: str) -> None:
    """Delete exactly one suppression row in its own committed transaction (P13-W foreground
    cleanup of its representative write)."""
    _cleanup_delete_batch(backend, [target_version_id])


def _safe_close(backend: KnowledgeBackend, errors: list[str], where: str) -> None:
    # Prefer a per-session close that does NOT tear down shared schema/state: PostgreSQL's
    # `connect_existing` sessions expose `close_session()`; SQLite file connections have no
    # shared-DDL teardown, so `close()` is correct there. Using `close()` on a PostgreSQL
    # contention session would DROP the schema out from under its concurrent peers.
    close = getattr(backend, "close_session", None) or backend.close
    try:
        close()
    except Exception as e:  # noqa: BLE001 -- a close failure is worth recording, not raising
        errors.append(f"{where}: {type(e).__name__}: {e}")


# --- The background cleanup writer -------------------------------------------------------

class _CleanupWriter:
    """One background bounded B4 cleanup writer. Batched, hygienic (no sleep-in-txn), keyed
    to its own dedicated pool, loops until stopped, and reports exactly what it did."""

    def __init__(
        self,
        *,
        open_backend: Callable[[], KnowledgeBackend],
        partition_id: str,
        is_operational_error: Callable[[Exception], bool],
    ):
        self._open_backend = open_backend
        self._partition_id = partition_id
        self._is_operational_error = is_operational_error
        self._pool = [f"{P13_CLEANUP_KEY_PREFIX}{i}" for i in range(CLEANUP_POOL_SIZE)]
        self.started = threading.Event()  # set once the FIRST batch has committed
        self._stop = threading.Event()
        self.evidence = CleanupEvidence()
        self._thread = threading.Thread(target=self._run, name="p13-cleanup-writer")

    def _run(self) -> None:
        be = None
        t0 = time.perf_counter()
        try:
            be = self._open_backend()
            # Seed the dedicated pool so the writer deletes ITS OWN rows, never the corpus's.
            _insert_suppression_batch(be, self._partition_id, list(self._pool))
            remaining = list(self._pool)
            while not self._stop.is_set():
                if not remaining:
                    # Reinsert the whole pool in one committed txn, then continue deleting.
                    _insert_suppression_batch(be, self._partition_id, list(self._pool))
                    remaining = list(self._pool)
                batch = remaining[:CLEANUP_BATCH_SIZE]
                remaining = remaining[CLEANUP_BATCH_SIZE:]
                deleted = _cleanup_delete_batch(be, batch)  # begin->delete batch->COMMIT
                self.evidence.batches_committed += 1
                self.evidence.rows_deleted += deleted
                if not self.started.is_set():
                    self.started.set()  # foreground may begin measuring: cleanup is live
                # Inter-batch sleep is OUTSIDE the transaction (commit already happened);
                # it paces cadence, it does NOT hold a lock (benchmark hygiene).
                time.sleep(CLEANUP_INTER_BATCH_SLEEP_S)
        except Exception as e:  # noqa: BLE001 -- any writer failure is a reportable outcome
            label = "operational" if self._is_operational_error(e) else "unexpected"
            self.evidence.errors.append(f"cleanup({label}): {type(e).__name__}: {e}")
            self.started.set()  # unblock the foreground; it will see the recorded error
        finally:
            self.evidence.duration_s = round(time.perf_counter() - t0, 4)
            # Best-effort tidy of the dedicated pool so it never lingers in the shared db.
            if be is not None:
                try:
                    _cleanup_delete_batch(be, list(self._pool))
                except Exception:  # noqa: BLE001 -- teardown tidy only
                    pass
                _safe_close(be, self.evidence.errors, "cleanup-close")

    def start_and_confirm_active(self) -> bool:
        self._thread.start()
        active = self.started.wait(timeout=CLEANUP_START_TIMEOUT_S)
        self.evidence.confirmed_active = active and not self.evidence.errors
        return self.evidence.confirmed_active

    def stop_and_join(self) -> None:
        self._stop.set()
        self._thread.join(timeout=JOIN_TIMEOUT_S)


# --- The sequential foreground loops -----------------------------------------------------

def _measure_reads(
    *,
    open_backend: Callable[[], KnowledgeBackend],
    partition_id: str,
    persons: tuple[str, ...],
    sample_count: int,
    cleanup_active: bool,
    is_operational_error: Callable[[Exception], bool],
) -> PhaseMeasurement:
    """Sequential foreground READ loop: one connection, `sample_count` metadata-planning +
    bounded-content-fetch reads issued back-to-back, each individually timed. No reader
    threads."""
    label = "cleanup_active_read" if cleanup_active else "baseline_read"
    m = PhaseMeasurement(
        label=label, cleanup_active=cleanup_active, operation="read",
        samples_requested=sample_count,
    )
    latencies: list[float] = []
    be = None
    try:
        be = open_backend()
        for i in range(sample_count):
            person = persons[i % len(persons)]
            t0 = time.perf_counter()
            try:
                planned = be.plan_metadata(
                    partition_id=partition_id, subject_person_ids=(person,),
                    domains=DOMAINS_ALL, as_of=AS_OF,
                )
                authz = AuthorizedSet(version_ids=planned.candidate_version_ids)
                log = ContentAccessLog()
                be.fetch_content(authz, log=log)
            except Exception as e:  # noqa: BLE001
                _classify_op_error(e, m, is_operational_error)
                continue
            latencies.append((time.perf_counter() - t0) * 1000.0)
    except Exception as e:  # noqa: BLE001 -- failure opening the read connection
        m.errors.append(f"read-setup: {type(e).__name__}: {e}")
        m.error_count += 1
    finally:
        if be is not None:
            _safe_close(be, m.errors, "read-close")
    _finalize(m, latencies)
    return m


def _measure_writes(
    *,
    open_backend: Callable[[], KnowledgeBackend],
    partition_id: str,
    sample_count: int,
    cleanup_active: bool,
    is_operational_error: Callable[[Exception], bool],
) -> PhaseMeasurement:
    """Sequential foreground WRITE loop: one connection issues `sample_count` small
    representative writes back-to-back, each individually timed. One write = INSERT a
    dedicated suppression row + DELETE it, each its own committed transaction, so the corpus
    is unmutated across samples but the foreground genuinely holds SQLite's single write lock
    in contention with the background cleanup writer."""
    label = "cleanup_active_write" if cleanup_active else "baseline_write"
    m = PhaseMeasurement(
        label=label, cleanup_active=cleanup_active, operation="write",
        samples_requested=sample_count,
    )
    latencies: list[float] = []
    be = None
    try:
        be = open_backend()
        for i in range(sample_count):
            vid = f"{P13_WRITE_KEY_PREFIX}{i}"
            t0 = time.perf_counter()
            try:
                _insert_suppression_batch(be, partition_id, [vid])
                _delete_suppression_one(be, vid)
            except Exception as e:  # noqa: BLE001
                _classify_op_error(e, m, is_operational_error)
                continue
            latencies.append((time.perf_counter() - t0) * 1000.0)
    except Exception as e:  # noqa: BLE001 -- failure opening the write connection
        m.errors.append(f"write-setup: {type(e).__name__}: {e}")
        m.error_count += 1
    finally:
        if be is not None:
            _safe_close(be, m.errors, "write-close")
    _finalize(m, latencies)
    return m


def _classify_op_error(
    e: Exception, m: PhaseMeasurement, is_operational_error: Callable[[Exception], bool]
) -> None:
    """Record a per-operation failure as busy/timeout/error evidence. NO retry: a failed op
    is recorded and the loop moves on -- P13 does not hide SQLITE_BUSY/timeout behind an
    unbounded retry (benchmark hygiene)."""
    text = f"{type(e).__name__}: {e}".lower()
    if "busy" in text or "locked" in text:
        m.busy_count += 1
    elif "timeout" in text or "timed out" in text:
        m.timeout_count += 1
    else:
        m.error_count += 1
    if is_operational_error(e):
        m.errors.append(f"op(operational): {type(e).__name__}: {e}")
    else:
        m.errors.append(f"op(unexpected): {type(e).__name__}: {e}")


def _finalize(m: PhaseMeasurement, latencies: list[float]) -> None:
    m.samples_completed = len(latencies)
    if latencies:
        p50, p95, p99 = _percentiles(latencies)
        m.p50_ms = round(p50, 3)
        m.p95_ms = round(p95, 3)
        m.p99_ms = round(p99, 3)
    m.underpowered = len(latencies) < UNDERPOWERED_THRESHOLD


def _run_phase_with_cleanup(
    *,
    measure: Callable[[bool], PhaseMeasurement],
    open_backend: Callable[[], KnowledgeBackend],
    partition_id: str,
    is_operational_error: Callable[[Exception], bool],
) -> tuple[PhaseMeasurement, PhaseMeasurement, CleanupEvidence]:
    """Run one phase (read or write) twice: baseline (no cleanup), then cleanup-active with a
    confirmed-live background cleanup writer. Returns (baseline, cleanup_active, evidence)."""
    baseline = measure(False)

    writer = _CleanupWriter(
        open_backend=open_backend, partition_id=partition_id,
        is_operational_error=is_operational_error,
    )
    confirmed = writer.start_and_confirm_active()
    try:
        active = measure(True)
    finally:
        writer.stop_and_join()
    if not confirmed:
        active.errors.append(
            "cleanup writer did not confirm active before the measurement window; "
            "cleanup-active numbers are not a trustworthy contention measurement"
        )
    return baseline, active, writer.evidence


def run_two_phase_contention(
    *,
    backend_name: str,
    open_backend: Callable[[], KnowledgeBackend],
    partition_id: str,
    persons: tuple[str, ...],
    concurrency_config: dict,
    sample_count: int = INTERACTIVE_SAMPLE_COUNT,
    is_operational_error: Callable[[Exception], bool] = lambda e: True,
) -> ContentionResult:
    """Run the full two-phase P13 contention measurement against a caller-provided backend.

    `open_backend()` returns a FRESH connection to the SAME already-loaded, already-reachable
    database; the caller loaded the corpus and owns final teardown. Measures four foreground
    runs -- baseline-read, cleanup-active-read, baseline-write, cleanup-active-write -- each a
    sequential loop of `sample_count` individually-timed operations, with cleanup-active runs
    overlapping a confirmed-live background bounded cleanup writer.

    Returns a closed-set-classified ContentionResult carrying every reporting field the PA's
    directive requires (baseline/cleanup-active p50/p95/p99 per phase, p95 delta+ratio,
    busy/timeout/error counts, cleanup duration/rows/batches, exact txn shape, backend
    config). NEVER fabricates numbers for a backend that could not run -- that path is the
    caller's NOT EXECUTED - ENVIRONMENT BLOCKED, produced without calling this function.
    """
    read_baseline, read_active, read_evidence = _run_phase_with_cleanup(
        measure=lambda active: _measure_reads(
            open_backend=open_backend, partition_id=partition_id, persons=persons,
            sample_count=sample_count, cleanup_active=active,
            is_operational_error=is_operational_error,
        ),
        open_backend=open_backend, partition_id=partition_id,
        is_operational_error=is_operational_error,
    )
    write_baseline, write_active, write_evidence = _run_phase_with_cleanup(
        measure=lambda active: _measure_writes(
            open_backend=open_backend, partition_id=partition_id,
            sample_count=sample_count, cleanup_active=active,
            is_operational_error=is_operational_error,
        ),
        open_backend=open_backend, partition_id=partition_id,
        is_operational_error=is_operational_error,
    )

    result = ContentionResult(
        backend_name=backend_name,
        classification="",  # set below
        concurrency_config=concurrency_config,
        read_baseline=read_baseline,
        read_cleanup_active=read_active,
        write_baseline=write_baseline,
        write_cleanup_active=write_active,
        read_cleanup_evidence=read_evidence,
        write_cleanup_evidence=write_evidence,
    )
    _compute_deltas(result)
    _classify(result)
    return result


def _compute_deltas(result: ContentionResult) -> None:
    """Delta/ratio the PA directive requires: cleanup-active p95 minus baseline p95, and the
    ratio, for each phase. Only computed when both percentiles are present."""
    rb, ra = result.read_baseline, result.read_cleanup_active
    if rb and ra and rb.p95_ms is not None and ra.p95_ms is not None:
        result.read_p95_delta_ms = round(ra.p95_ms - rb.p95_ms, 3)
        result.read_p95_ratio = round(ra.p95_ms / rb.p95_ms, 3) if rb.p95_ms else None
    wb, wa = result.write_baseline, result.write_cleanup_active
    if wb and wa and wb.p95_ms is not None and wa.p95_ms is not None:
        result.write_p95_delta_ms = round(wa.p95_ms - wb.p95_ms, 3)
        result.write_p95_ratio = round(wa.p95_ms / wb.p95_ms, 3) if wb.p95_ms else None


def _classify(result: ContentionResult) -> None:
    """Closed-set classification (correction 12). P13 invents no new pass/fail threshold, so
    `classification` reflects only MEASUREMENT VALIDITY, not a technology verdict:

      * FAIL  -- the harness could not obtain a trustworthy measurement (a foreground op
                 errored, a phase starved, or a cleanup-active run's writer never confirmed
                 live). A contention measurement contaminated by harness failure is not
                 evidence.
      * UNKNOWN - INSUFFICIENT EVIDENCE -- every run completed cleanly but a run was
                 underpowered (< threshold completed samples), so its percentiles are
                 informational only.
      * PASS  -- all four runs completed the full sample with no error, both cleanup-active
                 runs ran against a confirmed-live cleanup writer, and no run was
                 underpowered: a valid two-phase contention measurement was obtained.

    busy/timeout counts do NOT by themselves force FAIL -- they are the empirical signal P13
    exists to capture; but a busy/timeout that prevented an operation from completing shows
    up as a missing sample and is caught by the completeness check below.
    """
    phases = [
        result.read_baseline, result.read_cleanup_active,
        result.write_baseline, result.write_cleanup_active,
    ]
    all_errors: list[str] = []
    for p in phases:
        if p:
            all_errors.extend(p.errors)
    for ev in (result.read_cleanup_evidence, result.write_cleanup_evidence):
        if ev:
            all_errors.extend(ev.errors)

    incomplete = [p for p in phases if p and p.samples_completed != p.samples_requested]
    cleanup_not_live = [
        ev for ev in (result.read_cleanup_evidence, result.write_cleanup_evidence)
        if ev and not ev.confirmed_active
    ]
    underpowered = [p for p in phases if p and p.underpowered]

    if all_errors or incomplete or cleanup_not_live:
        result.classification = "FAIL"
        reasons = []
        if all_errors:
            reasons.append(f"{len(all_errors)} error(s) recorded")
        if incomplete:
            reasons.append(
                "incomplete phase(s): "
                + ", ".join(f"{p.label} {p.samples_completed}/{p.samples_requested}" for p in incomplete)
            )
        if cleanup_not_live:
            reasons.append("a cleanup-active phase ran without a confirmed-live cleanup writer")
        result.note = (
            "P13 measurement not trustworthy -- " + "; ".join(reasons)
            + ". A contention measurement contaminated by harness failure is not evidence "
            "(no technology verdict is drawn from a FAIL measurement)."
        )
    elif underpowered:
        result.classification = "UNKNOWN — INSUFFICIENT EVIDENCE"
        result.note = (
            "underpowered phase(s): "
            + ", ".join(f"{p.label} n={p.samples_completed}" for p in underpowered)
            + f" (< {UNDERPOWERED_THRESHOLD}); percentiles are informational only"
        )
    else:
        result.classification = "PASS"
        result.note = (
            "valid two-phase P13 contention measurement obtained: baseline and "
            "cleanup-active percentiles for both interactive reads and interactive writes, "
            "each foreground run a sequential loop overlapping a confirmed-live bounded B4 "
            "cleanup writer. Empirical numbers (deltas/ratios, busy/timeout counts) are the "
            "result; no technology is selected here."
        )
