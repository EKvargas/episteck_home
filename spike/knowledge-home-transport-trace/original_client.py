"""Replay the previous 250-byte synthetic RT#2 baseline against its responder."""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import socket
import ssl
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--client-prefix", default="runtime")
    parser.add_argument("--path", default="/rt2")
    args = parser.parse_args()
    plan = {"request_id": "BENCH-BASELINE-REQUEST", "plan_id": "BENCH-BASELINE-PLAN",
            "operations": [{"operation_id": "BENCH-BASELINE-OP-K", "domain": "KNOWLEDGE",
                            "subject_person_ids": ["PERSON-0000"],
                            "requirements": [["PERSON-0000", "KNOWLEDGE", "VIEW"]],
                            "request": None}]}
    body = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    if len(body) != 250:
        raise ValueError(f"unexpected plan size: {len(body)}")
    context = ssl.create_default_context(cafile=str(args.certs / "ca.pem"))
    if args.client_prefix == "runtime":
        context.load_cert_chain(args.certs / "runtime.cert.pem", args.certs / "runtime.key.pem")
    elif args.client_prefix == "client":
        context.load_cert_chain(args.certs / "client.pem", args.certs / "client.key")
    else:
        parser.error("client prefix must be runtime or client")
    conn = http.client.HTTPSConnection("home-bench.invalid", 18463, context=context, timeout=5)
    conn._create_connection = lambda address, timeout=5, source_address=None: socket.create_connection(
        ("100.71.79.33", 18463), timeout=timeout, source_address=source_address)
    try:
        with args.output.open("w", encoding="utf-8") as output:
            for index in range(-1, args.samples):
                start = time.perf_counter_ns()
                conn.request("POST", args.path, body=body, headers={"Content-Type": "application/json"})
                sent = time.perf_counter_ns()
                response = conn.getresponse()
                headers_read = time.perf_counter_ns()
                raw = response.read()
                end = time.perf_counter_ns()
                if response.status != 200 or json.loads(raw)["decisions"][0]["allowed"] is not True:
                    raise ValueError("unexpected Home decision")
                if index >= 0:
                    output.write(json.dumps({"case": "original_responder_rt2", "round": index,
                        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "request_bytes": len(body), "response_bytes": len(raw),
                        "request_ms": (end - start) / 1e6,
                        "send_ms": (sent - start) / 1e6,
                        "headers_read_ms": (headers_read - sent) / 1e6,
                        "body_read_ms": (end - headers_read) / 1e6}) + "\n")
                    output.flush()
    finally:
        conn.close()
    print(json.dumps({"rows": args.samples, "output": str(args.output), "request_bytes": len(body)}))


if __name__ == "__main__":
    main()
