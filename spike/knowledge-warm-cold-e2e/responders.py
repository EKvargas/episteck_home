"""Private, disposable Home and domain responders for the direct E2E probe."""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sqlite3
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from r13_wire import (
    DOMAINS, RUNTIME_URI, TRUST_PREFIX, canonical, decode_basis, domain_uri,
    encode_basis, peer_identity_and_spki,
)

ACTOR = "BENCH-ACTOR"
PARTITION = "BENCH-PARTITION"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())


def _load_public(path: Path) -> Any:
    return serialization.load_pem_public_key(path.read_bytes())


def _load_private(path: Path) -> Any:
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


class QuietHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: Any) -> None:
        pass

    def _request(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            raise ValueError("invalid request length")
        return json.loads(self.rfile.read(length), object_pairs_hook=_unique)

    def _response(self, status: int, payload: dict[str, Any]) -> None:
        body = canonical(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _valid_operation(operation: dict[str, Any]) -> bool:
    if type(operation) is not dict or set(operation) != {
        "operation_id", "domain", "subject_person_ids", "requirements", "request"
    }:
        return False
    subjects = operation["subject_person_ids"]
    if type(subjects) is not list or not subjects or any(
        type(s) is not str or not s.startswith("PERSON-") for s in subjects
    ):
        return False
    domain = operation["domain"]
    if domain not in ("KNOWLEDGE", *DOMAINS):
        return False
    requirements = operation["requirements"]
    if type(requirements) is not list or not requirements or any(
        type(pair) is not list or len(pair) != 3 or
        pair[0] not in subjects or pair[1] not in ("KNOWLEDGE", *DOMAINS) or pair[2] != "VIEW"
        for pair in requirements
    ):
        return False
    request = operation["request"]
    if domain == "KNOWLEDGE":
        return request is None and any(pair[1] == "KNOWLEDGE" for pair in requirements)
    return (
        type(request) is dict and set(request) == {
            "request_id", "plan_id", "operation_id", "subject_person_id", "resource_id"
        } and request["operation_id"] == operation["operation_id"] and
        request["subject_person_id"] in subjects and
        request["resource_id"] == f"BENCH-RESOURCE-{domain}" and
        [request["subject_person_id"], domain, "VIEW"] in requirements
    )


class HomeState:
    def __init__(self, root: Path):
        config = _load_json(root / "home-config.json")
        self.runtime_spki = config["runtime_spki"]
        self.kid = config["home_kid"]
        self.signer = _load_private(root / "home-signing.key.pem")
        self.revision = 1
        self.lock = threading.Lock()

    def evaluate(self, phase: str, payload: dict[str, Any], peer_der: bytes) -> dict[str, Any]:
        identity, spki = peer_identity_and_spki(peer_der)
        if identity != RUNTIME_URI or spki != self.runtime_spki:
            raise ValueError("unregistered runtime peer")
        if set(payload) != {"request_id", "plan_id", "operations"}:
            raise ValueError("invalid plan")
        operations = payload["operations"]
        if type(operations) is not list or not 1 <= len(operations) <= 6:
            raise ValueError("invalid operation count")
        ids = [op.get("operation_id") for op in operations]
        if len(ids) != len(set(ids)) or any(not _valid_operation(op) for op in operations):
            raise ValueError("invalid operation")
        if any(op["request"] is not None and (
            op["request"]["request_id"] != payload["request_id"] or
            op["request"]["plan_id"] != payload["plan_id"]
        ) for op in operations):
            raise ValueError("plan/request mismatch")
        with self.lock:
            revision = self.revision  # fresh authority snapshot for each request
        result = []
        now = int(time.time())
        for op in operations:
            item: dict[str, Any] = {"operation_id": op["operation_id"], "allowed": revision == 1}
            if phase == "rt1" and op["domain"] != "KNOWLEDGE" and item["allowed"]:
                request = op["request"]
                claims = {
                    "version": 1, "home_kid": self.kid,
                    "execution_id": f"BENCH-EXEC-{op['operation_id']}",
                    "request_id": payload["request_id"], "plan_id": payload["plan_id"],
                    "operation_id": op["operation_id"], "actor_person_id": ACTOR,
                    "partition_id": PARTITION, "subject_person_ids": op["subject_person_ids"],
                    "resource_ids": [request["resource_id"]], "domain": op["domain"],
                    "action": "VIEW", "use_class": "ORDINARY_READ",
                    "audience": domain_uri(op["domain"]), "caller_service": RUNTIME_URI,
                    "caller_spki_sha256": self.runtime_spki, "method": "POST", "target": "/r13/read",
                    "request_sha256": hashlib.sha256(canonical(request)).hexdigest(),
                    "issued_at": now, "expires_at": now + 60,
                    "authorization_revision": f"BENCH-REV-{revision}",
                    "window_id": "BENCH-WINDOW-1", "decision_id": "BENCH-CORRELATION",
                }
                item["basis"] = encode_basis(claims, self.signer)
            result.append(item)
        return {"decisions": result, "revision": revision}


class HomeHandler(QuietHandler):
    state: HomeState

    def do_POST(self) -> None:
        if self.path not in ("/rt1", "/rt2"):
            self._response(404, {"error": "unknown route"})
            return
        try:
            peer = self.connection.getpeercert(binary_form=True)
            result = self.state.evaluate(self.path[1:], self._request(), peer)
            self._response(200, result)
        except (KeyError, TypeError, ValueError, InvalidSignature):
            self._response(403, {"error": "denied"})


class DomainState:
    def __init__(self, root: Path, db_path: Path):
        self.root = root
        self.home_public = _load_public(root / "home-signing.pub.pem")
        self.distribution_public = _load_public(root / "distribution.pub.pem")
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("CREATE TABLE IF NOT EXISTS spent (audience TEXT, execution_id TEXT, PRIMARY KEY (audience,execution_id))")
        self.db.execute("CREATE TABLE IF NOT EXISTS security_state (id INTEGER PRIMARY KEY, generation INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS resource (domain TEXT PRIMARY KEY, resource_id TEXT NOT NULL)")
        for domain in DOMAINS:
            self.db.execute("INSERT OR IGNORE INTO resource VALUES (?,?)", (domain, f"BENCH-RESOURCE-{domain}"))
        self.db.commit()
        row = self.db.execute("SELECT generation FROM security_state WHERE id=1").fetchone()
        self.generation = row[0] if row else 0
        self.bundle: dict[str, Any] | None = None
        self.verified_at = 0
        self.trust_mtime_ns = 0
        self.lock = threading.Lock()
        self.install_trust()

    def install_trust(self) -> None:
        wire = _load_json(self.root / "trust.json")
        bundle = wire["bundle"]
        self.distribution_public.verify(bytes.fromhex(wire["signature_hex"]), TRUST_PREFIX + canonical(bundle))
        now = int(time.time())
        if set(bundle) != {"generation", "issued_at", "not_after", "active_home_kids", "service_spkis", "domain_audiences"}:
            raise ValueError("bad trust schema")
        if not (bundle["issued_at"] - 5 <= now <= bundle["not_after"] <= bundle["issued_at"] + 300):
            raise ValueError("stale trust")
        if bundle["generation"] <= self.generation:
            raise ValueError("trust rollback")
        with self.lock:
            self.db.execute("INSERT INTO security_state VALUES (1,?) ON CONFLICT(id) DO UPDATE SET generation=excluded.generation", (bundle["generation"],))
            self.db.commit()
            self.generation = bundle["generation"]
            self.bundle = bundle
            self.verified_at = now
            self.trust_mtime_ns = (self.root / "trust.json").stat().st_mtime_ns

    def execute(self, domain: str, wire: dict[str, Any], peer_der: bytes) -> dict[str, Any]:
        begin = time.perf_counter_ns()
        try:
            if (self.root / "trust.json").stat().st_mtime_ns != self.trust_mtime_ns:
                self.install_trust()
            if domain not in DOMAINS or set(wire) != {"request", "basis"}:
                raise ValueError("invalid wire")
            now = int(time.time())
            bundle = self.bundle
            if (bundle is None or now < self.verified_at or now - self.verified_at > 300 or
                now > bundle["not_after"]):
                raise ValueError("stale trust")
            claims = decode_basis(wire["basis"], self.home_public)
            request = wire["request"]
            identity, spki = peer_identity_and_spki(peer_der)
            if claims["home_kid"] not in bundle["active_home_kids"]:
                raise ValueError("revoked Home key")
            if identity != claims["caller_service"] or spki != claims["caller_spki_sha256"]:
                raise ValueError("peer binding mismatch")
            if spki not in bundle["service_spkis"].get(identity, []):
                raise ValueError("untrusted service key")
            if claims["audience"] != bundle["domain_audiences"][domain] or claims["audience"] != domain_uri(domain):
                raise ValueError("audience mismatch")
            if not (claims["issued_at"] - 5 <= now < claims["expires_at"] <= claims["issued_at"] + 60):
                raise ValueError("basis expired")
            if (claims["actor_person_id"], claims["partition_id"], claims["domain"],
                claims["action"], claims["use_class"]) != (ACTOR, PARTITION, domain, "VIEW", "ORDINARY_READ"):
                raise ValueError("scope mismatch")
            if type(request) is not dict or set(request) != {
                "request_id", "plan_id", "operation_id", "subject_person_id", "resource_id"
            }:
                raise ValueError("invalid operation request")
            if (claims["request_id"], claims["plan_id"], claims["operation_id"],
                claims["subject_person_ids"], claims["resource_ids"]) != (
                request["request_id"], request["plan_id"], request["operation_id"],
                [request["subject_person_id"]], [request["resource_id"]]
            ):
                raise ValueError("operation mismatch")
            if (claims["method"], claims["target"], claims["request_sha256"]) != (
                "POST", "/r13/read", hashlib.sha256(canonical(request)).hexdigest()
            ):
                raise ValueError("request digest mismatch")
            if request["resource_id"] != f"BENCH-RESOURCE-{domain}":
                raise ValueError("resource mismatch")
            verify_ms = (time.perf_counter_ns() - begin) / 1e6
            read_start = time.perf_counter_ns()
            with self.lock:
                self.db.execute("INSERT INTO spent VALUES (?,?)", (claims["audience"], claims["execution_id"]))
                self.db.commit()  # atomic single-use claim before repository access
                row = self.db.execute("SELECT resource_id FROM resource WHERE domain=?", (domain,)).fetchone()
            repository_ms = (time.perf_counter_ns() - read_start) / 1e6
            if row is None or row[0] != request["resource_id"]:
                raise ValueError("repository unavailable")
            return {"executed": True, "verifier_ms": verify_ms, "repository_ms": repository_ms,
                    "r13_verification_count": 1, "repository_read_count": 1}
        except (KeyError, TypeError, ValueError, InvalidSignature, sqlite3.Error, OSError):
            return {"executed": False, "verifier_ms": (time.perf_counter_ns() - begin) / 1e6,
                    "repository_ms": 0.0, "r13_verification_count": 1, "repository_read_count": 0}


class DomainHandler(QuietHandler):
    state: DomainState
    domain: str

    def do_POST(self) -> None:
        if self.path != "/r13/read":
            self._response(404, {"error": "unknown route"})
            return
        try:
            peer = self.connection.getpeercert(binary_form=True)
            result = self.state.execute(self.domain, self._request(), peer)
            self._response(200 if result["executed"] else 403, result)
        except (KeyError, TypeError, ValueError):
            self._response(403, {"executed": False, "verifier_ms": 0.0,
                                 "repository_ms": 0.0, "r13_verification_count": 1,
                                 "repository_read_count": 0})


def _serve(address: str, port: int, handler: type[QuietHandler], root: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((address, port), handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    prefix = "home" if handler is HomeHandler else "domain"
    context.load_cert_chain(root / f"{prefix}.cert.pem", root / f"{prefix}.key.pem")
    context.load_verify_locations(root / "ca.pem")
    context.verify_mode = ssl.CERT_REQUIRED
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("home", "domain"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=18443)
    parser.add_argument("--db", type=Path)
    args = parser.parse_args()
    if args.mode == "home":
        HomeHandler.state = HomeState(args.root)
        server = _serve(args.bind, args.port, HomeHandler, args.root)
        print(json.dumps({"ready": True, "mode": "home", "bind": args.bind, "port": args.port}), flush=True)
        server.serve_forever()
    else:
        if args.db is None:
            parser.error("domain mode requires --db")
        DomainHandler.state = DomainState(args.root, args.db)
        servers = []
        for index, domain in enumerate(DOMAINS):
            cls = type(f"Handler_{domain}", (DomainHandler,), {"domain": domain})
            server = _serve(args.bind, args.port + index, cls, args.root)
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        print(json.dumps({"ready": True, "mode": "domain", "bind": args.bind,
                          "ports": [args.port + i for i in range(len(DOMAINS))]}), flush=True)
        threading.Event().wait()


if __name__ == "__main__":
    main()
