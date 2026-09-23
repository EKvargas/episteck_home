"""R13 SECONDARY experiment: transport-authenticated service identity via local mTLS.

This is the correction-7 companion to `holder_of_key.py`. It exists for one reason: to
address the R13-B UNKNOWN that `classify_r13()` records. In the primary in-process
experiment, `DomainVerifier.verify_and_execute` takes `claimed_service_identity` as an
explicit CALLER-SUPPLIED string, so the experiment cannot show that a real caller could
not simply assert an identity it does not own. That is the gap.

Here the identity is instead DERIVED FROM A VERIFIED TLS PEER CERTIFICATE. A short-lived
in-memory certificate authority (created fresh per experiment, never persisted, never a
real PKI) issues one client certificate per service identity. A local TLS server on
127.0.0.1 requires a client certificate (`ssl.CERT_REQUIRED`) chaining to that CA. When a
service connects, the server reads the peer's authenticated Common Name from the
already-verified peer certificate (`getpeercert()`), and it is THAT transport-derived
identity -- not anything in the request body -- that is passed on as the authenticated
service identity. A caller therefore cannot claim to be `svc-nutrition` unless it holds a
private key whose certificate the CA actually signed for `svc-nutrition`.

STRICT SCOPE (Phase-1 SS11.4, Family 1 mTLS variant, explicitly NOT the primary
realization; correction 7):
  * SECONDARY LOCAL EXPERIMENT only. Not a production R13 mechanism, not a technology
    selection, not a deployment. No production certificate authority, no external network,
    no long-lived key material -- everything is generated in a temp dir and torn down.
  * Binds to 127.0.0.1 on an ephemeral port. Talks to nothing outside this process.
  * EC (SECP256R1) is used for the certificate chain purely because it verifies reliably
    under this environment's OpenSSL; the choice is experimental, not a selection. The
    Ed25519 holder-of-key proof-of-possession (R13-A) is unchanged and still runs on top.

What this experiment can and cannot conclude is recorded by `classify_r13b_transport()`:
it upgrades R13-B from "cannot be exercised at all" to a LOCALLY-DEMONSTRATED transport
binding, while still stating plainly that a single-host loopback mTLS harness is not
evidence about a production deployment's identity fabric.
"""
from __future__ import annotations

import datetime
import socket
import ssl
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

# Reuse the primary experiment's verdict vocabulary and verifier so R13-B's transport
# result classifies on the SAME closed set and executes through the SAME logic.
from r13.holder_of_key import R13ClaimVerdict


# ---------------------------------------------------------------------------
# Ephemeral certificate authority + per-service client certificates
# ---------------------------------------------------------------------------
_LOOPBACK = "127.0.0.1"
_SERVER_CN = "spike-r13-transport-server"


def _new_ec_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _pem_cert(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _pem_key(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _peer_common_name(peercert: dict | None) -> str | None:
    """Pull the Common Name out of an already-verified peer certificate. `getpeercert()`
    only returns a cert dict AFTER the handshake verified the chain, so any CN read here is
    a transport-authenticated identity, not a request-supplied claim."""
    if not peercert:
        return None
    for rdn in peercert.get("subject", ()):
        for attr, value in rdn:
            if attr == "commonName":
                return value
    return None


@dataclass(frozen=True)
class _Issued:
    cert_pem: bytes
    key_pem: bytes


class EphemeralServiceCA:
    """A throwaway CA that signs one leaf certificate per service identity. Created fresh
    per experiment run, written only under a caller-provided temp dir, never persisted and
    never a real PKI. This is the out-of-band trust root: the server trusts THIS CA, so a
    service's transport identity is authoritative only if the CA signed its certificate."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._ca_key = _new_ec_key()
        self._ca_cert = self._self_signed_ca(self._ca_key)
        self.ca_pem_path = self.workdir / "ca.pem"
        self.ca_pem_path.write_bytes(_pem_cert(self._ca_cert))

    @staticmethod
    def _now():
        return datetime.datetime.now(datetime.timezone.utc)

    def _self_signed_ca(self, key: ec.EllipticCurvePrivateKey) -> x509.Certificate:
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "spike-r13-ephemeral-ca")])
        now = self._now()
        return (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(minutes=10))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256())
        )

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
                x509.SubjectAlternativeName([x509.DNSName(_SERVER_CN), x509.IPAddress(_ip(_LOOPBACK))]),
                critical=False,
            )
        return builder.sign(self._ca_key, hashes.SHA256())

    def issue(self, common_name: str) -> _Issued:
        """Issue a leaf cert+key for a service identity, trusted because THIS CA signed it."""
        key = _new_ec_key()
        cert = self._leaf(common_name, key)
        return _Issued(cert_pem=_pem_cert(cert), key_pem=_pem_key(key))

    def server_materials(self) -> Path:
        key = _new_ec_key()
        cert = self._leaf(_SERVER_CN, key)
        path = self.workdir / "server.pem"
        path.write_bytes(_pem_cert(cert) + _pem_key(key))
        return path


def _ip(addr: str):
    import ipaddress

    return ipaddress.ip_address(addr)


# ---------------------------------------------------------------------------
# A rogue CA -- signs a cert that CLAIMS a real identity but is not trusted
# ---------------------------------------------------------------------------
class RogueCA(EphemeralServiceCA):
    """An attacker-controlled CA. It can mint a certificate whose Common Name claims to be
    `svc-nutrition`, but the server does not trust this CA, so the handshake must fail
    before any identity is accepted. Models an attacker who can forge a name but cannot
    forge the trust root."""


# ---------------------------------------------------------------------------
# Transport-bound verifier: identity comes from the verified peer cert
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TransportResult:
    handshake_ok: bool
    transport_identity: str | None  # authenticated CN, or None if rejected
    detail: str


class TransportIdentityServer:
    """A local mTLS server that requires a client certificate and reports the identity it
    read from the VERIFIED peer certificate. One accept per connection, loopback only."""

    def __init__(self, ca: EphemeralServiceCA) -> None:
        self._ca = ca
        self._server_pem = ca.server_materials()
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(self._server_pem)
        self._ctx.load_verify_locations(ca.ca_pem_path)
        self._ctx.verify_mode = ssl.CERT_REQUIRED  # reject any client without a trusted cert
        self._lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._lsock.bind((_LOOPBACK, 0))
        self._lsock.listen(1)
        self.port = self._lsock.getsockname()[1]
        self._result: TransportResult | None = None

    def _accept_once(self) -> None:
        try:
            conn, _ = self._lsock.accept()
        except OSError as exc:  # closed under us
            self._result = TransportResult(False, None, f"accept failed: {exc}")
            return
        try:
            tls = self._ctx.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError) as exc:
            # The authoritative rejection signal: the mutual handshake did NOT complete, so no
            # authenticated peer identity was ever accepted. An untrusted / missing client cert
            # surfaces here in one of two ways depending on exactly when the peer tears down on
            # Windows: as ssl.SSLError (this side's verification rejected the client cert) or as
            # ConnectionResetError/OSError (the peer reset mid-handshake -- e.g. the rogue client
            # rejecting the server cert it does not trust). Either way the property under test
            # holds: NO transport identity was accepted. We record both as a transport rejection
            # (never as a fabricated success); the classifier still requires the honest arm to
            # positively succeed, so a spurious failure here can only lower the verdict, never
            # raise it. Catching the broad set also keeps the accept thread from dying with an
            # uncaught exception, which previously made result() flaky.
            self._result = TransportResult(False, None, f"peer rejected at transport: {type(exc).__name__}")
            try:
                conn.close()
            except OSError:
                pass
            return
        identity = _peer_common_name(tls.getpeercert())
        self._result = TransportResult(
            handshake_ok=True,
            transport_identity=identity,
            detail="identity derived from verified peer certificate",
        )
        try:
            tls.sendall(b"ok")
        finally:
            tls.close()

    def serve_one(self) -> threading.Thread:
        t = threading.Thread(target=self._accept_once, daemon=True)
        t.start()
        return t

    def result(self) -> TransportResult:
        assert self._result is not None, "serve_one() thread has not completed"
        return self._result

    def close(self) -> None:
        try:
            self._lsock.close()
        except OSError:
            pass


def connect_as(ca: EphemeralServiceCA, issued: _Issued, port: int, workdir: Path, label: str) -> str:
    """Connect a client presenting `issued` (its cert+key) to the server. Returns the
    client-observed outcome string. NOTE: the AUTHORITATIVE identity/rejection decision is
    made server-side (see TransportIdentityServer); the client view is only corroboration,
    because on some platforms a server-side verification failure surfaces to the client as
    a reset rather than an SSLError."""
    client_pem = workdir / f"client-{label}.pem"
    client_pem.write_bytes(issued.cert_pem + issued.key_pem)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(client_pem)
    ctx.load_verify_locations(ca.ca_pem_path)
    ctx.check_hostname = True
    try:
        raw = socket.create_connection((_LOOPBACK, port), timeout=5)
        tls = ctx.wrap_socket(raw, server_hostname=_SERVER_CN)
        data = tls.recv(2)
        tls.close()
        return f"client_ok:{data!r}"
    except (ssl.SSLError, OSError) as exc:
        return f"client_failed:{type(exc).__name__}"


# ---------------------------------------------------------------------------
# Classification of the R13-B transport-binding result (correction 7)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class R13BTransportOutcome:
    verdict: R13ClaimVerdict
    evidence: str
    limit: str


def classify_r13b_transport(
    *, honest_identity: str | None, honest_ok: bool, rogue_rejected: bool
) -> R13BTransportOutcome:
    """Given the observed results of the local mTLS runs, classify what the SECONDARY
    experiment established about R13-B. This does NOT overwrite `classify_r13()`'s R13-B
    (that remains UNKNOWN for the IN-PROCESS experiment, which is honest about its own
    instrumentation); it records what the transport experiment specifically showed.

    The bar for a local PASS: (1) an honest service's identity was derived from its
    verified peer certificate and matched what it was issued, and (2) a rogue certificate
    that merely CLAIMS that identity but is not signed by the trusted CA was rejected at
    the transport before any identity was accepted. Anything less stays UNKNOWN -- never a
    fabricated pass."""
    demonstrated = bool(honest_ok and honest_identity and rogue_rejected)
    if demonstrated:
        return R13BTransportOutcome(
            verdict=R13ClaimVerdict.PASS,
            evidence=(
                "Local mTLS harness: an honest service's authenticated identity "
                f"({honest_identity!r}) was read from its VERIFIED peer certificate, not from "
                "any request field, and a rogue certificate that claimed the same identity "
                "but chained to an untrusted CA was rejected at the transport layer before "
                "any identity was accepted. The authenticated identity is therefore not "
                "caller-nominatable in this harness."
            ),
            limit=(
                "SECONDARY LOCAL EXPERIMENT ONLY: single-host 127.0.0.1 loopback mTLS with a "
                "throwaway EC CA. It demonstrates the transport-binding MECHANISM locally; it "
                "is NOT evidence about a production identity fabric, service mesh, or key "
                "distribution, and selects no technology. R13-B for the in-process experiment "
                "remains UNKNOWN by construction (classify_r13)."
            ),
        )
    return R13BTransportOutcome(
        verdict=R13ClaimVerdict.UNKNOWN,
        evidence=(
            "The local mTLS harness did not fully demonstrate the transport binding "
            f"(honest_ok={honest_ok}, honest_identity={honest_identity!r}, "
            f"rogue_rejected={rogue_rejected})."
        ),
        limit="Recorded UNKNOWN / INSUFFICIENT EVIDENCE; not upgraded to PASS on partial evidence.",
    )
