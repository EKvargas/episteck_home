"""Recompute transport distributions and selected TCP segment timelines."""
from __future__ import annotations

import datetime as dt
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "evidence"
CLIENT_IP = "100.81.4.57"
SERVER_IP = "100.71.79.33"
PORT = 18463
PACKET = re.compile(
    r"^(\d+\.\d+) IP ([\d.]+)\.(\d+) > ([\d.]+)\.(\d+): .* length (\d+)$"
)


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (ROOT / name).read_text().splitlines()]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    offset = (len(ordered) - 1) * fraction
    lower = int(offset)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (offset - lower)


def stats(values: list[float]) -> dict:
    return {"p50": round(statistics.median(values), 3),
            "p95": round(percentile(values, 0.95), 3),
            "min": round(min(values), 3), "max": round(max(values), 3)}


def packet_timeline(row: dict, packet_file: str) -> dict:
    end = dt.datetime.fromisoformat(row["utc"]).timestamp()
    start = end - row["request_ms"] / 1000
    packets = []
    for line in (ROOT / packet_file).read_text().splitlines():
        match = PACKET.match(line)
        if match is None:
            continue
        timestamp, source, source_port, target, target_port, length = match.groups()
        timestamp = float(timestamp)
        if start - 0.01 <= timestamp <= end + 0.01:
            packets.append((timestamp, source, int(source_port), target, int(target_port), int(length)))
    outbound = [p for p in packets if p[1] == CLIENT_IP and p[3] == SERVER_IP
                and p[4] == PORT and p[5] > 0 and p[0] >= start - 0.003]
    if not outbound:
        raise ValueError(f"no outgoing data packet for {row['id']}")
    source_port = outbound[0][2]
    flow = [p for p in packets if (p[1] == CLIENT_IP and p[2] == source_port and
                                   p[3] == SERVER_IP and p[4] == PORT) or
            (p[1] == SERVER_IP and p[2] == PORT and p[3] == CLIENT_IP and
             p[4] == source_port)]
    first = outbound[0][0]
    return {"case": row["case"], "round": row["round"], "request_ms": round(row["request_ms"], 3),
            "client_port": source_port,
            "segments": [{"from": "client" if p[1] == CLIENT_IP else "server",
                          "at_ms": round((p[0] - first) * 1000, 3), "tcp_payload_bytes": p[5]}
                         for p in flow if p[5] > 0 and first - 0.0001 <= p[0] <= end + 0.0002][:12]}


def main() -> None:
    server = {row["id"]: row for row in load("server-all.jsonl")}
    output = {"datasets": {}, "timelines": []}
    for label, client_file, packet_file, expected in (
        ("controlled", "client.jsonl", "packets.txt", 30),
        ("http_client_with_probe_headers", "legacy-client.jsonl", "packets-legacy.txt", 30),
        ("http_client_minimal_headers", "exact-client.jsonl", "packets-exact.txt", 30),
        ("http_client_py311_minimal_headers", "exact-py311-client.jsonl", "packets-py311.txt", 30),
    ):
        cases: dict[str, list[dict]] = defaultdict(list)
        for row in load(client_file):
            if row["id"] not in server:
                raise ValueError(f"missing server row: {row['id']}")
            cases[row["case"]].append(row)
        result = {}
        for name, rows in sorted(cases.items()):
            if len(rows) != expected:
                raise ValueError(f"{name}: {len(rows)} rows, expected {expected}")
            matches = [server[row["id"]] for row in rows]
            phases = {"request_ms": [row["request_ms"] for row in rows],
                      "send_ms": [row["send_ms"] for row in rows],
                      "client_body_read_ms": [row["body_read_ms"] for row in rows],
                      "server_body_read_ms": [(row["body_read_ns"] - row["started_ns"]) / 1e6
                                              for row in matches],
                      "server_processing_ms": [(row["before_write_ns"] - row["body_read_ns"]) / 1e6
                                               for row in matches],
                      "server_write_ms": [(row["after_body_ns"] - row["before_write_ns"]) / 1e6
                                          for row in matches]}
            if "wait_first_read_ms" in rows[0]:
                phases["client_wait_first_read_ms"] = [row["wait_first_read_ms"] for row in rows]
            else:
                phases["client_headers_read_ms"] = [row["headers_read_ms"] for row in rows]
            if rows[0].get("fresh_tls"):
                phases["tls_connect_ms"] = [row["tls_connect_ms"] for row in rows]
                phases["connection_plus_request_ms"] = [row["tls_connect_ms"] + row["request_ms"]
                                                        for row in rows]
            result[name] = {"n": len(rows), **{key: stats(values) for key, values in phases.items()}}
            if name in ("small_split_off", "medium_split_off", "large_split_off", "small_server_nodelay",
                        "small_both_nodelay", "exact_baseline", "exact_p3"):
                median_row = min(rows, key=lambda row: abs(row["request_ms"] -
                                                      statistics.median(phases["request_ms"])))
                output["timelines"].append(packet_timeline(median_row, packet_file))
        output["datasets"][label] = result
    output["response_comparators"] = {}
    for label, client_file, packet_file in (
        ("original_responder", "original-responder-client.jsonl", "packets-original.txt"),
        ("mimic_without_plan_evaluation", "mimic-responder-client.jsonl", "packets-mimic.txt"),
    ):
        rows = load(client_file)
        if len(rows) != 30:
            raise ValueError(f"{label}: expected 30, found {len(rows)}")
        output["response_comparators"][label] = {key: stats([row[key] for row in rows]) for key in (
            "request_ms", "send_ms", "headers_read_ms", "body_read_ms")}
        median_row = min(rows, key=lambda row: abs(row["request_ms"] -
                                             statistics.median([item["request_ms"] for item in rows])))
        timeline = packet_timeline(median_row, packet_file)
        timeline["comparator"] = label
        output["timelines"].append(timeline)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
