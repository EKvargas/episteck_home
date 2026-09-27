"""Disposable R13 composition probe: signed Home basis + authenticated mTLS peer.

All keys and certificates are local fixtures. This is not a runtime implementation.
"""
from __future__ import annotations

import hashlib
import datetime
import json
import socket
import sqlite3
import ssl
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from home_stub.stub import AuthorizationOperation, Grant, HomeStub
from r13.transport_identity import EphemeralServiceCA, _LOOPBACK, _SERVER_CN


RUNTIME = "spiffe://episteck.internal/service/olin-runtime"
ATTACKER = "spiffe://episteck.internal/service/svc-attacker"
AUDIENCE = "spiffe://episteck.internal/service/svc-nutrition"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class LocalServiceCA(EphemeralServiceCA):
    """Reuse the old ephemeral CA while exercising a URI SAN identity profile."""

    def _leaf(self, common_name: str, key: ec.EllipticCurvePrivateKey) -> x509.Certificate:
        now = self._now()
        builder = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
            .issuer_name(self._ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(minutes=10))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        )
        if common_name == _SERVER_CN:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName(_SERVER_CN)]), critical=False
            ).add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
        else:
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.UniformResourceIdentifier(common_name)]),
                critical=False,
            ).add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
            )
        return builder.sign(self._ca_key, hashes.SHA256())


def cert_identity_and_key(der: bytes) -> tuple[str, str]:
    cert = x509.load_der_x509_certificate(der)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    identities = san.get_values_for_type(x509.UniformResourceIdentifier)
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    if len(identities) != 1 or ExtendedKeyUsageOID.CLIENT_AUTH not in eku:
        raise ValueError("missing unique client service identity")
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return identities[0], hashlib.sha256(spki).hexdigest()


def cert_key_hash(pem: bytes) -> str:
    cert = x509.load_pem_x509_certificate(pem)
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(spki).hexdigest()


@dataclass
class SignedBasis:
    claims: dict
    kid: str
    signature: str

    def wire(self) -> dict:
        return {"claims": self.claims, "kid": self.kid, "signature": self.signature}


class HomeSigner:
    def __init__(self, home: HomeStub, runtime_key_hash: str):
        self.home = home
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        self.kid = "local-home-1"
        self.runtime_key_hash = runtime_key_hash  # trusted provisioning, never request input

    def mint_plan(self, requests: tuple[dict, ...], *, now: int) -> tuple[SignedBasis, ...]:
        operations = tuple(AuthorizationOperation(
            operation_id=request["operation_id"], actor_person_id="P1",
            subject_person_ids=(request["subject_person_id"],), domains=("NUTRITION",),
            action="VIEW", partition_id="PART-1", include_knowledge_scope=False,
        ) for request in requests)
        decision = self.home.evaluate_plan(
            operations, version_pool={op.operation_id: frozenset() for op in operations}
        )
        assert decision.all_allowed()  # test fixture; production never mints for a denial
        return tuple(self._sign(request, op, now) for request, op in zip(requests, operations))

    def mint_after_plan(self, request: dict, *, now: int) -> SignedBasis:
        return self.mint_plan((request,), now=now)[0]

    def _sign(self, request: dict, op: AuthorizationOperation, now: int) -> SignedBasis:
        claims = {
            "version": 1, "execution_id": f"exec-{request['operation_id']}",
            "request_id": request["request_id"], "plan_id": request["plan_id"],
            "operation_id": op.operation_id,
            "actor_person_id": op.actor_person_id, "partition_id": op.partition_id,
            "subject_person_id": request["subject_person_id"],
            "resource_id": request["resource_id"], "domain": "NUTRITION", "action": "VIEW",
            "use_class": "ORDINARY_READ",
            "audience": AUDIENCE, "caller_service": RUNTIME,
            "caller_spki_sha256": self.runtime_key_hash,
            "method": "POST", "target": "/r13/read",
            "request_sha256": hashlib.sha256(canonical(request)).hexdigest(),
            "issued_at": now, "expires_at": now + 60, "authorization_revision": "rev-1",
            "decision_id": "correlation-only",
        }
        return SignedBasis(claims, self.kid, self.private_key.sign(canonical(claims)).hex())


class Domain:
    def __init__(self, home_public_key: ed25519.Ed25519PublicKey, replay_path: Path):
        self.home_keys = {"local-home-1": home_public_key}
        self.conn = sqlite3.connect(replay_path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS spent (execution_id TEXT PRIMARY KEY)")
        self.lock = threading.Lock()
        self.domain_call_count = 0
        self.repository_read_count = 0
        self.revoked_key_hashes: set[str] = set()

    def execute(self, wire: dict, peer_der: bytes, *, now: int) -> tuple[bool, str]:
        self.domain_call_count += 1
        try:
            basis = wire["basis"]
            claims = basis["claims"]
            key = self.home_keys[basis["kid"]]
            key.verify(bytes.fromhex(basis["signature"]), canonical(claims))
            peer_identity, peer_key_hash = cert_identity_and_key(peer_der)
            request = wire["request"]
            required = {
                "request_id": request["request_id"],
                "plan_id": request["plan_id"],
                "operation_id": request["operation_id"],
                "subject_person_id": request["subject_person_id"],
                "resource_id": request["resource_id"],
            }
            if set(request) != set(required) or request != required:
                return False, "malformed operation"
            if peer_key_hash in self.revoked_key_hashes:
                return False, "revoked service key"
            if claims["caller_service"] != peer_identity or claims["caller_spki_sha256"] != peer_key_hash:
                return False, "authenticated service/key mismatch"
            if claims["audience"] != AUDIENCE:
                return False, "wrong audience"
            if not (claims["issued_at"] - 5 <= now < claims["expires_at"]):
                return False, "outside bounded lifetime"
            if claims["expires_at"] - claims["issued_at"] > 60:
                return False, "invalid lifetime"
            if (claims["partition_id"], claims["actor_person_id"], claims["domain"], claims["action"], claims["use_class"]) != (
                "PART-1", "P1", "NUTRITION", "VIEW", "ORDINARY_READ"
            ):
                return False, "operation scope mismatch"
            if (claims["request_id"], claims["plan_id"], claims["operation_id"], claims["subject_person_id"], claims["resource_id"]) != (
                request["request_id"], request["plan_id"], request["operation_id"],
                request["subject_person_id"], request["resource_id"]
            ):
                return False, "operation binding mismatch"
            if (claims["method"], claims["target"], claims["request_sha256"]) != (
                "POST", "/r13/read", hashlib.sha256(canonical(request)).hexdigest()
            ):
                return False, "request binding mismatch"
            with self.lock:
                try:
                    self.conn.execute("INSERT INTO spent VALUES (?)", (claims["execution_id"],))
                    self.conn.commit()
                except sqlite3.IntegrityError:
                    return False, "replay"
            self.repository_read_count += 1
            return True, "repository read"
        except (KeyError, TypeError, ValueError, InvalidSignature, sqlite3.Error):
            return False, "invalid basis or verifier state"


def exchange(ca: LocalServiceCA, client, domain: Domain, wire: dict, tmp_path: Path, label: str) -> tuple[dict, str | None]:
    """One actual loopback TLS exchange; identity comes only from the verified peer."""
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(ca.server_materials())
    server_ctx.load_verify_locations(ca.ca_pem_path)
    server_ctx.verify_mode = ssl.CERT_REQUIRED
    listener = socket.socket()
    listener.bind((_LOOPBACK, 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    observed: dict = {}

    def serve() -> None:
        conn, _ = listener.accept()
        try:
            with server_ctx.wrap_socket(conn, server_side=True) as tls:
                peer = tls.getpeercert(binary_form=True)
                observed["peer_identity"] = cert_identity_and_key(peer)[0]
                raw = tls.recv(65536)
                ok, reason = domain.execute(json.loads(raw), peer, now=int(time.time()))
                tls.sendall(canonical({"executed": ok, "reason": reason}))
        except ssl.SSLError:
            observed["tls_rejected"] = True
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if client is not None:
        client_pem = tmp_path / f"{label}.pem"
        client_pem.write_bytes(client.cert_pem + client.key_pem)
        client_ctx.load_cert_chain(client_pem)
    client_ctx.load_verify_locations(ca.ca_pem_path)
    client_ctx.check_hostname = True
    try:
        with socket.create_connection((_LOOPBACK, port), timeout=5) as sock:
            with client_ctx.wrap_socket(sock, server_hostname=_SERVER_CN) as tls:
                tls.sendall(canonical(wire))
                payload = tls.recv(65536)
                response = json.loads(payload) if payload else {"executed": False, "reason": "TLS rejected"}
    except (ssl.SSLError, ConnectionError, ValueError):
        response = {"executed": False, "reason": "TLS rejected"}
    thread.join(timeout=5)
    assert not thread.is_alive()
    return response, observed.get("peer_identity")


@pytest.fixture
def rig(tmp_path):
    ca = LocalServiceCA(tmp_path)
    runtime = ca.issue(RUNTIME)
    attacker = ca.issue(ATTACKER)
    home = HomeStub(grants=(Grant("P1", "P1", "NUTRITION", "VIEW", "PART-1"),), inject_latency=False)
    signer = HomeSigner(home, cert_key_hash(runtime.cert_pem))
    domain = Domain(signer.private_key.public_key(), tmp_path / "spent.sqlite")
    request = {
        "request_id": "req-1", "plan_id": "plan-1", "operation_id": "op-n-1",
        "subject_person_id": "P1", "resource_id": "meal-1",
    }
    return ca, runtime, attacker, home, signer, domain, request


def test_exact_operation_and_two_real_home_evaluations(rig, tmp_path, capsys):
    ca, runtime, _, home, signer, domain, request = rig
    basis = signer.mint_after_plan(request, now=int(time.time()))
    response, identity = exchange(ca, runtime, domain, {"basis": basis.wire(), "request": request}, tmp_path, "ok")
    assert identity == RUNTIME and response["executed"]
    assert home.home_auth_round_trip_count == 1, "domain verification must not contact Home"
    # This is a fresh HomeStub evaluation of the same operation, not a TTL check.
    op = AuthorizationOperation("op-n-1", "P1", ("P1",), ("NUTRITION",), "VIEW", "PART-1", False)
    assert home.evaluate_plan((op,), version_pool={"op-n-1": frozenset()}).all_allowed()
    counters = {
        "home_auth_round_trip_count": home.home_auth_round_trip_count,
        "authorization_operation_count": home.authorization_operation_count,
        "domain_call_count": domain.domain_call_count,
        "repository_read_count": domain.repository_read_count,
    }
    assert counters == {
        "home_auth_round_trip_count": 2, "authorization_operation_count": 1,
        "domain_call_count": 1, "repository_read_count": 1,
    }
    print(json.dumps(counters, sort_keys=True))


@pytest.mark.parametrize("attack", [
    "basis_alone", "wrong_service", "wrong_key", "wrong_audience", "replay",
    "mutated_operation", "expired_basis", "forged_home_basis", "revoked_service_key",
])
def test_adversarial_matrix(rig, tmp_path, attack):
    ca, runtime, attacker, _, signer, domain, request = rig
    basis = signer.mint_after_plan(request, now=int(time.time()))
    wire = {"basis": basis.wire(), "request": dict(request)}
    client = runtime
    if attack == "basis_alone":
        client = None
    elif attack == "wrong_service":
        client = attacker
        wire["service_identity"] = RUNTIME  # copied claim is ignored by the domain
    elif attack == "wrong_key":
        # A separate trusted cert for the same service name has the wrong bound key.
        client = ca.issue(RUNTIME)
    elif attack == "wrong_audience":
        wire["basis"]["claims"]["audience"] = ATTACKER
        wire["basis"]["signature"] = signer.private_key.sign(canonical(wire["basis"]["claims"])).hex()
    elif attack == "replay":
        first, _ = exchange(ca, runtime, domain, wire, tmp_path, "first")
        assert first["executed"]
    elif attack == "mutated_operation":
        wire["request"]["resource_id"] = "meal-2"
    elif attack == "expired_basis":
        wire["basis"]["claims"]["issued_at"] -= 120
        wire["basis"]["claims"]["expires_at"] -= 120
        wire["basis"]["signature"] = signer.private_key.sign(canonical(wire["basis"]["claims"])).hex()
    elif attack == "forged_home_basis":
        wire["basis"]["claims"]["resource_id"] = "meal-2"
    elif attack == "revoked_service_key":
        domain.revoked_key_hashes.add(cert_key_hash(runtime.cert_pem))
    response, identity = exchange(ca, client, domain, wire, tmp_path, attack)
    assert not response["executed"], (attack, response)
    if attack == "wrong_service":
        assert identity == ATTACKER and response["reason"] == "authenticated service/key mismatch"
    if attack == "wrong_key":
        assert identity == RUNTIME and response["reason"] == "authenticated service/key mismatch"
    if attack == "basis_alone":
        assert identity is None and domain.domain_call_count == 0
    assert domain.repository_read_count == (1 if attack == "replay" else 0)


def test_three_domain_operations_still_two_home_crossings(rig, tmp_path, capsys):
    ca, runtime, _, home, signer, domain, request = rig
    requests = tuple({**request, "operation_id": f"op-n-{i}"} for i in range(3))
    bases = signer.mint_plan(requests, now=int(time.time()))
    for i, (operation, basis) in enumerate(zip(requests, bases)):
        response, identity = exchange(
            ca, runtime, domain, {"basis": basis.wire(), "request": operation}, tmp_path, f"fanout-{i}"
        )
        assert response["executed"] and identity == RUNTIME
    assert home.home_auth_round_trip_count == 1, "fanout must not add a Home crossing"
    operations = tuple(AuthorizationOperation(
        request["operation_id"], "P1", ("P1",), ("NUTRITION",), "VIEW", "PART-1", False
    ) for request in requests)
    assert home.evaluate_plan(
        operations, version_pool={op.operation_id: frozenset() for op in operations}
    ).all_allowed()
    counters = {
        "home_auth_round_trip_count": home.home_auth_round_trip_count,
        "authorization_operation_count": home.authorization_operation_count,
        "domain_call_count": domain.domain_call_count,
    }
    assert counters == {
        "home_auth_round_trip_count": 2,
        "authorization_operation_count": 3,
        "domain_call_count": 3,
    }
    print(json.dumps(counters, sort_keys=True))


def test_replay_claim_survives_domain_restart(rig, tmp_path):
    ca, runtime, _, home, signer, domain, request = rig
    basis = signer.mint_after_plan(request, now=int(time.time()))
    wire = {"basis": basis.wire(), "request": request}
    first, _ = exchange(ca, runtime, domain, wire, tmp_path, "before-restart")
    assert first["executed"]
    domain.conn.close()
    restarted = Domain(signer.private_key.public_key(), tmp_path / "spent.sqlite")
    second, _ = exchange(ca, runtime, restarted, wire, tmp_path, "after-restart")
    assert not second["executed"] and second["reason"] == "replay"
    assert home.home_auth_round_trip_count == 1
