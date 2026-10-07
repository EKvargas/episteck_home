"""Observe authority write paths on an explicitly marked disposable Frappe site.

Run only with: bench --site kap2-probe-... execute episteck_home.probes.kap2_frappe.run
The site must contain sites/<site>/KAP2_DISPOSABLE_SITE. No production site qualifies.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path


def run() -> dict:
    import frappe

    site = frappe.local.site
    marker = Path(frappe.get_site_path("KAP2_DISPOSABLE_SITE"))
    if not site.startswith("kap2-probe-") or not marker.is_file():
        raise RuntimeError("KAP-2 probe requires a marked disposable site")
    if not frappe.db.exists("DocType", "Consent Grant"):
        raise RuntimeError("episteck_home DocTypes are not installed on disposable site")

    token = uuid.uuid4().hex[:12]
    result: dict[str, object] = {"probe": "frappe_authority_paths", "site": "marked_disposable", "observations": {}}
    observations: dict[str, object] = result["observations"]  # type: ignore[assignment]
    savepoint = f"kap2_{token}"
    original_user = frappe.session.user
    frappe.db.savepoint(savepoint)

    def observe(name: str, action, read) -> None:
        before = read()
        action_savepoint = f"kap2_action_{len(observations)}"
        frappe.db.savepoint(action_savepoint)
        try:
            action()
            after = read()
            observations[name] = {"permitted": True, "changed": before != after}
        except Exception as exc:
            observations[name] = {"permitted": False, "error_type": type(exc).__name__}
            frappe.db.rollback(save_point=action_savepoint)

    def save_field(doctype: str, name: str, field: str, value, *, ignore_permissions: bool = True) -> None:
        row = frappe.get_doc(doctype, name)
        setattr(row, field, value)
        row.save(ignore_permissions=ignore_permissions)

    try:
        user = frappe.get_doc({
            "doctype": "User", "email": f"kap2-{token}@example.invalid",
            "first_name": "KAP2", "send_welcome_email": 0, "enabled": 1,
        }).insert(ignore_permissions=True)
        other = frappe.get_doc({
            "doctype": "User", "email": f"kap2-other-{token}@example.invalid",
            "first_name": "KAP2", "send_welcome_email": 0, "enabled": 1,
        }).insert(ignore_permissions=True)
        person = frappe.get_doc({"doctype": "Person", "full_name": f"Synthetic {token}", "linked_user": user.name}).insert(ignore_permissions=True)
        subject = frappe.get_doc({"doctype": "Person", "full_name": f"Subject {token}"}).insert(ignore_permissions=True)
        circle = frappe.get_doc({"doctype": "Circle", "title": f"Synthetic {token}", "circle_type": "FAMILY"}).insert(ignore_permissions=True)
        membership = frappe.get_doc({"doctype": "Circle Membership", "circle": circle.name, "person": person.name}).insert(ignore_permissions=True)
        grant = frappe.get_doc({
            "doctype": "Consent Grant", "actor_person": person.name,
            "subject_person": subject.name, "domain": "KNOWLEDGE",
            "actions": "VIEW", "state": "ACTIVE", "granted_by": user.name,
        }).insert(ignore_permissions=True)
        session = frappe.get_doc({
            "doctype": "Home Delegated Session", "user": user.name,
            "status": "Active", "expires_at": "2099-01-01 00:00:00",
        }).insert(ignore_permissions=True)

        get = frappe.db.get_value
        from episteck_home.policy.wrappers import check_access
        def legacy_allows() -> bool:
            return check_access(person.name, subject.name, "KNOWLEDGE", "VIEW")["allow"]

        observations["legacy_wrapper_initial_allow"] = legacy_allows()
        observe("user_disable_save", lambda: save_field("User", user.name, "enabled", 0),
                lambda: get("User", user.name, "enabled"))
        observe("user_reenable_set_value", lambda: frappe.db.set_value("User", user.name, "enabled", 1),
                lambda: get("User", user.name, "enabled"))
        observe("user_disable_raw_sql", lambda: frappe.db.sql("UPDATE `tabUser` SET enabled=0 WHERE name=%s", user.name),
                lambda: get("User", user.name, "enabled"))
        frappe.set_user("Administrator")
        observe("admin_user_reenable_save", lambda: save_field("User", user.name, "enabled", 1, ignore_permissions=False),
                lambda: get("User", user.name, "enabled"))

        observe("person_relink_save", lambda: save_field("Person", person.name, "linked_user", other.name),
                lambda: get("Person", person.name, "linked_user"))
        observe("person_relink_set_value", lambda: frappe.db.set_value("Person", person.name, "linked_user", user.name),
                lambda: get("Person", person.name, "linked_user"))
        observe("person_unlink_raw_sql", lambda: frappe.db.sql("UPDATE `tabPerson` SET linked_user=NULL WHERE name=%s", person.name),
                lambda: get("Person", person.name, "linked_user"))

        observe("session_revoke_controller", lambda: frappe.get_doc("Home Delegated Session", session.name).revoke(),
                lambda: get("Home Delegated Session", session.name, "status"))
        observe("session_reenable_raw_sql", lambda: frappe.db.sql("UPDATE `tabHome Delegated Session` SET status='Active' WHERE name=%s", session.name),
                lambda: get("Home Delegated Session", session.name, "status"))
        observe("session_revoke_set_value", lambda: frappe.db.set_value("Home Delegated Session", session.name, "status", "Revoked"),
                lambda: get("Home Delegated Session", session.name, "status"))
        observe("grant_revoke_save", lambda: save_field("Consent Grant", grant.name, "state", "REVOKED"),
                lambda: get("Consent Grant", grant.name, "state"))
        observations["legacy_wrapper_after_revocation"] = legacy_allows()
        observe("grant_reenable_set_value", lambda: frappe.db.set_value("Consent Grant", grant.name, "state", "ACTIVE"),
                lambda: get("Consent Grant", grant.name, "state"))
        observations["legacy_wrapper_after_set_value"] = legacy_allows()
        observe("grant_revoke_raw_sql", lambda: frappe.db.sql("UPDATE `tabConsent Grant` SET state='REVOKED' WHERE name=%s", grant.name),
                lambda: get("Consent Grant", grant.name, "state"))
        observations["legacy_wrapper_after_raw_sql"] = legacy_allows()
        observe("admin_grant_reenable_save", lambda: save_field("Consent Grant", grant.name, "state", "ACTIVE", ignore_permissions=False),
                lambda: get("Consent Grant", grant.name, "state"))

        observe("ordinary_person_note_save", lambda: save_field("Person", person.name, "notes", "synthetic note"),
                lambda: get("Person", person.name, "notes"))
        observe("ordinary_user_name_save", lambda: save_field("User", user.name, "first_name", "Probe"),
                lambda: get("User", user.name, "first_name"))
        observe("ordinary_circle_note_save", lambda: save_field("Circle", circle.name, "notes", "synthetic note"),
                lambda: get("Circle", circle.name, "notes"))
        observe("circle_exit_membership_delete", lambda: membership.delete(ignore_permissions=True),
                lambda: frappe.db.exists("Circle Membership", membership.name))
        observations["legacy_grant_after_circle_exit"] = get("Consent Grant", grant.name, "state")
        observe("circle_target_delete", lambda: circle.delete(ignore_permissions=True),
                lambda: frappe.db.exists("Circle", circle.name))
        observe("grant_delete", lambda: frappe.get_doc("Consent Grant", grant.name).delete(ignore_permissions=True),
                lambda: frappe.db.exists("Consent Grant", grant.name))
        observe("ordinary_user_read", lambda: frappe.get_doc("User", user.name),
                lambda: frappe.db.exists("User", user.name))
        observe("ordinary_person_read", lambda: frappe.get_doc("Person", person.name),
                lambda: frappe.db.exists("Person", person.name))
        result["canonical_guard_verified"] = False  # No KAP-2 protected schema exists yet.
        return result
    finally:
        frappe.set_user(original_user)
        frappe.db.rollback(save_point=savepoint)
        print(json.dumps(result, sort_keys=True, default=str))
