"""Stubbed synthetic domain peers (Phase-1 doc SS16.2 "Home and domain peers stubbed").

Measures R14 -- raw domain access latency EXCLUDING authorization -- which Phase-1 E6
states is UNKNOWN today because the one measured figure (Nutrition's SQLite read)
contains a Home crossing. This stub's `access()` call is deliberately just local
processing time with NO Home call inside it, so R14 is isolated by construction rather
than inferred by subtraction.

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
    """One synthetic domain peer. `base_latency_ms` models a local indexed read, similar
    in shape to Nutrition's own SQLite `SELECT` (Phase-1 E6) but WITHOUT any Home call --
    that separation is the whole point of R14."""

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
