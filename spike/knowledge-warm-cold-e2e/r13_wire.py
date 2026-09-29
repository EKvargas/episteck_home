"""Restricted disposable R13 v1 wire profile for synthetic benchmarks only.

The accepted production design requires a vetted general RFC 8785 library. This
module deliberately accepts only printable ASCII strings, arrays thereof and
safe integers, for which Python's sorted compact JSON equals JCS. It is not a
production canonicalization library.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID

SIGNATURE_PREFIX = b"episteck-r13-v1\x00"
TRUST_PREFIX = b"episteck-r13-trust-v1\x00"
RUNTIME_URI = "spiffe://episteck.internal/service/olin-runtime-benchmark"
DOMAINS = ("NUTRITION", "CALENDAR", "HOUSEHOLD", "FINANCE", "HEALTH")
CLAIM_INTS = {"version", "issued_at", "expires_at"}
CLAIM_ARRAYS = {"subject_person_ids", "resource_ids"}
CLAIM_STRINGS = {
    "home_kid", "execution_id", "request_id", "plan_id", "operation_id",
    "actor_person_id", "partition_id", "domain", "action", "use_class",
    "audience", "caller_service", "caller_spki_sha256", "method", "target",
    "request_sha256", "authorization_revision", "window_id", "decision_id",
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _ascii(value: Any) -> bool:
    return type(value) is str and bool(value) and all(32 <= ord(c) <= 126 for c in value)


def jcs_v1(claims: dict[str, Any]) -> bytes:
    if set(claims) != CLAIM_INTS | CLAIM_ARRAYS | CLAIM_STRINGS:
        raise ValueError("wrong claim schema")
    if claims["version"] != 1:
        raise ValueError("unsupported version")
    if any(type(claims[k]) is not int or not 0 <= claims[k] <= 2**53 - 1 for k in CLAIM_INTS):
        raise ValueError("unsafe integer")
    if any(not _ascii(claims[k]) for k in CLAIM_STRINGS):
        raise ValueError("invalid string")
    if any(type(claims[k]) is not list or not claims[k] or
           any(not _ascii(v) for v in claims[k]) for k in CLAIM_ARRAYS):
        raise ValueError("invalid array")
    return canonical(claims)


def encode_basis(claims: dict[str, Any], signer: Any) -> dict[str, str]:
    raw = jcs_v1(claims)
    return {
        "claims_jcs_b64u": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "signature_hex": signer.sign(SIGNATURE_PREFIX + raw).hex(),
    }


def decode_basis(envelope: dict[str, Any], public_key: Any) -> dict[str, Any]:
    if type(envelope) is not dict or set(envelope) != {"claims_jcs_b64u", "signature_hex"}:
        raise ValueError("invalid basis envelope")
    encoded, signature = envelope["claims_jcs_b64u"], envelope["signature_hex"]
    if type(encoded) is not str or not re.fullmatch(r"[A-Za-z0-9_-]+", encoded):
        raise ValueError("invalid base64url")
    if type(signature) is not str or not re.fullmatch(r"[0-9a-f]{128}", signature):
        raise ValueError("invalid signature encoding")
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if base64.urlsafe_b64encode(raw).decode().rstrip("=") != encoded:
        raise ValueError("noncanonical base64url")
    claims = json.loads(raw, object_pairs_hook=_unique)
    if type(claims) is not dict or jcs_v1(claims) != raw:
        raise ValueError("non-JCS claims")
    public_key.verify(bytes.fromhex(signature), SIGNATURE_PREFIX + raw)
    return claims


def peer_identity_and_spki(cert_der: bytes) -> tuple[str, str]:
    cert = x509.load_der_x509_certificate(cert_der)
    sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    uris = sans.get_values_for_type(x509.UniformResourceIdentifier)
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    if len(uris) != 1 or ExtendedKeyUsageOID.CLIENT_AUTH not in eku:
        raise ValueError("invalid peer service identity")
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return uris[0], hashlib.sha256(spki).hexdigest()


def domain_uri(domain: str) -> str:
    if domain not in DOMAINS:
        raise ValueError("unknown domain")
    return f"spiffe://episteck.internal/service/benchmark-{domain.lower()}"
