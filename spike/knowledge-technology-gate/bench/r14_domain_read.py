"""R14 -- raw domain-repository read latency, EXCLUDING authorization (correction 5).

Phase-1 E6 recorded R14 as UNKNOWN because the one figure ever measured for a domain
read (Nutrition's SQLite `SELECT`) had a Home authorization crossing folded into it, so
the raw local read cost could only be *inferred by subtraction*, never isolated.

The first spike wiring papered over this by labelling the synthetic `domain_stub`'s
`time.sleep`-based latency as "R14". That was an OVERCLAIM: a calibrated fan-out topology
stub is not a measurement of any real domain repository. Correction 5 (Product Architect
review of PR #33) requires either a REAL domain read measured locally on synthetic data,
or an honest NOT EXECUTED - ENVIRONMENT BLOCKED -- and the synthetic stub relabelled as
fan-out topology latency, never R14 (see domain_stub/stub.py).

This module takes the first path where the environment allows it. It drives the REAL
`services/nutrition` repository (`app.store.sqlite_repo.SqliteNutritionRepository`) against
a throwaway on-disk SQLite database seeded with synthetic profile + intake rows, and times
`get_profile` / `list_intake` -- both of which are pure local reads with NO Home call inside
them, so R14 is isolated BY CONSTRUCTION rather than inferred by subtraction. If the real
service package cannot be imported from this environment (path/layout/optional-dependency
reasons), R14 is recorded NOT EXECUTED - ENVIRONMENT BLOCKED with the concrete reason named
-- never a fabricated number, and never silently upgraded from the synthetic stub.

No new pass/fail threshold is invented and no technology is selected: R14's job is only to
produce, at last, an isolated empirical figure for the raw domain-read cost.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# Sample sizing mirrors bench/contention.py (correction 6): >=200 measured samples for a
# real percentile set; anything under UNDERPOWERED_THRESHOLD is flagged informational-only.
R14_SAMPLE_COUNT = 200
R14_WARMUP_COUNT = 5
UNDERPOWERED_THRESHOLD = 30

# Synthetic subject + fixed date used only for this measurement's throwaway DB.
_R14_PERSON_ID = "PSN-R14-SYNTHETIC"
_R14_DATE = "2026-09-23"
_R14_INTAKE_ROWS = 50  # a realistic single-day intake list; bounded local read, not a scan

# The real Nutrition service package lives outside the spike tree; import it lazily so a
# SQLite-only spike run never hard-depends on it and an import failure is a reportable
# ENVIRONMENT-BLOCKED status, not a crash.
_NUTRITION_SERVICE_ROOT = (
    Path(__file__).resolve().parents[3] / "services" / "nutrition"
)


@dataclass
class R14Measurement:
    """One isolated raw-read percentile set for a single repository operation."""

    operation: str  # "get_profile" | "list_intake"
    classification: str  # "MEASURED" | "NOT EXECUTED — ENVIRONMENT BLOCKED"
    sample_count: int
    warmup_count: int
    row_count: int  # rows the read returned (evidence the read did real work)
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    underpowered: bool = False
    contains_home_crossing: bool = False  # ALWAYS False here -- the whole point of R14
    note: str = ""


@dataclass
class R14Result:
    classification: str  # "MEASURED" | "NOT EXECUTED — ENVIRONMENT BLOCKED"
    source: str  # what was actually measured / why it was blocked
    measurements: list[R14Measurement] = field(default_factory=list)
    note: str = ""


def _percentiles(samples: list[float]) -> tuple[float, float, float]:
    s = sorted(samples)
    n = len(s)
    p50 = s[n // 2]
    p95 = s[min(n - 1, int(n * 0.95))]
    p99 = s[min(n - 1, int(n * 0.99))]
    return p50, p95, p99


def _time_operation(op, *, sample_count: int, warmup_count: int) -> list[float]:
    for _ in range(warmup_count):
        op()
    samples: list[float] = []
    for _ in range(sample_count):
        t0 = time.perf_counter()
        op()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def _blocked(reason: str) -> R14Result:
    """Honest NOT EXECUTED - ENVIRONMENT BLOCKED result (correction 5/12): the real domain
    package is not reachable from here, so R14 stays unmeasured rather than being faked from
    the synthetic fan-out stub."""
    return R14Result(
        classification="NOT EXECUTED — ENVIRONMENT BLOCKED",
        source="real services/nutrition repository not importable from this environment",
        measurements=[],
        note=(
            f"R14 NOT EXECUTED — ENVIRONMENT BLOCKED: {reason}. The synthetic domain_stub "
            "fan-out latency is NOT a substitute (it is calibrated topology latency, not a "
            "real domain read); no R14 number is fabricated. Missing prerequisite: an "
            "importable real domain repository (services/nutrition) on this host."
        ),
    )


def measure_r14(
    *, sample_count: int = R14_SAMPLE_COUNT, warmup_count: int = R14_WARMUP_COUNT
) -> R14Result:
    """Measure raw domain-repository read latency with authorization excluded (R14).

    MEASURED when the real `services/nutrition` SQLite repository can be imported and driven
    locally against synthetic data; otherwise NOT EXECUTED - ENVIRONMENT BLOCKED. Each timed
    operation is a pure local read (`get_profile`, `list_intake`) with NO Home crossing in
    the call path -- that isolation is R14's entire purpose (Phase-1 E6)."""
    if not _NUTRITION_SERVICE_ROOT.exists():
        return _blocked(
            f"expected real domain service at {_NUTRITION_SERVICE_ROOT} does not exist"
        )

    # Import the REAL repository. Keep the sys.path insertion local; only app.store.sqlite_repo
    # is imported (its transitive imports are stdlib-only: json/sqlite3/uuid/threading + the
    # abstract base), so this does NOT build the Nutrition FastAPI app or a HomeControlPlaneClient.
    root_str = str(_NUTRITION_SERVICE_ROOT)
    inserted = root_str not in sys.path
    if inserted:
        sys.path.insert(0, root_str)
    try:
        from app.store.sqlite_repo import SqliteNutritionRepository  # type: ignore
    except Exception as e:  # ImportError or any transitive failure -> reportable, not fatal
        return _blocked(f"{type(e).__name__}: {e}")

    # mkdtemp + best-effort cleanup rather than TemporaryDirectory's strict auto-cleanup:
    # SqliteNutritionRepository opens a fresh connection per call, and on Windows a just-used
    # SQLite file can still hold a lock at teardown, which would raise PermissionError from
    # TemporaryDirectory and mask an already-completed measurement. The timed reads all finish
    # before cleanup, so a lingering throwaway temp file (swept by the OS) never affects R14.
    td = tempfile.mkdtemp(prefix="r14_")
    try:
        db_path = str(Path(td) / "r14.sqlite")
        repo = SqliteNutritionRepository(db_path)

        # Seed synthetic data only -- no real person, no production DB (the plan forbids real
        # data; TG-PA-7 authorizes synthetic).
        repo.upsert_profile(
            _R14_PERSON_ID,
            {"age": 34, "sex": "F", "weight_kg": 62, "goals": ["maintain"], "synthetic": True},
        )
        for i in range(_R14_INTAKE_ROWS):
            repo.add_intake(
                _R14_PERSON_ID,
                {"date": _R14_DATE, "kind": "actual", "food": f"synthetic-food-{i}", "grams": 100 + i},
            )

        measurements: list[R14Measurement] = []

        # --- list_intake: bounded indexed read over one subject/day (the representative
        # domain read shape from Phase-1 E6) -----------------------------------------------
        intake_rows = len(repo.list_intake(_R14_PERSON_ID, _R14_DATE, "actual"))
        intake_samples = _time_operation(
            lambda: repo.list_intake(_R14_PERSON_ID, _R14_DATE, "actual"),
            sample_count=sample_count, warmup_count=warmup_count,
        )
        p50, p95, p99 = _percentiles(intake_samples)
        measurements.append(
            R14Measurement(
                operation="list_intake",
                classification="MEASURED",
                sample_count=sample_count, warmup_count=warmup_count, row_count=intake_rows,
                p50_ms=round(p50, 4), p95_ms=round(p95, 4), p99_ms=round(p99, 4),
                underpowered=sample_count < UNDERPOWERED_THRESHOLD,
                contains_home_crossing=False,
                note=(
                    "Real SqliteNutritionRepository.list_intake over a synthetic single-day "
                    "intake list; bounded indexed read (ix_intake on person_id,date,kind); no "
                    "Home crossing in the call path."
                ),
            )
        )

        # --- get_profile: single-row primary-key read -------------------------------------
        profile_present = 1 if repo.get_profile(_R14_PERSON_ID) is not None else 0
        profile_samples = _time_operation(
            lambda: repo.get_profile(_R14_PERSON_ID),
            sample_count=sample_count, warmup_count=warmup_count,
        )
        p50, p95, p99 = _percentiles(profile_samples)
        measurements.append(
            R14Measurement(
                operation="get_profile",
                classification="MEASURED",
                sample_count=sample_count, warmup_count=warmup_count, row_count=profile_present,
                p50_ms=round(p50, 4), p95_ms=round(p95, 4), p99_ms=round(p99, 4),
                underpowered=sample_count < UNDERPOWERED_THRESHOLD,
                contains_home_crossing=False,
                note=(
                    "Real SqliteNutritionRepository.get_profile PRIMARY KEY read of one "
                    "synthetic profile row; no Home crossing in the call path."
                ),
            )
        )
    finally:
        shutil.rmtree(td, ignore_errors=True)

    return R14Result(
        classification="MEASURED",
        source=(
            "real services/nutrition SqliteNutritionRepository against a throwaway on-disk "
            "SQLite DB seeded with synthetic profile + intake rows"
        ),
        measurements=measurements,
        note=(
            "R14 isolated BY CONSTRUCTION: every timed operation is a pure local repository "
            "read with no Home authorization crossing inside it, resolving the Phase-1 E6 "
            "UNKNOWN (where the only measured domain figure had a Home crossing folded in). "
            "MEASURED only; no pass/fail threshold, no technology selected."
        ),
    )
