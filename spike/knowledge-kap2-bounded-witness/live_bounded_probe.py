"""Disposable Ashburn MariaDB/GCS/KMS probe. Synthetic authority only.

Reads an in-memory token bundle from stdin. Writes sanitized, fsynced JSONL
before and after every network request. Never import into production services.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pymysql
import requests
from cryptography.hazmat.primitives import serialization


CAPS = {"get": 4200, "create": 160, "head_cas": 160,
        "list": 200, "total": 5000, "sign_per_key": 160}
API = "https://storage.googleapis.com/storage/v1"
UPLOAD = "https://storage.googleapis.com/upload/storage/v1"
KMS = "https://cloudkms.googleapis.com/v1"
DOMAIN = b"KAP2_BOUNDED_SYNTHETIC_V1\0"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Deny(Exception):
    pass


class Evidence:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.count = {"get": 0, "create": 0, "head_cas": 0, "list": 0,
                      "other_object": 0, "bucket_get": 0, "key_metadata": 0,
                      "kms_sign": {}}
        self.previous_result: dict = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("type") == "attempt_reserved":
                    self.count = event["counts"]
                if event.get("type") == "final":
                    self.previous_result = event["result"]
        self.file = path.open("a", encoding="utf-8", buffering=1)

    def record(self, **event: object) -> None:
        with self.lock:
            self.file.write(json.dumps({"utc": time.time(), **event}, sort_keys=True) + "\n")
            self.file.flush()
            os.fsync(self.file.fileno())

    def charge(self, category: str, *, key: str = "") -> None:
        with self.lock:
            if category == "kms_sign":
                current = self.count["kms_sign"].get(key, 0)
                if current >= CAPS["sign_per_key"]:
                    raise RuntimeError(f"KMS sign cap reached: {key}")
                self.count["kms_sign"][key] = current + 1
            elif category in ("bucket_get", "key_metadata"):
                self.count[category] += 1
            else:
                object_total = sum(self.count[name] for name in
                                   ("get", "create", "head_cas", "list", "other_object"))
                if object_total >= CAPS["total"]:
                    raise RuntimeError("hard object-request cutoff reached")
                if category in CAPS and self.count[category] >= CAPS[category]:
                    raise RuntimeError(f"{category} category cap reached")
                self.count[category] += 1
            snapshot = json.loads(json.dumps(self.count))
            self.file.write(json.dumps({"utc": time.time(), "type": "attempt_reserved",
                                        "category": category, "key": key,
                                        "counts": snapshot}, sort_keys=True) + "\n")
            self.file.flush()
            os.fsync(self.file.fileno())


class Cloud:
    def __init__(self, config: dict, evidence: Evidence) -> None:
        self.c, self.e = config, evidence
        self.sessions = {role: requests.Session() for role in config["tokens"]}
        self.public_keys = {}
        self.bucket_pin = {}
        self.last_head_write = 0.0

    def request(self, role: str, category: str, method: str, url: str,
                *, params: dict | None = None, data: bytes | None = None,
                document: dict | None = None, session: requests.Session | None = None,
                timeout: float = 15, sign_key: str = "") -> requests.Response:
        self.e.charge(category, key=sign_key)
        started = time.perf_counter()
        client = session or self.sessions[role]
        try:
            response = client.request(
                method, url, params=params, data=data, json=document,
                headers={"Authorization": f"Bearer {self.c['tokens'][role]}",
                         "Content-Type": "application/json"}, timeout=timeout,
            )
            self.e.record(type="request", role=role, category=category, method=method,
                          status=response.status_code,
                          latency_ms=round((time.perf_counter() - started) * 1000, 3))
            return response
        except requests.RequestException as exc:
            self.e.record(type="request", role=role, category=category, method=method,
                          transport_error=type(exc).__name__,
                          latency_ms=round((time.perf_counter() - started) * 1000, 3))
            raise Deny(f"{category} transport uncertainty") from exc

    def bucket_metadata(self, bucket: str, *, expected: bool = True) -> bool:
        response = self.request("verifier", "bucket_get", "GET", f"{API}/b/{bucket}")
        if response.status_code != 200:
            return False
        try:
            body = response.json()
            pin = (str(body["projectNumber"]), body["timeCreated"],
                   body["location"].lower(), body["name"])
        except (ValueError, KeyError, TypeError):
            return False
        return not expected or pin == self.bucket_pin[bucket]

    def pin_buckets(self) -> None:
        for bucket in (self.c["head_bucket"], self.c["journal_bucket"]):
            response = self.request("verifier", "bucket_get", "GET", f"{API}/b/{bucket}")
            if response.status_code != 200:
                raise RuntimeError("bucket metadata not readable by verifier")
            body = response.json()
            if (str(body.get("projectNumber")) != self.c["project_number"]
                    or body.get("location", "").lower() != "us-east4"
                    or body.get("retentionPolicy") or body.get("versioning", {}).get("enabled")):
                raise RuntimeError("bucket outside pinned disposable configuration")
            self.bucket_pin[bucket] = (str(body["projectNumber"]), body["timeCreated"],
                                       body["location"].lower(), body["name"])
        self.e.record(type="bucket_pin", pins={k: list(v) for k, v in self.bucket_pin.items()})

    def object_get(self, bucket: str, key: str, *, role: str = "verifier",
                   session: requests.Session | None = None,
                   timeout: float = 15) -> tuple[int, bytes, str | None]:
        response = self.request(role, "get", "GET", f"{API}/b/{bucket}/o/{quote(key, safe='')}",
                                params={"alt": "media"}, session=session, timeout=timeout)
        return response.status_code, response.content, response.headers.get("x-goog-generation")

    def object_metadata(self, bucket: str, key: str) -> dict:
        response = self.request("verifier", "get", "GET",
                                f"{API}/b/{bucket}/o/{quote(key, safe='')}")
        if response.status_code != 200:
            raise Deny("object metadata unavailable")
        return response.json()

    def list_objects(self, bucket: str, prefix: str) -> list[str]:
        names: list[str] = []
        page_token = None
        while True:
            params = {"prefix": prefix, "maxResults": "7"}
            if page_token:
                params["pageToken"] = page_token
            response = self.request("verifier", "list", "GET", f"{API}/b/{bucket}/o",
                                    params=params)
            if response.status_code != 200:
                raise Deny("audit LIST unavailable")
            body = response.json()
            names.extend(item["name"] for item in body.get("items", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                return names

    def create(self, bucket: str, key: str, value: dict, *, role: str = "journal",
               category: str = "create", generation: str = "0") -> str:
        response = self.request(role, category, "POST", f"{UPLOAD}/b/{bucket}/o",
                                params={"uploadType": "media", "name": key,
                                        "ifGenerationMatch": generation}, data=canonical(value))
        if response.status_code != 200:
            raise Deny(f"{category} returned {response.status_code}")
        try:
            return str(response.json()["generation"])
        except (ValueError, KeyError, TypeError) as exc:
            raise Deny("malformed GCS create response") from exc

    def head_cas(self, value: dict, generation: str) -> str:
        expected = canonical(value)
        for attempt in range(4):
            wait = 1.15 - (time.monotonic() - self.last_head_write)
            if wait > 0:
                time.sleep(wait)
            response = self.request(
                "head", "head_cas", "POST", f"{UPLOAD}/b/{self.c['head_bucket']}/o",
                params={"uploadType": "media", "name": self.c["head_key"],
                        "ifGenerationMatch": generation}, data=expected)
            self.last_head_write = time.monotonic()
            if response.status_code == 200:
                try:
                    return str(response.json()["generation"])
                except (ValueError, KeyError, TypeError) as exc:
                    raise Deny("malformed head CAS response") from exc
            if response.status_code == 429:
                self.e.record(type="head_rate_limit", attempt=attempt + 1)
                time.sleep(1.2 * (attempt + 1))
                continue
            if response.status_code == 412:
                status, actual, observed = self.object_get(self.c["head_bucket"],
                                                           self.c["head_key"])
                if status == 200 and actual == expected and observed:
                    self.e.record(type="head_lost_ack_readback", generation=observed)
                    return observed
            raise Deny(f"head_cas returned {response.status_code}")
        raise Deny("head replacement retry limit")

    def signed(self, payload: dict, key: str) -> dict:
        version = self.c["versions"][key]
        response = self.request(
            "journal" if key == "checkpoint" else key,
            "kms_sign", "POST", f"{KMS}/{version}:asymmetricSign",
            document={"data": base64.b64encode(DOMAIN + canonical(payload)).decode()},
            sign_key=key,
        )
        if response.status_code != 200:
            raise Deny(f"KMS {key} returned {response.status_code}")
        body = response.json()
        if body.get("name") != version or not isinstance(body.get("signature"), str):
            raise Deny("KMS signer identity/version uncertainty")
        envelope = {"payload": payload, "signer": key, "version": version,
                    "signature": body["signature"]}
        self.verify(envelope)
        return envelope

    def pin_keys(self) -> None:
        for key, version in self.c["versions"].items():
            response = self.request("operator", "key_metadata", "GET",
                                    f"{KMS}/{version}/publicKey")
            if response.status_code != 200:
                raise RuntimeError("KMS public key unavailable")
            body = response.json()
            if body.get("algorithm") != "EC_SIGN_ED25519":
                raise RuntimeError("KMS key is not Ed25519")
            self.public_keys[key] = serialization.load_pem_public_key(body["pem"].encode())
            self.e.record(type="key_pin", key=key, version=version,
                          public_sha256=digest(body["pem"].encode()))

    def verify(self, envelope: dict) -> dict:
        try:
            key = envelope["signer"]
            if envelope["version"] != self.c["versions"][key]:
                raise ValueError("unregistered version")
            self.public_keys[key].verify(base64.b64decode(envelope["signature"]),
                                         DOMAIN + canonical(envelope["payload"]))
            return envelope["payload"]
        except Exception as exc:
            raise Deny("invalid signed envelope") from exc


class Protocol:
    def __init__(self, cloud: Cloud, socket: str) -> None:
        self.cloud, self.e, self.c = cloud, cloud.e, cloud.c
        self.socket = socket
        self.head: dict | None = None
        self.generation = "0"
        self.last_hash = "GENESIS"

    def db(self):
        return pymysql.connect(unix_socket=self.socket, user="root", database="kap2_probe",
                               charset="utf8mb4", autocommit=False,
                               connect_timeout=5, read_timeout=20, write_timeout=20)

    def init_db(self) -> None:
        connection = self.db()
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE IF NOT EXISTS authority (id INT PRIMARY KEY, seq INT NOT NULL, allowed TINYINT NOT NULL, epoch INT NOT NULL)")
                cursor.execute("DELETE FROM authority")
                cursor.execute("INSERT INTO authority VALUES (1,0,1,1)")
            connection.commit()
        finally:
            connection.close()

    def checkpoint(self, *, genesis: bool = False) -> None:
        assert self.head is not None or genesis
        head = self.head or {"seq": 0, "allowed": True, "epoch": 1}
        seq = head["seq"]
        cp_key = f"{self.c['prefix']}/checkpoints/{seq:04d}.json"
        cp = self.cloud.signed({"kind": "CHECKPOINT", "seq": seq,
                                "allowed": head["allowed"], "epoch": head["epoch"],
                                "last_hash": self.last_hash,
                                "journal_pin": self.cloud.bucket_pin[self.c["journal_bucket"]]},
                               "checkpoint")
        self.cloud.create(self.c["journal_bucket"], cp_key, cp)
        next_head = {**head, "checkpoint_key": cp_key, "checkpoint_seq": seq,
                     "checkpoint_hash": digest(canonical(cp)), "last_hash": self.last_hash,
                     "state": "COMMITTED"}
        self.generation = self.cloud.head_cas(next_head, self.generation)
        self.head = next_head
        self.e.record(type="checkpoint", seq=seq, generation=self.generation)

    def initialize(self) -> None:
        self.init_db()
        self.checkpoint(genesis=True)

    def attach(self) -> None:
        status, head_bytes, observed = self.cloud.object_get(
            self.c["head_bucket"], self.c["head_key"])
        if status != 200:
            raise Deny("resume head unavailable")
        self.head = json.loads(head_bytes)
        metadata = self.cloud.object_metadata(self.c["head_bucket"], self.c["head_key"])
        self.generation = str(metadata["generation"])
        if observed and observed != self.generation:
            raise Deny("resume head generation changed")
        if self.head["state"] != "COMMITTED":
            raise Deny("resume requires conservative PENDING recovery")
        self.last_hash = self.head["last_hash"]
        connection = self.db()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT seq,allowed,epoch FROM authority WHERE id=1 FOR UPDATE")
                seq, allowed, epoch = cursor.fetchone()
                if (seq, bool(allowed), epoch) != (
                    self.head["seq"], self.head["allowed"], self.head["epoch"]
                ):
                    raise Deny("resume DB/head mismatch")
        finally:
            connection.rollback(); connection.close()
        self.e.record(type="resume_attached", seq=self.head["seq"],
                      generation=self.generation)

    def recover_orphan_allow7(self) -> None:
        if self.head is None or self.head["seq"] != 6:
            raise Deny("unexpected orphan recovery point")
        slot_key = f"{self.c['prefix']}/slots/0007.json"
        status, value, _ = self.cloud.object_get(self.c["journal_bucket"], slot_key)
        if status != 200:
            raise Deny("orphan slot unavailable")
        slot = json.loads(value)
        payload = self.cloud.verify(slot)
        if (payload["seq"], payload["kind"], payload["allowed"], payload["previous"]) != (
            7, "ALLOW_7", True, self.last_hash
        ):
            raise Deny("orphan slot does not match expected event")
        connection = self.db()
        cursor = connection.cursor()
        cursor.execute("SELECT seq FROM authority WHERE id=1 FOR UPDATE")
        if cursor.fetchone()[0] != 6:
            connection.rollback(); connection.close()
            raise Deny("orphan DB state changed")
        self.finish((connection, cursor, slot, slot_key, None),
                    allowed=True, epoch=1, signer="old")
        self.e.record(type="orphan_recovered", seq=7)

    def begin(self, *, event: str, allowed: bool, epoch: int, signer: str,
              delayed_prepare: bool = False):
        assert self.head is not None
        connection = self.db()
        cursor = connection.cursor()
        cursor.execute("SELECT seq, allowed, epoch FROM authority WHERE id=1 FOR UPDATE")
        seq, db_allowed, db_epoch = cursor.fetchone()
        if (seq, bool(db_allowed), db_epoch) != (self.head["seq"], self.head["allowed"],
                                                 self.head["epoch"]):
            connection.rollback(); connection.close()
            raise Deny("publisher DB/head mismatch")
        signer_expected = "old" if epoch == 1 else "new"
        legal_epoch = (epoch == db_epoch and event != "TAKEOVER") or (
            epoch == db_epoch + 1 and event == "TAKEOVER")
        if (self.head["state"] != "COMMITTED" or not legal_epoch
                or signer != signer_expected):
            connection.rollback(); connection.close()
            raise Deny("publisher epoch/state reject")
        number = seq + 1
        slot_key = f"{self.c['prefix']}/slots/{number:04d}.json"
        status, _, _ = self.cloud.object_get(self.c["journal_bucket"], slot_key)
        if status != 404:
            connection.rollback(); connection.close()
            raise Deny("successor reserved or uncertain")
        slot = self.cloud.signed({"kind": event, "seq": number, "epoch": epoch,
                                  "allowed": allowed, "previous": self.last_hash}, signer)
        self.cloud.create(self.c["journal_bucket"], slot_key, slot)
        if delayed_prepare:
            self.e.record(type="delayed_prepare_slot_visible", seq=number)
            return connection, cursor, slot, slot_key, None
        pending = {**self.head, "state": "PENDING", "event": event}
        self.generation = self.cloud.head_cas(pending, self.generation)
        self.head = pending
        return connection, cursor, slot, slot_key, pending

    def finish(self, started, *, allowed: bool, epoch: int, signer: str,
               commit_gap: bool = False) -> None:
        connection, cursor, slot, slot_key, pending = started
        if pending is None:
            pending = {**self.head, "state": "PENDING", "event": slot["payload"]["kind"]}
            self.generation = self.cloud.head_cas(pending, self.generation)
            self.head = pending
        number = slot["payload"]["seq"]
        cursor.execute("UPDATE authority SET seq=%s,allowed=%s,epoch=%s WHERE id=1",
                       (number, int(allowed), epoch))
        connection.commit()
        connection.close()
        if commit_gap:
            self.e.record(type="external_commit_gap", seq=number)
            if self.reader():
                raise AssertionError("PENDING allowed during COMMIT gap")
        outcome = self.cloud.signed({"kind": "COMMIT", "seq": number,
                                     "epoch": epoch, "allowed": allowed,
                                     "slot_hash": digest(canonical(slot))}, signer)
        outcome_key = f"{self.c['prefix']}/outcomes/{number:04d}.json"
        self.cloud.create(self.c["journal_bucket"], outcome_key, outcome)
        self.last_hash = digest(canonical(outcome))
        committed = {**pending, "seq": number, "allowed": allowed, "epoch": epoch,
                     "state": "COMMITTED", "last_hash": self.last_hash, "event": None}
        self.generation = self.cloud.head_cas(committed, self.generation)
        self.head = committed
        self.e.record(type="committed", seq=number, allowed=allowed,
                      epoch=epoch, generation=self.generation)

    def publish(self, *, event: str, allowed: bool, epoch: int, signer: str,
                commit_gap: bool = False) -> None:
        started = self.begin(event=event, allowed=allowed, epoch=epoch, signer=signer)
        self.finish(started, allowed=allowed, epoch=epoch, signer=signer,
                    commit_gap=commit_gap)

    def reader(self, *, session: requests.Session | None = None,
               expected_pin: tuple | None = None, timeout: float = 15) -> bool:
        connection = self.db()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT seq,allowed,epoch FROM authority WHERE id=1 FOR UPDATE")
                db_seq, db_allowed, db_epoch = cursor.fetchone()
                if not self.cloud.bucket_metadata(self.c["journal_bucket"]):
                    return False
                if expected_pin is not None and expected_pin != self.cloud.bucket_pin[self.c["journal_bucket"]]:
                    return False
                status, head_bytes, _ = self.cloud.object_get(
                    self.c["head_bucket"], self.c["head_key"], session=session, timeout=timeout)
                if status != 200:
                    return False
                try:
                    head = json.loads(head_bytes)
                    if head_bytes != canonical(head) or head["state"] != "COMMITTED":
                        return False
                    status, cp_bytes, _ = self.cloud.object_get(
                        self.c["journal_bucket"], head["checkpoint_key"],
                        session=session, timeout=timeout)
                    if status != 200 or digest(cp_bytes) != head["checkpoint_hash"]:
                        return False
                    cp = self.cloud.verify(json.loads(cp_bytes))
                    if (cp["kind"] != "CHECKPOINT" or cp["seq"] != head["checkpoint_seq"]
                            or tuple(cp["journal_pin"]) != self.cloud.bucket_pin[self.c["journal_bucket"]]):
                        return False
                    seq, allowed, epoch, previous = (cp["seq"], cp["allowed"],
                                                     cp["epoch"], cp["last_hash"])
                    if head["seq"] - seq > 8 or head["seq"] < seq:
                        return False
                    for number in range(seq + 1, head["seq"] + 1):
                        slot_key = f"{self.c['prefix']}/slots/{number:04d}.json"
                        outcome_key = f"{self.c['prefix']}/outcomes/{number:04d}.json"
                        a, slot_bytes, _ = self.cloud.object_get(self.c["journal_bucket"], slot_key,
                                                                  session=session, timeout=timeout)
                        b, outcome_bytes, _ = self.cloud.object_get(self.c["journal_bucket"], outcome_key,
                                                                     session=session, timeout=timeout)
                        if a != 200 or b != 200:
                            return False
                        slot = self.cloud.verify(json.loads(slot_bytes))
                        outcome = self.cloud.verify(json.loads(outcome_bytes))
                        if (slot["seq"] != number or slot["previous"] != previous
                                or outcome["seq"] != number
                                or outcome["slot_hash"] != digest(slot_bytes)
                                or slot["allowed"] != outcome["allowed"]
                                or slot["epoch"] != outcome["epoch"]):
                            return False
                        seq, allowed, epoch = number, outcome["allowed"], outcome["epoch"]
                        previous = digest(outcome_bytes)
                    if (seq, allowed, epoch, previous) != (
                        head["seq"], head["allowed"], head["epoch"], head["last_hash"]
                    ) or (db_seq, bool(db_allowed), db_epoch) != (seq, allowed, epoch):
                        return False
                    next_key = f"{self.c['prefix']}/slots/{seq + 1:04d}.json"
                    status, _, _ = self.cloud.object_get(self.c["journal_bucket"], next_key,
                                                          session=session, timeout=timeout)
                    return status == 404 and bool(allowed)
                except (ValueError, KeyError, TypeError, Deny):
                    return False
        except Deny:
            return False
        finally:
            connection.rollback()
            connection.close()


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percent + 0.5)))]


def benchmark(protocol: Protocol, suffix: int) -> dict:
    result = {}
    for temperature in ("warm", "cold"):
        individuals: list[float] = []
        pairs: list[float] = []
        warm = requests.Session()
        try:
            for _ in range(30):
                client = warm if temperature == "warm" else requests.Session()
                try:
                    start = time.perf_counter()
                    for _read in range(2):
                        one = time.perf_counter()
                        if not protocol.reader(session=client):
                            raise AssertionError("permissive benchmark reader denied")
                        individuals.append((time.perf_counter() - one) * 1000)
                    pairs.append((time.perf_counter() - start) * 1000)
                finally:
                    if temperature == "cold":
                        client.close()
        finally:
            warm.close()
        result[temperature] = {
            label: {"p50": percentile(values, .50), "p95": percentile(values, .95),
                    "p99": percentile(values, .99), "min": min(values), "max": max(values),
                    "n": len(values)}
            for label, values in (("individual_ms", individuals), ("pair_ms", pairs))
        }
        protocol.e.record(type="benchmark", suffix=suffix, temperature=temperature,
                          result=result[temperature], counts=protocol.e.count)
    return result


def test_competing_connections(protocol: Protocol) -> bool:
    first, second = protocol.db(), protocol.db()
    try:
        with first.cursor() as cursor:
            cursor.execute("SELECT seq FROM authority WHERE id=1 FOR UPDATE")
        with second.cursor() as cursor:
            cursor.execute("SET innodb_lock_wait_timeout=1")
            started = time.perf_counter()
            try:
                cursor.execute("SELECT seq FROM authority WHERE id=1 FOR UPDATE")
            except pymysql.err.OperationalError as exc:
                blocked = exc.args[0] == 1205
            else:
                blocked = False
            wait_ms = (time.perf_counter() - started) * 1000
        first.rollback()
        second.rollback()
        with second.cursor() as cursor:
            cursor.execute("SELECT seq FROM authority WHERE id=1 FOR UPDATE")
        second.rollback()
        protocol.e.record(type="competing_db_connections", blocked=blocked,
                          wait_ms=round(wait_ms, 3))
        return blocked and wait_ms >= 500
    finally:
        first.close(); second.close()


def test_credential_isolation(protocol: Protocol) -> dict:
    cloud, config = protocol.cloud, protocol.c
    journal = config["journal_bucket"]
    head = config["head_bucket"]
    cp_key = protocol.head["checkpoint_key"]
    cp_generation = str(cloud.object_metadata(journal, cp_key)["generation"])
    checks = {}
    url = f"{API}/b/{journal}/o/{quote(cp_key, safe='')}"
    checks["head_cannot_delete_journal"] = cloud.request(
        "head", "other_object", "DELETE", url,
        params={"ifGenerationMatch": cp_generation}).status_code == 403
    checks["head_cannot_replace_journal"] = cloud.request(
        "head", "create", "POST", f"{UPLOAD}/b/{journal}/o",
        params={"uploadType": "media", "name": cp_key,
                "ifGenerationMatch": cp_generation}, data=b"synthetic-overwrite").status_code == 403
    checks["old_writer_cannot_append_journal"] = cloud.request(
        "old", "create", "POST", f"{UPLOAD}/b/{journal}/o",
        params={"uploadType": "media", "name": f"{config['prefix']}/isolated-old.json",
                "ifGenerationMatch": "0"}, data=b"synthetic").status_code == 403
    checks["old_writer_cannot_replace_head"] = cloud.request(
        "old", "head_cas", "POST", f"{UPLOAD}/b/{head}/o",
        params={"uploadType": "media", "name": config["head_key"],
                "ifGenerationMatch": protocol.generation}, data=b"synthetic").status_code == 403
    cloud.e.record(type="credential_isolation", results=checks)
    return checks


def audit_history(protocol: Protocol, *, repeats: int = 2) -> list[dict]:
    cloud, config = protocol.cloud, protocol.c
    results = []
    for _ in range(repeats):
        started = time.perf_counter()
        names = set(cloud.list_objects(config["journal_bucket"], config["prefix"] + "/"))
        verified = 0
        for number in range(1, 65):
            for kind in ("slots", "outcomes"):
                key = f"{config['prefix']}/{kind}/{number:04d}.json"
                if key not in names:
                    raise Deny("full audit missing event")
                status, value, _ = cloud.object_get(config["journal_bucket"], key)
                if status != 200:
                    raise Deny("full audit GET unavailable")
                cloud.verify(json.loads(value))
                verified += 1
        for number in range(0, 65, 8):
            key = f"{config['prefix']}/checkpoints/{number:04d}.json"
            if key not in names:
                raise Deny("full audit missing checkpoint")
            status, value, _ = cloud.object_get(config["journal_bucket"], key)
            if status != 200:
                raise Deny("full audit checkpoint GET unavailable")
            cloud.verify(json.loads(value))
            verified += 1
        results.append({"verified_objects": verified, "listed_objects": len(names),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3)})
        protocol.e.record(type="full_audit", result=results[-1])
    return results


def fault_reads(protocol: Protocol) -> dict:
    """Use a permissive smoke snapshot; label injected responses explicitly."""
    protocol.init_db()  # The private synthetic DB row only.
    protocol.attach()
    checks = {"baseline_allows": protocol.reader()}

    class FakeSession:
        def __init__(self, status: int, body: bytes = b"") -> None:
            self.status, self.body = status, body

        def request(self, *_args, **_kwargs) -> requests.Response:
            response = requests.Response()
            response.status_code = self.status
            response._content = self.body
            return response

    class TimeoutSession:
        def request(self, *_args, **_kwargs) -> requests.Response:
            raise requests.Timeout("synthetic response timeout")

    checks["injected_malformed_head_denies"] = not protocol.reader(
        session=FakeSession(200, b"not-json"))
    checks["injected_head_403_denies"] = not protocol.reader(
        session=FakeSession(403))
    checks["injected_timeout_denies"] = not protocol.reader(session=TimeoutSession())
    pin = protocol.cloud.bucket_pin[protocol.c["journal_bucket"]]
    checks["wrong_incarnation_denies"] = not protocol.reader(
        expected_pin=("wrong-project", *pin[1:]))
    original_bucket = protocol.c["journal_bucket"]
    protocol.c["journal_bucket"] = "kap2-bnd-missing-771685799600"
    try:
        checks["real_missing_bucket_denies"] = not protocol.reader()
    finally:
        protocol.c["journal_bucket"] = original_bucket
    original_token = protocol.c["tokens"]["verifier"]
    protocol.c["tokens"]["verifier"] = protocol.c["tokens"]["old"]
    try:
        checks["real_permission_failure_denies"] = not protocol.reader()
    finally:
        protocol.c["tokens"]["verifier"] = original_token
    protocol.e.record(type="fault_reads", results=checks)
    return checks


def stale_head_requests(cloud: Cloud, evidence_path: Path) -> dict:
    commits = {}
    for line in evidence_path.with_name("events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == "committed" and event.get("seq") in (64, 65):
            commits[event["seq"]] = event["generation"]
    if set(commits) != {64, 65}:
        raise RuntimeError("missing independently archived prior head generations")
    results = {}
    for seq in (64, 65):
        response = cloud.request(
            "head", "head_cas", "POST", f"{UPLOAD}/b/{cloud.c['head_bucket']}/o",
            params={"uploadType": "media", "name": cloud.c["head_key"],
                    "ifGenerationMatch": commits[seq]},
            data=canonical({"synthetic_delayed_request_after_takeover": seq}))
        results[f"stale_seq_{seq}_rejected_412"] = response.status_code == 412
    cloud.e.record(type="stale_head_requests", results=results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--fault-reads", action="store_true")
    parser.add_argument("--stale-cas", action="store_true")
    args = parser.parse_args()
    config = json.loads(sys.stdin.readline())
    evidence = Evidence(Path(args.evidence))
    cloud = Cloud(config, evidence)
    result: dict = {"probe": "kap2_real_bounded_ashburn", "status": "INCOMPLETE"}
    try:
        cloud.pin_buckets()
        cloud.pin_keys()
        if args.preflight:
            result["status"] = "PREFLIGHT_PASS"
            return
        if args.stale_cas:
            result["stale_cas"] = stale_head_requests(cloud, Path(args.evidence))
            if not all(result["stale_cas"].values()):
                raise AssertionError("stale head CAS was not rejected")
            result["status"] = "STALE_CAS_PASS"
            return
        protocol = Protocol(cloud, args.socket)
        if args.fault_reads:
            result["fault_reads"] = fault_reads(protocol)
            if not all(result["fault_reads"].values()):
                raise AssertionError("fault-read fail-closed check failed")
            result["status"] = "FAULT_READS_PASS"
            return
        if args.resume:
            protocol.attach()
            protocol.recover_orphan_allow7()
            result["benchmark"] = dict(evidence.previous_result.get("benchmark", {}))
            result["competing_publishers_blocked"] = evidence.previous_result.get(
                "competing_publishers_blocked", False)
            result["credential_isolation"] = evidence.previous_result.get(
                "credential_isolation", {})
        else:
            protocol.initialize()
        if args.smoke:
            result["smoke_authorization_allows"] = protocol.reader()
            if not result["smoke_authorization_allows"]:
                raise AssertionError("smoke authorization denied")
            result["status"] = "SMOKE_PASS"
            return
        if not args.resume:
            result["competing_publishers_blocked"] = test_competing_connections(protocol)
            result["credential_isolation"] = test_credential_isolation(protocol)
            result["benchmark"] = {"0": benchmark(protocol, 0)}
            protocol.publish(event="ALLOW", allowed=True, epoch=1, signer="old")
            result["benchmark"]["1"] = benchmark(protocol, 1)
            for number in range(2, 9):
                protocol.publish(event=f"ALLOW_{number}", allowed=True, epoch=1, signer="old")
        else:
            protocol.publish(event="ALLOW_8", allowed=True, epoch=1, signer="old")
        result["benchmark"]["8"] = benchmark(protocol, 8)
        protocol.checkpoint()
        for number in range(9, 65):
            protocol.publish(event=f"ALLOW_{number}", allowed=True, epoch=1, signer="old")
            if number % 8 == 0:
                protocol.checkpoint()
        result["full_audits"] = audit_history(protocol)
        result["before_takeover_allows"] = protocol.reader()
        protocol.publish(event="TAKEOVER", allowed=True, epoch=2, signer="new",
                         commit_gap=True)
        result["after_takeover_allows"] = protocol.reader()
        cloud.signed({"kind": "OLD_TOKEN_STILL_SIGNS", "synthetic": True}, "old")
        result["old_signer_still_works"] = True
        try:
            protocol.begin(event="OLD_WRITER_RETRY", allowed=True, epoch=1, signer="old")
        except Deny:
            result["old_writer_rejected_by_publisher"] = True
        else:
            result["old_writer_rejected_by_publisher"] = False
        old_permissive_head = dict(protocol.head)
        old_permissive_seq = old_permissive_head["seq"]
        protocol.publish(event="REVOKE", allowed=False, epoch=2, signer="new",
                         commit_gap=True)
        result["revoked_denies"] = not protocol.reader()
        revoked_head = dict(protocol.head)
        connection = protocol.db()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE authority SET seq=%s,allowed=1,epoch=2 WHERE id=1",
                           (old_permissive_seq,))
        connection.commit(); connection.close()
        protocol.generation = cloud.head_cas(old_permissive_head, protocol.generation)
        result["combined_rollback_denies"] = not protocol.reader()
        evidence.record(type="combined_rollback", denied=result["combined_rollback_denies"])
        connection = protocol.db()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE authority SET seq=%s,allowed=0,epoch=2 WHERE id=1",
                           (revoked_head["seq"],))
        connection.commit(); connection.close()
        protocol.generation = cloud.head_cas(revoked_head, protocol.generation)
        protocol.head = revoked_head
        result["restored_current_denies"] = not protocol.reader()
        wrong_pin = ("wrong-project", *cloud.bucket_pin[config["journal_bucket"]][1:])
        result["wrong_incarnation_denies"] = not protocol.reader(expected_pin=wrong_pin)
        result["missing_bucket_denies"] = not cloud.bucket_metadata("kap2-bnd-missing-771685799600",
                                                                       expected=False)
        result["timeout_denies"] = not protocol.reader(timeout=0.000001)
        # A reserved slot without a new head already blocks obsolete-head readers.
        started = protocol.begin(event="DELAYED_PREPARE", allowed=False, epoch=2,
                                 signer="new", delayed_prepare=True)
        started[0].close()  # Simulated publisher connection loss; no authority commit.
        result["delayed_prepare_denies"] = not protocol.reader()
        result["lost_connection_denies"] = not protocol.reader()
        evidence.record(type="scenario_results", results={k: v for k, v in result.items()
                                                         if k not in ("benchmark", "full_audits")})
        scalar_checks = [v for k, v in result.items()
                         if k not in ("benchmark", "full_audits", "credential_isolation",
                                      "probe", "status")]
        if not all(scalar_checks) or not all(result["credential_isolation"].values()):
            raise AssertionError("one or more safety scenarios failed")
        result["status"] = "PASS_WITH_OPEN_PROOFS"
    except Exception as exc:
        result["status"] = "FAIL"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:300]
        evidence.record(type="failure", error_type=type(exc).__name__, message=str(exc)[:300])
        raise
    finally:
        result["counts"] = evidence.count
        evidence.record(type="final", result=result)
        print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
