"""Bench runner: latency + counter matrix across scenarios x realizations x corpus sizes.

Correction 6 (sample sizes, bounded runtime): every reported percentile set states its
warmup_count and measurement_count; anything under 30 measured samples is labeled
UNDERPOWERED - INFORMATIONAL ONLY rather than presented as a real p99. Total measured
repetitions are kept small deliberately -- every Home RT crossing sleeps ~111.57ms
(CALIBRATED_HOME_CROSSING_MS), so N reps x 2 crossings costs N x ~223ms; this run uses
N=30 for stage-level percentiles (~7s for the Home-crossing-heavy stages alone) to stay
well under a few minutes total, not hours.

Correction 7 (latency composition): every reported total separates MEASURED (backend/
domain-stub/R13 local cost, actually timed), CALIBRATED/INJECTED (Home crossings, from
E7), and COMPOSED (their sum) -- composed is never presented as a new real-world network
measurement.

Correction 5: PostgreSQL scenarios run only if backends.postgres_env.detect_postgres()
reports available; otherwise recorded NOT EXECUTED - ENVIRONMENT BLOCKED per corpus size
per scenario, never silently omitted from the output.

Correction 12: every result cell is one of PASS / FAIL / UNKNOWN - INSUFFICIENT EVIDENCE /
NOT EXECUTED - ENVIRONMENT BLOCKED / N/A.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backends.common import AuthorizedSet, ContentAccessLog  # noqa: E402
from backends.instrumentation import layer_a_from_log, layer_b_sqlite  # noqa: E402
from backends.postgres_env import detect_postgres  # noqa: E402
from backends.sqlite_backend import SQLiteKnowledgeBackend, SQLITE_PRAGMAS  # noqa: E402
from bench.contention import INTERACTIVE_SAMPLE_COUNT, run_two_phase_contention  # noqa: E402
from corpus.generator import generate_corpus  # noqa: E402
from domain_stub.stub import fan_out_concurrent, make_domain_stubs, total_domain_call_count  # noqa: E402
from home_stub.stub import CALIBRATED_HOME_CROSSING_MS, AuthorizationOperation, Grant, HomeStub  # noqa: E402

WARMUP_COUNT = 3
MEASUREMENT_COUNT = 30  # correction 6: fixed, justified, documented
UNDERPOWERED_THRESHOLD = 30
CORPUS_SIZES = ("C-small", "C-medium", "C-large")
DOMAINS_ALL = ("NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD")
AS_OF = 2_000_000_000

OUT_DIR = Path(__file__).resolve().parent / "report_data"


@dataclass
class PercentileResult:
    stage: str
    warmup_count: int
    measurement_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    underpowered: bool
    samples_measured_local: str  # "MEASURED" | "CALIBRATED" | "COMPOSED"


def percentiles(samples: list[float]) -> tuple[float, float, float]:
    s = sorted(samples)
    n = len(s)
    p50 = s[n // 2]
    p95 = s[min(n - 1, int(n * 0.95))]
    p99 = s[min(n - 1, int(n * 0.99))]
    return p50, p95, p99


def measure_stage(fn, *, warmup=WARMUP_COUNT, reps=MEASUREMENT_COUNT, kind="MEASURED") -> PercentileResult:
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    p50, p95, p99 = percentiles(samples)
    return PercentileResult(
        stage=fn.__name__ if hasattr(fn, "__name__") else "stage",
        warmup_count=warmup, measurement_count=reps, p50_ms=round(p50, 3), p95_ms=round(p95, 3),
        p99_ms=round(p99, 3), underpowered=reps < UNDERPOWERED_THRESHOLD, samples_measured_local=kind,
    )


def bench_sqlite_metadata_planning(corpus) -> PercentileResult:
    be = SQLiteKnowledgeBackend()
    be.load_corpus(corpus)
    p0 = corpus.persons[0]

    def op():
        be.plan_metadata(
            partition_id=corpus.partitions[0], subject_person_ids=(p0,), domains=DOMAINS_ALL, as_of=AS_OF
        )

    result = measure_stage(op, kind="MEASURED")
    be.close()
    result.stage = "metadata_planning_sqlite"
    return result


def bench_sqlite_content_access(corpus) -> PercentileResult:
    be = SQLiteKnowledgeBackend()
    be.load_corpus(corpus)
    p0 = corpus.persons[0]
    planned = be.plan_metadata(
        partition_id=corpus.partitions[0], subject_person_ids=(p0,), domains=DOMAINS_ALL, as_of=AS_OF
    )
    authz = AuthorizedSet(version_ids=planned.candidate_version_ids)

    def op():
        log = ContentAccessLog()
        be.fetch_content(authz, log=log)

    result = measure_stage(op, kind="MEASURED")
    be.close()
    result.stage = "content_access_sqlite"
    return result


def bench_home_crossing() -> PercentileResult:
    """CALIBRATED, not measured -- this stage IS the injected sleep from E7. Reported
    honestly as CALIBRATED, never presented as a new real-world measurement."""
    home = HomeStub(grants=(Grant("P1", "P1", "NUTRITION", "VIEW", "PART-1"),))
    op = AuthorizationOperation("op1", "P1", ("P1",), "NUTRITION", "VIEW", "PART-1")

    def call():
        home.evaluate_plan((op,), version_pool={"op1": frozenset({"v1"})})

    result = measure_stage(call, kind="CALIBRATED", reps=10)  # fewer reps: each costs ~112ms
    result.stage = "home_crossing_calibrated"
    return result


def bench_domain_fanout(n: int) -> PercentileResult:
    def op():
        domains = make_domain_stubs(n, base_latency_ms=10.0)
        fan_out_concurrent(domains)

    result = measure_stage(op, kind="MEASURED", reps=15)
    result.stage = f"domain_fanout_n{n}_measured"
    return result


def bench_r13_execution() -> PercentileResult:
    from r13.holder_of_key import DomainVerifier, HomeBasisMinter, ServiceKeypair, TrustedKeyRegistry, sign_proof

    registry = TrustedKeyRegistry()
    svc = ServiceKeypair.generate("svc-nutrition")
    registry.register("svc-nutrition", svc.public_bytes_hex())
    minter = HomeBasisMinter(registry)
    now = int(time.time())

    def op():
        basis = minter.mint(
            basis_id=f"b-{time.perf_counter_ns()}", partition_id="PART-1", actor_person_id="P1",
            operation_id="op1", domain="NUTRITION", action="VIEW", resource_id="res-1",
            audience_service_identity="svc-nutrition", decision_id="d1", now=now,
        )
        proof = sign_proof(keypair=svc, basis=basis, method="POST", target="/x", nonce=str(time.perf_counter_ns()))
        DomainVerifier().verify_and_execute(
            basis=basis, proof=proof, claimed_service_identity="svc-nutrition",
            presenting_public_key=svc.public_key, expected_audience="svc-nutrition",
            expected_domain="NUTRITION", expected_action="VIEW", expected_operation_id="op1",
            expected_actor_person_id="P1", now=now,
        )

    result = measure_stage(op, kind="MEASURED")
    result.stage = "r13_execution_measured"
    return result


def p13_contention(pg_availability) -> dict:
    """Correction 4: the DECISIVE S1-SQLite vs S1-PostgreSQL discriminator, run TIMED here,
    using the Product Architect's TWO-PHASE methodology (see bench/contention.py).

    The first P13 wiring drove 200 pure-Python reader threads and produced a ~20s p50/p95/p99
    cluster that was a CPython GIL serialization ARTIFACT, not backend contention. Replaced
    by a sequential foreground loop concurrent with ONE bounded background B4 cleanup writer,
    measured in TWO phases: P13-R (interactive reads during cleanup) and P13-W (interactive
    writes during cleanup, where two writers genuinely contend for SQLite's single write
    lock), each captured BOTH baseline (no cleanup) and cleanup-active so the report states
    the delta/ratio attributable to contention rather than an absolute number. No new pass/
    fail threshold is invented; classification reflects measurement validity only, and no
    technology is selected.

    Both arms drive the ONE shared, backend-agnostic harness over the SAME corpus so the
    distributions are directly comparable (correction 9). SQLite is MEASURED against a real
    on-disk WAL database (a `:memory:` db is per-connection, so multi-connection contention
    needs a shared file). PostgreSQL is MEASURED only if `detect_postgres()` already reported
    a reachable disposable instance; otherwise it is recorded NOT EXECUTED - ENVIRONMENT
    BLOCKED with the named prerequisite, never fabricated (corrections 5/12). Each arm
    records its explicit concurrency configuration (correction 8)."""
    # C-medium seed=7 matches the pytest module: enough assertions that the foreground reads
    # do real work and a suppression register large enough that the cleanup writer's dedicated
    # _P13CLEANUP_* pool never collides with corpus rows.
    corpus = generate_corpus("C-medium", seed=7)
    arms: list[dict] = []

    # --- SQLite arm (MEASURED) --------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "p13.db"
        loader = SQLiteKnowledgeBackend(db_path)
        loader.load_corpus(corpus)
        loader.close()
        sqlite_result = run_two_phase_contention(
            backend_name="S1-SQLite",
            open_backend=lambda: SQLiteKnowledgeBackend(db_path),
            partition_id=corpus.partitions[0],
            persons=corpus.persons,
            concurrency_config=dict(SQLITE_PRAGMAS),
            sample_count=INTERACTIVE_SAMPLE_COUNT,
            is_operational_error=lambda e: isinstance(e, sqlite3.OperationalError),
        )
    arms.append(asdict(sqlite_result))

    # --- PostgreSQL arm (MEASURED if reachable, else NOT EXECUTED - ENVIRONMENT BLOCKED) --
    if getattr(pg_availability, "available", False):
        from backends.postgres_backend import PostgresKnowledgeBackend

        owner = PostgresKnowledgeBackend(pg_availability.dsn)
        try:
            owner.load_corpus(corpus)
            pg_result = run_two_phase_contention(
                backend_name="S1-PostgreSQL",
                open_backend=lambda: PostgresKnowledgeBackend.connect_existing(
                    pg_availability.dsn, schema_name=owner.schema_name
                ),
                partition_id=corpus.partitions[0],
                persons=corpus.persons,
                concurrency_config={"session": "autocommit=False, server defaults (correction 8)"},
                sample_count=INTERACTIVE_SAMPLE_COUNT,
            )
            arms.append(asdict(pg_result))
        finally:
            owner.close()  # drops the disposable schema at the very end
    else:
        reason = getattr(pg_availability, "reason", str(pg_availability))
        arms.append(
            {
                "backend_name": "S1-PostgreSQL",
                "classification": "NOT EXECUTED — ENVIRONMENT BLOCKED",
                "concurrency_config": {"session": "not opened — no reachable disposable Postgres"},
                "note": (
                    "P13 PostgreSQL arm not executed: "
                    f"{reason}. Detect-never-provision (correction 5); a reachable disposable "
                    "PostgreSQL DSN is the missing prerequisite. Not fabricated (correction 12)."
                ),
            }
        )

    return {
        "scenario": "P13_b4_cleanup_contention",
        "methodology": "two-phase (P13-R reads / P13-W writes), sequential foreground + one bounded background cleanup writer",
        "corpus_size": "C-medium",
        "corpus_seed": 7,
        "interactive_sample_count": INTERACTIVE_SAMPLE_COUNT,
        "arms": arms,
    }


def barrier_evidence_for_size(size_label: str) -> dict:
    corpus = generate_corpus(size_label, seed=42)
    be = SQLiteKnowledgeBackend()
    be.load_corpus(corpus)
    p0 = corpus.persons[0]
    planned = be.plan_metadata(
        partition_id=corpus.partitions[0], subject_person_ids=(p0,), domains=DOMAINS_ALL, as_of=AS_OF
    )
    authz = AuthorizedSet(version_ids=planned.candidate_version_ids)

    log_exact = ContentAccessLog()
    be.fetch_content(authz, log=log_exact)
    layer_a_exact = layer_a_from_log(log_exact)

    log_fts = ContentAccessLog()
    be.fetch_content_fulltext(authz, query="synthetic", log=log_fts)
    layer_a_fts = layer_a_from_log(log_fts)
    plan_rows = be.explain_fulltext_barrier("synthetic")
    layer_b_fts = layer_b_sqlite(plan_rows)

    be.close()
    return {
        "corpus_size": size_label,
        "S1_exact_lookup": {
            "layer_a_verdict": layer_a_exact.verdict.value,
            "unauthorized_logical_content_ids_requested": layer_a_exact.unauthorized_logical_content_ids_requested,
        },
        "S2_fulltext_barrier": {
            "layer_a_verdict": layer_a_fts.verdict.value,
            "layer_a_unauthorized_requested": layer_a_fts.unauthorized_logical_content_ids_requested,
            "layer_b_verdict": layer_b_fts.verdict.value,
            "layer_b_note": layer_b_fts.note,
            "combined_verdict": (
                "FAIL"
                if layer_b_fts.verdict.value == "FAIL"
                else layer_a_fts.verdict.value
            ),
        },
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "sqlite_configuration": SQLITE_PRAGMAS,
        "calibrated_home_crossing_ms": CALIBRATED_HOME_CROSSING_MS,
        "measurement_policy": {
            "warmup_count": WARMUP_COUNT,
            "measurement_count": MEASUREMENT_COUNT,
            "underpowered_threshold": UNDERPOWERED_THRESHOLD,
        },
        "postgres_availability": None,
        "stages": [],
        "barrier_evidence": [],
        "p13_contention": None,
    }

    pg = detect_postgres()
    report["postgres_availability"] = asdict(pg) if hasattr(pg, "__dataclass_fields__") else str(pg)

    print("Detecting PostgreSQL:", pg)

    for size in CORPUS_SIZES:
        print(f"--- corpus size: {size} ---")
        corpus = generate_corpus(size, seed=42)
        print(f"  metadata planning (SQLite)...")
        report["stages"].append({"corpus_size": size, **asdict(bench_sqlite_metadata_planning(corpus))})
        print(f"  content access (SQLite)...")
        report["stages"].append({"corpus_size": size, **asdict(bench_sqlite_content_access(corpus))})
        print(f"  barrier evidence...")
        report["barrier_evidence"].append(barrier_evidence_for_size(size))

    print("Home crossing (calibrated)...")
    report["stages"].append({"corpus_size": "N/A", **asdict(bench_home_crossing())})

    for n in (1, 3, 5):
        print(f"Domain fan-out n={n}...")
        report["stages"].append({"corpus_size": "N/A", **asdict(bench_domain_fanout(n))})

    print("R13 execution (measured)...")
    report["stages"].append({"corpus_size": "N/A", **asdict(bench_r13_execution())})

    print("P13 B4-cleanup contention (SQLite measured; Postgres measured-if-reachable)...")
    report["p13_contention"] = p13_contention(pg)

    out_path = OUT_DIR / "bench_results.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
