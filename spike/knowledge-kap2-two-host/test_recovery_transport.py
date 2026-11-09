"""Recovery proof over real loopback mTLS and two private MariaDB instances."""

from __future__ import annotations

import shutil
import ssl
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "knowledge-kap2-person-vertical"))
from test_integrated import Binding, install_home, person_requirement  # noqa: E402
from test_gateway import PrivateDB  # noqa: E402
from certs import generate  # noqa: E402
from transport import RemoteWitness, RequestLedger, WitnessClient, WitnessTransportError  # noqa: E402
from witness_runner import Evidence, Handler, Server, WitnessFixture  # noqa: E402
from episteck_home.knowledge_authority.integrated import PersonAuthority  # noqa: E402


def test_recovery_handshake_and_role_isolation_over_mtls(tmp_path):
    cert_dir = tmp_path / "certs"
    generate(cert_dir, "127.0.0.1", local=True)
    evidence = Evidence(tmp_path / "witness.jsonl")
    root = Path("/tmp") / f"kap2-pr71-twohost-transport-{uuid4().hex}"
    fixture = WitnessFixture(root, evidence)
    home_root = tmp_path / "home"
    home_root.mkdir()
    home = PrivateDB(home_root)
    server = Server(("127.0.0.1", 0), Handler)
    server.fixture, server.evidence = fixture, evidence
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert_dir / "server.crt"), str(cert_dir / "server.key"))
    context.load_verify_locations(cafile=str(cert_dir / "ca.crt"))
    context.verify_mode = ssl.CERT_REQUIRED
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    ledger = RequestLedger()
    clients = {
        role: WitnessClient(host="127.0.0.1", port=server.server_port,
                            ca=cert_dir / "ca.crt", cert=cert_dir / f"{role}.crt",
                            key=cert_dir / f"{role}.key", role=role, ledger=ledger)
        for role in ("serving", "recovery")
    }
    remote = RemoteWitness(clients["serving"], clients["recovery"])
    authority = None
    try:
        install_home(home)
        for operation, args in (
            ("close_admission", ()),
            ("confirm_home", ("p1", "old-incarnation", ["old-incarnation", 0, "DENY_ALL"])),
            ("open_admission", ("p1", "old-incarnation")),
        ):
            with pytest.raises(WitnessTransportError):
                clients["serving"].call(operation, *args)
        assert clients["recovery"].call("status")["closed"] is True
        incarnation = remote.recover("p1")
        assert clients["recovery"].call("status")["closed"] is True
        with pytest.raises(WitnessTransportError):
            remote.prepare("p1", incarnation, "too-early", 0, "ALLOW_A")
        authority = PersonAuthority(
            home_socket=str(home.socket), witness=remote, binding=Binding(),
            reader_password="synthetic-reader", mutator_password="synthetic-mutator")
        fresh = authority.recover(recovery_password="synthetic-home-recover")
        assert fresh != incarnation
        assert clients["recovery"].call("status")["closed"] is False
        assert not authority.authorize(person_requirement("owner")).allow
        authority.activate_self("KNOWLEDGE", "VIEW", "fresh-self")
        assert authority.authorize(person_requirement("owner")).allow
        remote.close_admission()
        # Local OPEN cannot bypass the independent remote gate.
        assert authority.open
        assert not authority.authorize(person_requirement("owner")).allow
        authority.recover(recovery_password="synthetic-home-recover")
        assert not authority.authorize(person_requirement("owner")).allow
        authority._head = lambda *_: ("mismatch", 0, "DENY_ALL")
        with pytest.raises(RuntimeError, match="readback failed"):
            authority.recover(recovery_password="synthetic-home-recover")
        assert clients["recovery"].call("status")["closed"] is True
        assert not authority.open
        assert ledger.count() < 400
    finally:
        if authority is not None:
            authority.close()
        for client in clients.values():
            client.close()
        server.shutdown()
        thread.join(5)
        server.server_close()
        fixture.close()
        evidence.close()
        home.stop()
        assert home_root.resolve().parent == tmp_path.resolve()
        shutil.rmtree(home_root)
        # Only this test's marked certificate subtree is removed.
        assert cert_dir.resolve().parent == tmp_path.resolve()
        assert (cert_dir / "KAP2_PR71_CERTS").is_file()
        shutil.rmtree(cert_dir)
    assert not thread.is_alive()
    assert not root.exists() and not cert_dir.exists()


class _StubFixture:
    """Transport-only stand-in for WitnessFixture: no database, scripted delays."""

    def __init__(self, delays: dict[str, float] | None = None) -> None:
        self.delays = delays or {}

    def dispatch(self, role, operation, args):
        time.sleep(self.delays.get(operation, 0))
        return {"closed": True}


class _SignallingEvidence(Evidence):
    """The real evidence log, also signalling each witness request the Handler finished."""

    def __init__(self, path) -> None:
        super().__init__(path)
        self.operations: set[str] = set()
        self._changed = threading.Condition()

    def write(self, **event) -> None:
        super().write(**event)
        if event.get("step") == "witness_request":
            with self._changed:
                self.operations.add(event["operation"])
                self._changed.notify_all()

    def wait_for(self, operation: str, timeout: float) -> bool:
        with self._changed:
            return self._changed.wait_for(lambda: operation in self.operations, timeout)


@contextmanager
def _stub_witness(tmp_path, fixture, evidence=None):
    """Real witness Handler over loopback mTLS in front of a stub fixture."""
    cert_dir = tmp_path / "certs"
    generate(cert_dir, "127.0.0.1", local=True)
    evidence = evidence or Evidence(tmp_path / "witness.jsonl")
    server = Server(("127.0.0.1", 0), Handler)
    server.fixture, server.evidence = fixture, evidence
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert_dir / "server.crt"), str(cert_dir / "server.key"))
    context.load_verify_locations(cafile=str(cert_dir / "ca.crt"))
    context.verify_mode = ssl.CERT_REQUIRED
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    ledger = RequestLedger()
    clients = {
        role: WitnessClient(host="127.0.0.1", port=server.server_port,
                            ca=cert_dir / "ca.crt", cert=cert_dir / f"{role}.crt",
                            key=cert_dir / f"{role}.key", role=role, ledger=ledger)
        for role in ("serving", "recovery")
    }
    try:
        yield clients
    finally:
        for client in clients.values():
            client.close()
        server.shutdown()
        thread.join(5)
        server.server_close()
        evidence.close()
        shutil.rmtree(cert_dir)


def test_warm_rpc_has_no_small_write_stall(tmp_path):
    """Each witness reply is a header write followed by a body write. Without
    TCP_NODELAY, Nagle holds the body until the client's delayed ACK (about 40 ms on
    Linux; a further round trip across hosts), inflating every call that A10 measures."""
    with _stub_witness(tmp_path, _StubFixture()) as clients:
        client = clients["recovery"]
        assert client.call("status") == {"closed": True}  # TLS handshake
        durations = []
        for _ in range(15):
            started = time.perf_counter()
            client.call("status")
            durations.append((time.perf_counter() - started) * 1000)
        assert statistics.median(durations) < 20, durations


def test_disposable_restarts_outlast_the_serving_timeout(tmp_path):
    """A9 snapshot/restore restart the witness MariaDB (about 2-2.5 s for 11.8 in the
    local replica). Only those disposable restarts get a longer bound; every serving
    call keeps the 2 s fail-closed timeout."""
    slow = {"snapshot": 2.6, "restore": 2.6, "authorize": 2.6}
    evidence = _SignallingEvidence(tmp_path / "witness.jsonl")
    with _stub_witness(tmp_path, _StubFixture(slow), evidence) as clients:
        assert clients["recovery"].call("snapshot") == {"closed": True}
        assert clients["recovery"].call("restore") == {"closed": True}
        assert clients["recovery"].call("status") == {"closed": True}
        with pytest.raises(WitnessTransportError, match="uncertain witness authorize"):
            clients["serving"].call("authorize", "p1", "incarnation", 0, "ALLOW_A")
        # The abandoned handler still logs its request; wait for it before teardown.
        assert evidence.wait_for("authorize", timeout=10)
