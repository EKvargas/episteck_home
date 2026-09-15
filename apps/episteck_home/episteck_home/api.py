"""Stable Home Core API — the CONTRACT domain services + Home Agent depend on.
Domain services must NOT call /api/resource/<DocType> directly; they call these.
All are @frappe.whitelist(); cross-person data access always runs through check_access.
"""
from __future__ import annotations
import frappe
from episteck_home.policy.wrappers import check_access as _check_access


def _actor() -> str:
    """Resolve the acting Person from the session user. The Home Agent acts on behalf
    of an actor_person_id; here we map the logged-in User to their Person."""
    user = frappe.session.user
    person = frappe.db.get_value("Person", {"linked_user": user}, "name")
    if not person:
        frappe.throw("no Person linked to current user")
    return person


@frappe.whitelist()
def check_access(actor_person_id: str, subject_person_id: str, domain: str, action: str):
    """Authorization decision. Business-safe: returns allow/reason only."""
    return _check_access(actor_person_id, subject_person_id, domain, action)


@frappe.whitelist()
def get_person(person_id: str):
    p = frappe.get_doc("Person", person_id)
    return {"person_id": p.name, "full_name": p.full_name, "external_ref": p.external_ref}


@frappe.whitelist()
def list_my_circles():
    actor = _actor()
    rows = frappe.get_all("Circle Membership", filters={"person": actor}, fields=["circle"])
    out = []
    for r in rows:
        c = frappe.get_doc("Circle", r["circle"])
        out.append({"circle_id": c.name, "title": c.title, "circle_type": c.circle_type})
    return out


@frappe.whitelist()
def list_circle_members(circle_id: str):
    rows = frappe.get_all("Circle Membership", filters={"circle": circle_id}, fields=["person", "role_in_circle"])
    return [{"person_id": r["person"], "role_in_circle": r.get("role_in_circle")} for r in rows]


@frappe.whitelist()
def list_people_i_care_for():
    actor = _actor()
    rows = frappe.get_all("Care Relationship", filters={"caregiver_person": actor},
                          fields=["subject_person", "relationship_type"])
    return [{"person_id": r["subject_person"], "relationship_type": r["relationship_type"]} for r in rows]


@frappe.whitelist()
def get_access_to_person(subject_person_id: str):
    """What CAN the actor do for this subject, per domain? Runs check_access per domain."""
    actor = _actor()
    domains = ["NUTRITION", "HEALTH", "CALENDAR", "DOCUMENTS", "FINANCE", "MIND", "HOUSEHOLD", "KNOWLEDGE"]
    result = {}
    for dom in domains:
        allowed = [a for a in ("VIEW", "CREATE", "UPDATE", "MANAGE")
                   if _check_access(actor, subject_person_id, dom, a)["allow"]]
        if allowed:
            result[dom] = allowed
    return {"actor_person_id": actor, "subject_person_id": subject_person_id, "access": result}


@frappe.whitelist()
def get_care_dashboard():
    """Summary for the acting person: their circles + who they care for + access map."""
    actor = _actor()
    return {
        "actor_person_id": actor,
        "circles": list_my_circles(),
        "caring_for": list_people_i_care_for(),
    }
