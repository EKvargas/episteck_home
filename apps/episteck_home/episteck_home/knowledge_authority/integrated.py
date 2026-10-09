"""Disposable, disconnected KAP-2 PERSON authorization vertical.

One pinned Home MariaDB advisory lane spans each whole decision or mutation.
No hook, endpoint or persistent credential imports this candidate.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator, Protocol

import pymysql

from episteck_home.policy.access import Decision
from episteck_home.policy.access import ACTIONS, DOMAINS
from episteck_home.policy.typed_access import AccessRequirement, Actor, TypedGrant, TypedTarget

from .policy import (
    Activation, GrantEvidence, KnowledgeSnapshot, SelfActivation, evaluate_current,
)


class TrustedBinding(Protocol):
    def site_name(self) -> str: ...
    def service_name(self) -> str: ...
    def user_name(self) -> str: ...


@dataclass(frozen=True)
class _Site:
    partition: str
    database: str


class PersonAuthority:
    """A local integration unit, not a production admission interface."""

    def __init__(self, *, home_socket: str, witness, binding: TrustedBinding,
                 reader_password: str, mutator_password: str,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.witness = witness
        self.binding = binding
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.reader = pymysql.connect(unix_socket=home_socket, user="ha_reader",
                                      password=reader_password, database="home_auth",
                                      autocommit=True, connect_timeout=2,
                                      read_timeout=2, write_timeout=2)
        self.mutator = pymysql.connect(unix_socket=home_socket, user="ha_mutator",
                                       password=mutator_password, database="home_auth",
                                       autocommit=True, connect_timeout=2,
                                       read_timeout=2, write_timeout=2)
        self.open = False

    def _site(self, conn: pymysql.Connection) -> _Site:
        site_name, service_name = self.binding.site_name(), self.binding.service_name()
        if type(site_name) is not str or type(service_name) is not str:
            raise PermissionError("untrusted Home site or service")
        with conn.cursor() as cursor:
            cursor.execute("SELECT partition_id,site_database,service_name,active "
                           "FROM home_auth.binding WHERE site_name=%s", (site_name,))
            row = cursor.fetchone()
        if (not row or row[2] != service_name or row[3] != 1
                or type(row[0]) is not str or not row[0]
                or not re.fullmatch(r"_[0-9a-f]{16}", row[1])):
            raise PermissionError("unbound Home site or service")
        return _Site(row[0], row[1])

    @staticmethod
    def _lane_name(partition: str) -> str:
        return "kap2_person_" + hashlib.sha256(partition.encode("utf-8")).hexdigest()[:40]

    @contextmanager
    def _lane(self, conn: pymysql.Connection, site: _Site) -> Iterator[None]:
        name = self._lane_name(site.partition)
        conn.ping(reconnect=False)
        with conn.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s,5)", (name,))
            if cursor.fetchone() != (1,):
                raise TimeoutError("Home partition lane unavailable")
        try:
            self._assert_lane(conn, name)
            yield
        except (pymysql.MySQLError, TimeoutError):
            self.open = False
            raise
        finally:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
                    if cursor.fetchone() != (1,):
                        self.open = False
            except pymysql.MySQLError:
                self.open = False

    def _assert_lane(self, conn: pymysql.Connection, name: str) -> None:
        conn.ping(reconnect=False)
        with conn.cursor() as cursor:
            cursor.execute("SELECT IS_USED_LOCK(%s),CONNECTION_ID()", (name,))
            owner, current = cursor.fetchone()
        if owner != current:
            self.open = False
            raise RuntimeError("Home partition lane ownership lost")

    @staticmethod
    def _person_binding(conn: pymysql.Connection, db: str, person: str) -> tuple[str | None, int | None]:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT linked_user FROM `{db}`.`tabPerson` WHERE name=%s", (person,))
            row = cursor.fetchone()
            if not row or not row[0]:
                return None, None
            cursor.execute(f"SELECT enabled FROM `{db}`.`tabUser` WHERE name=%s", (row[0],))
            user = cursor.fetchone()
        return row[0], user[0] if user else None

    def _actor(self, conn: pymysql.Connection, site: _Site) -> str:
        user = self.binding.user_name()
        if type(user) is not str or not user or user == "Guest":
            raise PermissionError("authenticated Home human required")
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT enabled FROM `{site.database}`.`tabUser` WHERE name=%s", (user,))
            enabled = cursor.fetchone()
            cursor.execute(f"SELECT name FROM `{site.database}`.`tabPerson` WHERE linked_user=%s", (user,))
            people = cursor.fetchall()
        if not enabled or enabled[0] != 1 or len(people) != 1:
            raise PermissionError("enabled unique Person binding required")
        return people[0][0]

    @staticmethod
    def _head(conn: pymysql.Connection, partition: str) -> tuple[str, int, str]:
        with conn.cursor() as cursor:
            cursor.execute("SELECT incarnation,revision,digest FROM home_auth.head "
                           "WHERE partition_id=%s", (partition,))
            row = cursor.fetchone()
        if not row:
            raise RuntimeError("missing protected Home partition")
        return row

    def _state(self, conn: pymysql.Connection, site: _Site, incarnation: str,
               revision: int) -> tuple[str, tuple[GrantEvidence, ...],
                                       tuple[Activation, ...], tuple[SelfActivation, ...]]:
        with conn.cursor() as cursor:
            cursor.execute("SELECT event_id,kind,actor_person_id,resource_id,domain,action,"
                           "source_grant_id,issuer_person_id FROM home_auth.activations "
                           "WHERE partition_id=%s AND incarnation=%s ORDER BY event_id",
                           (site.partition, incarnation))
            rows = cursor.fetchall()
        canonical: list[dict] = []
        grants: list[GrantEvidence] = []
        activations: list[Activation] = []
        self_activations: list[SelfActivation] = []
        for event_id, kind, actor_id, target_id, domain, action, grant_id, issuer_id in rows:
            actor_user, actor_enabled = self._person_binding(conn, site.database, actor_id)
            target_user, target_enabled = self._person_binding(conn, site.database, target_id)
            item = {"event": event_id, "kind": kind, "actor": actor_id, "target": target_id,
                    "domain": domain, "action": action, "source": grant_id, "issuer": issuer_id,
                    "actor_user": actor_user, "actor_enabled": actor_enabled,
                    "target_user": target_user, "target_enabled": target_enabled}
            if kind == "SELF":
                self_activations.append(SelfActivation(
                    incarnation, site.partition, actor_id, domain, action, event_id))
            elif kind == "GRANT":
                with conn.cursor() as cursor:
                    cursor.execute(f"SELECT actor_person,subject_person,domain,actions,state,"
                                   f"valid_from,valid_until,granted_by FROM `{site.database}`.`tabConsent Grant` "
                                   "WHERE name=%s", (grant_id,))
                    source = cursor.fetchone()
                    cursor.execute("SELECT current_state FROM home_auth.dependency "
                                   "WHERE partition_id=%s AND grant_id=%s",
                                   (site.partition, grant_id))
                    dependency = cursor.fetchone()
                source_values = [value.isoformat() if isinstance(value, datetime) else value
                                 for value in source] if source else None
                item["source_values"] = source_values
                item["dependency"] = dependency[0] if dependency else None
                source_matches = bool(source and source[0] == actor_id and source[1] == target_id
                                      and source[2] == domain and source[7] == issuer_id
                                      and action in self._actions(source[3]))
                valid_from = source[5].replace(tzinfo=timezone.utc) if source and source[5] else None
                valid_until = source[6].replace(tzinfo=timezone.utc) if source and source[6] else None
                typed = TypedGrant(
                    site.partition, actor_id, "PERSON", target_id, domain,
                    frozenset(self._actions(source[3]))
                    if source else frozenset(),
                    source[4] if source and source_matches else "REVOKED",
                    issuer_verified=bool(issuer_id == target_id and target_user and target_enabled == 1),
                    dependency_current=bool(dependency and dependency[0] == 1
                                            and actor_user and actor_enabled == 1),
                    valid_from=valid_from, valid_until=valid_until, legacy=True,
                )
                grants.append(GrantEvidence(grant_id, issuer_id, typed))
                activations.append(Activation(
                    incarnation, site.partition, actor_id, "PERSON", target_id,
                    domain, frozenset({action}), grant_id, issuer_id, event_id))
            else:
                raise RuntimeError("unknown protected activation kind")
            canonical.append(item)
        if not canonical:
            digest = "DENY_ALL"
        else:
            payload = {"version": 1, "partition": site.partition,
                       "incarnation": incarnation, "revision": revision,
                       "activations": canonical}
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                               ensure_ascii=True).encode("ascii")).hexdigest()
        return digest, tuple(grants), tuple(activations), tuple(self_activations)

    @staticmethod
    def _actions(value: str | None) -> frozenset[str]:
        return frozenset(action.strip() for action in (value or "").replace("\n", ",").split(",")
                         if action.strip())

    def recover(self) -> str:
        self.open = False
        site = self._site(self.mutator)
        with self._lane(self.mutator, site):
            incarnation = self.witness.recover(site.partition)
            self.mutator.begin()
            try:
                with self.mutator.cursor() as cursor:
                    cursor.execute("UPDATE home_auth.head SET incarnation=%s,revision=0,digest='DENY_ALL' "
                                   "WHERE partition_id=%s", (incarnation, site.partition))
                self.mutator.commit()
            except Exception:
                self.mutator.rollback()
                raise
            home = self._head(self.mutator, site.partition)
            witness_row = self.witness._read_current(site.partition)
            if home != (incarnation, 0, "DENY_ALL") or witness_row != (
                incarnation, 0, 2, 2, "COMMITTED", None, "DENY_ALL"
            ):
                raise RuntimeError("fresh default-deny Home/witness readback failed")
        self.open = True
        return incarnation

    def authorize(self, requirements: tuple[AccessRequirement, ...], *,
                  caller_partition: str | None = None,
                  caller_actor: str | None = None) -> Decision:
        deny = Decision(False, "unverified protected Home authority")
        if not self.open or type(requirements) is not tuple or not requirements:
            return deny
        try:
            site = self._site(self.reader)
            if (caller_partition is not None and caller_partition != site.partition):
                return deny
            with self._lane(self.reader, site):
                self.reader.begin()
                try:
                    actor_id = self._actor(self.reader, site)
                    if caller_actor is not None and caller_actor != actor_id:
                        return deny
                    incarnation, revision, stored_digest = self._head(self.reader, site.partition)
                    digest, grants, activations, selves = self._state(
                        self.reader, site, incarnation, revision)
                    if digest != stored_digest:
                        return deny
                    targets: list[TypedTarget] = []
                    with self.reader.cursor() as cursor:
                        for requirement in requirements:
                            if not isinstance(requirement, AccessRequirement) or requirement.resource_type != "PERSON":
                                return deny
                            cursor.execute(f"SELECT 1 FROM `{site.database}`.`tabPerson` WHERE name=%s",
                                           (requirement.resource_id,))
                            targets.append(TypedTarget(site.partition, "PERSON", requirement.resource_id,
                                                       cursor.fetchone() is not None))
                    self._assert_lane(self.reader, self._lane_name(site.partition))
                    snapshot = KnowledgeSnapshot(
                        site.partition, incarnation, revision, digest,
                        Actor(site.partition, actor_id), requirements, tuple(targets),
                        grants, activations, selves, self.clock())
                    return evaluate_current(snapshot, self.witness)
                finally:
                    self.reader.rollback()
        except (PermissionError, ValueError):
            return deny
        except Exception:
            self.open = False
            return deny

    def _mutate(self, kind: str, source: str, event_id: str, *, domain: str = "KNOWLEDGE",
                action: str = "VIEW", caller_partition: str | None = None,
                caller_issuer: str | None = None) -> tuple[int, str]:
        if not self.open:
            raise RuntimeError("Knowledge admission is closed")
        if (type(event_id) is not str or not event_id or type(domain) is not str
                or domain not in DOMAINS or type(action) is not str or action not in ACTIONS):
            raise ValueError("invalid exact authority event")
        site = self._site(self.mutator)
        if caller_partition is not None and caller_partition != site.partition:
            raise PermissionError("caller partition disagrees with trusted Home binding")
        with self._lane(self.mutator, site):
            self.mutator.begin()
            home_committed = False
            try:
                issuer = self._actor(self.mutator, site)
                if caller_issuer is not None and caller_issuer != issuer:
                    raise PermissionError("caller issuer disagrees with authenticated Person")
                incarnation, revision, _ = self._head(self.mutator, site.partition)
                with self.mutator.cursor() as cursor:
                    cursor.execute("SELECT request_sha,revision,digest,kind FROM home_auth.events "
                                   "WHERE partition_id=%s AND incarnation=%s AND event_id=%s",
                                   (site.partition, incarnation, event_id))
                    prior = cursor.fetchone()
                request_sha = hashlib.sha256(json.dumps({
                    "kind": kind, "source": source, "issuer": issuer,
                    "domain": domain, "action": action,
                }, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
                if prior:
                    if prior[0] != request_sha or prior[3] != kind:
                        raise ValueError("conflicting exact event retry")
                    self.mutator.rollback()
                    self.witness.prepare(site.partition, incarnation, event_id,
                                         prior[1] - 1, prior[2])
                    self.witness.commit(site.partition, incarnation, event_id, prior[2])
                    return prior[1], prior[2]
                with self.mutator.cursor() as cursor:
                    if kind == "GRANT":
                        cursor.execute(f"SELECT actor_person,subject_person,domain,actions,state,"
                                       f"valid_from,valid_until,granted_by FROM `{site.database}`.`tabConsent Grant` "
                                       "WHERE name=%s", (source,))
                        grant = cursor.fetchone()
                        if (not grant or grant[1] != issuer or grant[2] != domain
                                or grant[7] != issuer
                                or grant[4] != "ACTIVE" or action not in self._actions(grant[3])
                                or (grant[5] and self.clock() < grant[5].replace(tzinfo=timezone.utc))
                                or (grant[6] and self.clock() > grant[6].replace(tzinfo=timezone.utc))):
                            raise PermissionError("current exact issuer/grant proof absent")
                        cursor.execute("SELECT current_state FROM home_auth.dependency "
                                       "WHERE partition_id=%s AND grant_id=%s", (site.partition, source))
                        dependency = cursor.fetchone()
                        if not dependency or dependency[0] != 1:
                            raise PermissionError("grant dependency is not current")
                        cursor.execute("INSERT INTO home_auth.activations VALUES "
                                       "(%s,%s,%s,'GRANT',%s,%s,%s,%s,%s,%s)",
                                       (site.partition, incarnation, event_id, grant[0], grant[1],
                                        domain, action, source, issuer))
                    elif kind == "SELF":
                        cursor.execute("INSERT INTO home_auth.activations VALUES "
                                       "(%s,%s,%s,'SELF',%s,%s,%s,%s,'',%s)",
                                       (site.partition, incarnation, event_id, issuer, issuer,
                                        domain, action, issuer))
                    elif kind in {"REVOKE", "DEPENDENCY_OFF"}:
                        cursor.execute(f"SELECT subject_person FROM `{site.database}`.`tabConsent Grant` "
                                       "WHERE name=%s", (source,))
                        owner = cursor.fetchone()
                        if not owner or owner[0] != issuer:
                            raise PermissionError("current grant issuer required")
                        if kind == "REVOKE":
                            cursor.execute(f"UPDATE `{site.database}`.`tabConsent Grant` "
                                           "SET state='REVOKED' WHERE name=%s", (source,))
                        else:
                            cursor.execute("UPDATE home_auth.dependency SET current_state=0 "
                                           "WHERE partition_id=%s AND grant_id=%s",
                                           (site.partition, source))
                            if cursor.rowcount != 1:
                                raise PermissionError("current dependency absent")
                    elif kind == "DISABLE_ISSUER":
                        if source != self.binding.user_name():
                            raise PermissionError("issuer may only disable own bound User")
                        cursor.execute(f"UPDATE `{site.database}`.`tabUser` SET enabled=0 WHERE name=%s",
                                       (source,))
                        if cursor.rowcount != 1:
                            raise PermissionError("issuer User absent")
                    elif kind == "UNLINK_ISSUER":
                        if source != issuer:
                            raise PermissionError("issuer may only unlink own Person")
                        cursor.execute(f"UPDATE `{site.database}`.`tabPerson` SET linked_user=NULL "
                                       "WHERE name=%s", (issuer,))
                        if cursor.rowcount != 1:
                            raise PermissionError("issuer Person binding absent")
                    else:
                        raise ValueError("unsupported authority mutation")
                    next_revision = revision + 1
                    digest, _, _, _ = self._state(self.mutator, site, incarnation, next_revision)
                    cursor.execute("UPDATE home_auth.head SET revision=%s,digest=%s "
                                   "WHERE partition_id=%s", (next_revision, digest, site.partition))
                    cursor.execute("INSERT INTO home_auth.events VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                   (site.partition, incarnation, event_id, request_sha,
                                    next_revision, digest, kind))
                self._assert_lane(self.mutator, self._lane_name(site.partition))
                self.witness.prepare(site.partition, incarnation, event_id, revision, digest)
                self.mutator.commit()
                home_committed = True
                self._assert_lane(self.mutator, self._lane_name(site.partition))
                self.witness.commit(site.partition, incarnation, event_id, digest)
                return next_revision, digest
            except (PermissionError, ValueError):
                if not home_committed:
                    self.mutator.rollback()
                raise
            except Exception:
                if not home_committed:
                    self.mutator.rollback()
                self.open = False
                raise

    def activate_grant(self, grant_id: str, event_id: str, *,
                       caller_partition: str | None = None,
                       caller_issuer: str | None = None) -> tuple[int, str]:
        return self._mutate("GRANT", grant_id, event_id,
                            caller_partition=caller_partition, caller_issuer=caller_issuer)

    def activate_self(self, domain: str, action: str, event_id: str, *,
                      caller_partition: str | None = None,
                      caller_issuer: str | None = None) -> tuple[int, str]:
        return self._mutate("SELF", "", event_id, domain=domain, action=action,
                            caller_partition=caller_partition, caller_issuer=caller_issuer)

    def revoke_grant(self, grant_id: str, event_id: str) -> tuple[int, str]:
        return self._mutate("REVOKE", grant_id, event_id)

    def invalidate_dependency(self, grant_id: str, event_id: str) -> tuple[int, str]:
        return self._mutate("DEPENDENCY_OFF", grant_id, event_id)

    def disable_issuer(self, user_name: str, event_id: str) -> tuple[int, str]:
        return self._mutate("DISABLE_ISSUER", user_name, event_id)

    def unlink_issuer(self, person_id: str, event_id: str) -> tuple[int, str]:
        return self._mutate("UNLINK_ISSUER", person_id, event_id)

    def close(self) -> None:
        self.open = False
        self.reader.close()
        self.mutator.close()
