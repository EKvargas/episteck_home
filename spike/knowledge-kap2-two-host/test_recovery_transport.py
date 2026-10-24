"""Recovery proof over real loopback mTLS and two private MariaDB instances."""

from __future__ import annotations

import shutil
import ssl
import sys
import threading
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
