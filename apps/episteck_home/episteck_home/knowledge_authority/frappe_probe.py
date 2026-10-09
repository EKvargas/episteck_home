"""Explicit bench-only Task 2 probe on a marked disposable Frappe site."""

from __future__ import annotations

import uuid
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path


class SyntheticWitness:
    """Only the policy decision is exercised here; DB witness is tested separately."""

    @staticmethod
    def authorize(partition, incarnation, revision, digest):
        return (partition, incarnation, revision, digest) == ("p1", "inc-new", 1, "digest-1")


def run() -> dict:
    import frappe

    from episteck_home.identity.actor import resolve_actor
    from episteck_home.policy.wrappers import check_access
    from episteck_home.policy.typed_access import (
        AccessRequirement, Actor, TypedGrant, TypedTarget,
    )
    from episteck_home.knowledge_authority.policy import (
        Activation, GrantEvidence, KnowledgeSnapshot, SelfActivation, evaluate_current,
    )
    from episteck_home.knowledge_authority.frappe_binding import (
        authenticated_person, current_person_grant,
    )
    from episteck_home.knowledge_authority.lane import ActivationRequest

    if not frappe.local.site.startswith("kap2-probe-") or not Path(
        frappe.get_site_path("KAP2_DISPOSABLE_SITE")
    ).is_file():
        raise RuntimeError("marked disposable site required")

    token = uuid.uuid4().hex[:12]
    owner = frappe.get_doc({
        "doctype": "User", "email": f"kap2-owner-{token}@example.invalid",
        "first_name": "Synthetic", "send_welcome_email": 0, "enabled": 1,
    }).insert(ignore_permissions=True)
    grantee = frappe.get_doc({
        "doctype": "User", "email": f"kap2-grantee-{token}@example.invalid",
        "first_name": "Synthetic", "send_welcome_email": 0, "enabled": 1,
    }).insert(ignore_permissions=True)
    owner_person = frappe.get_doc({
        "doctype": "Person", "full_name": "Synthetic Owner", "linked_user": owner.name,
    }).insert(ignore_permissions=True)
    grantee_person = frappe.get_doc({
        "doctype": "Person", "full_name": "Synthetic Grantee", "linked_user": grantee.name,
    }).insert(ignore_permissions=True)
    grant = frappe.get_doc({
        "doctype": "Consent Grant", "actor_person": grantee_person.name,
        "subject_person": owner_person.name, "domain": "KNOWLEDGE",
        "actions": "VIEW", "state": "ACTIVE", "granted_by": owner_person.name,
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    original_user = frappe.session.user
    try:
        from pymysql import MySQLError

        def canonical_dml_denied() -> bool:
            try:
                frappe.db.sql("INSERT INTO home_auth.head VALUES "
                              "('forged','forged',0,'ALLOW')")
            except MySQLError as exc:
                return bool(exc.args and exc.args[0] in {1044, 1142, 1143})
            return False

        assert canonical_dml_denied()
        frappe.set_user(owner.name)
        assert resolve_actor() == owner_person.name
        assert authenticated_person() == owner_person.name
        req = ActivationRequest("p1", "inc-new", "event-grant", "GRANT",
                                grantee_person.name, "PERSON", owner_person.name,
                                "KNOWLEDGE", frozenset({"VIEW"}), grant.name,
                                owner_person.name)
        assert current_person_grant(req, "p1") is True
        assert current_person_grant(req, "p2") is False
        frappe.db.set_value("Consent Grant", grant.name, "state", "REVOKED")
        assert current_person_grant(req, "p1") is False
        frappe.db.set_value("Consent Grant", grant.name, "state", "ACTIVE")
        assert current_person_grant(req, "p1") is True
        frappe.set_user(grantee.name)
        assert resolve_actor() == grantee_person.name
        assert current_person_grant(req, "p1") is False
        legacy_before = check_access(grantee_person.name, owner_person.name, "KNOWLEDGE", "VIEW")
        assert legacy_before["allow"] is True

        typed = TypedGrant("p1", grantee_person.name, "PERSON", owner_person.name,
                           "KNOWLEDGE", frozenset({"VIEW"}), "ACTIVE", True, True,
                           legacy=True)
        base = KnowledgeSnapshot(
            "p1", "inc-new", 1, "digest-1", Actor("p1", grantee_person.name),
            (AccessRequirement("PERSON", owner_person.name, "KNOWLEDGE", "VIEW"),),
            (TypedTarget("p1", "PERSON", owner_person.name),),
            (GrantEvidence(grant.name, owner_person.name, typed),), (), (),
            datetime.now(timezone.utc),
        )
        witness = SyntheticWitness()
        assert evaluate_current(base, witness).allow is False
        activation = Activation("inc-new", "p1", grantee_person.name, "PERSON",
                                owner_person.name, "KNOWLEDGE", frozenset({"VIEW"}),
                                grant.name, owner_person.name, "event-grant")
        assert evaluate_current(replace(base, activations=(activation,)), witness).allow is True
        assert evaluate_current(replace(base, activations=(replace(activation, incarnation="old"),)), witness).allow is False

        frappe.set_user(owner.name)
        own = replace(base, actor=Actor("p1", owner_person.name),
                      requirements=(AccessRequirement("PERSON", owner_person.name, "KNOWLEDGE", "VIEW"),),
                      targets=(TypedTarget("p1", "PERSON", owner_person.name),),
                      grants=(), activations=())
        assert evaluate_current(own, witness).allow is False
        self_activation = SelfActivation("inc-new", "p1", owner_person.name,
                                         "KNOWLEDGE", "VIEW", "event-self")
        assert evaluate_current(replace(own, self_activations=(self_activation,)), witness).allow is True
        legacy_after = check_access(grantee_person.name, owner_person.name, "KNOWLEDGE", "VIEW")
        assert legacy_after == legacy_before

        # The following is a disposable same-host end-to-end lane exercise. The
        # runner supplies synthetic recovery credentials only to this marked site.
        import pymysql
        from gateway import Gateway
        from episteck_home.knowledge_authority.lane import HomeAuthorityStore, KnowledgeMutationLane

        socket = os.environ["KAP2_DB_SOCKET"]
        with Gateway(socket=socket, lock_path=str(Path(socket).parent / "task2-gateway.lock"),
                     reader_password="synthetic-read", writer_password="synthetic-two",
                     recovery_password="synthetic-recover") as real_witness:
            incarnation = real_witness.recover("p1")
            with pymysql.connect(unix_socket=socket, user="root",
                                 password=os.environ["KAP2_DB_ROOT_PASSWORD"],
                                 autocommit=True) as root:
                with root.cursor() as cursor:
                    cursor.execute("INSERT INTO home_auth.head VALUES (%s,%s,0,'DENY_ALL')",
                                   ("p1", incarnation))
            store = HomeAuthorityStore(socket, "synthetic-home-write", "synthetic-home-read")
            try:
                lane = KnowledgeMutationLane(real_witness, store, authenticated_person,
                                             lambda request: current_person_grant(request, "p1"))
                actual_grant = replace(req, incarnation=incarnation, event_id="actual-grant")
                revision, digest = lane.reauthorize(actual_grant, 0)
                with store.reader.cursor() as cursor:
                    cursor.execute("SELECT partition_id,incarnation,event_id,kind,actor_person_id,"
                                   "resource_type,resource_id,domain,actions,source_grant_id,issuer_person_id "
                                   "FROM home_auth.activations WHERE event_id=%s", ("actual-grant",))
                    row = cursor.fetchone()
                assert row and row[3] == "GRANT"
                recorded_grant = Activation(row[1], row[0], row[4], row[5], row[6],
                                            row[7], frozenset(row[8].split(",")), row[9],
                                            row[10], row[2])
                actual_snapshot = replace(base, incarnation=incarnation,
                                          revision=revision, digest=digest,
                                          activations=(recorded_grant,))
                assert evaluate_current(actual_snapshot, real_witness).allow is True

                self_request = ActivationRequest("p1", incarnation, "actual-self", "SELF",
                                                 owner_person.name, "PERSON", owner_person.name,
                                                 "KNOWLEDGE", frozenset({"VIEW"}), "",
                                                 owner_person.name)
                self_revision, self_digest = lane.reauthorize(self_request, revision)
                with store.reader.cursor() as cursor:
                    cursor.execute("SELECT partition_id,incarnation,event_id,kind,actor_person_id,"
                                   "domain,actions FROM home_auth.activations WHERE event_id=%s",
                                   ("actual-self",))
                    self_row = cursor.fetchone()
                assert self_row and self_row[3] == "SELF" and self_row[6] == "VIEW"
                recorded_self = SelfActivation(self_row[1], self_row[0], self_row[4],
                                               self_row[5], self_row[6], self_row[2])
                own_current = replace(own, incarnation=incarnation,
                                      revision=self_revision, digest=self_digest,
                                      self_activations=(recorded_self,))
                assert evaluate_current(own_current, real_witness).allow is True
            finally:
                store.close()
        frappe.set_user("Administrator")
        assert canonical_dml_denied()
        return {
            "marked_disposable_site": True, "frappe_actor_bound": True,
            "old_grant_quarantined": True, "current_activation_allowed": True,
            "old_incarnation_denied": True, "person_self_activation_required": True,
            "existing_wrapper_unchanged": True, "witness": "synthetic policy stub",
            "current_issuer_and_grant_checked": True,
            "canonical_sql_bypass_denied": True,
            "real_local_lane_grant_and_self": True,
        }
    finally:
        frappe.set_user(original_user)
