"""Separate fail-closed probes; never included in successful latency percentiles."""
from __future__ import annotations

import argparse
import copy
import json
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from r13_wire import canonical
from responders import DomainState
from runner import AS_OF, Transport, _context, _domain_call, _operations, _backend, run_one


def _args(root: Path, db: Path, *, home_port: int, domain_port: int) -> SimpleNamespace:
    return SimpleNamespace(root=str(root), db=str(db), home_host="100.71.79.33",
                           home_port=home_port, domain_port=domain_port, git_sha="fault-probe",
                           scenario="P2", classification="failure", iteration=0,
                           home_count_start=0)


def _raw_domain(root: Path, port: int, payload: dict) -> tuple[int, dict]:
    # Same verified mTLS peer as the measured runner, but retain denial body.
    transport = Transport("127.0.0.1", port, "domain-bench.invalid", _context(root))
    try:
        body = canonical(payload)
        transport.connection.request("POST", "/r13/read", body=body,
                                     headers={"Content-Type": "application/json"})
        response = transport.connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        transport.close()


class MissingRT2(Transport):
    def post(self, path: str, payload: dict) -> dict:
        if path == "/rt2":
            raise ConnectionError("injected RT2 transport unavailable")
        return super().post(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--home-port", type=int, default=18443)
    parser.add_argument("--domain-port", type=int, default=18444)
    args = parser.parse_args()
    results = {}

    row = run_one(_args(args.root, args.db, home_port=18499, domain_port=args.domain_port))
    results["home_rt1_unavailable"] = not row["success"] and row["counters"]["home_auth_round_trip_count"] == 0 and "context_bundle_construction_ms" not in row["phases_ms"]

    home = MissingRT2("100.71.79.33", args.home_port, "home-bench.invalid", _context(args.root))
    try:
        row = run_one(_args(args.root, args.db, home_port=args.home_port,
                            domain_port=args.domain_port), home=home)
        results["home_rt2_unavailable"] = (
            not row["success"] and row["counters"]["home_auth_round_trip_count"] == 1 and
            row["counters"]["repository_read_count"] == 1 and
            "context_bundle_construction_ms" not in row["phases_ms"]
        )
    finally:
        home.close()

    row = run_one(_args(args.root, args.db, home_port=args.home_port,
                        domain_port=18499))
    results["domain_unavailable"] = not row["success"] and "context_bundle_construction_ms" not in row["phases_ms"]

    backend = _backend(args.db)
    transport = Transport("100.71.79.33", args.home_port, "home-bench.invalid", _context(args.root))
    try:
        planned = backend.plan_metadata(
            partition_id="PARTITION-C-small-1", subject_person_ids=("PERSON-0000",),
            domains=("NUTRITION", "CALENDAR", "HOUSEHOLD"), as_of=AS_OF)
        suppressed = backend.suppressed_version_ids("PARTITION-C-small-1")
        surviving = frozenset(v for v in planned.candidate_version_ids if v not in suppressed)
        request_id = f"BENCH-FAULT-{uuid.uuid4().hex}"
        plan_id = f"BENCH-PLAN-{request_id}"
        operations = _operations(planned, surviving, ("NUTRITION",), request_id, plan_id)
        plan = {"request_id": request_id, "plan_id": plan_id, "operations": operations}
        rt1 = transport.post("/rt1", plan)
        basis = rt1["decisions"][1]["basis"]
        wire = {"request": operations[1]["request"], "basis": basis}
        changed = copy.deepcopy(wire)
        sig = changed["basis"]["signature_hex"]
        changed["basis"]["signature_hex"] = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        status, response = _raw_domain(args.root, args.domain_port, changed)
        results["r13_bad_signature"] = status == 403 and response["repository_read_count"] == 0

        status, response = _raw_domain(args.root, args.domain_port, wire)
        if status != 200 or response["repository_read_count"] != 1:
            raise AssertionError("first execution failed")
        status, response = _raw_domain(args.root, args.domain_port, wire)
        results["r13_replay"] = status == 403 and response["repository_read_count"] == 0

        with tempfile.TemporaryDirectory(prefix="knowledge-e2e-stale-") as temporary:
            local = DomainState(args.root, Path(temporary) / "security.sqlite")
            local.verified_at = int(time.time()) - 301
            peer = x509.load_pem_x509_certificate((args.root / "runtime.cert.pem").read_bytes()).public_bytes(
                serialization.Encoding.DER
            )
            stale = local.execute("NUTRITION", wire, peer)
            results["r13_stale_trust"] = not stale["executed"] and stale["repository_read_count"] == 0
            local.db.close()
    finally:
        transport.close()
        backend.close()
    print(json.dumps({"failure_probes": results, "all_fail_closed": all(results.values())},
                     sort_keys=True))
    if not all(results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
