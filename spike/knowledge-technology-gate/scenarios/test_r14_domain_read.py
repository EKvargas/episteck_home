"""R14: raw domain-repository read latency, EXCLUDING authorization (correction 5).

Phase-1 E6 recorded R14 as UNKNOWN because the one domain-read figure ever taken had a Home
authorization crossing folded into it, so the raw local read cost could only be inferred by
subtraction. The first spike wiring then papered over this by presenting the synthetic
`domain_stub`'s calibrated `time.sleep` latency as "R14" -- an overclaim: a fan-out topology
stub is not a measurement of any real domain repository.

Correction 5 requires either a REAL domain read measured locally on synthetic data, or an
honest NOT EXECUTED - ENVIRONMENT BLOCKED -- never the synthetic stub relabelled as R14.
`bench/r14_domain_read.measure_r14()` drives the actual `services/nutrition`
`SqliteNutritionRepository` against a throwaway on-disk SQLite DB seeded with synthetic rows;
each timed op (`get_profile`, `list_intake`) is a pure local read with NO Home crossing in
its call path, so R14 is isolated BY CONSTRUCTION rather than inferred by subtraction.

These tests assert measurement VALIDITY only -- no new pass/fail threshold, no technology
selected. When the real service package cannot be imported from this environment, R14 is
NOT EXECUTED - ENVIRONMENT BLOCKED (a reportable status), and the test asserts the blocked
result is honest (named reason, no fabricated numbers, synthetic stub explicitly refused as
a substitute) rather than failing the suite.
"""
from __future__ import annotations

import pytest

from bench.r14_domain_read import UNDERPOWERED_THRESHOLD, measure_r14

# Keep the pytest run tractable while staying above the underpowered threshold; the bench
# runner (bench/run_bench.py) collects the full R14_SAMPLE_COUNT numbers for the report.
R14_TEST_SAMPLE_COUNT = 50


def test_r14_isolated_domain_read_measured_or_blocked():
    """R14 is measured against the real repository when importable, else honestly blocked.

    MEASURED path: both `list_intake` and `get_profile` produce real percentile sets from
    reads that did real work (returned rows), every one flagged as containing NO Home crossing
    -- that isolation is R14's entire purpose. BLOCKED path (real service not importable here):
    the result names a concrete reason, fabricates no number, and explicitly refuses the
    synthetic fan-out stub as a substitute -- a reportable NOT EXECUTED status, not a pass and
    not a silent gap.
    """
    result = measure_r14(sample_count=R14_TEST_SAMPLE_COUNT)

    if result.classification == "NOT EXECUTED — ENVIRONMENT BLOCKED":
        # Honest blocked result: no measurements, a concrete reason, and the synthetic stub
        # explicitly refused as a substitute (correction 5 -- never fake R14 from the stub).
        assert result.measurements == []
        assert "ENVIRONMENT BLOCKED" in result.note
        assert "NOT a substitute" in result.note
        pytest.skip(f"R14 NOT EXECUTED - ENVIRONMENT BLOCKED: {result.note}")

    # MEASURED path.
    assert result.classification == "MEASURED", result.note
    ops = {m.operation for m in result.measurements}
    assert {"list_intake", "get_profile"} <= ops, f"missing R14 operations: measured {ops}"

    for m in result.measurements:
        assert m.classification == "MEASURED"
        # R14 EXCLUDES authorization -- every timed op must be a pure local read.
        assert m.contains_home_crossing is False, (
            f"{m.operation} folded a Home crossing into R14 -- that is the exact Phase-1 E6 "
            "defect correction 5 exists to remove"
        )
        # Real percentiles from a read that actually returned rows.
        assert m.sample_count == R14_TEST_SAMPLE_COUNT
        assert m.row_count > 0, f"{m.operation} returned no rows -- read did no real work"
        assert m.p50_ms is not None and m.p95_ms is not None and m.p99_ms is not None
        assert m.p50_ms >= 0.0 and m.p95_ms >= m.p50_ms and m.p99_ms >= m.p95_ms
        assert m.underpowered == (R14_TEST_SAMPLE_COUNT < UNDERPOWERED_THRESHOLD)
