"""Deterministic type-7 summaries; rejects incomplete or mixed result files."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from client import CASES


def percentile(values: list[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    low = int(position)
    fraction = position - low
    return values[low] + fraction * (values[min(low + 1, len(values) - 1)] - values[low])


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p50": percentile(ordered, 0.50),
        "p90": percentile(ordered, 0.90),
        "p95": percentile(ordered, 0.95),
        "p99": percentile(ordered, 0.99),
        "max": ordered[-1],
        "mean": statistics.mean(ordered),
        "sample_sd": statistics.stdev(ordered),
    }


def trace_summary(rows: list[dict], event: str) -> dict | None:
    values = [row["trace_ms"][event] for row in rows if event in row["trace_ms"]]
    return summarize(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    lines = [json.loads(line) for line in args.raw.read_text(encoding="utf-8").splitlines()]
    if len(lines) < 2 or "meta" not in lines[0]:
        raise SystemExit("missing metadata or observations")
    expected = lines[0]["meta"]["samples_per_case"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in lines[1:]:
        if row.get("case") not in CASES or not isinstance(row.get("total_ms"), (int, float)):
            raise SystemExit("invalid observation")
        groups[row["case"]].append(row)
    if not groups or any(len(rows) != expected for rows in groups.values()):
        raise SystemExit("incomplete case or sample count")
    if any({row["sequence"] for row in rows} != set(range(expected)) for rows in groups.values()):
        raise SystemExit("missing or duplicate sequence")
    result = {
        "meta": lines[0]["meta"],
        "cases": {
            case: {
                "total_ms": summarize([row["total_ms"] for row in rows]),
                "tcp_connect_complete_ms": trace_summary(rows, "connection.connect_tcp.complete"),
                "tls_complete_ms": trace_summary(rows, "connection.start_tls.complete"),
                "request_write_complete_ms": trace_summary(rows, "http11.send_request_body.complete"),
                "header_complete_ms": summarize([row["header_complete_ms"] for row in rows]),
                "first_body_ms": summarize([row["first_body_ms"] for row in rows]),
                "server_receive_ms": summarize([row["server_receive_ms"] for row in rows]),
                "app_ms": summarize([row["app_ms"] for row in rows]),
                "tls_handshakes": sum(
                    any("start_tls" in event and event.endswith("complete") for event in row["trace_ms"])
                    for row in rows
                ),
                "tcp_connects": sum(
                    any("connect_tcp" in event and event.endswith("complete") for event in row["trace_ms"])
                    for row in rows
                ),
                "request_write_complete": sum(
                    any("send_request_body.complete" in event for event in row["trace_ms"])
                    for row in rows
                ),
            }
            for case, rows in sorted(groups.items())
        },
    }
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
