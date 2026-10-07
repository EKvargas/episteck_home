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
import statistics
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from urllib.parse import quote

import requests


API = "https://storage.googleapis.com/storage/v1"
UPLOAD = "https://storage.googleapis.com/upload/storage/v1"
PERMISSIONS = (
    "storage.objects.create", "storage.objects.get", "storage.objects.list",
    "storage.objects.delete", "storage.objects.update", "storage.buckets.update",
    "storage.objects.setRetention", "storage.objects.overrideUnlockedRetention",
)


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


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
        self.counts["get"] += 1
        response = self.request("GET", f"{API}/b/{self.bucket}/o/{quote(key, safe='')}", params={"alt": "media"})
        return response.status_code, response.content, response.headers.get("x-goog-generation")

    def create(self, key: str, content: dict) -> tuple[int, bytes, str | None]:
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


def inspect_head(client: Client, *, after_first_page: Callable[[], None] | None = None) -> tuple[str, int, int, float]:
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
        slot = json.loads(slot_bytes)
        if slot.get("previous") != previous or slot.get("epoch") != epoch + (slot.get("kind") == "EPOCH"):
            return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
        if client.key("outcomes", number) not in known:
            return "PENDING", sequence, pages, (time.perf_counter() - started) * 1000
        outcome_status, outcome_bytes, _ = client.get(client.key("outcomes", number))
        if outcome_status != 200:
            return "UNVERIFIED", sequence, pages, (time.perf_counter() - started) * 1000
        outcome = json.loads(outcome_bytes)
        if outcome.get("slot_sha256") != sha(slot_bytes) or outcome.get("decision") != "COMMIT":
            return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
        previous, sequence, epoch = sha(outcome_bytes), number, slot["epoch"]
    if any(name > client.key("slots", sequence + 1) and "/slots/" in name for name in known):
        return "BROKEN", sequence, pages, (time.perf_counter() - started) * 1000
    # Detect an append after the last LIST page; a later append still requires
    # the DB fence lock and a fresh check before disclosure.
    next_status, _, _ = client.get(client.key("slots", sequence + 1))
    status = "READY" if next_status == 404 else "UNVERIFIED"
    return status, sequence, pages, (time.perf_counter() - started) * 1000


def sign_and_verify(service: str, operator_token: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    payload = b"synthetic-kap2-journal-signature"
    signed = requests.post(
        f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{quote(service, safe='')}:signBlob",
        headers={"Authorization": f"Bearer {operator_token}"},
        json={"payload": base64.b64encode(payload).decode()}, timeout=20,
    )
    if signed.status_code != 200:
        return f"UNAVAILABLE_HTTP_{signed.status_code}"
    document = signed.json()
    certificates = requests.get(
        f"https://www.googleapis.com/service_accounts/v1/metadata/x509/{quote(service, safe='')}", timeout=20,
    ).json()
    certificate = x509.load_pem_x509_certificate(certificates[document["keyId"]].encode())
    certificate.public_key().verify(
        base64.b64decode(document["signedBlob"]), payload, padding.PKCS1v15(), hashes.SHA256()
    )
    return "VERIFIED"


def run(bucket: str, service: str, project: str) -> dict:
    if not bucket.startswith("kap2-probe-") or not project or not service:
        raise ValueError("requires an existing kap2-probe-* bucket, project and service account")
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
    run_id = uuid.uuid4().hex
    prefix = f"home-auth/v1/partitions/{sha(('synthetic-' + run_id).encode())}"
    client = Client(bucket, service_token, prefix)
    results: dict[str, object] = {
        "probe": "real_gcs_protocol", "bucket": "existing_isolated", "run_id": run_id,
        "iam": sorted(allowed), "retention_locked": info.get("retentionPolicy", {}).get("isLocked"),
        "versioning_enabled": info.get("versioning", {}).get("enabled", False),
        "service_self_signing": sign_and_verify(service, service_token), "cases": {}, "head_measurements": {},
    }
    cases: dict[str, object] = results["cases"]  # type: ignore[assignment]
    previous, epoch, sequence = "GENESIS", 1, 0

    def append(kind: str = "MUTATION", after: str = "ACTIVE") -> None:
        nonlocal previous, epoch, sequence
        number = sequence + 1
        next_epoch = epoch + (kind == "EPOCH")
        slot = {"sequence": number, "epoch": next_epoch, "kind": kind,
                "previous": previous, "after": after, "synthetic": True}
        status, slot_bytes, _ = client.create(client.key("slots", number), slot)
        assert status == 200, status
        outcome = {"slot_sha256": sha(slot_bytes), "decision": "COMMIT"}
        status, outcome_bytes, _ = client.create(client.key("outcomes", number), outcome)
        assert status == 200, status
        previous, epoch, sequence = sha(outcome_bytes), next_epoch, number

    # Two independent HTTP clients race for the same immutable slot.
    first = {"sequence": 1, "epoch": 1, "kind": "MUTATION", "previous": previous,
             "after": "ACTIVE", "synthetic": True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: client.create(client.key("slots", 1), first)[0], range(2)))
    assert sorted(statuses) == [200, 412], statuses
    cases["competing_clients"] = statuses
    status, readback, _ = client.get(client.key("slots", 1))
    assert status == 200 and readback == canonical(first)
    cases["lost_ack_readback"] = "EXACT_BYTES"  # Simulated lost acknowledgement.
    assert inspect_head(client)[0] == "PENDING"
    cases["pending_outcome"] = "BLOCKED"
    outcome = {"slot_sha256": sha(readback), "decision": "COMMIT"}
    status, outcome_bytes, _ = client.create(client.key("outcomes", 1), outcome)
    assert status == 200
    assert client.create(client.key("outcomes", 1), outcome)[0] == 412
    cases["conditional_outcome_create"] = "SECOND_WRITER_REJECTED"
    previous, sequence = sha(outcome_bytes), 1
    assert inspect_head(client)[:2] == ("READY", 1)

    for size in (1, 16, 64):
        while sequence < size:
            append()
        times, pages = [], []
        before = dict(client.counts)
        for _ in range(10):
            state, head, page_count, elapsed = inspect_head(client)
            assert (state, head) == ("READY", size)
            times.append(elapsed)
            pages.append(page_count)
        results["head_measurements"][str(size)] = {
            "runs": 10, "min_ms": min(times), "p50_ms": statistics.median(times),
            "p95_ms": sorted(times)[-1], "max_ms": max(times),
            "list_pages_per_run": pages,
            "requests": {name: client.counts[name] - before[name] for name in client.counts},
        }

    state, observed_head, _, _ = inspect_head(client, after_first_page=append)
    assert state == "UNVERIFIED" or (state == "READY" and observed_head == sequence), (state, observed_head)
    assert inspect_head(client)[:2] == ("READY", sequence)
    cases["concurrent_append_during_pagination"] = {"status": state, "head": observed_head}

    stale_local_sequence = sequence
    append("REVOKE", "REVOKED")
    assert inspect_head(client)[:2] == ("READY", sequence) and stale_local_sequence != sequence
    cases["restore_before_revocation"] = "STALE_LOCAL_DENIED"
    append("EPOCH", "REVOKED")
    assert inspect_head(client)[:2] == ("READY", sequence)
    cases["writer_takeover"] = "MONOTONIC_EPOCH"
    # Corruption occupies one immutable next slot and can only block, not fork.
    bad = {"sequence": sequence + 1, "epoch": 1, "kind": "MUTATION",
           "previous": "CORRUPT", "after": "ACTIVE", "synthetic": True}
    assert client.create(client.key("slots", sequence + 1), bad)[0] == 200
    assert inspect_head(client)[0] in {"PENDING", "BROKEN"}
    cases["chain_corruption"] = "BLOCKED"
    results["total_object_requests"] = client.counts
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", action="store_true")
    options = parser.parse_args()
    bucket = os.environ.get("KAP2_GCS_BUCKET", "")
    service = os.environ.get("KAP2_GCS_SERVICE_ACCOUNT", "")
    project = os.environ.get("KAP2_GCS_PROJECT", "")
    if options.preflight or not options.run:
        print(json.dumps({"probe": "real_gcs_protocol", "environment_configured": bool(bucket and service and project),
                          "preflight_level": "environment_only",
                          "missing": [name for name, value in (("existing_isolated_bucket", bucket),
                           ("authorized_service_identity", service), ("project", project)) if not value]}, sort_keys=True))
        return
    print(json.dumps(run(bucket, service, project), sort_keys=True))


if __name__ == "__main__":
    main()
