"""Fault injections for the disposable GCS journal probe; no tokens are logged."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

import gcs_live_probe as probe


class FaultHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/slow":
            time.sleep(0.5)
            try:
                self.send_response(200)
                self.end_headers()
            except BrokenPipeError:
                pass
            return
        self.send_response(429 if self.path == "/throttle" else 503)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


def main() -> None:
    results: dict = {"environment": "localhost fault injection plus disposable GCS bucket"}
    server = HTTPServer(("127.0.0.1", 0), FaultHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        try:
            requests.get(f"{base}/slow", timeout=0.05)
            results["timeout"] = "unexpected_success"
        except requests.Timeout as exc:
            results["timeout"] = type(exc).__name__
        results["throttle_injected_status"] = requests.get(f"{base}/throttle", timeout=2).status_code
        results["unavailable_injected_status"] = requests.get(f"{base}/unavailable", timeout=2).status_code
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    name = probe.key(1, "generation-test-ambiguous")
    payload = b"SYNTHETIC-AMBIGUOUS-RESPONSE"
    status, _, _ = probe.put("ambiguous_server_create", name, payload)
    results["server_create_status_hidden_from_client"] = status
    results["injected_client_outcome"] = "UNKNOWN: post-send response discarded"
    read_status, read_body, _ = probe.get("ambiguous_authoritative_read", name, media=True)
    results["reconciliation_status"] = read_status
    results["reconciliation_exact_bytes"] = read_body == payload
    duplicate_status, _, _ = probe.put("ambiguous_safe_retry", name, payload)
    results["safe_retry_conflict_status"] = duplicate_status

    page_status, page_body, _ = probe.listing(
        "interrupted_page_1", f"{probe.ROOT}/generation-test-1/", max_results=1,
    )
    results["interrupted_page_status"] = page_status
    results["interrupted_page_has_next_token"] = bool(
        isinstance(page_body, dict) and page_body.get("nextPageToken")
    )
    results["interrupted_verification_state"] = "UNVERIFIED"
    results["events"] = probe.events
    output = Path(__file__).with_name("gcs_failure_observations.json")
    output.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in results.items() if k != "events"}, indent=2, sort_keys=True))
    print(f"RAW_OBSERVATIONS={output}")


if __name__ == "__main__":
    main()
