"""Bench-only real Frappe probe on a marked disposable KAP-2 site."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def _marked():
    import frappe

    if not frappe.local.site.startswith("kap2-probe-person-") or not Path(
        frappe.get_site_path("KAP2_DISPOSABLE_SITE")
    ).is_file():
        raise RuntimeError("marked disposable site required")
    return frappe


def setup() -> dict:
    frappe = _marked()
    token = uuid.uuid4().hex[:10]
    owner = frappe.get_doc({
        "doctype": "User", "email": f"kap2-owner-{token}@example.invalid",
        "first_name": "Synthetic", "send_welcome_email": 0, "enabled": 1,
    }).insert(ignore_permissions=True)
    actor = frappe.get_doc({
        "doctype": "User", "email": f"kap2-actor-{token}@example.invalid",
        "first_name": "Synthetic", "send_welcome_email": 0, "enabled": 1,
    }).insert(ignore_permissions=True)
    owner_person = frappe.get_doc({
        "doctype": "Person", "full_name": "Synthetic Owner", "linked_user": owner.name,
    }).insert(ignore_permissions=True)
    actor_person = frappe.get_doc({
        "doctype": "Person", "full_name": "Synthetic Actor", "linked_user": actor.name,
    }).insert(ignore_permissions=True)
    grant = frappe.get_doc({
        "doctype": "Consent Grant", "actor_person": actor_person.name,
        "subject_person": owner_person.name, "domain": "KNOWLEDGE",
        "actions": "VIEW", "state": "ACTIVE", "granted_by": owner_person.name,
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"owner_user": owner.name, "actor_user": actor.name,
            "owner_person": owner_person.name, "actor_person": actor_person.name,
            "grant": grant.name, "database": frappe.conf.db_name}


def run() -> dict:
    frappe = _marked()
    import pymysql

    from gateway import Gateway
    from episteck_home.knowledge_authority.integrated import PersonAuthority
    from episteck_home.policy.typed_access import AccessRequirement
    from episteck_home.policy.wrappers import check_access
    from episteck_home.identity.session import open_session, close_session

    class FrappeBinding:
        def site_name(self) -> str:
            return frappe.local.site

        def service_name(self) -> str:
            return "home-probe"

        def user_name(self) -> str:
            return frappe.session.user

    owner_user = os.environ["KAP2_OWNER_USER"]
    actor_user = os.environ["KAP2_ACTOR_USER"]
    owner_person = os.environ["KAP2_OWNER_PERSON"]
    actor_person = os.environ["KAP2_ACTOR_PERSON"]
    grant = os.environ["KAP2_GRANT"]
    req = (AccessRequirement("PERSON", owner_person, "KNOWLEDGE", "VIEW"),)
    socket = os.environ["KAP2_DB_SOCKET"]
    witness_socket = os.environ["KAP2_WITNESS_SOCKET"]
    original_user = frappe.session.user
    output = {}
    gateway = Gateway(socket=witness_socket,
                      lock_path=str(Path(witness_socket).parent / "person-flock"),
                      reader_password="synthetic-read", writer_password="synthetic-two",
                      recovery_password="synthetic-recover")
    authority = PersonAuthority(home_socket=socket, witness=gateway,
                                binding=FrappeBinding(),
                                reader_password="synthetic-reader",
                                mutator_password="synthetic-mutator")
    try:
        frappe.set_user(actor_user)
        old_api = check_access(actor_person, owner_person, "KNOWLEDGE", "VIEW")
        assert old_api["allow"] is True
        assert authority.authorize(req).allow is False
        output["first_read_closed"] = True
        authority.recover(recovery_password="synthetic-home-recover")
        assert authority.authorize(req).allow is False
        frappe.set_user(owner_user)
        authority.activate_grant(grant, "frappe-grant")
        frappe.set_user(actor_user)
        assert authority.authorize(req).allow is True
        output["authenticated_grant"] = True
        frappe.set_user(owner_user)
        authority.activate_self("KNOWLEDGE", "VIEW", "frappe-self")
        assert authority.authorize(req).allow is True
        output["person_self"] = True

        # Real Frappe document, set_value and raw SQL paths run through the
        # site principal, including Administrator and ignore_permissions.
        def rejected(operation) -> bool:
            try:
                operation()
                frappe.db.rollback()
                return False
            except pymysql.MySQLError as exc:
                frappe.db.rollback()
                return "KAP2_PERSON_GUARD" in str(exc)

        frappe.set_user("Administrator")
        doc = frappe.get_doc("Consent Grant", grant)
        doc.state = "REVOKED"
        assert rejected(lambda: doc.save(ignore_permissions=True))
        assert rejected(lambda: frappe.db.set_value("Consent Grant", grant, "state", "REVOKED"))
        assert rejected(lambda: frappe.db.sql(
            "UPDATE `tabConsent Grant` SET state='REVOKED' WHERE name=%s", grant))
        assert rejected(lambda: frappe.get_doc("Consent Grant", grant).delete(ignore_permissions=True))
        assert rejected(lambda: frappe.db.set_value("Person", owner_person, "linked_user", None))
        assert rejected(lambda: frappe.db.set_value("User", owner_user, "enabled", 0))
        output["frappe_generic_writes_denied"] = True

        with pymysql.connect(unix_socket=socket, user="ha_mutator",
                             password="synthetic-mutator",
                             database=frappe.conf.db_name, autocommit=True) as serving:
            with serving.cursor() as cursor:
                for statement in (
                    "SELECT name FROM `tabDocType` LIMIT 1",
                    "UPDATE home_auth.head SET digest='FORGED' WHERE partition_id='p1'",
                    "UPDATE `tabConsent Grant` SET state='REVOKED' WHERE name=%s",
                ):
                    try:
                        cursor.execute(statement, (grant,) if "%s" in statement else None)
                    except pymysql.MySQLError as exc:
                        assert exc.args[0] in {1044, 1142, 1143}
                    else:
                        raise AssertionError("restricted serving principal bypassed a grant")
        output["serving_privileges_narrow"] = True

        # The site principal retains ordinary, unrelated Home data writes.
        frappe.db.set_value("Person", actor_person, "notes", "synthetic ordinary note")
        assert frappe.db.get_value("Person", actor_person, "notes") == "synthetic ordinary note"
        frappe.db.commit()
        output["ordinary_person_write"] = True
        frappe.set_user(actor_user)
        assert check_access(actor_person, owner_person, "KNOWLEDGE", "VIEW") == old_api
        assert authority.authorize(req).allow is True
        session = open_session(client="kap2-person-disposable")
        assert session["session_id"]
        assert close_session(session["session_id"]) == {"closed": True}
        output["existing_api_unchanged"] = True
        output["ordinary_session_lifecycle"] = True
        frappe.set_user(owner_user)
        authority.recover(recovery_password="synthetic-home-recover")
        assert authority.authorize(req).allow is False
        frappe.set_user(actor_user)
        assert authority.authorize(req).allow is False
        frappe.set_user(owner_user)
        authority.activate_grant(grant, "frappe-fresh-grant")
        assert authority.authorize(req).allow is False  # old self activation is quarantined
        authority.activate_self("KNOWLEDGE", "VIEW", "frappe-fresh-self")
        assert authority.authorize(req).allow is True
        frappe.set_user(actor_user)
        assert authority.authorize(req).allow is True
        output["fresh_incarnation_selected_reauthorization"] = True
        return output
    finally:
        authority.close()
        gateway.close()
        frappe.set_user(original_user)
