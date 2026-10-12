"""Disposable mTLS transport for the disconnected KAP-2 PERSON probe.

The caller counts every attempted request, including failed TLS/HTTP attempts.
There are no automatic retries or cached authorization answers.
"""

from __future__ import annotations

import http.client
import json
import ssl
import threading
import time
from pathlib import Path
from typing import Any


class WitnessTransportError(RuntimeError):
    pass


class RequestLedger:
    def __init__(self, cap: int = 400) -> None:
        self.cap = cap
        self._lock = threading.Lock()
        self.attempts: list[dict[str, Any]] = []

    def reserve(self, role: str, operation: str) -> int:
        with self._lock:
            if len(self.attempts) >= self.cap:
                raise WitnessTransportError("witness request cap reached")
            self.attempts.append({"role": role, "operation": operation,
                                  "duration_ms": None, "outcome": "uncertain"})
            return len(self.attempts) - 1

    def finish(self, index: int, duration_ms: float, outcome: str) -> None:
        with self._lock:
            self.attempts[index]["duration_ms"] = round(duration_ms, 3)
            self.attempts[index]["outcome"] = outcome

    def count(self, operation: str | None = None) -> int:
        with self._lock:
            return sum(1 for item in self.attempts
                       if operation is None or item["operation"] == operation)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            by_operation: dict[str, int] = {}
            by_role: dict[str, int] = {}
            by_outcome: dict[str, int] = {}
            for item in self.attempts:
                for counts, key in ((by_operation, item["operation"]),
                                    (by_role, item["role"]),
                                    (by_outcome, item["outcome"])):
                    counts[key] = counts.get(key, 0) + 1
            return {"total": len(self.attempts), "cap": self.cap,
                    "by_operation": by_operation, "by_role": by_role,
                    "by_outcome": by_outcome}


class WitnessClient:
    """One authenticated identity, with thread-local warm connections."""

    def __init__(self, *, host: str, port: int, ca: Path, cert: Path, key: Path,
                 role: str, ledger: RequestLedger, timeout: float = 2.0) -> None:
        if role not in {"serving", "recovery"}:
            raise ValueError("unknown witness client role")
        self.host, self.port, self.role = host, port, role
        self.ledger, self.timeout = ledger, timeout
        self.context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
        self.context.load_cert_chain(str(cert), str(key))
        self.context.check_hostname = True
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._local = threading.local()

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def call(self, operation: str, *args: Any, cold: bool = False) -> Any:
        if cold:
            self.close()
        index = self.ledger.reserve(self.role, operation)
        start = time.perf_counter_ns()
        try:
            connection = getattr(self._local, "connection", None)
            if connection is None:
                connection = http.client.HTTPSConnection(
                    self.host, self.port, context=self.context, timeout=self.timeout)
                self._local.connection = connection
            payload = json.dumps({"operation": operation, "args": args},
                                 separators=(",", ":"), ensure_ascii=True).encode("ascii")
            if len(payload) > 4096:
                raise WitnessTransportError("request body exceeds probe limit")
            connection.request("POST", "/rpc", payload,
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(4097)
            if len(body) > 4096:
                raise WitnessTransportError("response body exceeds probe limit")
            value = json.loads(body)
            if (response.status != 200 or type(value) is not dict
                    or value.get("ok") is not True or "result" not in value):
                raise WitnessTransportError(f"witness refused {operation} ({response.status})")
            self.ledger.finish(index, (time.perf_counter_ns() - start) / 1e6, "ok")
            return value["result"]
        except Exception as exc:
            self.close()
            self.ledger.finish(index, (time.perf_counter_ns() - start) / 1e6,
                               type(exc).__name__)
            if isinstance(exc, WitnessTransportError):
                raise
            raise WitnessTransportError(f"uncertain witness {operation}") from exc


class RemoteWitness:
    """Test adapter with distinct serving and recovery mTLS identities."""

    def __init__(self, serving: WitnessClient, recovery: WitnessClient) -> None:
        self.serving, self.recovery = serving, recovery

    def recover(self, partition: str) -> str:
        value = self.recovery.call("recover", partition)
        if type(value) is not str or len(value) != 64:
            raise WitnessTransportError("invalid incarnation response")
        return value

    def _read_current(self, partition: str) -> tuple[Any, ...] | None:
        value = self.recovery.call("read_current", partition)
        return tuple(value) if type(value) is list else None

    def authorize(self, partition: str, incarnation: str, revision: int,
                  digest: str) -> bool:
        value = self.serving.call("authorize", partition, incarnation, revision, digest)
        if type(value) is not bool:
            raise WitnessTransportError("invalid authorization response")
        return value

    def prepare(self, partition: str, incarnation: str, event: str,
                expected_revision: int, digest: str) -> None:
        if self.serving.call("prepare", partition, incarnation, event,
                             expected_revision, digest) is not None:
            raise WitnessTransportError("invalid prepare response")

    def commit(self, partition: str, incarnation: str, event: str,
               digest: str) -> None:
        if self.serving.call("commit", partition, incarnation, event, digest) is not None:
            raise WitnessTransportError("invalid commit response")

    def event_outcome(self, partition: str, incarnation: str,
                      event: str) -> tuple[str, int, str] | None:
        value = self.serving.call("event_outcome", partition, incarnation, event)
        return tuple(value) if type(value) is list and len(value) == 3 else None
