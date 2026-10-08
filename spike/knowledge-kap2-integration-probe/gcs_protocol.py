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
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
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
_token_bundle: dict | None = None
_token_bundle_loaded_at: float | None = None


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def token(service: str | None = None) -> str:
    global _token_bundle, _token_bundle_loaded_at
    if os.environ.get("KAP2_TOKEN_STDIN") == "1":
        if _token_bundle is None:
            _token_bundle = json.loads(sys.stdin.readline())
            _token_bundle_loaded_at = time.monotonic()
        value = _token_bundle.get("tokens", {}).get(service or "operator")
        if not isinstance(value, str) or not value:
            raise RuntimeError("missing short-lived in-memory probe token")
        return value
    command = ["gcloud", "auth", "print-access-token"]
    if service:
        command.append(f"--impersonate-service-account={service}")
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def confirm(phase: str, prompt: str) -> str:
    control = os.environ.get("KAP2_CONTROL_DIR")
    if not control:
        return input(prompt)
    directory = Path(control)
    if not str(directory).startswith("/tmp/kap2-gcs-probe-") or not directory.is_dir():
        raise RuntimeError("invalid isolated probe control directory")
    (directory / f"AWAIT_{phase}").touch()
    print(f"KAP2_AWAIT_{phase}", flush=True)
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        if (directory / phase).is_file():
            return phase
        time.sleep(1)
    raise TimeoutError(f"{phase} operator barrier timed out")


def induced_timeout_create(client: Client, key: str, content: dict) -> tuple[int, bytes, str | None]:
    """Lose a real HTTP response after an upstream GCS conditional create."""
    result: dict[str, tuple[int, bytes, str | None] | Exception] = {}

    class DropResponse(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                result["upstream"] = client.create(key, content)
            except Exception as exc:
                result["error"] = exc
            time.sleep(0.25)  # Deliberately exceed the loopback client's read timeout.

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), DropResponse)
    thread = Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        try:
            requests.post(f"http://127.0.0.1:{server.server_port}/", data=b"synthetic",
                          timeout=(1, 0.05))
        except requests.exceptions.ReadTimeout:
            pass
        else:
            raise RuntimeError("induced HTTP response timeout did not occur")
        thread.join(timeout=20)
        if thread.is_alive() or "error" in result or "upstream" not in result:
            raise RuntimeError("upstream create outcome not established") from result.get("error")
        return result["upstream"]
    finally:
        server.server_close()


class Client:
    def __init__(self, bucket: str, bearer: str, prefix: str, counts: dict[str, int] | None = None) -> None:
        self.bucket, self.bearer, self.prefix = bucket, bearer, prefix
        self.counts = counts if counts is not None else {"list": 0, "get": 0, "create": 0}

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


def run(bucket: str, old_writer_service: str, new_writer_service: str, verifier_service: str,
        project: str, region: str, run_id: str, kms_version: str,
        root_pem_file: str, registration_file: str, next_kms_version: str,
        next_registration_file: str, root_sha256: str) -> dict:
    if (not bucket.startswith("kap2-probe-") or not project or region not in {"us-east4", "europe-west3"}
            or len({old_writer_service, new_writer_service, verifier_service}) != 3
            or not all((old_writer_service, new_writer_service, verifier_service))
            or not re.fullmatch(r"[0-9a-f]{32}", run_id) or not kms_version
            or not root_pem_file or not registration_file or not next_kms_version
            or not next_registration_file or kms_version == next_kms_version
            or not re.fullmatch(r"[0-9a-f]{64}", root_sha256)):
        raise ValueError("requires an isolated bucket, three identities, run ID and pinned signing inputs")
    first_key = kms_version.rsplit("/cryptoKeyVersions/", 1)
    second_key = next_kms_version.rsplit("/cryptoKeyVersions/", 1)
    if len(first_key) != 2 or len(second_key) != 2 or first_key[0] == second_key[0]:
        raise ValueError("writer epochs require separate CryptoKeys, not versions of one key")
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
    project_response = requests.get(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{quote(project, safe='')}",
        headers={"Authorization": f"Bearer {operator}"}, timeout=20,
    )
    project_response.raise_for_status()
    if str(info["projectNumber"]) != str(project_response.json().get("projectNumber")):
        raise ValueError("isolated bucket is outside the explicitly named project")
    if info.get("versioning", {}).get("enabled", False):
        raise ValueError("versioned bucket is outside this immutable live-view probe")
    if info.get("location", "").lower() != region or info.get("retentionPolicy"):
        raise ValueError("bucket region or retention policy differs from approved disposable probe")
    for version in (kms_version, next_kms_version):
        response = requests.get(f"https://cloudkms.googleapis.com/v1/{version}",
                                headers={"Authorization": f"Bearer {operator}"}, timeout=20)
        response.raise_for_status()
        key_info = response.json()
        if (key_info.get("protectionLevel") != "SOFTWARE" or
                key_info.get("algorithm") != "EC_SIGN_ED25519" or key_info.get("state") != "ENABLED"):
            raise ValueError("signer version must be enabled SOFTWARE Ed25519")
    old_token, new_token, verifier_token = (token(identity) for identity in
                                             (old_writer_service, new_writer_service, verifier_service))

    def permissions(bearer: str) -> set[str]:
        check = requests.get(
            f"{API}/b/{bucket}/iam/testPermissions",
            headers={"Authorization": f"Bearer {bearer}"},
            params=[("permissions", permission) for permission in PERMISSIONS], timeout=20,
        )
        check.raise_for_status()
        return set(check.json().get("permissions", []))

    writer_permissions = set(PERMISSIONS[:3])
    reader_permissions = {"storage.objects.get", "storage.objects.list"}
    allowed = {"old_writer": permissions(old_token), "new_writer": permissions(new_token),
               "verifier": permissions(verifier_token)}
    if (not writer_permissions.issubset(allowed["old_writer"])
            or set(PERMISSIONS[3:]) & allowed["old_writer"]
            or allowed["new_writer"] != reader_permissions
            or allowed["verifier"] != reader_permissions):
        raise RuntimeError("writer/verifier IAM exceeds or lacks scoped probe permissions; no objects written")
    counts = {"list": 0, "get": 0, "create": 0}
    old_client = Client(bucket, old_token, prefix, counts)
    new_client = Client(bucket, new_token, prefix, counts)
    verifier_client = Client(bucket, verifier_token, prefix, counts)
    client = old_client
    signer = KmsSigner(old_token, trust, operator)
    next_signer = KmsSigner(new_token, next_trust, operator)
    direct_sign_counts = {kms_version: 0, next_kms_version: 0}

    def sign_probe(version: str, bearer: str) -> int:
        signed = signer.count if version == kms_version else next_signer.count
        if signed + direct_sign_counts[version] >= MAX_SIGN_REQUESTS:
            raise RuntimeError("probe KMS signing-request cap reached")
        direct_sign_counts[version] += 1
        response = requests.post(
            f"https://cloudkms.googleapis.com/v1/{version}:asymmetricSign",
            headers={"Authorization": f"Bearer {bearer}"},
            json={"data": base64.b64encode(JOURNAL_DOMAIN + b"synthetic-iam-denial").decode()},
            timeout=20,
        )
        return response.status_code

    if (sign_probe(next_kms_version, old_token) != 403 or
            sign_probe(next_kms_version, new_token) != 403):
        raise RuntimeError("writer key isolation or pre-admission signing denial failed")
    registration_key = f"{prefix}/trust/00000000000000000001.json"
    status, exact_registration, _ = client.create(registration_key, registration)
    if status != 200 or verifier_client.get(registration_key)[:2] != (200, exact_registration):
        raise RuntimeError("conditional trusted registration publication failed")
    next_registration_key = f"{prefix}/trust/00000000000000000002.json"
    status, exact_next_registration, _ = client.create(next_registration_key, next_registration)
    if status != 200 or verifier_client.get(next_registration_key)[:2] != (200, exact_next_registration):
        raise RuntimeError("conditional rotated registration publication failed")
    current_signer, current_trust = signer, trust

    def signed_create(key: str, payload: dict) -> tuple[int, bytes, str | None]:
        return client.create(key, current_signer.envelope({**payload, "signer_epoch": current_trust.epoch}))

    def head(**kwargs):
        return inspect_head(verifier_client, trust=registry, **kwargs)

    results: dict[str, object] = {
        "probe": "real_gcs_protocol", "bucket": "existing_isolated", "run_id": run_id,
        "iam": {role: sorted(value) for role, value in allowed.items()},
        "retention_locked": info.get("retentionPolicy", {}).get("isLocked"),
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

    number = sequence + 1
    timeout_slot = {"sequence": number, "epoch": epoch, "kind": "MUTATION",
                    "previous": previous, "after": "ACTIVE", "synthetic": True}
    timeout_envelope = current_signer.envelope({**timeout_slot, "signer_epoch": current_trust.epoch})
    timeout_key = client.key("slots", number)
    timeout_status, timeout_bytes, _ = induced_timeout_create(client, timeout_key, timeout_envelope)
    read_status, readback, _ = verifier_client.get(timeout_key)
    if timeout_status != 200 or read_status != 200 or readback != timeout_bytes:
        raise RuntimeError("timeout-after-accepted-create exact readback failed")
    outcome = {"slot_sha256": sha(readback), "decision": "COMMIT"}
    outcome_status, outcome_bytes, _ = signed_create(client.key("outcomes", number), outcome)
    if outcome_status != 200:
        raise RuntimeError("timeout recovery outcome publication failed")
    previous, sequence = sha(outcome_bytes), number
    if head()[:2] != ("READY", sequence):
        raise RuntimeError("timeout recovery did not produce a verified head")
    cases["induced_http_read_timeout_after_gcs_acceptance"] = "EXACT_READBACK_AND_COMMIT"

    state, observed_head, _, _ = head(after_first_page=append)
    assert state == "UNVERIFIED" or (state == "READY" and observed_head == sequence), (state, observed_head)
    assert head()[:2] == ("READY", sequence)
    cases["concurrent_append_during_pagination"] = {"status": state, "head": observed_head}

    stale_local_sequence = sequence
    append("REVOKE", "REVOKED")
    assert head()[:2] == ("READY", sequence) and stale_local_sequence != sequence
    cases["restore_before_revocation"] = "STALE_LOCAL_DENIED"
    # Capture an already-issued credential before operator cutover. This runner
    # does not mutate IAM and never refreshes the credential after cutover.
    old_token = token(old_writer_service)
    old_client.bearer = old_token
    token_issued_at = time.monotonic()
    confirmation = confirm("CUTOVER", "Drain old writers; revoke old key signing and bucket create IAM; "
                           "wait for propagation. Type CUTOVER to test old token before new writer admission: ")
    token_age = time.monotonic() - (_token_bundle_loaded_at if os.environ.get("KAP2_TOKEN_STDIN") == "1"
                                    else token_issued_at)
    if confirmation != "CUTOVER" or token_age > 1200:
        raise RuntimeError("cutover not confirmed or old token too old for a valid denial test")
    if "storage.objects.create" in permissions(old_token):
        raise RuntimeError("old token still has object-create permission")
    denied: list[dict[str, int]] = []
    for round_number in range(3):
        statuses: dict[str, int] = {}
        for label, version in (("old_key", kms_version), ("new_key", next_kms_version)):
            statuses[label] = sign_probe(version, old_token)
        status, _, _ = old_client.create(old_client.key("old-writer-denial", round_number),
                                         {"synthetic": True, "round": round_number})
        statuses["journal_create"] = status
        denied.append(statuses)
        if set(statuses.values()) != {403}:
            raise RuntimeError(f"old issued credential retained access at cutover: {statuses}")
        if round_number < 2:
            time.sleep(2)
    cases["old_issued_token_before_new_admission"] = denied
    # New writer starts without create/sign grants. The operator admits it only
    # after the old-token denial rounds, then the runner checks its bucket IAM.
    confirmation = confirm("ADMIT", "Now grant the new writer bucket create and its own key signing; "
                           "type ADMIT after propagation: ")
    if confirmation != "ADMIT":
        raise RuntimeError("new writer admission not confirmed")
    new_token = token(new_writer_service)
    if permissions(new_token) != writer_permissions:
        raise RuntimeError("new writer bucket admission missing or overprivileged")
    new_client.bearer = new_token
    next_signer.bearer = new_token
    client = new_client
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
    results["total_object_requests"] = counts
    results["kms_sign_requests"] = signer.count + next_signer.count + sum(direct_sign_counts.values())
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", action="store_true")
    options = parser.parse_args()
    bucket = os.environ.get("KAP2_GCS_BUCKET", "")
    old_writer = os.environ.get("KAP2_GCS_OLD_WRITER_SERVICE_ACCOUNT", "")
    new_writer = os.environ.get("KAP2_GCS_NEW_WRITER_SERVICE_ACCOUNT", "")
    verifier = os.environ.get("KAP2_GCS_VERIFIER_SERVICE_ACCOUNT", "")
    project = os.environ.get("KAP2_GCS_PROJECT", "")
    region = os.environ.get("KAP2_GCS_EXPECTED_REGION", "")
    run_id = os.environ.get("KAP2_GCS_RUN_ID", "")
    kms_version = os.environ.get("KAP2_KMS_SIGNER_VERSION", "")
    root_pem_file = os.environ.get("KAP2_TRUST_ROOT_PEM_FILE", "")
    registration_file = os.environ.get("KAP2_SIGNED_REGISTRATION_FILE", "")
    next_kms_version = os.environ.get("KAP2_NEXT_KMS_SIGNER_VERSION", "")
    next_registration_file = os.environ.get("KAP2_NEXT_SIGNED_REGISTRATION_FILE", "")
    root_sha256 = os.environ.get("KAP2_TRUST_ROOT_SHA256", "")
    if options.preflight or not options.run:
        print(json.dumps({"probe": "real_gcs_protocol", "environment_configured": bool(
                          bucket and old_writer and new_writer and verifier and project and region and run_id and kms_version and root_pem_file
                          and registration_file and next_kms_version and next_registration_file and root_sha256),
                          "preflight_level": "environment_only",
                          "missing": [name for name, value in (("existing_isolated_bucket", bucket),
                           ("old_writer_identity", old_writer), ("new_writer_identity", new_writer),
                           ("verifier_identity", verifier), ("project", project), ("expected_region", region),
                           ("synthetic_run_id", run_id), ("kms_signer_version", kms_version),
                           ("independent_root_pin", root_pem_file),
                           ("independent_root_fingerprint", root_sha256),
                           ("root_signed_registration", registration_file),
                           ("next_kms_signer_version", next_kms_version),
                           ("next_root_signed_registration", next_registration_file)) if not value]}, sort_keys=True))
        return
    print(json.dumps(run(bucket, old_writer, new_writer, verifier, project, region, run_id, kms_version,
                         root_pem_file, registration_file, next_kms_version,
                         next_registration_file, root_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
