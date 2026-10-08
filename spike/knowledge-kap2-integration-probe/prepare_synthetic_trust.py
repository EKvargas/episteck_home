"""Prepare public synthetic trust material; the disposable root secret stays in memory."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from gcs_protocol import sha
from journal_trust import REGISTRATION_DOMAIN, canonical, root_fingerprint, verify_registration


def prepare(version1: str, version2: str, run_id: str, bearer: str, output: Path) -> dict:
    if not output.is_dir() or not run_id or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("requires an existing output directory and 32-hex synthetic run ID")
    if version1.split("/cryptoKeyVersions/")[0] == version2.split("/cryptoKeyVersions/")[0]:
        raise ValueError("epochs require distinct CryptoKeys")
    partition = f"home-auth/v1/partitions/{sha(('synthetic-' + run_id).encode())}"
    root = Ed25519PrivateKey.generate()
    root_pem = root.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    prior = "GENESIS"
    registrations = []
    for epoch, version in enumerate((version1, version2), 1):
        response = requests.get(f"https://cloudkms.googleapis.com/v1/{version}/publicKey",
                                headers={"Authorization": f"Bearer {bearer}"}, timeout=20)
        response.raise_for_status()
        key = response.json()
        if key.get("algorithm") != "EC_SIGN_ED25519":
            raise ValueError("KMS signer is not Ed25519")
        payload = {"version": 1, "partition": partition, "epoch": epoch,
                   "kms_version": version, "public_key_pem": key["pem"],
                   "previous_registration_sha256": prior}
        document = {"payload": payload, "root_signature_b64": base64.b64encode(
            root.sign(REGISTRATION_DOMAIN + canonical(payload))).decode()}
        registrations.append(document)
        prior = sha(canonical(document))
    first = verify_registration(registrations[0], root_pem, partition=partition, kms_version=version1)
    verify_registration(registrations[1], root_pem, partition=partition, kms_version=version2, prior=first)
    files = {"root_public.pem": root_pem.encode(),
             "registration1.json": canonical(registrations[0]),
             "registration2.json": canonical(registrations[1])}
    for name, data in files.items():
        path = output / name
        with path.open("xb") as handle:
            handle.write(data)
    return {"partition": partition, "root_sha256": root_fingerprint(root_pem),
            "public_files_sha256": {name: sha(data) for name, data in files.items()}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version1", required=True)
    parser.add_argument("--version2", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bearer = sys.stdin.readline().strip()
    if not bearer:
        raise RuntimeError("operator access token required on stdin")
    print(json.dumps(prepare(args.version1, args.version2, args.run_id, bearer, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
