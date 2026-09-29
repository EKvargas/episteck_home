"""Deterministic, dependency-free analysis of sanitized JSONL observations."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

THRESHOLDS = {"p50": 300.0, "p95": 500.0, "p99": 800.0}


def percentile(values: list[float], fraction: float) -> float:
    """Hyndman-Fan type 7 linear interpolation (NumPy's default)."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty sample")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def distribution(values: list[float]) -> dict[str, float]:
    return {"n": len(values), "min": min(values), "p50": percentile(values, 0.5),
            "p90": percentile(values, 0.9), "p95": percentile(values, 0.95),
            "p99": percentile(values, 0.99), "max": max(values),
            "mean": statistics.mean(values),
            "standard_deviation": statistics.stdev(values) if len(values) > 1 else 0.0}


def summarize(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not rows:
        raise ValueError(f"no samples: {path}")
    scenario, classification = rows[0]["scenario"], rows[0]["classification"]
    expected_domains = {"P1": 0, "P2": 1, "P3": 3, "P4": 5}[scenario]
    for index, row in enumerate(rows):
        if row["scenario"] != scenario or row["classification"] != classification:
            raise ValueError(f"mixed scenario/classification: {path}")
        if row["iteration"] != index:
            raise ValueError(f"nonconsecutive iteration: {path}")
        if row["success"] is not True:
            raise ValueError(f"failure mixed into success distribution: {path}:{index}")
        counters = row["counters"]
        expected = {"home_auth_round_trip_count": 2,
                    "authorization_operation_count": expected_domains + 1,
                    "domain_call_count": expected_domains,
                    "knowledge_read_count": 1,
                    "r13_verification_count": expected_domains,
                    "repository_read_count": expected_domains,
                    "source_expansion_count": 0}
        if any(counters.get(key) != value for key, value in expected.items()):
            raise ValueError(f"counter invariant failed: {path}:{index}")
    # V1 cold rows retained the direct child request timer separately, then
    # overwrote total_pre_llm_ms with process launch-through-exit wall time.
    # Use the measured request boundary, not process teardown, for acceptance.
    latency = distribution([float(row["internal_request_ms"] if classification == "cold"
                                  else row["total_pre_llm_ms"]) for row in rows])
    phase_keys = sorted({key for row in rows for key in row["phases_ms"]})
    phases = {key: distribution([float(row["phases_ms"].get(key, 0.0)) for row in rows])
              for key in phase_keys}
    sizes = {"rt1_request": [], "rt1_response": [], "rt2_request": [], "rt2_response": []}
    for row in rows:
        if len(row["home_body_bytes"]) != 2:
            raise ValueError(f"missing Home body sizes: {path}")
        for label, pair in zip(("rt1", "rt2"), row["home_body_bytes"]):
            sizes[f"{label}_request"].append(pair[0])
            sizes[f"{label}_response"].append(pair[1])
    result = {"file": str(path), "scenario": scenario, "classification": classification,
            "latency_ms": latency, "phases_ms": phases,
            "threshold_pass": {key: latency[key] <= threshold for key, threshold in THRESHOLDS.items()},
            "home_body_bytes_range": {key: [min(v), max(v)] for key, v in sizes.items()},
            "all_counter_invariants_pass": True,
            "first_timestamp_utc": rows[0]["timestamp_utc"],
            "last_timestamp_utc": rows[-1]["timestamp_utc"]}
    if classification == "cold":
        result["process_lifetime_ms"] = distribution(
            [float(row.get("process_lifetime_ms", row["total_pre_llm_ms"])) for row in rows])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([summarize(path) for path in args.files], sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
