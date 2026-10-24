"""Disconnected Home Knowledge event lane; callers must supply trusted adapters.

The site runtime must not hold the store's writer credential. This module is not
registered as a Frappe endpoint, hook or scheduler task.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Protocol

import pymysql

from episteck_home.policy.access import ACTIONS, DOMAINS


@dataclass(frozen=True)
class ActivationRequest:
    partition_id: str
    incarnation: str
    event_id: str
    kind: str
    actor_person_id: str
    resource_type: str
    resource_id: str
    domain: str
    actions: frozenset[str]
    source_grant_id: str
    issuer_person_id: str


@dataclass(frozen=True)
class PreparedActivation:
    request: ActivationRequest
    expected_revision: int
    digest: str
    request_sha: str


class WitnessWriter(Protocol):
    def prepare(self, partition: str, incarnation: str, event: str,
                expected_revision: int, digest: str) -> None: ...

    def commit(self, partition: str, incarnation: str, event: str, digest: str) -> None: ...


def _request_bytes(request: ActivationRequest) -> bytes:
    if (
        not isinstance(request, ActivationRequest)
        or any(type(value) is not str or not value for value in (
            request.partition_id, request.incarnation, request.event_id, request.kind,
            request.actor_person_id, request.resource_type, request.resource_id,
            request.domain, request.issuer_person_id))
        or type(request.actions) is not frozenset or not request.actions
        or any(type(action) is not str for action in request.actions)
        or request.kind not in {"GRANT", "SELF"}
        or request.resource_type not in {"PERSON", "CIRCLE"}
        or request.domain not in DOMAINS or not request.actions.issubset(ACTIONS)
        or (request.kind == "SELF" and (
            request.resource_type != "PERSON" or request.resource_id != request.actor_person_id
            or request.issuer_person_id != request.actor_person_id
            or request.source_grant_id != ""))
        or (request.kind == "GRANT" and (
            not request.source_grant_id or request.resource_type == "PERSON"
            and request.issuer_person_id != request.resource_id))
    ):
        raise ValueError("invalid Knowledge activation request")
    return json.dumps({
        "partition": request.partition_id, "incarnation": request.incarnation,
        "event": request.event_id, "kind": request.kind,
        "actor": request.actor_person_id, "resource_type": request.resource_type,
        "resource_id": request.resource_id, "domain": request.domain,
        "actions": sorted(request.actions), "source": request.source_grant_id,
        "issuer": request.issuer_person_id,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class HomeAuthorityStore:
    """EXECUTE-only writer and separate reader on a disposable private schema."""

    def __init__(self, socket: str, writer_password: str, reader_password: str) -> None:
        def connect(user: str, password: str) -> pymysql.Connection:
            return pymysql.connect(unix_socket=socket, user=user, password=password,
                                   database="home_auth", autocommit=True,
                                   connect_timeout=2, read_timeout=2, write_timeout=2)
        self.reader = connect("home_auth_reader", reader_password)
        self.writer = connect("home_auth_writer", writer_password)

    def current(self, partition: str) -> tuple[str, int, str]:
        self.reader.ping(reconnect=False)
        with self.reader.cursor() as cursor:
            cursor.execute("CALL home_auth.read_head(%s)", (partition,))
            row = cursor.fetchone()
            while cursor.nextset():
                pass
        if row is None:
            raise ValueError("missing Home authority partition")
        return row

    def event(self, partition: str, incarnation: str, event_id: str):
        self.reader.ping(reconnect=False)
        with self.reader.cursor() as cursor:
            cursor.execute("SELECT expected_revision,revision,digest,request_sha FROM "
                           "home_auth.events WHERE partition_id=%s AND incarnation=%s AND event_id=%s",
                           (partition, incarnation, event_id))
            return cursor.fetchone()

    def apply(self, prepared: PreparedActivation) -> tuple[int, str]:
        req = prepared.request
        self.writer.ping(reconnect=False)
        with self.writer.cursor() as cursor:
            cursor.execute("CALL home_auth.apply_event(" + ",".join(["%s"] * 15) + ")", (
                req.partition_id, req.incarnation, req.event_id,
                prepared.expected_revision, prepared.digest, prepared.request_sha,
                req.kind, req.actor_person_id, req.resource_type, req.resource_id,
                req.domain, ",".join(sorted(req.actions)), req.source_grant_id,
                req.issuer_person_id, 2,
            ))
            row = cursor.fetchone()
            while cursor.nextset():
                pass
        if row is None or row != (prepared.expected_revision + 1, prepared.digest):
            raise ValueError("Home event readback mismatch")
        return row

    def close(self) -> None:
        self.reader.close()
        self.writer.close()


class KnowledgeMutationLane:
    def __init__(self, witness: WitnessWriter, store: HomeAuthorityStore,
                 issuer_resolver: Callable[[], str],
                 grant_validator: Callable[[ActivationRequest], bool]) -> None:
        self.witness = witness
        self.store = store
        self.issuer_resolver = issuer_resolver
        self.grant_validator = grant_validator

    def prepare(self, request: ActivationRequest, expected_revision: int) -> PreparedActivation:
        request_bytes = _request_bytes(request)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("invalid revision")
        if self.issuer_resolver() != request.issuer_person_id:
            raise PermissionError("issuer is not the authenticated Person")
        if request.kind == "GRANT" and self.grant_validator(request) is not True:
            raise PermissionError("current grant or issuer dependency is unproved")
        request_sha = hashlib.sha256(request_bytes).hexdigest()
        prior = self.store.event(request.partition_id, request.incarnation, request.event_id)
        if prior:
            if prior[0] != expected_revision or prior[3] != request_sha:
                raise ValueError("conflicting event retry")
            digest = prior[2]
        else:
            incarnation, revision, before_digest = self.store.current(request.partition_id)
            if incarnation != request.incarnation or revision != expected_revision:
                raise ValueError("obsolete Home incarnation or revision")
            digest = hashlib.sha256(json.dumps({
                "previous_digest": before_digest, "expected_revision": expected_revision,
                "request_sha": request_sha,
            }, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
        self.witness.prepare(request.partition_id, request.incarnation,
                             request.event_id, expected_revision, digest)
        return PreparedActivation(request, expected_revision, digest, request_sha)

    def reauthorize(self, request: ActivationRequest,
                    expected_revision: int) -> tuple[int, str]:
        prepared = self.prepare(request, expected_revision)
        result = self.store.apply(prepared)
        self.witness.commit(request.partition_id, request.incarnation,
                            request.event_id, prepared.digest)
        return result
