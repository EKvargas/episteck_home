"""Disposable journal trust verifier. The root PEM is pinned outside GCS/MariaDB."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REGISTRATION_DOMAIN = b"KAP2_REGISTER_V1\0"
JOURNAL_DOMAIN = b"KAP2_JOURNAL_V1\0"


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _public_key(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("expected Ed25519 public key")
    return key


def root_fingerprint(pem: str) -> str:
    key = _public_key(pem)
    return digest(key.public_bytes(serialization.Encoding.DER,
                                   serialization.PublicFormat.SubjectPublicKeyInfo))


@dataclass(frozen=True)
class Trust:
    registration_sha256: str
    partition: str
    kms_version: str
    epoch: int
    signer_public_key: Ed25519PublicKey

    def verify(self, envelope: dict) -> dict:
        if set(envelope) != {"payload", "registration_sha256", "signature_b64"}:
            raise ValueError("invalid journal envelope")
        if envelope["registration_sha256"] != self.registration_sha256:
            raise ValueError("unregistered signer epoch")
        payload = envelope["payload"]
        if not isinstance(payload, dict) or payload.get("signer_epoch") != self.epoch:
            raise ValueError("invalid signer epoch")
        signature = base64.b64decode(envelope["signature_b64"], validate=True)
        self.signer_public_key.verify(signature, JOURNAL_DOMAIN + canonical(payload))
        return payload


def verify_registration(document: dict, trusted_root_pem: str, *, partition: str,
                        kms_version: str, prior: Trust | None = None) -> Trust:
    if set(document) != {"payload", "root_signature_b64"}:
        raise ValueError("invalid registration envelope")
    payload = document["payload"]
    if not isinstance(payload, dict) or set(payload) != {
        "version", "partition", "epoch", "kms_version", "public_key_pem", "previous_registration_sha256"
    }:
        raise ValueError("invalid registration payload")
    if (type(payload["version"]) is not int or payload["version"] != 1
            or type(payload["epoch"]) is not int or payload["epoch"] != (prior.epoch + 1 if prior else 1)
            or payload["partition"] != partition or payload["kms_version"] != kms_version
            or (prior is not None and prior.partition != partition)
            or payload["previous_registration_sha256"] != (prior.registration_sha256 if prior else "GENESIS")):
        raise ValueError("registration binding mismatch")
    root = _public_key(trusted_root_pem)
    root.verify(base64.b64decode(document["root_signature_b64"], validate=True),
                REGISTRATION_DOMAIN + canonical(payload))
    return Trust(digest(canonical(document)), partition, kms_version, payload["epoch"],
                 _public_key(payload["public_key_pem"]))


def verify_envelope(registry: dict[str, Trust], envelope: dict) -> dict:
    registration = envelope.get("registration_sha256")
    if registration not in registry:
        raise ValueError("journal signer has no root-authenticated registration")
    return registry[registration].verify(envelope)
