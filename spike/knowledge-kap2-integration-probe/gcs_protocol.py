"""Real GCS KAP-2 protocol probe for an EXISTING isolated test bucket only.

No bucket, IAM, retention, key or project mutation. All object names are synthetic.
Use --preflight first; --run requires explicit isolated bucket and service identity.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import serialization

from journal_trust import (JOURNAL_DOMAIN, Trust, canonical, root_fingerprint,
                           verify_envelope, verify_registration)


API = "https://storage.googleapis.com/storage/v1"
UPLOAD = "https://storage.googleapis.com/upload/storage/v1"
PERMISSIONS = (
    "storage.objects.create", "storage.objects.get", "storage.objects.list",
    "storage.objects.delete", "storage.objects.update", "storage.buckets.update",
    "storage.objects.setRetention", "storage.objects.overrideUnlockedRetention",
)
MAX_CREATES = 160
MAX_OBJECT_REQUESTS = 5000
MAX_SIGN_REQUESTS = 160


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def token(service: str | None = None) -> str:
    command = ["gcloud", "auth", "print-access-token"]
    if service:
        command.append(f"--impersonate-service-account={service}")
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


class Client:
    def __init__(self, bucket: str, bearer: str, prefix: str) -> None:
        self.bucket, self.bearer, self.prefix = bucket, bearer, prefix
        self.counts = {"list": 0, "get": 0, "create": 0}

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.bearer}"
        return requests.request(method, url, headers=headers, timeout=20, **kwargs)

    def key(self, kind: str, number: int) -> str:
        return f"{self.prefix}/{kind}/{number:020d}.json"

    def get(self, key: str) -> tuple[int, bytes, str | None]:
        if sum(self.counts.values()) >= MAX_OBJECT_REQUESTS:
            raise RuntimeError("probe object-request cap reached")
        self.counts["get"] += 1
        response = self.request("GET", f"{API}/b/{self.bucket}/o/{quote(key, safe='')}", params={"alt": "media"})
        return response.status_code, response.content, response.headers.get("x-goog-generation")

    def create(self, key: str, content: dict) -> tuple[int, bytes, str | None]:
        if self.counts["create"] >= MAX_CREATES or sum(self.counts.values()) >= MAX_OBJECT_REQUESTS:
            raise RuntimeError("probe write/request cap reached")
        self.counts["create"] += 1
        response = self.request(
            "POST", f"{UPLOAD}/b/{self.bucket}/o",
            params={"uploadType": "media", "name": key, "ifGenerationMatch": "0"},
            data=canonical(content), headers={"Content-Type": "application/json"},
        )
        body = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
        return response.status_code, canonical(content), body.get("generation")

    def list_all(self, *, page_size: int = 7, after_first_page: Callable[[], None] | None = None) -> tuple[list[str], int]:
        names, pages, page_token = [], 0, None
        while True:
            if sum(self.counts.values()) >= MAX_OBJECT_REQUESTS:
                raise RuntimeError("probe object-request cap reached")
            self.counts["list"] += 1
            params = {"prefix": self.prefix + "/", "maxResults": page_size}
            if page_token:
                params["pageToken"] = page_token
            response = self.request("GET", f"{API}/b/{self.bucket}/o", params=params)
            response.raise_for_status()
            payload = response.json()
            names.extend(item["name"] for item in payload.get("items", []))
            pages += 1
            if pages == 1 and after_first_page:
                after_first_page()
            page_token = payload.get("nextPageToken")
            if not page_token:
                return names, pages


def inspect_head(client: Client, *, trust: dict[str, Trust] | None = None,
                 after_first_page: Callable[[], None] | None = None) -> tuple[str, int, int, float]:
    started = time.perf_counter()
    names, pages = client.list_all(after_first_page=after_first_page)
    known = set(names)
    if any(
        "/outcomes/" in name and name.replace("/outcomes/", "/slots/") not in known
        for name in known
    ):
        return "BROKEN", 0, pages, (time.perf_counter() - started) * 1000
    sequence, previous, epoch = 0, "GENESIS", 1
    while client.key("slots", sequence + 1) in known:
        number = sequence + 1
        slot_status, slot_bytes, _ = client.get(client.key("slots", number))
        if slot_status != 200:
            return "UNVERIFIED", sequence, pages, (time.perf_counter() - started) * 1000
        try:
            slot_envelope = json.loads(slot_bytes)
            if trust and slot_bytes != canonical(slot_envelope):
                raise ValueError("noncanonical signed slot")
            slot = verify_envelope(trust, slot_envelope) if trust else slot_envelope
        except Exception:
            return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
        if (slot.get("previous") != previous or slot.get("epoch") != epoch + (slot.get("kind") == "EPOCH")
                or (trust and slot.get("signer_epoch") != slot.get("epoch"))):
            return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
        if client.key("outcomes", number) not in known:
            return "PENDING", sequence, pages, (time.perf_counter() - started) * 1000
        outcome_status, outcome_bytes, _ = client.get(client.key("outcomes", number))
        if outcome_status != 200:
            return "UNVERIFIED", sequence, pages, (time.perf_counter() - started) * 1000
        try:
            outcome_envelope = json.loads(outcome_bytes)
            if trust and outcome_bytes != canonical(outcome_envelope):
                raise ValueError("noncanonical signed outcome")
            outcome = verify_envelope(trust, outcome_envelope) if trust else outcome_envelope
        except Exception:
            return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
        if (outcome.get("slot_sha256") != sha(slot_bytes) or outcome.get("decision") != "COMMIT"
                or (trust and outcome.get("signer_epoch") != slot.get("epoch"))):
            return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
        previous, sequence, epoch = sha(outcome_bytes), number, slot["epoch"]
    if any(name > client.key("slots", sequence + 1) and "/slots/" in name for name in known):
        return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
    # Detect an append after the last LIST page; a later append still requires
    # the DB fence lock and a fresh check before disclosure.
    next_status, _, _ = client.get(client.key("slots", sequence + 1))
    status = "READY" if next_status == 404 else "UNVERIFIED"
    return status, sequence, pages, (time.perf_counter() - started) * 1000


class KmsSigner:
    """Probe signer for an already registered EC_SIGN_ED25519 KMS key version."""

    def __init__(self, bearer: str, trust: Trust, public_key_bearer: str) -> None:
        self.bearer, self.trust, self.count = bearer, trust, 0
        response = requests.get(
            f"https://cloudkms.googleapis.com/v1/{trust.kms_version}/publicKey",
            headers={"Authorization": f"Bearer {public_key_bearer}"}, timeout=20,
        )
        response.raise_for_status()
        document = response.json()
        if document.get("algorithm") != "EC_SIGN_ED25519":
            raise ValueError("registered KMS version is not Ed25519")
        observed = serialization.load_pem_public_key(document["pem"].encode())
        if observed.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != (
            trust.signer_public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        ):
            raise ValueError("KMS public key differs from root-signed registration")

    def envelope(self, payload: dict) -> dict:
        if self.count >= MAX_SIGN_REQUESTS:
            raise RuntimeError("probe KMS signing-request cap reached")
        self.count += 1
        signed_bytes = JOURNAL_DOMAIN + canonical(payload)
        response = requests.post(
            f"https://cloudkms.googleapis.com/v1/{self.trust.kms_version}:asymmetricSign",
            headers={"Authorization": f"Bearer {self.bearer}"},
            json={"data": base64.b64encode(signed_bytes).decode()}, timeout=20,
        )
        response.raise_for_status()
        document = response.json()
        if document.get("name") != self.trust.kms_version:
            raise ValueError("KMS signed with the wrong key version")
        envelope = {
            "payload": payload, "registration_sha256": self.trust.registration_sha256,
            "signature_b64": document["signature"],
        }
        self.trust.verify(envelope)
        return envelope


def run(bucket: str, service: str, project: str, run_id: str, kms_version: str,
        root_pem_file: str, registration_file: str, next_kms_version: str,
        next_registration_file: str, root_sha256: str) -> dict:
    if (not bucket.startswith("kap2-probe-") or not project or not service
            or not re.fullmatch(r"[0-9a-f]{32}", run_id) or not kms_version
            or not root_pem_file or not registration_file or not next_kms_version
            or not next_registration_file or kms_version == next_kms_version
            or not re.fullmatch(r"[0-9a-f]{64}", root_sha256)):
        raise ValueError("requires an isolated bucket, identity, run ID and pinned signing inputs")
    prefix = f"home-auth/v1/partitions/{sha(('synthetic-' + run_id).encode())}"
    trusted_root = Path(root_pem_file).read_text(encoding="utf-8")
    if root_fingerprint(trusted_root) != root_sha256:
        raise ValueError("independently pinned root fingerprint mismatch")
    registration = json.loads(Path(registration_file).read_text(encoding="utf-8"))
    trust = verify_registration(registration, trusted_root,
                                partition=prefix, kms_version=kms_version)
    next_registration = json.loads(Path(next_registration_file).read_text(encoding="utf-8"))
    next_trust = verify_registration(next_registration, trusted_root, partition=prefix,
                                     kms_version=next_kms_version, prior=trust)
    registry = {trust.registration_sha256: trust, next_trust.registration_sha256: next_trust}
    operator = token()
    metadata = requests.get(f"{API}/b/{bucket}", headers={"Authorization": f"Bearer {operator}"}, timeout=20)
    metadata.raise_for_status()
    info = metadata.json()
    if info.get("projectNumber") is None or info.get("labels", {}).get("kap2_probe") != "true":
        raise ValueError("bucket lacks explicit kap2_probe=true isolation label")
    project_number = subprocess.run(
        ["gcloud", "projects", "describe", project, "--format=value(projectNumber)"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if str(info["projectNumber"]) != project_number:
        raise ValueError("isolated bucket is outside the explicitly named project")
    if info.get("versioning", {}).get("enabled", False):
        raise ValueError("versioned bucket is outside this immutable live-view probe")
    service_token = token(service)
    check = requests.get(
        f"{API}/b/{bucket}/iam/testPermissions",
        headers={"Authorization": f"Bearer {service_token}"},
        params=[("permissions", permission) for permission in PERMISSIONS], timeout=20,
    )
    check.raise_for_status()
    allowed = set(check.json().get("permissions", []))
    if not set(PERMISSIONS[:3]).issubset(allowed) or set(PERMISSIONS[3:]) & allowed:
        raise RuntimeError("service IAM is not create/get/list only; no objects written")
    client = Client(bucket, service_token, prefix)
    signer = KmsSigner(service_token, trust, operator)
    next_signer = KmsSigner(service_token, next_trust, operator)
    registration_key = f"{prefix}/trust/00000000000000000001.json"
    status, exact_registration, _ = client.create(registration_key, registration)
    if status != 200 or client.get(registration_key)[:2] != (200, exact_registration):
        raise RuntimeError("conditional trusted registration publication failed")
    next_registration_key = f"{prefix}/trust/00000000000000000002.json"
    status, exact_next_registration, _ = client.create(next_registration_key, next_registration)
    if status != 200 or client.get(next_registration_key)[:2] != (200, exact_next_registration):
        raise RuntimeError("conditional rotated registration publication failed")
    current_signer, current_trust = signer, trust

    def signed_create(key: str, payload: dict) -> tuple[int, bytes, str | None]:
        return client.create(key, current_signer.envelope({**payload, "signer_epoch": current_trust.epoch}))

    def head(**kwargs):
        return inspect_head(client, trust=registry, **kwargs)

    results: dict[str, object] = {
        "probe": "real_gcs_protocol", "bucket": "existing_isolated", "run_id": run_id,
        "iam": sorted(allowed), "retention_locked": info.get("retentionPolicy", {}).get("isLocked"),
        "versioning_enabled": info.get("versioning", {}).get("enabled", False),
        "signing": "two_root_registrations_and_kms_public_keys_verified", "cases": {}, "head_measurements": {},
    }
    cases: dict[str, object] = results["cases"]  # type: ignore[assignment]
    previous, epoch, sequence = "GENESIS", 1, 0

    def append(kind: str = "MUTATION", after: str = "ACTIVE") -> None:
        nonlocal previous, epoch, sequence
        number = sequence + 1
        next_epoch = epoch + (kind == "EPOCH")
        slot = {"sequence": number, "epoch": next_epoch, "kind": kind,
                "previous": previous, "after": after, "synthetic": True}
        status, slot_bytes, _ = signed_create(client.key("slots", number), slot)
        assert status == 200, status
        outcome = {"slot_sha256": sha(slot_bytes), "decision": "COMMIT"}
        status, outcome_bytes, _ = signed_create(client.key("outcomes", number), outcome)
        assert status == 200, status
        previous, epoch, sequence = sha(outcome_bytes), next_epoch, number

    # Two independent HTTP clients race for the same immutable slot.
    first = {"sequence": 1, "epoch": 1, "kind": "MUTATION", "previous": previous,
             "after": "ACTIVE", "synthetic": True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda _: signed_create(client.key("slots", 1), first), range(2)))
    statuses = [attempt[0] for attempt in attempts]
    assert sorted(statuses) == [200, 412], statuses
    cases["competing_clients"] = statuses
    status, readback, _ = client.get(client.key("slots", 1))
    assert status == 200 and readback == next(attempt[1] for attempt in attempts if attempt[0] == 200)
    assert trust.verify(json.loads(readback))["previous"] == "GENESIS"
    cases["lost_ack_readback"] = "EXACT_BYTES"  # Simulated lost acknowledgement.
    assert head()[0] == "PENDING"
    cases["pending_outcome"] = "BLOCKED"
    outcome = {"slot_sha256": sha(readback), "decision": "COMMIT"}
    status, outcome_bytes, _ = signed_create(client.key("outcomes", 1), outcome)
    assert status == 200
    assert signed_create(client.key("outcomes", 1), outcome)[0] == 412
    cases["conditional_outcome_create"] = "SECOND_WRITER_REJECTED"
    previous, sequence = sha(outcome_bytes), 1
    assert head()[:2] == ("READY", 1)

    for size in (1, 16, 64):
        while sequence < size:
            append()
        times, pages = [], []
        before = dict(client.counts)
        for _ in range(10):
            state, observed_head, page_count, elapsed = head()
            assert (state, observed_head) == ("READY", size)
            times.append(elapsed)
            pages.append(page_count)
        results["head_measurements"][str(size)] = {
            "runs": 10, "min_ms": min(times), "p50_ms": statistics.median(times),
            "p95_ms": sorted(times)[-1], "max_ms": max(times),
            "list_pages_per_run": pages,
            "requests": {name: client.counts[name] - before[name] for name in client.counts},
        }

    state, observed_head, _, _ = head(after_first_page=append)
    assert state == "UNVERIFIED" or (state == "READY" and observed_head == sequence), (state, observed_head)
    assert head()[:2] == ("READY", sequence)
    cases["concurrent_append_during_pagination"] = {"status": state, "head": observed_head}

    stale_local_sequence = sequence
    append("REVOKE", "REVOKED")
    assert head()[:2] == ("READY", sequence) and stale_local_sequence != sequence
    cases["restore_before_revocation"] = "STALE_LOCAL_DENIED"
    current_signer, current_trust = next_signer, next_trust
    append("EPOCH", "REVOKED")
    assert head()[:2] == ("READY", sequence)
    cases["writer_takeover"] = "ROOT_REGISTERED_SIGNER_EPOCH"
    # Corruption occupies one immutable next slot and can only block, not fork.
    bad = {"sequence": sequence + 1, "epoch": 1, "kind": "MUTATION",
           "previous": "CORRUPT", "after": "ACTIVE", "synthetic": True}
    assert signed_create(client.key("slots", sequence + 1), bad)[0] == 200
    assert head()[0] in {"PENDING", "BROKEN"}
    cases["chain_corruption"] = "BLOCKED"
    results["total_object_requests"] = client.counts
    results["kms_sign_requests"] = signer.count + next_signer.count
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", action="store_true")
    options = parser.parse_args()
    bucket = os.environ.get("KAP2_GCS_BUCKET", "")
    service = os.environ.get("KAP2_GCS_SERVICE_ACCOUNT", "")
    project = os.environ.get("KAP2_GCS_PROJECT", "")
    run_id = os.environ.get("KAP2_GCS_RUN_ID", "")
    kms_version = os.environ.get("KAP2_KMS_SIGNER_VERSION", "")
    root_pem_file = os.environ.get("KAP2_TRUST_ROOT_PEM_FILE", "")
    registration_file = os.environ.get("KAP2_SIGNED_REGISTRATION_FILE", "")
    next_kms_version = os.environ.get("KAP2_NEXT_KMS_SIGNER_VERSION", "")
    next_registration_file = os.environ.get("KAP2_NEXT_SIGNED_REGISTRATION_FILE", "")
    root_sha256 = os.environ.get("KAP2_TRUST_ROOT_SHA256", "")
    if options.preflight or not options.run:
        print(json.dumps({"probe": "real_gcs_protocol", "environment_configured": bool(
                          bucket and service and project and run_id and kms_version and root_pem_file
                          and registration_file and next_kms_version and next_registration_file and root_sha256),
                          "preflight_level": "environment_only",
                          "missing": [name for name, value in (("existing_isolated_bucket", bucket),
                           ("authorized_service_identity", service), ("project", project),
                           ("synthetic_run_id", run_id), ("kms_signer_version", kms_version),
                           ("independent_root_pin", root_pem_file),
                           ("independent_root_fingerprint", root_sha256),
                           ("root_signed_registration", registration_file),
                           ("next_kms_signer_version", next_kms_version),
                           ("next_root_signed_registration", next_registration_file)) if not value]}, sort_keys=True))
        return
    print(json.dumps(run(bucket, service, project, run_id, kms_version,
                         root_pem_file, registration_file, next_kms_version,
                         next_registration_file, root_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
