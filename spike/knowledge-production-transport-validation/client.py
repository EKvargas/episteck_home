"""Measure synthetic Home HTTP/TLS requests across the private route."""

from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import httpcore
import httpx


CASES = {
    "reused_small_small": (832, 112, False),
    "reused_large_small": (2222, 112, False),
    "reused_small_large": (832, 5036, False),
    "reused_large_large": (2222, 5036, False),
    "fresh_rt1": (1297, 1756, True),
    "fresh_rt2": (1297, 204, True),
    "representative_rt1": (2222, 5036, False),
    "representative_rt2": (2222, 387, False),
}


def _client(ca: str) -> httpx.Client:
    # Match the deployed Nutrition Home client's httpx.Client defaults and 3 s timeout.
    # Only the disposable CA and a disabled environment proxy differ.
    return httpx.Client(
        verify=ca,
        timeout=3.0,
        trust_env=False,
        headers={
            "Authorization": "token synthetic:synthetic",
            "Accept": "application/json",
        },
    )


def _body(size: int) -> bytes:
    prefix, suffix = b'{"pad":"', b'"}'
    return prefix + b"a" * (size - len(prefix) - len(suffix)) + suffix


def measure(client: httpx.Client, url: str, case: str, sequence: int) -> dict:
    request_size, response_size, fresh = CASES[case]
    trace: dict[str, int] = {}

    def on_trace(event: str, info: dict) -> None:
        del info
        trace[event] = time.perf_counter_ns()

    body = _body(request_size)
    request = client.build_request(
        "POST",
        url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Response-Bytes": str(response_size),
            "X-Case": case,
        },
    )
    request.extensions["trace"] = on_trace
    started = time.perf_counter_ns()
    response = client.send(request, stream=True)
    header_complete = time.perf_counter_ns()
    first_body = None
    actual_body_size = 0
    for chunk in response.iter_raw():
        if first_body is None:
            first_body = time.perf_counter_ns()
        actual_body_size += len(chunk)
    completed = time.perf_counter_ns()
    status = response.status_code
    server_receive = int(response.headers.get("x-probe-server-receive-ns", "-1"))
    app = int(response.headers.get("x-probe-app-ns", "-1"))
    response.close()
    if status != 200 or server_receive < 0 or app < 0 or first_body is None:
        raise RuntimeError(f"invalid synthetic response: status={status}")
    return {
        "case": case,
        "sequence": sequence,
        "fresh": fresh,
        "request_bytes": request_size,
        "response_bytes": response_size,
        "wire_body_bytes": actual_body_size,
        "total_ms": (completed - started) / 1e6,
        "header_complete_ms": (header_complete - started) / 1e6,
        "first_body_ms": (first_body - started) / 1e6,
        "body_complete_ms": (completed - started) / 1e6,
        "server_receive_ms": server_receive / 1e6,
        "app_ms": app / 1e6,
        "trace_ms": {key: (value - started) / 1e6 for key, value in trace.items()},
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--case", choices=[*CASES, "all"], default="all")
    args = parser.parse_args()
    if args.samples < 30:
        raise SystemExit("at least 30 observations required")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    chosen = CASES if args.case == "all" else {args.case: CASES[args.case]}
    with output.open("w", encoding="utf-8") as sink:
        sink.write(json.dumps({"meta": {
            "python": platform.python_version(),
            "httpx": httpx.__version__,
            "httpcore": httpcore.__version__,
            "url": args.url,
            "samples_per_case": args.samples,
        }}, sort_keys=True) + "\n")
        for case, (_, _, fresh) in chosen.items():
            if fresh:
                for sequence in range(args.samples):
                    with _client(args.ca) as client:
                        sink.write(json.dumps(measure(client, args.url, case, sequence), sort_keys=True) + "\n")
            else:
                with _client(args.ca) as client:
                    measure(client, args.url, case, -1)  # excluded connection warmup
                    for sequence in range(args.samples):
                        sink.write(json.dumps(measure(client, args.url, case, sequence), sort_keys=True) + "\n")
            sink.flush()


if __name__ == "__main__":
    main()
