"""Disposable GCS journal capability probe. No production data or credentials."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests


PROJECT = "episteck-kn-probe-260926-5512"
BUCKET = PROJECT
SERVICE = f"kn-journal-probe@{PROJECT}.iam.gserviceaccount.com"
GCLOUD = os.environ.get("GCLOUD_BIN") or shutil.which("gcloud") or shutil.which("gcloud.cmd")
ROOT = "TEST-PARTITION-0001"
API = "https://storage.googleapis.com/storage/v1"
UPLOAD = "https://storage.googleapis.com/upload/storage/v1"
OUT = Path(__file__).with_name("gcs_live_observations.json")


def access_token(service: bool) -> str:
    if GCLOUD is None:
        raise RuntimeError("gcloud not found; set GCLOUD_BIN to the installed executable")
    args = [GCLOUD, "auth", "print-access-token"]
    if service:
        args.append(f"--impersonate-service-account={SERVICE}")
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout.strip()


TOKENS = {"service": access_token(True), "admin": access_token(False)}
events: list[dict] = []


def request(
    label: str,
    method: str,
    url: str,
    *,
    who: str = "service",
    params: dict | None = None,
    payload: bytes | None = None,
    document: dict | None = None,
    timeout: float = 20,
) -> tuple[int | None, dict | bytes | None, float]:
    headers = {"Authorization": f"Bearer {TOKENS[who]}"}
    if payload is not None:
        headers["Content-Type"] = "application/octet-stream"
    start = time.perf_counter()
    try:
        with requests.Session() as session:
            response = session.request(
                method, url, headers=headers, params=params, data=payload,
                json=document, timeout=timeout,
            )
        elapsed = (time.perf_counter() - start) * 1000
        if params and params.get("alt") == "media":
            body: dict | bytes = response.content
        else:
            try:
                body = response.json()
            except ValueError:
                body = response.content
        error = body.get("error", {}) if isinstance(body, dict) else {}
        event = {
            "label": label, "principal": who, "status": response.status_code,
            "error_reason": error.get("message") if isinstance(error, dict) else None,
            "latency_ms": round(elapsed, 3),
        }
        if response.ok and isinstance(body, dict):
            event["generation"] = body.get("generation")
            event["md5Hash"] = body.get("md5Hash")
        events.append(event)
        return response.status_code, body, elapsed
    except requests.RequestException as exc:
        elapsed = (time.perf_counter() - start) * 1000
        events.append({
            "label": label, "principal": who, "status": None,
            "transport_error": type(exc).__name__, "latency_ms": round(elapsed, 3),
        })
        return None, None, elapsed


def object_url(key: str) -> str:
    return f"{API}/b/{BUCKET}/o/{quote(key, safe='')}"


def content(revision: int, previous: str, *, valid: bool = True) -> bytes:
    return json.dumps({
        "partition": ROOT, "generation": "generation-test-1", "revision": revision,
        "previous_entry_hash": previous if valid else "INVALID-PREVIOUS-HASH",
        "synthetic": True,
    }, sort_keys=True, separators=(",", ":")).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key(revision: int, generation: str = "generation-test-1") -> str:
    return f"{ROOT}/{generation}/revision-{revision:06d}"


def put(label: str, name: str, data: bytes, *, conditional: bool = True) -> tuple[int | None, dict | bytes | None, float]:
    params = {"uploadType": "media", "name": name}
    if conditional:
        params["ifGenerationMatch"] = "0"
    return request(label, "POST", f"{UPLOAD}/b/{BUCKET}/o", params=params, payload=data)


def get(label: str, name: str, *, media: bool = False) -> tuple[int | None, dict | bytes | None, float]:
    return request(label, "GET", object_url(name), params={"alt": "media"} if media else None)


def listing(label: str, prefix: str, page_token: str | None = None, max_results: int = 1) -> tuple[int | None, dict | bytes | None, float]:
    params = {"prefix": prefix, "maxResults": max_results}
    if page_token:
        params["pageToken"] = page_token
    return request(label, "GET", f"{API}/b/{BUCKET}/o", params=params)


def scan(prefix: str, *, after_first_page=None, before_head_lookup=None) -> dict:
    names: list[str] = []
    token: str | None = None
    seen_tokens: set[str] = set()
    page = 0
    while True:
        status, body, _ = listing(f"scan_page_{page}", prefix, token)
        if status != 200 or not isinstance(body, dict):
            return {"state": "UNVERIFIED", "reason": "list failure"}
        names += [item["name"] for item in body.get("items", [])]
        token = body.get("nextPageToken")
        if page == 0 and after_first_page:
            after_first_page()
        if not token:
            break
        if token in seen_tokens:
            return {"state": "UNVERIFIED", "reason": "repeated page token"}
        seen_tokens.add(token)
        page += 1
    revisions = sorted(int(name.rsplit("-", 1)[1]) for name in names)
    if revisions != list(range(1, len(revisions) + 1)):
        return {"state": "BLOCKED", "reason": "gap or duplicate", "revisions": revisions}
    previous = "GENESIS"
    for revision in revisions:
        status, body, _ = get(f"chain_read_{revision}", f"{prefix}revision-{revision:06d}", media=True)
        if status != 200 or not isinstance(body, bytes):
            return {"state": "UNVERIFIED", "reason": "chain read failure"}
        entry = json.loads(body)
        if entry.get("revision") != revision or entry.get("previous_entry_hash") != previous:
            return {"state": "BLOCKED", "reason": "chain mismatch", "revision": revision}
        previous = digest(body)
    if before_head_lookup:
        before_head_lookup()
    highest = len(revisions)
    while True:
        next_name = f"{prefix}revision-{highest + 1:06d}"
        status, body, _ = get(f"head_lookup_{highest + 1}", next_name, media=True)
        if status == 404:
            return {"state": "PROVEN", "head": highest, "pages": page + 1, "revisions": revisions}
        if status != 200 or not isinstance(body, bytes):
            return {"state": "UNVERIFIED", "reason": "head lookup ambiguous"}
        entry = json.loads(body)
        if entry.get("revision") != highest + 1 or entry.get("previous_entry_hash") != previous:
            return {"state": "BLOCKED", "reason": "next chain mismatch"}
        previous = digest(body)
        highest += 1


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low, high = int(index), min(int(index) + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 3)


def main() -> None:
    results: dict = {"project": PROJECT, "bucket": BUCKET, "environment": "local Windows workstation; network location not confirmed as Nuremberg", "started_utc": datetime.now(timezone.utc).isoformat()}
    data1 = content(1, "GENESIS")
    results["ws1_first"] = put("ws1_first", key(1), data1)[0]
    results["ws1_duplicate"] = put("ws1_duplicate", key(1), b"DIFFERENT-SYNTHETIC-BYTES")[0]
    results["ws1_unconditional"] = put("ws1_unconditional", key(1), b"UNCONDITIONAL-SYNTHETIC-BYTES", conditional=False)[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(lambda i: put(f"ws1_race_{i}", key(2, "generation-test-race"), f"RACE-{i}".encode())[0], (1, 2)))
    results["ws1_race"] = attempts
    results["ws1_after"] = get("ws1_after", key(1), media=True)[1] == data1
    results["ws3_meta"] = get("ws3_metadata", key(1))[0]
    results["ws3_fresh_read"] = get("ws3_fresh_read", key(1), media=True)[1] == data1

    obj = object_url(key(1))
    results["ws2_delete"] = request("ws2_delete", "DELETE", obj)[0]
    results["ws2_metadata_patch"] = request("ws2_metadata_patch", "PATCH", obj, document={"metadata": {"probe": "mutation"}})[0]
    results["ws2_retention_patch"] = request("ws2_retention_patch", "PATCH", obj, document={"retention": {"mode": "Unlocked", "retainUntilTime": "2026-09-26T17:00:00Z"}})[0]
    bucket_url = f"{API}/b/{BUCKET}"
    iam_status, iam_body, _ = request("admin_get_bucket_iam", "GET", f"{bucket_url}/iam", who="admin")
    if iam_status == 200 and isinstance(iam_body, dict):
        results["ws2_bucket_iam_put"] = request("ws2_bucket_iam_put", "PUT", f"{bucket_url}/iam", document=iam_body)[0]
    results["ws2_bucket_retention_patch"] = request("ws2_bucket_retention_patch", "PATCH", bucket_url, document={"retentionPolicy": {"retentionPeriod": "1"}})[0]
    results["ws2_bucket_delete"] = request("ws2_bucket_delete", "DELETE", bucket_url)[0]
    results["ws2_admin_delete_protected"] = request("ws2_admin_delete_protected", "DELETE", obj, who="admin")[0]
    results["ws2_admin_shorten_locked"] = request("ws2_admin_shorten_locked", "PATCH", bucket_url, who="admin", document={"retentionPolicy": {"retentionPeriod": "1"}})[0]
    results["ws2_still_intact"] = get("ws2_still_intact", key(1), media=True)[1] == data1

    data2 = content(2, digest(data1))
    data3 = content(3, digest(data2))
    data4 = content(4, digest(data3))
    results["chain_put_2"] = put("chain_put_2", key(2), data2)[0]
    results["chain_put_3"] = put("chain_put_3", key(3), data3)[0]

    def add_4() -> None:
        results["concurrent_append_4"] = put("concurrent_append_4", key(4), data4)[0]

    results["ws5_during_pagination"] = scan(f"{ROOT}/generation-test-1/", after_first_page=add_4)
    data5 = content(5, digest(data4))

    def add_5() -> None:
        results["between_scan_and_lookup_5"] = put("between_scan_and_lookup_5", key(5), data5)[0]

    results["ws5_before_lookup"] = scan(f"{ROOT}/generation-test-1/", before_head_lookup=add_5)
    gap_prefix = f"{ROOT}/generation-test-gap/"
    put("gap_revision_1", f"{gap_prefix}revision-000001", content(1, "GENESIS"))
    put("gap_revision_3", f"{gap_prefix}revision-000003", content(3, "SYNTHETIC-GAP"))
    results["ws5_gap"] = scan(gap_prefix)
    tamper_prefix = f"{ROOT}/generation-test-tamper/"
    put("tamper_revision_1", f"{tamper_prefix}revision-000001", content(1, "GENESIS"))
    put("tamper_revision_2", f"{tamper_prefix}revision-000002", content(2, "IGNORED", valid=False))
    results["ws5_tamper"] = scan(tamper_prefix)

    results["ws6_missing"] = get("ws6_missing", f"{ROOT}/generation-test-1/revision-999999")[0]
    results["ws6_unreachable"] = request("ws6_unreachable", "GET", "http://127.0.0.1:1/unreachable", timeout=0.2)[0]
    results["ws6_ambiguous_reconciliation"] = get("ws6_ambiguous_reconciliation", key(1), media=True)[1] == data1
    first_page = listing("ws6_incomplete_first_page", f"{ROOT}/generation-test-1/")[1]
    results["ws6_incomplete_pagination"] = bool(isinstance(first_page, dict) and first_page.get("nextPageToken"))

    appends: list[float] = []
    reads: list[float] = []
    for i in range(100):
        status, _, elapsed = put(f"latency_append_{i}", f"{ROOT}/generation-test-latency/revision-{i+1:06d}", f"SYNTHETIC-{i}".encode())
        if status == 200:
            appends.append(elapsed)
        if i < 20:
            status, _, elapsed = get(f"latency_get_{i}", f"{ROOT}/generation-test-latency/revision-{i+1:06d}", media=True)
            if status == 200:
                reads.append(elapsed)
    list_times: list[float] = []
    for i in range(10):
        status, _, elapsed = listing(f"latency_list_{i}", f"{ROOT}/generation-test-latency/", max_results=1000)
        if status == 200:
            list_times.append(elapsed)
    results["latency_ms"] = {
        "append": {"n": len(appends), "p50": percentile(appends, .5), "p95": percentile(appends, .95), "p99": percentile(appends, .99)},
        "get": {"n": len(reads), "p50": percentile(reads, .5), "p95": percentile(reads, .95)},
        "list_100_objects": {"n": len(list_times), "p50": percentile(list_times, .5), "p95": percentile(list_times, .95)},
    }
    results["completed_utc"] = datetime.now(timezone.utc).isoformat()
    results["events"] = events
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in results.items() if k != "events"}, indent=2, sort_keys=True))
    print(f"RAW_OBSERVATIONS={OUT}")


if __name__ == "__main__":
    main()
