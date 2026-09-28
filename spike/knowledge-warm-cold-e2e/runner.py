"""One direct Nuremberg -> Ashburn -> Nuremberg pre-LLM request per row."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from r13_wire import DOMAINS, canonical

GATE_ROOT = Path(__file__).resolve().parents[1] / "knowledge-technology-gate"
sys.path.insert(0, str(GATE_ROOT))
from backends.common import AuthorizedSet, ContentAccessLog  # noqa: E402
from backends.sqlite_backend import SQLiteKnowledgeBackend  # noqa: E402
from corpus.generator import generate_corpus  # noqa: E402

VERSION = "warm-cold-e2e-3"
AS_OF = 2_000_000_000
SCENARIOS = {
    "P1": (),
    "P2": ("NUTRITION",),
    "P3": ("NUTRITION", "CALENDAR", "HOUSEHOLD"),
    "P4": ("NUTRITION", "CALENDAR", "HOUSEHOLD", "FINANCE", "HEALTH"),
}


def ms(start: int) -> float:
    return (time.perf_counter_ns() - start) / 1e6


def _context(root: Path) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(root / "ca.pem"))
    context.load_cert_chain(root / "runtime.cert.pem", root / "runtime.key.pem")
    return context


class Transport:
    """Counts a Home crossing only after an actual HTTPS request send returns."""

    def __init__(self, host: str, port: int, hostname: str, context: ssl.SSLContext):
        self.connection = http.client.HTTPSConnection(host, port, context=context, timeout=5)
        self.connection._create_connection = lambda address, timeout=5, source_address=None: socket.create_connection(
            (host, port), timeout=timeout, source_address=source_address
        )
        # HTTPSConnection uses `host` as the SNI/verification name. The private
        # address is retained as the TCP destination, while cert name stays pinned.
        self.connection.host = hostname
        self._tcp_host = host
        self.port = port
        self.count = 0
        self.bytes: list[tuple[int, int]] = []

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = canonical(payload)
        self.connection.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        self.count += 1
        response = self.connection.getresponse()
        raw = response.read()
        self.bytes.append((len(body), len(raw)))
        if response.status != 200:
            raise PermissionError(f"transport status {response.status}")
        return json.loads(raw)

    def close(self) -> None:
        self.connection.close()


def _backend(path: Path) -> SQLiteKnowledgeBackend:
    backend = SQLiteKnowledgeBackend(path, create_schema=False)
    # The old Gate's reusable backend defaults to NORMAL. This probe explicitly
    # sets and reads back the accepted production durability profile before use.
    for pragma, value in (("synchronous", "FULL"), ("wal_autocheckpoint", 1000),
                          ("busy_timeout", 5000), ("foreign_keys", "ON")):
        backend.conn.execute(f"PRAGMA {pragma}={value}")
    checks = {name: backend.conn.execute(f"PRAGMA {name}").fetchone()[0] for name in (
        "journal_mode", "synchronous", "wal_autocheckpoint", "busy_timeout", "foreign_keys"
    )}
    if checks != {"journal_mode": "wal", "synchronous": 2, "wal_autocheckpoint": 1000,
                  "busy_timeout": 5000, "foreign_keys": 1}:
        raise RuntimeError(f"SQLite profile mismatch: {checks}")
    return backend


def prepare_database(path: Path) -> dict[str, Any]:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    corpus = generate_corpus("C-small", seed=42)
    backend = SQLiteKnowledgeBackend(path, create_schema=True)
    backend.conn.execute("PRAGMA synchronous=FULL")
    backend.conn.execute("PRAGMA wal_autocheckpoint=1000")
    backend.conn.execute("PRAGMA foreign_keys=ON")
    backend.load_corpus(corpus)
    checks = {name: backend.conn.execute(f"PRAGMA {name}").fetchone()[0] for name in (
        "journal_mode", "synchronous", "wal_autocheckpoint", "busy_timeout", "foreign_keys"
    )}
    backend.close()
    return {"created": True, "corpus": "C-small", "assertions": len(corpus.assertions),
            "sqlite_version": __import__("sqlite3").sqlite_version, "profile": checks}


def _operations(planned: Any, surviving: frozenset[str], domains: tuple[str, ...],
                request_id: str, plan_id: str) -> list[dict[str, Any]]:
    requirements = [r for r in planned.candidate_requirements if r.version_id in surviving]
    subjects = sorted({s for r in requirements for s in r.subject_person_ids})
    pairs = sorted({(subject, domain, "VIEW") for r in requirements
                    for subject in r.subject_person_ids for domain in (*r.domains, "KNOWLEDGE")})
    if not subjects or not pairs:
        raise RuntimeError("empty protected plan")
    operations = [{"operation_id": f"BENCH-OP-K-{request_id}", "domain": "KNOWLEDGE",
                   "subject_person_ids": subjects, "requirements": [list(pair) for pair in pairs],
                   "request": None}]
    for domain in domains:
        op_id = f"BENCH-OP-{domain}-{request_id}"
        request = {"request_id": request_id, "plan_id": plan_id, "operation_id": op_id,
                   "subject_person_id": "PERSON-0000", "resource_id": f"BENCH-RESOURCE-{domain}"}
        operations.append({"operation_id": op_id, "domain": domain,
                           "subject_person_ids": ["PERSON-0000"],
                           "requirements": [["PERSON-0000", domain, "VIEW"]],
                           "request": request})
    return operations


def _domain_call(domain: str, operation: dict[str, Any], basis: dict[str, str],
                 root: Path, port: int, shared: Transport | None = None) -> dict[str, Any]:
    transport = shared or Transport("127.0.0.1", port + DOMAINS.index(domain),
                                    "domain-bench.invalid", _context(root))
    before = transport.count
    started = time.perf_counter_ns()
    try:
        result = transport.post("/r13/read", {"request": operation["request"], "basis": basis})
        if result.get("executed") is not True:
            raise PermissionError("domain denied")
        return {"transport_ms": ms(started), "response": result,
                "call_count": transport.count - before}
    finally:
        if shared is None:
            transport.close()


def run_one(args: argparse.Namespace, home: Transport | None = None,
            backend: SQLiteKnowledgeBackend | None = None,
            domain_transports: dict[str, Transport] | None = None) -> dict[str, Any]:
    total_start = time.perf_counter_ns()
    phases: dict[str, float] = {}
    counts = {"home_auth_round_trip_count": 0, "authorization_operation_count": 0,
              "domain_call_count": 0, "knowledge_read_count": 0,
              "r13_verification_count": 0, "repository_read_count": 0,
              "source_expansion_count": 0}
    own_home = home is None
    own_backend = backend is None
    result: dict[str, Any] = {}
    try:
        started = time.perf_counter_ns()
        request_id = f"BENCH-{uuid.uuid4().hex}"
        plan_id = f"BENCH-PLAN-{request_id}"
        domains = SCENARIOS[args.scenario]
        root = Path(args.root)
        if own_backend:
            backend = _backend(Path(args.db))
        if own_home:
            home = Transport(args.home_host, args.home_port, "home-bench.invalid", _context(root))
        assert backend is not None and home is not None
        phases["request_preparation_ms"] = ms(started)

        started = time.perf_counter_ns()
        planned = backend.plan_metadata(
            partition_id="PARTITION-C-small-1", subject_person_ids=("PERSON-0000",),
            domains=("NUTRITION", "CALENDAR", "HOUSEHOLD"), as_of=AS_OF,
        )
        suppressed = backend.suppressed_version_ids("PARTITION-C-small-1")
        surviving = frozenset(v for v in planned.candidate_version_ids if v not in suppressed)
        operations = _operations(planned, surviving, domains, request_id, plan_id)
        plan = {"request_id": request_id, "plan_id": plan_id, "operations": operations}
        counts["authorization_operation_count"] = len(operations)
        phases["protected_metadata_planning_ms"] = ms(started)

        started = time.perf_counter_ns()
        rt1 = home.post("/rt1", plan)
        phases["home_rt1_transport_ms"] = ms(started)
        if [x.get("operation_id") for x in rt1.get("decisions", [])] != [o["operation_id"] for o in operations]:
            raise PermissionError("RT1 decision coverage mismatch")
        if any(x.get("allowed") is not True for x in rt1["decisions"]):
            raise PermissionError("RT1 denied")

        started = time.perf_counter_ns()
        bases = {o["operation_id"]: d["basis"] for o, d in zip(operations, rt1["decisions"])
                 if o["domain"] != "KNOWLEDGE"}
        phases["r13_basis_handling_ms"] = ms(started)

        domain_started = time.perf_counter_ns()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(domains))) as pool:
            futures = [pool.submit(_domain_call, domain, op, bases[op["operation_id"]], root,
                                   args.domain_port,
                                   domain_transports.get(domain) if domain_transports else None)
                       for domain, op in zip(domains, operations[1:])]
            started = time.perf_counter_ns()
            content_log = ContentAccessLog()
            content = backend.fetch_content(AuthorizedSet(tuple(sorted(surviving))), log=content_log)
            counts["knowledge_read_count"] = 1
            phases["sqlite_knowledge_execution_ms"] = ms(started)
            domain_results = [future.result() for future in futures]
        phases["domain_transport_ms"] = ms(domain_started) if domains else 0.0
        counts["domain_call_count"] = sum(row["call_count"] for row in domain_results)
        counts["r13_verification_count"] = sum(row["response"]["r13_verification_count"] for row in domain_results)
        counts["repository_read_count"] = sum(row["response"]["repository_read_count"] for row in domain_results)
        phases["domain_verifier_ms"] = max((row["response"]["verifier_ms"] for row in domain_results), default=0.0)
        phases["domain_repository_read_ms"] = max((row["response"]["repository_ms"] for row in domain_results), default=0.0)

        started = time.perf_counter_ns()
        selected = tuple(sorted(row["version_id"] for row in content))[:8]
        phases["rank_select_ms"] = ms(started)

        started = time.perf_counter_ns()
        rt2 = home.post("/rt2", plan)
        phases["home_rt2_transport_ms"] = ms(started)
        started = time.perf_counter_ns()
        if [x.get("operation_id") for x in rt2.get("decisions", [])] != [o["operation_id"] for o in operations]:
            raise PermissionError("RT2 decision coverage mismatch")
        if any(x.get("allowed") is not True for x in rt2["decisions"]):
            raise PermissionError("RT2 denied")
        if any(v in backend.suppressed_version_ids("PARTITION-C-small-1") for v in selected):
            raise PermissionError("suppressed before disclosure")
        if len(domain_results) != len(domains):
            raise PermissionError("missing domain result")
        phases["final_pre_disclosure_validation_ms"] = ms(started)
        started = time.perf_counter_ns()
        _bundle = (selected, tuple(domain_results), request_id)  # ephemeral; never logged
        phases["context_bundle_construction_ms"] = ms(started)
        if home.count - args.home_count_start != 2:
            raise RuntimeError("Home crossing invariant failed")
        if counts["authorization_operation_count"] != 1 + len(domains):
            raise RuntimeError("authorization operation invariant failed")
        result["success"] = True
        result["selected_count"] = len(selected)
    except Exception as exc:
        result["success"] = False
        result["failure_class"] = type(exc).__name__
    finally:
        counts["home_auth_round_trip_count"] = home.count - args.home_count_start if home else 0
        result.update({"benchmark_version": VERSION, "git_sha": args.git_sha,
                       "topology": "Nuremberg SQLite/runtime + Ashburn private TLS Home + Nuremberg mTLS domains",
                       "scenario": args.scenario, "classification": args.classification,
                       "iteration": args.iteration, "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                       "total_pre_llm_ms": ms(total_start), "phases_ms": phases, "counters": counts,
                       "home_body_bytes": home.bytes[-2:] if home else []})
        if own_home and home:
            home.close()
        if own_backend and backend:
            backend.close()
    return result


def _one(args: argparse.Namespace) -> None:
    args.home_count_start = 0
    print(json.dumps(run_one(args), sort_keys=True), flush=True)


def _batch(args: argparse.Namespace) -> None:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    with output.open("x", encoding="utf-8") as out:
        if args.classification == "warm":
            backend = _backend(Path(args.db))
            home = Transport(args.home_host, args.home_port, "home-bench.invalid", _context(Path(args.root)))
            domain_transports = {
                domain: Transport("127.0.0.1", args.domain_port + DOMAINS.index(domain),
                                  "domain-bench.invalid", _context(Path(args.root)))
                for domain in SCENARIOS[args.scenario]
            }
            try:
                for iteration in range(-args.warmup, args.samples):
                    args.iteration = iteration
                    args.home_count_start = home.count
                    row = run_one(args, home=home, backend=backend,
                                  domain_transports=domain_transports)
                    if not row["success"]:
                        raise RuntimeError(f"warm request failed at {iteration}: {row['failure_class']}")
                    if iteration >= 0:
                        out.write(json.dumps(row, sort_keys=True) + "\n")
                        out.flush()
            finally:
                home.close()
                for transport in domain_transports.values():
                    transport.close()
                backend.close()
        else:
            for iteration in range(args.samples):
                command = [sys.executable, __file__, "one", "--root", args.root, "--db", args.db,
                           "--home-host", args.home_host, "--home-port", str(args.home_port),
                           "--domain-port", str(args.domain_port), "--git-sha", args.git_sha,
                           "--scenario", args.scenario, "--classification", "cold",
                           "--iteration", str(iteration)]
                started = time.perf_counter_ns()
                completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
                wall_ms = ms(started)
                row = json.loads(completed.stdout)
                row["process_start_and_exit_ms"] = wall_ms - row["total_pre_llm_ms"]
                row["internal_request_ms"] = row["total_pre_llm_ms"]
                row["process_lifetime_ms"] = wall_ms
                if not row["success"]:
                    raise RuntimeError(f"cold request failed at {iteration}: {row['failure_class']}")
                out.write(json.dumps(row, sort_keys=True) + "\n")
                out.flush()
    print(json.dumps({"completed": True, "scenario": args.scenario,
                      "classification": args.classification, "samples": args.samples,
                      "output": str(output)}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "one", "batch"))
    parser.add_argument("--root", default="")
    parser.add_argument("--db", required=True)
    parser.add_argument("--home-host", default="100.71.79.33")
    parser.add_argument("--home-port", type=int, default=18443)
    parser.add_argument("--domain-port", type=int, default=18444)
    parser.add_argument("--git-sha", default="")
    parser.add_argument("--scenario", choices=SCENARIOS, default="P1")
    parser.add_argument("--classification", choices=("warm", "cold"), default="warm")
    parser.add_argument("--iteration", type=int, default=0)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    if args.mode == "prepare":
        print(json.dumps(prepare_database(Path(args.db)), sort_keys=True))
    elif args.mode == "one":
        _one(args)
    else:
        _batch(args)


if __name__ == "__main__":
    main()
