"""Disposable R13 composition probe: signed Home basis + authenticated mTLS peer.

All keys and certificates are local fixtures. This is not a runtime implementation.
"""
from __future__ import annotations

import hashlib
import datetime
import base64
import json
import re
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
SIGNATURE_PREFIX = b"episteck-r13-v1\x00"
TRUST_PREFIX = b"episteck-r13-trust-v1\x00"
TRUST_BUNDLE_MAX_AGE = 300
MAX_SAFE_INTEGER = 2**53 - 1
CLAIM_INT_FIELDS = {"version", "issued_at", "expires_at"}
CLAIM_ARRAY_FIELDS = {"subject_person_ids", "resource_ids"}
CLAIM_STRING_FIELDS = {
    "home_kid", "execution_id", "request_id", "plan_id", "operation_id",
    "actor_person_id", "partition_id", "domain", "action", "use_class",
    "audience", "caller_service", "caller_spki_sha256", "method", "target",
    "request_sha256", "authorization_revision", "window_id", "decision_id",
}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def jcs_v1_test_helper(claims: dict) -> bytes:
    """JCS for this fixture's restricted v1 ASCII/string/array/safe-int schema only.

    This is NOT a general RFC 8785 implementation or a production JCS library.
    """
    if set(claims) != CLAIM_INT_FIELDS | CLAIM_ARRAY_FIELDS | CLAIM_STRING_FIELDS:
        raise ValueError("unknown or missing v1 claim")
    if claims["version"] != 1:
        raise ValueError("unsupported version")
    for name in CLAIM_INT_FIELDS:
        value = claims[name]
        if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
            raise ValueError("unsafe v1 integer")
    def valid_string(value: object) -> bool:
        return type(value) is str and bool(value) and all(32 <= ord(c) <= 126 for c in value)
    if any(not valid_string(claims[name]) for name in CLAIM_STRING_FIELDS):
        raise ValueError("invalid v1 string")
    if any(
        type(claims[name]) is not list or not claims[name]
        or any(not valid_string(item) for item in claims[name])
        for name in CLAIM_ARRAY_FIELDS
    ):
        raise ValueError("invalid v1 array")
    # All keys and admitted string values are printable ASCII; numeric values are safe
    # integers. For this deliberately limited subset, Python's sorted compact JSON is JCS.
    return canonical(claims)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON member")
        result[name] = value
    return result


def decode_v1_claims(encoded: str) -> tuple[dict, bytes]:
    if type(encoded) is not str or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        raise ValueError("invalid claims encoding")
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if base64.urlsafe_b64encode(raw).decode().rstrip("=") != encoded:
        raise ValueError("noncanonical base64url")
    claims = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    if type(claims) is not dict or jcs_v1_test_helper(claims) != raw:
        raise ValueError("non-JCS v1 claims")
    return claims, raw


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
    signature: str

    def wire(self) -> dict:
        raw = jcs_v1_test_helper(self.claims)
        return {
            "claims_jcs_b64u": base64.urlsafe_b64encode(raw).decode().rstrip("="),
            "signature_hex": self.signature,
        }


class HomeSigner:
    def __init__(self, home: HomeStub, runtime_key_hash: str):
        self.home = home
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        self.kid = "local-home-1"
        self.accepted_spkis = {runtime_key_hash}  # fixture-provisioned, never request input
        self.issuance_active_spkis = {runtime_key_hash}

    def mint_plan(self, requests: tuple[dict, ...], *, now: int) -> tuple[SignedBasis, ...]:
        if len(self.issuance_active_spkis) != 1:
            raise ValueError("zero or ambiguous issuance-active SPKI")
        active_spki = next(iter(self.issuance_active_spkis))
        if active_spki not in self.accepted_spkis:
            raise ValueError("issuance-active SPKI is not registered")
        operations = tuple(AuthorizationOperation(
            operation_id=request["operation_id"], actor_person_id="P1",
            subject_person_ids=(request["subject_person_id"],), domains=("NUTRITION",),
            action="VIEW", partition_id="PART-1", include_knowledge_scope=False,
        ) for request in requests)
        decision = self.home.evaluate_plan(
            operations, version_pool={op.operation_id: frozenset() for op in operations}
        )
        assert decision.all_allowed()  # test fixture; production never mints for a denial
        return tuple(self._sign(request, op, now, active_spki) for request, op in zip(requests, operations))

    def mint_after_plan(self, request: dict, *, now: int) -> SignedBasis:
        return self.mint_plan((request,), now=now)[0]

    def _sign(self, request: dict, op: AuthorizationOperation, now: int, active_spki: str) -> SignedBasis:
        claims = {
            "version": 1, "home_kid": self.kid,
            "execution_id": f"exec-{request['operation_id']}",
            "request_id": request["request_id"], "plan_id": request["plan_id"],
            "operation_id": op.operation_id,
            "actor_person_id": op.actor_person_id, "partition_id": op.partition_id,
            "subject_person_ids": [request["subject_person_id"]],
            "resource_ids": [request["resource_id"]], "domain": "NUTRITION", "action": "VIEW",
            "use_class": "ORDINARY_READ",
            "audience": AUDIENCE, "caller_service": RUNTIME,
            "caller_spki_sha256": active_spki,
            "method": "POST", "target": "/r13/read",
            "request_sha256": hashlib.sha256(canonical(request)).hexdigest(),
            "issued_at": now, "expires_at": now + 60, "authorization_revision": "rev-1",
            "window_id": "window-1",
            "decision_id": "correlation-only",
        }
        return SignedBasis(claims, self.private_key.sign(SIGNATURE_PREFIX + jcs_v1_test_helper(claims)).hex())


class Domain:
    def __init__(
        self, home_public_key: ed25519.Ed25519PublicKey, replay_path: Path,
        distribution_public_key: ed25519.Ed25519PublicKey,
    ):
        self.home_keys = {"local-home-1": home_public_key}
        self.distribution_public_key = distribution_public_key
        self.conn = sqlite3.connect(replay_path, check_same_thread=False)
        self.conn.execute("CREATE TABLE IF NOT EXISTS spent (execution_id TEXT PRIMARY KEY)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS security_state (id INTEGER PRIMARY KEY, generation INTEGER NOT NULL)")
        saved = self.conn.execute("SELECT generation FROM security_state WHERE id = 1").fetchone()
        self.last_accepted_trust_generation = saved[0] if saved else 0
        self.trust_bundle: dict | None = None  # restart requires fresh verified trust
        self.trust_verified_at: int | None = None
        self.lock = threading.Lock()
        self.domain_call_count = 0
        self.repository_read_count = 0
        self.revoked_key_hashes: set[str] = set()

    def install_trust_bundle(self, bundle: dict, signature: bytes, *, now: int) -> None:
        """Accept one signed, newer snapshot; persist generation apart from bundle bytes."""
        self.distribution_public_key.verify(signature, TRUST_PREFIX + canonical(bundle))
        if set(bundle) != {"generation", "issued_at", "service_spkis", "active_home_kids"}:
            raise ValueError("malformed trust bundle")
        generation, issued_at = bundle["generation"], bundle["issued_at"]
        if (type(generation) is not int or generation <= 0 or
            type(issued_at) is not int or not issued_at - 5 <= now <= issued_at + TRUST_BUNDLE_MAX_AGE or
            type(bundle["service_spkis"]) is not dict or
            type(bundle["active_home_kids"]) is not list or
            any(type(kid) is not str for kid in bundle["active_home_kids"])):
            raise ValueError("stale or malformed trust bundle")
        with self.lock:
            if generation <= self.last_accepted_trust_generation:
                raise ValueError("trust generation rollback")
            self.conn.execute(
                "INSERT INTO security_state (id, generation) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET generation = excluded.generation", (generation,)
            )
            self.conn.commit()
            self.last_accepted_trust_generation = generation
            self.trust_bundle = bundle
            self.trust_verified_at = now

    def execute(self, wire: dict, peer_der: bytes, *, now: int) -> tuple[bool, str]:
        self.domain_call_count += 1
        try:
            if (self.trust_bundle is None or self.trust_verified_at is None or
                now < self.trust_verified_at or
                now - self.trust_verified_at > TRUST_BUNDLE_MAX_AGE or
                now - self.trust_bundle["issued_at"] > TRUST_BUNDLE_MAX_AGE):
                return False, "trust state stale"
            basis = wire["basis"]
            if set(basis) != {"claims_jcs_b64u", "signature_hex"}:
                return False, "malformed basis envelope"
            if type(basis["signature_hex"]) is not str or not re.fullmatch(r"[0-9a-f]{128}", basis["signature_hex"]):
                return False, "malformed signature encoding"
            claims, raw_claims = decode_v1_claims(basis["claims_jcs_b64u"])
            if claims["home_kid"] not in self.trust_bundle["active_home_kids"]:
                return False, "Home signing key revoked"
            key = self.home_keys[claims["home_kid"]]
            key.verify(bytes.fromhex(basis["signature_hex"]), SIGNATURE_PREFIX + raw_claims)
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
            if peer_key_hash not in self.trust_bundle["service_spkis"].get(peer_identity, []):
                return False, "service key not in current trust bundle"
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
            if (claims["request_id"], claims["plan_id"], claims["operation_id"], claims["subject_person_ids"], claims["resource_ids"]) != (
                request["request_id"], request["plan_id"], request["operation_id"],
                [request["subject_person_id"]], [request["resource_id"]]
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
                try:
                    payload = json.loads(raw, object_pairs_hook=unique_object)
                    ok, reason = domain.execute(payload, peer, now=int(time.time()))
                except ValueError:
                    ok, reason = False, "malformed JSON request"
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
    distribution = ed25519.Ed25519PrivateKey.generate()
    domain = Domain(signer.private_key.public_key(), tmp_path / "spent.sqlite", distribution.public_key())
    now = int(time.time())
    bundle = {"generation": 1, "issued_at": now, "active_home_kids": [signer.kid],
              "service_spkis": {RUNTIME: [cert_key_hash(runtime.cert_pem)]}}
    domain.install_trust_bundle(bundle, distribution.sign(TRUST_PREFIX + canonical(bundle)), now=now)
    request = {
        "request_id": "req-1", "plan_id": "plan-1", "operation_id": "op-n-1",
        "subject_person_id": "P1", "resource_id": "meal-1",
    }
    return ca, runtime, attacker, home, signer, domain, request, distribution


def test_exact_operation_and_two_real_home_evaluations(rig, tmp_path, capsys):
    ca, runtime, _, home, signer, domain, request, _ = rig
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
    ca, runtime, attacker, _, signer, domain, request, _ = rig
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
        changed = {**basis.claims, "audience": ATTACKER}
        wire["basis"] = SignedBasis(
            changed, signer.private_key.sign(SIGNATURE_PREFIX + jcs_v1_test_helper(changed)).hex()
        ).wire()
    elif attack == "replay":
        first, _ = exchange(ca, runtime, domain, wire, tmp_path, "first")
        assert first["executed"]
    elif attack == "mutated_operation":
        wire["request"]["resource_id"] = "meal-2"
    elif attack == "expired_basis":
        changed = {**basis.claims, "issued_at": basis.claims["issued_at"] - 120,
                   "expires_at": basis.claims["expires_at"] - 120}
        wire["basis"] = SignedBasis(
            changed, signer.private_key.sign(SIGNATURE_PREFIX + jcs_v1_test_helper(changed)).hex()
        ).wire()
    elif attack == "forged_home_basis":
        changed = {**basis.claims, "resource_ids": ["meal-2"]}
        wire["basis"]["claims_jcs_b64u"] = base64.urlsafe_b64encode(
            jcs_v1_test_helper(changed)
        ).decode().rstrip("=")
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
    ca, runtime, _, home, signer, domain, request, _ = rig
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
    ca, runtime, _, home, signer, domain, request, distribution = rig
    basis = signer.mint_after_plan(request, now=int(time.time()))
    wire = {"basis": basis.wire(), "request": request}
    first, _ = exchange(ca, runtime, domain, wire, tmp_path, "before-restart")
    assert first["executed"]
    domain.conn.close()
    restarted = Domain(signer.private_key.public_key(), tmp_path / "spent.sqlite", distribution.public_key())
    fresh_time = int(time.time())
    fresh_bundle = {"generation": 2, "issued_at": fresh_time, "active_home_kids": [signer.kid],
                    "service_spkis": {RUNTIME: [cert_key_hash(runtime.cert_pem)]}}
    restarted.install_trust_bundle(
        fresh_bundle, distribution.sign(TRUST_PREFIX + canonical(fresh_bundle)), now=fresh_time
    )
    second, _ = exchange(ca, runtime, restarted, wire, tmp_path, "after-restart")
    assert not second["executed"] and second["reason"] == "replay"
    assert home.home_auth_round_trip_count == 1


def test_v1_signature_uses_exact_prefixed_jcs_claim_bytes(rig, tmp_path):
    ca, runtime, _, _, signer, domain, request, _ = rig
    basis = signer.mint_after_plan(request, now=int(time.time()))
    wire_basis = basis.wire()
    raw = base64.urlsafe_b64decode(wire_basis["claims_jcs_b64u"] + "==")
    assert raw.startswith(b'{"action":"VIEW","actor_person_id":"P1",')
    assert b'"version":1,' in raw
    signer.private_key.public_key().verify(
        bytes.fromhex(wire_basis["signature_hex"]), b"episteck-r13-v1\x00" + raw
    )
    response, _ = exchange(ca, runtime, domain, {"basis": wire_basis, "request": request}, tmp_path, "jcs")
    assert response["executed"]


@pytest.mark.parametrize("bad_claims", [
    lambda raw: b" " + raw,  # valid JSON with non-JCS whitespace
    lambda raw: raw.replace(
        b'{"action":"VIEW","actor_person_id":"P1",',
        b'{"actor_person_id":"P1","action":"VIEW",', 1,
    ),
    lambda raw: raw.replace(b'"action":"VIEW",', b'"action":"VIEW","action":"VIEW",', 1),
    lambda raw: raw.replace(b'"version":1,', b'"version":2,', 1),
    lambda raw: canonical({**json.loads(raw), "unknown": 0}),
    lambda raw: re.sub(rb'"issued_at":[0-9]+', b'"issued_at":9007199254740992', raw, count=1),
    lambda raw: raw.replace(b'"version":1,', b'"version":true,', 1),
])
def test_noncanonical_or_invalid_v1_claims_fail_closed(rig, tmp_path, bad_claims):
    ca, runtime, _, _, signer, domain, request, _ = rig
    basis = signer.mint_after_plan(request, now=int(time.time()))
    wire_basis = basis.wire()
    raw = base64.urlsafe_b64decode(wire_basis["claims_jcs_b64u"] + "==")
    bad_raw = bad_claims(raw)
    assert bad_raw != raw
    wire_basis["claims_jcs_b64u"] = base64.urlsafe_b64encode(bad_raw).decode().rstrip("=")
    wire_basis["signature_hex"] = signer.private_key.sign(SIGNATURE_PREFIX + bad_raw).hex()
    response, _ = exchange(ca, runtime, domain, {"basis": wire_basis, "request": request}, tmp_path, "bad-jcs")
    assert not response["executed"] and domain.repository_read_count == 0


def test_trust_bundle_older_than_five_minutes_denies_execution(rig, tmp_path):
    ca, runtime, _, home, signer, _, request, _ = rig
    distribution = ed25519.Ed25519PrivateKey.generate()
    domain = Domain(signer.private_key.public_key(), tmp_path / "stale-spent.sqlite", distribution.public_key())
    old_time = int(time.time()) - 301
    bundle = {
        "generation": 1, "issued_at": old_time, "active_home_kids": [signer.kid],
        "service_spkis": {RUNTIME: [cert_key_hash(runtime.cert_pem)]},
    }
    domain.install_trust_bundle(bundle, distribution.sign(TRUST_PREFIX + canonical(bundle)), now=old_time)
    basis = signer.mint_after_plan(request, now=int(time.time()))
    response, _ = exchange(ca, runtime, domain, {"basis": basis.wire(), "request": request}, tmp_path, "stale")
    assert not response["executed"] and domain.repository_read_count == 0
    assert home.home_auth_round_trip_count == 1  # no hidden Home lookup on stale trust


def test_signed_trust_generation_rollback_denied_after_restart(rig, tmp_path):
    _, runtime, _, _, signer, _, _, _ = rig
    distribution = ed25519.Ed25519PrivateKey.generate()
    ledger = tmp_path / "generation.sqlite"
    domain = Domain(signer.private_key.public_key(), ledger, distribution.public_key())
    now = int(time.time())

    def install(generation: int, target: Domain) -> None:
        bundle = {
            "generation": generation, "issued_at": now, "active_home_kids": [signer.kid],
            "service_spkis": {RUNTIME: [cert_key_hash(runtime.cert_pem)]},
        }
        target.install_trust_bundle(bundle, distribution.sign(TRUST_PREFIX + canonical(bundle)), now=now)

    install(2, domain)
    with pytest.raises(ValueError, match="rollback"):
        install(1, domain)
    domain.conn.close()
    restarted = Domain(signer.private_key.public_key(), ledger, distribution.public_key())
    with pytest.raises(ValueError, match="rollback"):
        install(1, restarted)
    install(3, restarted)


def test_zero_or_ambiguous_issuance_active_spki_refuses_mint(rig):
    ca, _, _, home, signer, _, request, _ = rig
    old_spki = next(iter(signer.issuance_active_spkis))
    signer.issuance_active_spkis.clear()
    with pytest.raises(ValueError, match="issuance-active"):
        signer.mint_after_plan(request, now=int(time.time()))
    new_spki = cert_key_hash(ca.issue(RUNTIME).cert_pem)
    signer.accepted_spkis.add(new_spki)
    signer.issuance_active_spkis.update({old_spki, new_spki})
    with pytest.raises(ValueError, match="issuance-active"):
        signer.mint_after_plan(request, now=int(time.time()))
    assert home.home_auth_round_trip_count == 0


def test_old_and_new_spki_bases_do_not_cross_execute(rig, tmp_path):
    ca, old_client, _, _, signer, domain, request, distribution = rig
    now = int(time.time())
    old_basis = signer.mint_after_plan(request, now=now)
    old_spki = cert_key_hash(old_client.cert_pem)
    new_client = ca.issue(RUNTIME)
    new_spki = cert_key_hash(new_client.cert_pem)
    bundle = {"generation": 2, "issued_at": now, "active_home_kids": [signer.kid],
              "service_spkis": {RUNTIME: [old_spki, new_spki]}}
    domain.install_trust_bundle(bundle, distribution.sign(TRUST_PREFIX + canonical(bundle)), now=now)
    signer.accepted_spkis.add(new_spki)
    signer.issuance_active_spkis = {new_spki}
    new_request = {**request, "operation_id": "op-n-new"}
    new_basis = signer.mint_after_plan(new_request, now=now)
    assert old_basis.claims["caller_spki_sha256"] == old_spki
    assert new_basis.claims["caller_spki_sha256"] == new_spki

    wrong_new, _ = exchange(
        ca, new_client, domain, {"basis": old_basis.wire(), "request": request}, tmp_path, "old-basis-new-key"
    )
    wrong_old, _ = exchange(
        ca, old_client, domain, {"basis": new_basis.wire(), "request": new_request}, tmp_path, "new-basis-old-key"
    )
    assert not wrong_new["executed"] and wrong_new["reason"] == "authenticated service/key mismatch"
    assert not wrong_old["executed"] and wrong_old["reason"] == "authenticated service/key mismatch"
    correct_new, _ = exchange(
        ca, new_client, domain, {"basis": new_basis.wire(), "request": new_request}, tmp_path, "new-basis-new-key"
    )
    assert correct_new["executed"] and domain.repository_read_count == 1


def test_fresh_bundle_revoking_home_kid_rejects_new_forged_basis(rig, tmp_path):
    ca, runtime, _, _, signer, domain, request, distribution = rig
    now = int(time.time())
    revoked_bundle = {
        "generation": 2, "issued_at": now,
        "active_home_kids": [],
        "service_spkis": {RUNTIME: [cert_key_hash(runtime.cert_pem)]},
    }
    domain.install_trust_bundle(
        revoked_bundle, distribution.sign(TRUST_PREFIX + canonical(revoked_bundle)), now=now
    )
    basis = signer.mint_after_plan(request, now=now)
    response, _ = exchange(
        ca, runtime, domain, {"basis": basis.wire(), "request": request}, tmp_path, "revoked-home-kid"
    )
    assert not response["executed"] and domain.repository_read_count == 0
