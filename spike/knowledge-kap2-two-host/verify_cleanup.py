"""Read-only verification of the exact disposable two-host resources."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path


def verify(*, side: str, root: Path, cert_dir: Path, evidence: Path,
           host: str, port: int, bench: Path | None = None,
           source: Path | None = None, frappe_result: Path | None = None) -> dict:
    if side not in {"home", "witness"}:
        raise ValueError("invalid side")
    if not root.name.startswith("kap2-pr71-twohost-") or root.parent != Path("/tmp"):
        raise ValueError("invalid disposable root")
    if not cert_dir.name.startswith("kap2-pr71-") or cert_dir.parent != Path("/tmp"):
        raise ValueError("invalid disposable certificate path")
    checked = {"root_absent": not root.exists(), "cert_dir_absent": not cert_dir.exists()}
    if bench is not None:
        checked["bench_absent"] = not bench.exists()
    if source is not None:
        checked["source_absent"] = not source.exists()
    if not evidence.is_file():
        checked["evidence_present"] = False
    else:
        checked["evidence_present"] = True
        events = [json.loads(line) for line in evidence.read_text().splitlines() if line]
        cleanup_name = "home_cleanup" if side == "home" else "witness_cleanup"
        checked["runner_cleanup_recorded"] = any(
            event.get("step") == cleanup_name and event.get("root_absent") is True
            for event in events)
    if side == "witness":
        with socket.socket() as connection:
            connection.settimeout(1)
            checked["listener_absent"] = connection.connect_ex((host, port)) != 0
    if frappe_result is not None:
        if frappe_result.is_file():
            value = json.loads(frappe_result.read_text())
            cleanup = value.get("cleanup", {})
            checked["frappe_cleanup_recorded"] = (
                len(cleanup) == 4 and all(flag is True for flag in cleanup.values()))
        else:
            checked["frappe_cleanup_recorded"] = False
    return {"side": side, "checks": checked, "complete": all(checked.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--side", choices=("home", "witness"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cert-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=19442)
    parser.add_argument("--bench", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--frappe-result", type=Path)
    args = parser.parse_args()
    result = verify(**vars(args))
    print(json.dumps(result, sort_keys=True))
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
