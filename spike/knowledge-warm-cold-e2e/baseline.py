"""Explanatory private-network and instrumentation baselines, not E2E evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import socket
import statistics
import subprocess
import time
from pathlib import Path

from runner import Transport, _context


def _stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {"n": len(ordered), "min": ordered[0], "median": statistics.median(ordered),
            "p95_nearest_rank": ordered[max(0, int(0.95 * len(ordered) + 0.9999) - 1)],
            "max": ordered[-1], "mean": statistics.mean(ordered)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--home-host", default="100.71.79.33")
    parser.add_argument("--home-port", type=int, default=18443)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--skip-ping", action="store_true")
    args = parser.parse_args()
    rtts = []
    if not args.skip_ping:
        # `--c` is a maximum attempt count; Tailscale stops on first success.
        for _ in range(args.samples):
            ping = subprocess.run(["tailscale", "ping", "--c", "1", args.home_host],
                                  capture_output=True, text=True, check=True, timeout=10)
            rtts.extend(float(value) for value in re.findall(r"\bin ([0-9.]+)ms\b", ping.stdout))
    if not args.skip_ping and len(rtts) != args.samples:
        raise RuntimeError(f"expected {args.samples} Tailscale RTTs, got {len(rtts)}")
    context = _context(args.root)
    tls: list[float] = []
    for _ in range(args.samples):
        start = time.perf_counter_ns()
        with socket.create_connection((args.home_host, args.home_port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname="home-bench.invalid"):
                pass
        tls.append((time.perf_counter_ns() - start) / 1e6)

    plan = {"request_id": "BENCH-BASELINE-REQUEST", "plan_id": "BENCH-BASELINE-PLAN",
            "operations": [{"operation_id": "BENCH-BASELINE-OP-K", "domain": "KNOWLEDGE",
                            "subject_person_ids": ["PERSON-0000"],
                            "requirements": [["PERSON-0000", "KNOWLEDGE", "VIEW"]],
                            "request": None}]}
    transport = Transport(args.home_host, args.home_port, "home-bench.invalid", context)
    reused: list[float] = []
    try:
        transport.post("/rt2", plan)  # connection establishment excluded
        for _ in range(args.samples):
            start = time.perf_counter_ns()
            result = transport.post("/rt2", plan)
            if result["decisions"][0]["allowed"] is not True:
                raise RuntimeError("baseline plan denied")
            reused.append((time.perf_counter_ns() - start) / 1e6)
    finally:
        transport.close()

    overhead: list[float] = []
    for _ in range(100_000):
        start = time.perf_counter_ns()
        overhead.append((time.perf_counter_ns() - start) / 1e6)
    print(json.dumps({"timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                      "tailscale_ping_ms": _stats(rtts) if rtts else None,
                      "tls_new_connection_ms": _stats(tls),
                      "home_reused_request_ms": _stats(reused),
                      "perf_counter_pair_ms": _stats(overhead),
                      "home_body_bytes_range": {
                          "request": [min(x[0] for x in transport.bytes), max(x[0] for x in transport.bytes)],
                          "response": [min(x[1] for x in transport.bytes), max(x[1] for x in transport.bytes)]}},
                     sort_keys=True))


if __name__ == "__main__":
    main()
