"""Generate disposable benchmark identity material outside the repository."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from r13_wire import DOMAINS, RUNTIME_URI, TRUST_PREFIX, canonical, domain_uri, peer_identity_and_spki


def _write(path: Path, data: bytes, *, secret: bool = False) -> None:
    path.write_bytes(data)
    path.chmod(0o600 if secret else 0o644)


def _key_pem(key: object) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def create(root: Path) -> None:
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(mode=0o700, parents=True)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Episteck disposable benchmark CA")])
    ca_cert = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    _write(root / "ca.pem", ca_cert.public_bytes(serialization.Encoding.PEM))

    def leaf(label: str, *, dns: str | None = None, uri: str | None = None) -> bytes:
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])
        san = x509.DNSName(dns) if dns else x509.UniformResourceIdentifier(uri or "")
        eku = ExtendedKeyUsageOID.SERVER_AUTH if dns else ExtendedKeyUsageOID.CLIENT_AUTH
        cert = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(ca_name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([san]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        _write(root / f"{label}.cert.pem", cert_pem)
        _write(root / f"{label}.key.pem", _key_pem(key), secret=True)
        return cert.public_bytes(serialization.Encoding.DER)

    leaf("home", dns="home-bench.invalid")
    leaf("domain", dns="domain-bench.invalid")
    runtime_der = leaf("runtime", uri=RUNTIME_URI)
    _, runtime_spki = peer_identity_and_spki(runtime_der)
    home_signer = ed25519.Ed25519PrivateKey.generate()
    distribution = ed25519.Ed25519PrivateKey.generate()
    _write(root / "home-signing.key.pem", _key_pem(home_signer), secret=True)
    _write(root / "home-signing.pub.pem", home_signer.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    _write(root / "distribution.pub.pem", distribution.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    _write(root / "distribution.key.pem", _key_pem(distribution), secret=True)
    issued_at = int(time.time())
    bundle = {
        "generation": 1, "issued_at": issued_at, "not_after": issued_at + 300,
        "active_home_kids": ["bench-home-1"],
        "service_spkis": {RUNTIME_URI: [runtime_spki]},
        "domain_audiences": {domain: domain_uri(domain) for domain in DOMAINS},
    }
    signature = distribution.sign(TRUST_PREFIX + canonical(bundle)).hex()
    _write(root / "trust.json", canonical({"bundle": bundle, "signature_hex": signature}))
    _write(root / "home-config.json", canonical({"runtime_service": RUNTIME_URI, "runtime_spki": runtime_spki,
                                                   "home_kid": "bench-home-1"}))
    # This private key stays in the disposable provisioning directory. It must not
    # be included in the domain container's mount or committed as evidence.
    print(json.dumps({"created": True, "directory": str(root), "cert_count": 3,
                      "trust_generation": 1, "expires_at_utc_epoch": issued_at + 300}))


def refresh(root: Path) -> None:
    distribution = serialization.load_pem_private_key(
        (root / "distribution.key.pem").read_bytes(), password=None
    )
    old = _load_trust(root)
    bundle = old["bundle"]
    issued_at = int(time.time())
    bundle.update(generation=bundle["generation"] + 1, issued_at=issued_at,
                  not_after=issued_at + 300)
    signature = distribution.sign(TRUST_PREFIX + canonical(bundle)).hex()
    next_path = root / "trust.json.next"
    _write(next_path, canonical({"bundle": bundle, "signature_hex": signature}))
    os.replace(next_path, root / "trust.json")
    print(json.dumps({"refreshed": True, "trust_generation": bundle["generation"],
                      "expires_at_utc_epoch": issued_at + 300}))


def _load_trust(root: Path) -> dict:
    return json.loads((root / "trust.json").read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "refresh"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    (create if args.action == "create" else refresh)(args.directory)
