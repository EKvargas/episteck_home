"""Stubbed synthetic domain peers (Phase-1 doc SS16.2 "Home and domain peers stubbed").

This stub measures FAN-OUT TOPOLOGY LATENCY -- NOT R14 (correction 5). Its `access()`
call is a calibrated `time.sleep`, a deliberately synthetic placeholder standing in for
"a domain peer does some bounded local work," used ONLY to observe the concurrency shape
of P2/P3/P4 (does wall clock approximate the slowest domain, or the sum?). It is not, and
must never be reported as, a measurement of any real domain repository.

R14 -- raw domain-repository read latency EXCLUDING authorization -- is measured
SEPARATELY and for real against the actual `services/nutrition` SQLite repository in
`bench/r14_domain_read.py`. Phase-1 E6 left R14 UNKNOWN because the one figure ever taken
for a domain read had a Home crossing folded in; correction 5 resolves that with a real
isolated read there, and downgrades this stub to what it always actually was: topology
latency for the fan-out concurrency assertions below.

Supports 1/3/5 independent domain configurations run CONCURRENTLY (P2/P3/P4), so wall
clock approximates the slowest domain rather than the sum -- the property B6 SS18A.6
requires and P3/P4 must observe.
"""
from __future__ import annotations

import concurrent.futures
import random
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class DomainAccessResult:
    domain_name: str
    elapsed_ms: float  # raw access time, NO authorization crossing included
    record_count: int


class DomainStub:
    """One synthetic domain peer. `base_latency_ms` is a calibrated placeholder for "a
    domain peer does some bounded local work" -- it is fan-out TOPOLOGY latency, deliberately
    synthetic, and is NOT a measurement of a real domain read (that is R14, measured for real
    in bench/r14_domain_read.py; see this module's header and correction 5)."""

    def __init__(self, name: str, *, base_latency_ms: float = 2.0, jitter_ms: float = 0.5, seed: int = 0):
        self.name = name
        self.base_latency_ms = base_latency_ms
        self.jitter_ms = jitter_ms
        self._rng = random.Random(seed)
        self.call_count = 0

    def access(self, record_count: int = 1) -> DomainAccessResult:
        self.call_count += 1
        start = time.monotonic()
        jitter = self._rng.uniform(-self.jitter_ms, self.jitter_ms)
        time.sleep(max(0.0, self.base_latency_ms + jitter) / 1000.0)
        elapsed = (time.monotonic() - start) * 1000.0
        return DomainAccessResult(domain_name=self.name, elapsed_ms=elapsed, record_count=record_count)


def make_domain_stubs(n: int, *, base_latency_ms: float = 2.0) -> tuple[DomainStub, ...]:
    return tuple(DomainStub(f"DOMAIN-{i}", base_latency_ms=base_latency_ms, seed=i) for i in range(n))


def fan_out_concurrent(domains: tuple[DomainStub, ...]) -> tuple[list[DomainAccessResult], float]:
    """Run all domain accesses concurrently; return (results, wall_clock_ms).

    B6 SS18A.6 requires independent domain reads to be concurrent by default -- P3/P4
    assert wall_clock_ms approx= max(individual elapsed), NOT sum(individual elapsed).
    """
    start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(domains))) as executor:
        futures = [executor.submit(d.access) for d in domains]
        results = [f.result() for f in futures]
    wall_clock_ms = (time.monotonic() - start) * 1000.0
    return results, wall_clock_ms


def total_domain_call_count(domains: tuple[DomainStub, ...]) -> int:
    return sum(d.call_count for d in domains)
