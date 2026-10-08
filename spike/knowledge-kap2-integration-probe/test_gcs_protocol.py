"""Local algorithm checks for the unrun live GCS client; no cloud access."""

from __future__ import annotations

import importlib.util
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from journal_trust import JOURNAL_DOMAIN, REGISTRATION_DOMAIN, Trust, root_fingerprint


spec = importlib.util.spec_from_file_location("gcs_protocol", Path(__file__).with_name("gcs_protocol.py"))
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def key(self, kind: str, number: int) -> str:
        return f"test/{kind}/{number:020d}.json"

    def list_all(self, *, page_size=7, after_first_page=None):
        if after_first_page:
            after_first_page()
        return sorted(self.objects), 1

    def get(self, key: str):
        return (200, self.objects[key], None) if key in self.objects else (404, b"", None)


def test_orphan_outcome_blocks_head():
    client = FakeClient()
    client.objects[client.key("outcomes", 1)] = b"{}"
    assert module.inspect_head(client)[0] == "BROKEN"


def test_gap_before_later_slot_blocks_head():
    client = FakeClient()
    client.objects[client.key("slots", 2)] = b"{}"
    assert module.inspect_head(client)[0] == "BROKEN"


def test_pending_slot_blocks_head():
    client = FakeClient()
    client.objects[client.key("slots", 1)] = module.canonical(
        {"sequence": 1, "epoch": 1, "kind": "MUTATION", "previous": "GENESIS"}
    )
    assert module.inspect_head(client)[0] == "PENDING"


def test_signed_head_rejects_tampered_slot():
    client = FakeClient()
    signer = Ed25519PrivateKey.generate()
    trust = Trust("registered", "synthetic", "synthetic/version/1", 1, signer.public_key())
    registry = {trust.registration_sha256: trust}

    def envelope(payload):
        return {"payload": payload, "registration_sha256": trust.registration_sha256,
                "signature_b64": base64.b64encode(signer.sign(JOURNAL_DOMAIN + module.canonical(payload))).decode()}

    slot = {"sequence": 1, "epoch": 1, "signer_epoch": 1, "kind": "MUTATION", "previous": "GENESIS"}
    slot_bytes = module.canonical(envelope(slot))
    client.objects[client.key("slots", 1)] = slot_bytes
    outcome = {"signer_epoch": 1, "slot_sha256": module.sha(slot_bytes), "decision": "COMMIT"}
    client.objects[client.key("outcomes", 1)] = module.canonical(envelope(outcome))
    assert module.inspect_head(client, trust=registry)[:2] == ("READY", 1)
    forged = envelope(slot)
    forged["payload"]["previous"] = "FORGED"
    client.objects[client.key("slots", 1)] = module.canonical(forged)
    assert module.inspect_head(client, trust=registry)[0] == "BROKEN"


def test_full_signed_runner_with_synthetic_clients(monkeypatch, tmp_path):
    run_id = "a" * 32
    partition = f"home-auth/v1/partitions/{module.sha(('synthetic-' + run_id).encode())}"
    root = Ed25519PrivateKey.generate()
    signers = {str(i): Ed25519PrivateKey.generate() for i in (1, 2)}

    def pem(key):
        return key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

    def registration(epoch, previous):
        payload = {"version": 1, "partition": partition, "epoch": epoch,
                   "kms_version": str(epoch), "public_key_pem": pem(signers[str(epoch)]),
                   "previous_registration_sha256": previous}
        return {"payload": payload, "root_signature_b64": base64.b64encode(
            root.sign(REGISTRATION_DOMAIN + module.canonical(payload))).decode()}

    first = registration(1, "GENESIS")
    second = registration(2, module.sha(module.canonical(first)))
    root_file, first_file, second_file = (tmp_path / name for name in ("root.pem", "first.json", "second.json"))
    root_file.write_text(pem(root))
    first_file.write_text(json.dumps(first))
    second_file.write_text(json.dumps(second))

    class MemoryClient:
        def __init__(self, bucket, bearer, prefix):
            self.prefix, self.objects = prefix, {}
            self.counts = {"list": 0, "get": 0, "create": 0}

        def key(self, kind, number):
            return f"{self.prefix}/{kind}/{number:020d}.json"

        def create(self, key, content):
            self.counts["create"] += 1
            raw = module.canonical(content)
            if key in self.objects:
                return 412, raw, None
            self.objects[key] = raw
            return 200, raw, "1"

        def get(self, key):
            self.counts["get"] += 1
            return (200, self.objects[key], "1") if key in self.objects else (404, b"", None)

        def list_all(self, *, page_size=7, after_first_page=None):
            self.counts["list"] += 1
            names = sorted(self.objects)
            if after_first_page:
                after_first_page()
            return names, max(1, (len(names) + page_size - 1) // page_size)

    class SyntheticKmsSigner:
        def __init__(self, bearer, trust, public_key_bearer):
            self.trust, self.count = trust, 0

        def envelope(self, payload):
            self.count += 1
            return {"payload": payload, "registration_sha256": self.trust.registration_sha256,
                    "signature_b64": base64.b64encode(signers[self.trust.kms_version].sign(
                        JOURNAL_DOMAIN + module.canonical(payload))).decode()}

    class Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass

        def json(self):
            return self.content

    monkeypatch.setattr(module, "Client", MemoryClient)
    monkeypatch.setattr(module, "KmsSigner", SyntheticKmsSigner)
    monkeypatch.setattr(module, "token", lambda service=None: "synthetic-token")
    monkeypatch.setattr(module.requests, "get", lambda url, **kwargs: Response(
        {"projectNumber": "123", "labels": {"kap2_probe": "true"}}
        if url.endswith("/b/kap2-probe-synthetic") else {"permissions": list(module.PERMISSIONS[:3])}))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="123"))
    with pytest.raises(ValueError, match="fingerprint"):
        module.run("kap2-probe-synthetic", "synthetic-service", "synthetic-project", run_id,
                   "1", str(root_file), str(first_file), "2", str(second_file), "0" * 64)
    result = module.run("kap2-probe-synthetic", "synthetic-service", "synthetic-project", run_id,
                        "1", str(root_file), str(first_file), "2", str(second_file), root_fingerprint(pem(root)))
    assert result["cases"]["writer_takeover"] == "ROOT_REGISTERED_SIGNER_EPOCH"
    assert result["cases"]["chain_corruption"] == "BLOCKED"
    assert result["total_object_requests"]["create"] <= module.MAX_CREATES
    assert result["kms_sign_requests"] <= 2 * module.MAX_SIGN_REQUESTS


def test_kms_signer_compares_registered_key_and_verifies_signature(monkeypatch):
    signer = Ed25519PrivateKey.generate()
    pem = signer.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    trust = Trust("registered", "synthetic", "synthetic/version/1", 1, signer.public_key())

    class Response:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            pass

        def json(self):
            return self.value

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response(
        {"algorithm": "EC_SIGN_ED25519", "pem": pem}))

    def sign_call(url, **kwargs):
        raw = base64.b64decode(kwargs["json"]["data"])
        return Response({"name": trust.kms_version,
                         "signature": base64.b64encode(signer.sign(raw)).decode()})

    monkeypatch.setattr(module.requests, "post", sign_call)
    envelope = module.KmsSigner("writer", trust, "verifier").envelope({"signer_epoch": 1, "after": "ACTIVE"})
    assert trust.verify(envelope)["after"] == "ACTIVE"
    attacker = Ed25519PrivateKey.generate()
    attacker_pem = attacker.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response(
        {"algorithm": "EC_SIGN_ED25519", "pem": attacker_pem}))
    with pytest.raises(ValueError, match="differs"):
        module.KmsSigner("writer", trust, "verifier")
