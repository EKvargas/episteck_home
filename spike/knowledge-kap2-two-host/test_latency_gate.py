"""The KAP-2 policy/witness latency screen accepted as a gate on 2026-11-07 (R5)."""

from __future__ import annotations

import pytest

from home_runner import KAP2_LATENCY_GATE_MS, latency_gate_breaches


def test_gate_thresholds_are_the_accepted_screen():
    assert KAP2_LATENCY_GATE_MS == {
        "call_p95_ms": 100.0, "call_p99_ms": 200.0,
        "pair_p95_ms": 200.0, "pair_p99_ms": 400.0,
    }


def test_gate_passes_at_and_below_each_threshold():
    assert latency_gate_breaches(dict(KAP2_LATENCY_GATE_MS)) == []
    assert latency_gate_breaches({name: 0.5 for name in KAP2_LATENCY_GATE_MS}) == []


@pytest.mark.parametrize("metric", sorted(KAP2_LATENCY_GATE_MS))
def test_gate_reports_each_breach(metric):
    distribution = {name: 1.0 for name in KAP2_LATENCY_GATE_MS}
    distribution[metric] = KAP2_LATENCY_GATE_MS[metric] + 0.001
    assert latency_gate_breaches(distribution) == [metric]


@pytest.mark.parametrize("value", [None, "12", float("nan"), -1.0])
def test_gate_fails_closed_on_missing_or_invalid_metric(value):
    distribution = {name: 1.0 for name in KAP2_LATENCY_GATE_MS}
    distribution["pair_p99_ms"] = value
    assert latency_gate_breaches(distribution) == ["pair_p99_ms"]
    del distribution["pair_p99_ms"]
    assert latency_gate_breaches(distribution) == ["pair_p99_ms"]
