"""Foreground, disposable mTLS witness on the Nuremberg test host.

No production service registration, endpoint or database is touched. The only
network listener is the explicitly bound Tailscale address (loopback in tests).
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import secrets
import shutil
import signal
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pymysql

GATEWAY_DIR = Path(__file__).resolve().parents[1] / "knowledge-kap2-transactional-witness"
sys.path.insert(0, str(GATEWAY_DIR))
from gateway import Gateway  # noqa: E402
from test_gateway import PrivateDB  # noqa: E402
from preflight import verify as verify_preflight  # noqa: E402

MARKER = "KAP2_PR71_DISPOSABLE_WITNESS"
SERVING_OPS = frozenset({"authorize", "prepare", "commit", "event_outcome"})
RECOVERY_OPS = frozenset({"recover", "restart_gateway", "snapshot", "restore",
                          "kill_writer", "probe_privileges", "status", "read_current"})


class Evidence:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("a", encoding="utf-8")
        self.lock = threading.Lock()

    def write(self, **event: Any) -> None:
        with self.lock:
            self.handle.write(json.dumps(event, sort_keys=True) + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())

    def close(self) -> None:
        self.handle.close()


class WitnessFixture:
    def __init__(self, root: Path, evidence: Evidence) -> None:
        if root.exists() or root.parent != Path("/tmp") or not root.name.startswith("kap2-pr71-twohost-"):
            raise ValueError("witness root must be a new marked /tmp/kap2-pr71-twohost-* path")
        root.mkdir(mode=0o700)
        (root / MARKER).write_text("synthetic PERSON authority only\n")
        self.root, self.evidence = root, evidence
        (root / "db").mkdir(mode=0o700)
        self.db = PrivateDB(root / "db")
        # Passwords are distinct, per-run, and never written to the evidence log.
        self.passwords = {name: secrets.token_hex(24)
                          for name in ("gw_reader", "gw_writer1", "gw_writer2", "gw_recovery")}
        for name, password in self.passwords.items():
            self.db.sql(f"ALTER USER '{name}'@'localhost' IDENTIFIED BY '{password}'")
        self.gateway = self._new_gateway()
        self.lock = threading.RLock()
        self.requests = 0
        evidence.write(step="witness_started", admission="CLOSED", socket="private",
                       root=str(root))

    def _new_gateway(self) -> Gateway:
        return Gateway(socket=str(self.db.socket), lock_path=str(self.root / "gateway.lock"),
                       reader_password=self.passwords["gw_reader"],
                       writer_password=self.passwords["gw_writer2"],
                       recovery_password=self.passwords["gw_recovery"])

    def _restart_gateway(self) -> None:
        self.gateway.close()
        self.gateway = self._new_gateway()
        assert self.gateway.closed

    def _restart_db(self, restore: bool) -> None:
        self.gateway.close()
        self.db.stop()
        snapshot = self.root / "snapshot"
        if restore:
            if not (snapshot / MARKER).is_file():
                raise RuntimeError("marked physical snapshot absent")
            data = self.db.data.resolve()
            if data.parent != (self.root / "db").resolve() or not data.is_dir():
                raise RuntimeError("unsafe disposable datadir")
            shutil.rmtree(data)
            shutil.copytree(snapshot / "data", data)
        else:
            if snapshot.exists():
                raise RuntimeError("snapshot already exists")
            snapshot.mkdir(mode=0o700)
            (snapshot / MARKER).write_text("synthetic physical snapshot\n")
            shutil.copytree(self.db.data, snapshot / "data")
        self.db.start()
        self.gateway = self._new_gateway()
        assert self.gateway.closed

    def _privileges(self) -> dict[str, bool]:
        result: dict[str, bool] = {}
        probes = {
            "reader_direct_dml_denied": ("gw_reader", "UPDATE witness.head SET digest='FORGED'"),
            "writer_direct_dml_denied": ("gw_writer2", "UPDATE witness.head SET digest='FORGED'"),
            "recovery_direct_dml_denied": ("gw_recovery", "UPDATE witness.head SET digest='FORGED'"),
            "old_writer_new_epoch_denied": (
                "gw_writer1", "CALL witness.prepare_e2('p1','old-incarnation','old',0,'FORGED')"),
        }
        for label, (user, statement) in probes.items():
            with self.db.connect(user, self.passwords[user]) as connection:
                with connection.cursor() as cursor:
                    try:
                        cursor.execute(statement)
                    except pymysql.MySQLError as exc:
                        result[label] = bool(exc.args and exc.args[0] in {1142, 1143, 1370, 1644})
                    else:
                        result[label] = False
        head = self.db.sql("SELECT incarnation,writer_epoch,revision FROM witness.head "
                           "WHERE partition_id='p1'").split("\t")
        if len(head) == 3 and head[1] == "2":
            with self.db.connect("gw_writer1", self.passwords["gw_writer1"]) as old:
                with old.cursor() as cursor:
                    try:
                        cursor.execute("CALL witness.prepare_e1(%s,%s,%s,%s,%s)",
                                       ("p1", head[0], "obsolete-principal-probe",
                                        int(head[2]), "FORGED"))
                    except pymysql.MySQLError as exc:
                        result["old_writer_epoch_denied"] = bool(exc.args and exc.args[0] == 1644)
                    else:
                        result["old_writer_epoch_denied"] = False
        return result

    def dispatch(self, role: str, operation: str, args: list[Any]) -> Any:
        with self.lock:
            self.requests += 1
            if self.requests > 400:
                raise RuntimeError("server request cap reached")
            if operation not in (SERVING_OPS if role == "serving" else RECOVERY_OPS):
                raise PermissionError("credential cannot invoke this route")
            if operation == "restart_gateway" and args == []:
                self._restart_gateway()
                return {"closed": self.gateway.closed}
            if operation in {"snapshot", "restore"} and args == []:
                self._restart_db(operation == "restore")
                return {"closed": self.gateway.closed}
            if operation == "kill_writer" and args == []:
                if self.gateway._writer is None:
                    raise RuntimeError("pinned writer absent")
                with self.gateway._writer.cursor() as cursor:
                    cursor.execute("SELECT CONNECTION_ID()")
                    connection_id = int(cursor.fetchone()[0])
                self.db.sql(f"KILL {connection_id}")
                return {"writer_killed": True}
            if operation == "probe_privileges" and args == []:
                return self._privileges()
            if operation == "status" and args == []:
                return {"closed": self.gateway.closed, "requests": self.requests}
            signatures = {
                "recover": 1, "authorize": 4, "prepare": 5, "commit": 4,
                "event_outcome": 3, "read_current": 1,
            }
            if operation not in signatures or len(args) != signatures[operation]:
                raise ValueError("invalid operation arguments")
            method = getattr(self.gateway, "_read_current" if operation == "read_current" else operation)
            return method(*args)

    def close(self) -> None:
        self.gateway.close()
        self.db.stop()
        marker = self.root / MARKER
        if not marker.is_file() or self.root.parent != Path("/tmp"):
            raise RuntimeError("refusing unmarked witness cleanup")
        shutil.rmtree(self.root)
        self.evidence.write(step="witness_cleanup", root_absent=not self.root.exists(),
                            admission="CLOSED")


class Server(ThreadingHTTPServer):
    fixture: WitnessFixture
    evidence: Evidence


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_: Any) -> None:
        pass

    def _reply(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        started = time.perf_counter_ns()
        role, operation, status = "unknown", "unknown", 400
        try:
            if self.path != "/rpc":
                raise ValueError("unknown path")
            certificate = self.connection.getpeercert()
            common_names = [value for group in certificate.get("subject", ())
                            for key, value in group if key == "commonName"]
            if common_names == ["kap2-home-serving"]:
                role = "serving"
            elif common_names == ["kap2-home-recovery"]:
                role = "recovery"
            else:
                raise PermissionError("unregistered client identity")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                raise ValueError("invalid request length")
            payload = json.loads(self.rfile.read(size))
            if (type(payload) is not dict or set(payload) != {"operation", "args"}
                    or type(payload["operation"]) is not str or type(payload["args"]) is not list):
                raise ValueError("invalid request envelope")
            operation = payload["operation"]
            result = self.server.fixture.dispatch(role, operation, payload["args"])
            status = 200
            self._reply(status, {"ok": True, "result": result})
        except PermissionError:
            status = 403
            self._reply(status, {"ok": False, "error": "denied"})
        except Exception:
            status = 503
            self._reply(status, {"ok": False, "error": "uncertain"})
        finally:
            self.server.evidence.write(step="witness_request", role=role,
                                       operation=operation, status=status,
                                       duration_ms=round((time.perf_counter_ns()-started)/1e6, 3))


def serve(args: argparse.Namespace) -> None:
    if not args.evidence.parent.is_dir():
        raise ValueError("create the separate evidence directory before witness startup")
    if not args.loopback_only and args.evidence.exists():
        raise FileExistsError("remote witness evidence must start empty")
    if args.evidence.resolve().is_relative_to(args.root.resolve()):
        raise ValueError("evidence must be outside the disposable witness root")
    bind = ipaddress.ip_address(args.bind)
    if args.loopback_only:
        if bind != ipaddress.ip_address("127.0.0.1"):
            raise ValueError("local test mode binds loopback only")
    elif bind not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("remote witness must bind a literal Tailscale IPv4 address")
    evidence = Evidence(args.evidence)
    fixture: WitnessFixture | None = None
    server: Server | None = None
    try:
        if not args.loopback_only:
            if not args.expected_sha:
                raise ValueError("reviewed exact SHA is required for remote witness")
            preflight = verify_preflight(
                side="witness", repo=Path(__file__).resolve().parents[2],
                expected_sha=args.expected_sha, root=args.root,
                cert_dir=args.ca.parent, evidence_dir=args.evidence.parent,
                host=args.bind, port=args.port)
            evidence.write(step="preflight", **preflight)
            if not preflight["complete"]:
                raise RuntimeError("witness preflight rejected")
        else:
            evidence.write(step="preflight", status="LOCAL_ONLY_REMOTE_PREFLIGHT_UNEXECUTED")
        fixture = WitnessFixture(args.root, evidence)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(args.cert), str(args.key))
        context.load_verify_locations(cafile=str(args.ca))
        context.verify_mode = ssl.CERT_REQUIRED
        server = Server((args.bind, args.port), Handler)
        server.fixture, server.evidence = fixture, evidence
        server.socket = context.wrap_socket(server.socket, server_side=True)
        evidence.write(step="listener_ready", bind=args.bind, port=args.port,
                       admission="CLOSED")
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(
            target=server.shutdown, daemon=True).start())
        server.serve_forever(poll_interval=0.2)
    finally:
        if server is not None:
            server.server_close()
        if fixture is not None:
            fixture.close()
        evidence.close()


def main() -> None:
    if not __debug__:
        raise SystemExit("optimized Python disables probe assertions")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=19442)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--expected-sha")
    parser.add_argument("--loopback-only", action="store_true")
    serve(parser.parse_args())


if __name__ == "__main__":
    main()
