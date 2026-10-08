"""Local algorithm checks for the unrun live GCS client; no cloud access."""

from __future__ import annotations

import importlib.util
import base64
import io
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


def test_runner_rejects_shared_key_or_identity_before_cloud_access():
    first = "projects/synthetic/locations/us-east4/keyRings/probe/cryptoKeys/shared/cryptoKeyVersions/1"
    second = first.removesuffix("/1") + "/2"
    args = ("kap2-probe-synthetic", "old-service", "new-service", "verifier-service",
            "synthetic-project", "us-east4", "a" * 32, first, "root.pem", "first.json",
            second, "second.json", "0" * 64)
    with pytest.raises(ValueError, match="separate CryptoKeys"):
        module.run(*args)
    with pytest.raises(ValueError, match="three identities"):
        module.run(*((args[0], args[1], args[1]) + args[3:]))


def test_ashburn_token_input_stays_in_memory(monkeypatch):
    monkeypatch.setenv("KAP2_TOKEN_STDIN", "1")
    monkeypatch.setattr(module, "_token_bundle", None)
    monkeypatch.setattr(module, "_token_bundle_loaded_at", None)
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(json.dumps(
        {"tokens": {"operator": "operator-short-lived", "old-service": "old-short-lived"}}) + "\n"))
    assert module.token() == "operator-short-lived"
    assert module.token("old-service") == "old-short-lived"
    with pytest.raises(RuntimeError, match="missing short-lived"):
        module.token("unlisted-service")


@pytest.mark.parametrize("old_key_after_cutover", [403, 200])
def test_full_signed_runner_with_synthetic_clients(monkeypatch, tmp_path, old_key_after_cutover):
    run_id = "a" * 32
    partition = f"home-auth/v1/partitions/{module.sha(('synthetic-' + run_id).encode())}"
    root = Ed25519PrivateKey.generate()
    versions = {i: f"projects/synthetic/locations/us-east4/keyRings/probe/cryptoKeys/epoch{i}/cryptoKeyVersions/1"
                for i in (1, 2)}
    signers = {versions[i]: Ed25519PrivateKey.generate() for i in (1, 2)}

    def pem(key):
        return key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

    def registration(epoch, previous):
        payload = {"version": 1, "partition": partition, "epoch": epoch,
                   "kms_version": versions[epoch], "public_key_pem": pem(signers[versions[epoch]]),
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
        objects: dict[str, bytes] = {}

        def __init__(self, bucket, bearer, prefix, counts=None):
            self.prefix, self.bearer = prefix, bearer
            self.counts = counts if counts is not None else {"list": 0, "get": 0, "create": 0}

        def key(self, kind, number):
            return f"{self.prefix}/{kind}/{number:020d}.json"

        def create(self, key, content):
            self.counts["create"] += 1
            raw = module.canonical(content)
            if cutover["phase"] != "before" and self.bearer == "old-issued-token":
                return 403, raw, None
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
            assert bearer == ("old-issued-token" if trust.epoch == 1 else "new-token")

        def envelope(self, payload):
            self.count += 1
            return {"payload": payload, "registration_sha256": self.trust.registration_sha256,
                    "signature_b64": base64.b64encode(signers[self.trust.kms_version].sign(
                        JOURNAL_DOMAIN + module.canonical(payload))).decode()}

    class Response:
        def __init__(self, content, status_code=200):
            self.content, self.status_code = content, status_code

        def raise_for_status(self):
            pass

        def json(self):
            return self.content

    cutover = {"phase": "before"}
    monkeypatch.setattr(module, "Client", MemoryClient)
    monkeypatch.setattr(module, "KmsSigner", SyntheticKmsSigner)
    monkeypatch.setattr(module, "induced_timeout_create", lambda client, key, content: client.create(key, content))
    monkeypatch.setattr(module, "token", lambda service=None: {
        None: "operator-token", "old-service": "old-issued-token", "new-service": "new-token",
        "verifier-service": "verifier-token",
    }[service])

    def get(url, **kwargs):
        if url.endswith("/b/kap2-probe-synthetic"):
            return Response({"projectNumber": "123", "labels": {"kap2_probe": "true"},
                             "location": "US-EAST4"})
        if "cloudresourcemanager.googleapis.com" in url:
            return Response({"projectNumber": "123"})
        if "/cryptoKeyVersions/" in url:
            return Response({"protectionLevel": "SOFTWARE", "algorithm": "EC_SIGN_ED25519",
                             "state": "ENABLED"})
        bearer = kwargs["headers"]["Authorization"]
        permissions = list(module.PERMISSIONS[:3]) if bearer == "Bearer old-issued-token" else list(module.PERMISSIONS[1:3])
        if cutover["phase"] == "admitted" and bearer == "Bearer new-token":
            permissions.append("storage.objects.create")
        if cutover["phase"] != "before" and bearer == "Bearer old-issued-token":
            permissions.remove("storage.objects.create")
        return Response({"permissions": permissions})

    monkeypatch.setattr(module.requests, "get", get)
    monkeypatch.setattr(module.requests, "post", lambda url, **kwargs: Response(
        {}, (403 if cutover["phase"] == "before" else
             old_key_after_cutover if url.endswith(versions[1] + ":asymmetricSign") else 403)
        if kwargs["headers"]["Authorization"] in {"Bearer old-issued-token", "Bearer new-token"}
        else 200))

    def confirm(prompt):
        if prompt.startswith("Drain"):
            cutover["phase"] = "cutover"
            return "CUTOVER"
        assert cutover["phase"] == "cutover"
        cutover["phase"] = "admitted"
        return "ADMIT"

    monkeypatch.setattr(module, "input", confirm, raising=False)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="123"))
    with pytest.raises(ValueError, match="fingerprint"):
        module.run("kap2-probe-synthetic", "old-service", "new-service", "verifier-service",
                   "synthetic-project", "us-east4", run_id, versions[1], str(root_file), str(first_file),
                   versions[2], str(second_file), "0" * 64)
    if old_key_after_cutover == 200:
        with pytest.raises(RuntimeError, match="retained access"):
            module.run("kap2-probe-synthetic", "old-service", "new-service", "verifier-service",
                       "synthetic-project", "us-east4", run_id, versions[1], str(root_file), str(first_file),
                       versions[2], str(second_file), root_fingerprint(pem(root)))
        return
    result = module.run("kap2-probe-synthetic", "old-service", "new-service", "verifier-service",
                        "synthetic-project", "us-east4", run_id, versions[1], str(root_file), str(first_file),
                        versions[2], str(second_file), root_fingerprint(pem(root)))
    assert result["cases"]["writer_takeover"] == "ROOT_REGISTERED_SIGNER_EPOCH"
    assert result["cases"]["chain_corruption"] == "BLOCKED"
    assert result["cases"]["induced_http_read_timeout_after_gcs_acceptance"] == "EXACT_READBACK_AND_COMMIT"
    assert result["cases"]["old_issued_token_before_new_admission"] == [
        {"old_key": 403, "new_key": 403, "journal_create": 403}] * 3
    assert result["total_object_requests"]["create"] <= module.MAX_CREATES
    assert result["kms_sign_requests"] <= 2 * module.MAX_SIGN_REQUESTS


def test_induced_timeout_follows_accepted_upstream_create():
    class AcceptedClient:
        def create(self, key, content):
            return 200, module.canonical(content), "1"

    assert module.induced_timeout_create(AcceptedClient(), "synthetic/slot", {"synthetic": True}) == (
        200, b'{"synthetic":true}', "1")


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
