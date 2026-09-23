"""R13 / Phase-1 §16.7 condition 5 — minimum transport-backed closure test.

Neither existing R13 experiment, alone, exercises the exact end-to-end P12 case 2b arm
(`test_case2b_correct_key_wrong_authenticated_identity_fails_closed` in
`test_p12_r13_adversarial.py`) over a genuinely authenticated channel:

  * The primary in-process P12 suite proves the verification LOGIC rejects a mismatch
    between a claimed identity and the basis-bound (identity, key) pair -- but
    `claimed_service_identity` there is a caller-supplied Python string, not an
    authenticated identity, so it cannot show a real caller could not simply assert an
    identity it does not hold (classify_r13()'s R13-B stays UNKNOWN for exactly this
    reason; unchanged by this file).
  * The secondary mTLS harness (correction 7, `r13/transport_identity.py`) proves identity
    IS transport-derived (from a verified peer certificate) and composes with the Ed25519
    holder-of-key verifier -- but its composition test closes the TLS connection and only
    afterward calls `DomainVerifier.verify_and_execute` in process with the CN as a plain
    variable. It never runs the 2b arm (an attacker AUTHENTICATED as themselves, holding a
    GENUINE key and basis for someone else) over that live connection.

This file closes exactly that gap with ONE minimal test, reusing both existing mechanisms
unmodified: `EphemeralServiceCA` / `TransportIdentityServer` primitives from
`r13/transport_identity.py`, and `DomainVerifier` / `HomeBasisMinter` / `TrustedKeyRegistry`
/ `sign_proof` from `r13/holder_of_key.py`. The only new code here is the wire exchange
(server reads a basis+proof payload sent over the ALREADY-AUTHENTICATED TLS socket, calls
the unmodified verifier with the transport-derived identity, writes the result back) --
test-only plumbing, not a new production or spike mechanism.

Scope, restated (Phase-1 SS11.4, Family 1 mTLS variant -- explicitly NOT the primary
realization): SECONDARY LOCAL EXPERIMENT ONLY. Single-host 127.0.0.1 loopback, throwaway
ephemeral CA, no production identity fabric, no technology selection, no production code
touched. On PASS this closes §16.7 condition 5 at the spike's experimental scope; it does
not upgrade the primary in-process R13-B verdict (`classify_r13()`), which stays UNKNOWN by
construction, and it is not evidence about a production identity fabric.
"""
from __future__ import annotations

import json
import socket
import ssl
import tempfile
import time
from pathlib import Path

import pytest

from r13.holder_of_key import (
    DomainVerifier,
    HomeBasisMinter,
    ServiceKeypair,
    TrustedKeyRegistry,
    sign_proof,
)
from r13.transport_identity import (
    _LOOPBACK,
    _SERVER_CN,
    _peer_common_name,
    EphemeralServiceCA,
)


@pytest.fixture
def workdir():
    import shutil

    td = Path(tempfile.mkdtemp(prefix="r13-case2b-closure-"))
    try:
        yield td
    finally:
        shutil.rmtree(td, ignore_errors=True)


def _basis_to_wire(basis) -> dict:
    return {
        "basis_id": basis.basis_id,
        "partition_id": basis.partition_id,
        "actor_person_id": basis.actor_person_id,
        "operation_id": basis.operation_id,
        "domain": basis.domain,
        "action": basis.action,
        "resource_id": basis.resource_id,
        "audience": basis.audience,
        "authenticated_service_identity": basis.authenticated_service_identity,
        "accepted_public_key_hex": basis.accepted_public_key_hex,
        "issued_at": basis.issued_at,
        "expires_at": basis.expires_at,
        "decision_id": basis.decision_id,
    }


def _basis_from_wire(payload: dict):
    from r13.holder_of_key import ExecutionBasis

    return ExecutionBasis(
        basis_id=payload["basis_id"], partition_id=payload["partition_id"],
        actor_person_id=payload["actor_person_id"], operation_id=payload["operation_id"],
        domain=payload["domain"], action=payload["action"], resource_id=payload["resource_id"],
        audience=payload["audience"],
        authenticated_service_identity=payload["authenticated_service_identity"],
        accepted_public_key_hex=payload["accepted_public_key_hex"],
        issued_at=payload["issued_at"], expires_at=payload["expires_at"],
        decision_id=payload["decision_id"],
    )


def _proof_to_wire(proof) -> dict:
    return {
        "basis_id": proof.basis_id, "method": proof.method, "target": proof.target,
        "nonce": proof.nonce, "basis_hash": proof.basis_hash,
        "signature_hex": proof.signature_hex,
    }


def _proof_from_wire(payload: dict):
    from r13.holder_of_key import PossessionProof

    return PossessionProof(
        basis_id=payload["basis_id"], method=payload["method"], target=payload["target"],
        nonce=payload["nonce"], basis_hash=payload["basis_hash"],
        signature_hex=payload["signature_hex"],
    )


class _ExchangeServer:
    """A local mTLS server that, AFTER completing the mutual handshake, reads one
    basis+proof exchange request over the authenticated socket, calls the UNMODIFIED
    `DomainVerifier.verify_and_execute` with the identity read from `getpeercert()` (never
    from the request payload), and writes the result back over the same connection.

    This is deliberately test-only wiring: it does not add any new verification logic, it
    only carries the existing `DomainVerifier` call onto the live TLS stream so the basis
    and proof genuinely travel over the authenticated channel rather than being
    reconstructed in-process after the socket closes.
    """

    def __init__(self, ca: EphemeralServiceCA) -> None:
        self._ca = ca
        server_pem = ca.server_materials()
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(server_pem)
        self._ctx.load_verify_locations(ca.ca_pem_path)
        self._ctx.verify_mode = ssl.CERT_REQUIRED
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._lsock.bind((_LOOPBACK, 0))
        self._lsock.listen(1)
        self.port = self._lsock.getsockname()[1]
        self.transport_identity: str | None = None
        self.handshake_ok = False
        self.exec_result = None  # ExecutionResult, set only if we got far enough to verify
        self.server_payload_service_identity: str | None = None  # what the payload claimed

    def _serve_one(self, *, verify_kwargs: dict) -> None:
        conn, _ = self._lsock.accept()
        try:
            tls = self._ctx.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError):
            self.handshake_ok = False
            return
        self.handshake_ok = True
        self.transport_identity = _peer_common_name(tls.getpeercert())
        try:
            raw = tls.recv(65536)
            payload = json.loads(raw.decode("utf-8"))
            self.server_payload_service_identity = payload.get("service_identity")

            basis = _basis_from_wire(payload["basis"])
            proof = _proof_from_wire(payload["proof"])
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            presenting_public_key = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(payload["presenting_public_key_hex"])
            )

            verifier = DomainVerifier()
            # CRITICAL: identity passed to the verifier is the TRANSPORT-derived one from
            # the verified peer certificate -- never anything read from the payload above,
            # even though the payload may (and in the attack arm, does) also claim one.
            result = verifier.verify_and_execute(
                basis=basis, proof=proof,
                claimed_service_identity=self.transport_identity,
                presenting_public_key=presenting_public_key,
                **verify_kwargs,
            )
            self.exec_result = result
            tls.sendall(json.dumps({"executed": result.executed, "reason": result.reason}).encode("utf-8"))
        finally:
            tls.close()

    def serve_one_blocking(self, *, verify_kwargs: dict) -> None:
        self._serve_one(verify_kwargs=verify_kwargs)

    def close(self) -> None:
        try:
            self._lsock.close()
        except OSError:
            pass


def _connect_and_exchange(
    *, ca: EphemeralServiceCA, client_issued, port: int, workdir: Path, label: str,
    basis, proof, presenting_public_key_hex: str, claimed_identity_in_payload: str,
) -> dict:
    """Client side: complete the mTLS handshake presenting `client_issued`'s cert, THEN
    send the basis+proof (plus an attacker-controlled `service_identity` payload field)
    over that same authenticated socket, and return the server's JSON response."""
    client_pem = workdir / f"client-{label}.pem"
    client_pem.write_bytes(client_issued.cert_pem + client_issued.key_pem)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(client_pem)
    ctx.load_verify_locations(ca.ca_pem_path)
    ctx.check_hostname = True

    raw = socket.create_connection((_LOOPBACK, port), timeout=5)
    tls = ctx.wrap_socket(raw, server_hostname=_SERVER_CN)
    try:
        wire = {
            "basis": _basis_to_wire(basis),
            "proof": _proof_to_wire(proof),
            "presenting_public_key_hex": presenting_public_key_hex,
            # An attacker-controlled field the server MUST ignore -- the request-supplied
            # identity claim the task requires the server to disregard in favor of the
            # transport-derived one.
            "service_identity": claimed_identity_in_payload,
        }
        tls.sendall(json.dumps(wire).encode("utf-8"))
        response = json.loads(tls.recv(65536).decode("utf-8"))
        return response
    finally:
        tls.close()


def _run_exchange(*, ca, client_issued, workdir, label, basis, proof, presenting_keypair, claimed_identity_in_payload):
    """Start a one-shot exchange server, run the client against it in a thread, return the
    server object (with `.transport_identity`, `.handshake_ok`, `.exec_result` populated)
    and the client-observed response dict."""
    import threading

    server = _ExchangeServer(ca)
    verify_kwargs = dict(
        expected_audience="svc-nutrition", expected_domain="NUTRITION", expected_action="VIEW",
        expected_operation_id=basis.operation_id, expected_actor_person_id="P1",
        now=int(time.time()),
    )
    try:
        t = threading.Thread(target=server.serve_one_blocking, kwargs={"verify_kwargs": verify_kwargs}, daemon=True)
        t.start()
        response = _connect_and_exchange(
            ca=ca, client_issued=client_issued, port=server.port, workdir=workdir, label=label,
            basis=basis, proof=proof,
            presenting_public_key_hex=presenting_keypair.public_bytes_hex(),
            claimed_identity_in_payload=claimed_identity_in_payload,
        )
        t.join(timeout=5)
        return server, response
    finally:
        server.close()


@pytest.fixture
def rig(workdir):
    ca = EphemeralServiceCA(workdir)
    nutrition_cert = ca.issue("svc-nutrition")
    attacker_cert = ca.issue("svc-attacker")

    registry = TrustedKeyRegistry()
    svc_nutrition_key = ServiceKeypair.generate("svc-nutrition")
    svc_attacker_key = ServiceKeypair.generate("svc-attacker")
    registry.register("svc-nutrition", svc_nutrition_key.public_bytes_hex())
    registry.register("svc-attacker", svc_attacker_key.public_bytes_hex())
    minter = HomeBasisMinter(registry)

    return {
        "workdir": workdir, "ca": ca,
        "nutrition_cert": nutrition_cert, "attacker_cert": attacker_cert,
        "svc_nutrition_key": svc_nutrition_key, "svc_attacker_key": svc_attacker_key,
        "minter": minter,
    }


def _mint(rig, *, op: str):
    now = int(time.time())
    return rig["minter"].mint(
        basis_id=f"basis-{op}-{now}", partition_id="PART-1", actor_person_id="P1",
        operation_id=op, domain="NUTRITION", action="VIEW", resource_id="res-1",
        audience_service_identity="svc-nutrition", decision_id="dec-1", now=now,
    )


def test_case2b_transport_authenticated_wrong_service_with_genuine_key_fails_closed(rig):
    """§16.7 condition 5 minimum closure test.

    Attack arm: client is TLS-AUTHENTICATED as `svc-attacker` (trusted certificate, real
    mTLS handshake to the honest CA -- not forged, not rejected at transport) but sends,
    over that same connection, a basis bound to `svc-nutrition` plus a proof signed with
    the GENUINE `svc-nutrition` Ed25519 private key, and a payload field that additionally
    (falsely) claims `service_identity=svc-nutrition`. The server must derive the
    authenticated identity ONLY from the verified peer certificate (`svc-attacker`),
    ignore the payload claim, and the UNMODIFIED `DomainVerifier.verify_and_execute` must
    reject the execution specifically because the transport-authenticated identity does
    not match the basis-bound identity -- not because the TLS handshake or the Ed25519
    signature failed (both of those independently succeed here).
    """
    basis = _mint(rig, op="closure-2b-attack")
    proof = sign_proof(
        keypair=rig["svc_nutrition_key"], basis=basis, method="POST", target="/x",
        nonce="closure-2b-attack-nonce",
    )

    server, response = _run_exchange(
        ca=rig["ca"], client_issued=rig["attacker_cert"], workdir=rig["workdir"],
        label="attack", basis=basis, proof=proof,
        presenting_keypair=rig["svc_nutrition_key"],
        claimed_identity_in_payload="svc-nutrition",  # attacker-controlled, must be ignored
    )

    # A: TLS handshake succeeded (this is a TRUSTED cert, not a rogue/untrusted one).
    assert server.handshake_ok, "the attacker's certificate IS trusted by the CA -- the handshake must succeed"

    # B: transport-derived identity is the attacker's real authenticated identity.
    assert server.transport_identity == "svc-attacker"
    # Sanity: the server actually saw (and ignored) the attacker's false payload claim.
    assert server.server_payload_service_identity == "svc-nutrition"

    # C: the svc-nutrition proof itself is genuine, verified independently of the
    # DomainVerifier call above, so failure below cannot be attributed to a bad signature.
    rig["svc_nutrition_key"].public_key.verify(
        bytes.fromhex(proof.signature_hex), proof.signed_payload()
    )  # raises InvalidSignature if not genuine -- no exception means C holds

    # D: execution is rejected.
    assert server.exec_result is not None, "the exchange must have reached the verifier"
    assert server.exec_result.executed is False
    assert response["executed"] is False

    # E: rejection reason is specifically the identity mismatch, not TLS/signature failure.
    assert server.exec_result.reason == "claimed service identity != basis-bound identity (fail closed)"
    assert "signature" not in server.exec_result.reason
    assert "TLS" not in server.exec_result.reason and "handshake" not in server.exec_result.reason


def test_case2b_positive_control_transport_authenticated_correct_service_succeeds(rig):
    """Positive control, SAME wire path as the attack arm above: trusted `svc-nutrition`
    certificate, fresh `svc-nutrition` basis, genuine `svc-nutrition` proof -> execution
    succeeds. Proves the closure test's failure above is caused by the identity mismatch
    specifically, not by some unrelated defect in the exchange harness that would reject
    everything."""
    basis = _mint(rig, op="closure-2b-control")
    proof = sign_proof(
        keypair=rig["svc_nutrition_key"], basis=basis, method="POST", target="/x",
        nonce="closure-2b-control-nonce",
    )

    server, response = _run_exchange(
        ca=rig["ca"], client_issued=rig["nutrition_cert"], workdir=rig["workdir"],
        label="control", basis=basis, proof=proof,
        presenting_keypair=rig["svc_nutrition_key"],
        claimed_identity_in_payload="svc-nutrition",
    )

    assert server.handshake_ok
    assert server.transport_identity == "svc-nutrition"
    assert server.exec_result is not None
    assert server.exec_result.executed is True
    assert response["executed"] is True
