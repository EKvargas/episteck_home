"""Synthetic signing trust checks; no cloud access."""

import base64

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from journal_trust import JOURNAL_DOMAIN, REGISTRATION_DOMAIN, canonical, verify_envelope, verify_registration


def pem(key):
    return key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def fixture():
    root, signer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    payload = {"version": 1, "partition": "synthetic", "epoch": 1, "kms_version": "synthetic/version/1",
               "public_key_pem": pem(signer), "previous_registration_sha256": "GENESIS"}
    registration = {"payload": payload, "root_signature_b64": base64.b64encode(
        root.sign(REGISTRATION_DOMAIN + canonical(payload))).decode()}
    return root, signer, registration


def test_registered_signer_and_tamper():
    root, signer, registration = fixture()
    trust = verify_registration(registration, pem(root), partition="synthetic", kms_version="synthetic/version/1")
    payload = {"signer_epoch": 1, "after": "ACTIVE"}
    envelope = {"payload": payload, "registration_sha256": trust.registration_sha256,
                "signature_b64": base64.b64encode(signer.sign(JOURNAL_DOMAIN + canonical(payload))).decode()}
    assert trust.verify(envelope) == payload
    envelope["payload"] = {"signer_epoch": 1, "after": "REVOKED"}
    with pytest.raises(InvalidSignature):
        trust.verify(envelope)


def test_self_supplied_key_cannot_register_itself():
    root, _, registration = fixture()
    attacker = Ed25519PrivateKey.generate()
    registration["payload"]["public_key_pem"] = pem(attacker)
    registration["root_signature_b64"] = base64.b64encode(
        attacker.sign(REGISTRATION_DOMAIN + canonical(registration["payload"]))).decode()
    with pytest.raises(InvalidSignature):
        verify_registration(registration, pem(root), partition="synthetic", kms_version="synthetic/version/1")


def test_rotation_and_restore_use_pinned_root_and_archived_public_keys():
    root, signer1, registration1 = fixture()
    prior = verify_registration(registration1, pem(root), partition="synthetic", kms_version="synthetic/version/1")
    signer2 = Ed25519PrivateKey.generate()
    payload2 = {"version": 1, "partition": "synthetic", "epoch": 2, "kms_version": "synthetic/version/2",
                "public_key_pem": pem(signer2), "previous_registration_sha256": prior.registration_sha256}
    registration2 = {"payload": payload2, "root_signature_b64": base64.b64encode(
        root.sign(REGISTRATION_DOMAIN + canonical(payload2))).decode()}
    current = verify_registration(registration2, pem(root), partition="synthetic",
                                  kms_version="synthetic/version/2", prior=prior)
    registry = {prior.registration_sha256: prior, current.registration_sha256: current}
    for trust, signer in ((prior, signer1), (current, signer2)):
        payload = {"signer_epoch": trust.epoch, "after": "REVOKED"}
        envelope = {"payload": payload, "registration_sha256": trust.registration_sha256,
                    "signature_b64": base64.b64encode(signer.sign(JOURNAL_DOMAIN + canonical(payload))).decode()}
        assert verify_envelope(registry, envelope) == payload
    registration2["payload"]["previous_registration_sha256"] = "FORGED"
    with pytest.raises((InvalidSignature, ValueError)):
        verify_registration(registration2, pem(root), partition="synthetic",
                            kms_version="synthetic/version/2", prior=prior)
