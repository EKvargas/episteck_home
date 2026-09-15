"""Stable, actor-aware Home Control Plane business API.

Domain services and the Home Agent call these methods rather than generic DocType
resources. Relationship and consent metadata is evaluated before sensitive records
are loaded. Explicit actor ids are a synthetic G1.5 bridge only; real users require
an authoritative session-to-Person binding before G2.
"""
from __future__ import annotations

import frappe

from episteck_home.policy.access import ACTIONS, DOMAINS
from episteck_home.policy.wrappers import check_access as _check_access


def _not_found(resource: str) -> None:
    """Return the same response for missing and undiscoverable resources."""
    frappe.throw(f"{resource} not found", frappe.DoesNotExistError)


def _service_users() -> set[str]:
    configured = frappe.conf.get("home_control_plane_service_users") or []
    if isinstance(configured, str):
        configured = [value.strip() for value in configured.split(",") if value.strip()]
    return set(configured)


def _actor(actor_person_id: str | None = None) -> str:
    """Resolve the actor without treating a machine credential as a Person."""
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw("authentication required", frappe.PermissionError)

    linked_person = frappe.db.get_value("Person", {"linked_user": user}, "name")
    if linked_person:
        if actor_person_id and actor_person_id != linked_person:
            frappe.throw("actor mismatch", frappe.PermissionError)
        return linked_person

    if user not in _service_users() or not actor_person_id:
        frappe.throw("actor binding required", frappe.PermissionError)
    if not frappe.db.exists("Person", actor_person_id):
        _not_found("Person")
    return actor_person_id


def _shares_circle(actor_person_id: str, subject_person_id: str) -> bool:
    rows = frappe.get_all(
        "Circle Membership",
        filters={"person": actor_person_id},
        fields=["circle"],
    )
    return any(
        frappe.db.exists(
            "Circle Membership",
            {"circle": row["circle"], "person": subject_person_id},
        )
        for row in rows
    )


def _active_care_rows(actor_person_id: str) -> list[dict]:
    rows = frappe.get_all(
        "Care Relationship",
        filters={"caregiver_person": actor_person_id},
        fields=["subject_person", "relationship_type", "valid_from", "valid_to"],
    )
    today = frappe.utils.today()
    return [
        row
        for row in rows
        if (not row.get("valid_from") or str(row["valid_from"]) <= today)
        and (not row.get("valid_to") or str(row["valid_to"]) >= today)
    ]


def _has_care_context(actor_person_id: str, subject_person_id: str) -> bool:
    return any(
        row["subject_person"] == subject_person_id
        for row in _active_care_rows(actor_person_id)
    )


def _has_effective_access(actor_person_id: str, subject_person_id: str) -> bool:
    return any(
        _check_access(actor_person_id, subject_person_id, domain, action)["allow"]
        for domain in sorted(DOMAINS)
        for action in sorted(ACTIONS)
    )


def _can_discover_person(actor_person_id: str, subject_person_id: str) -> bool:
    if actor_person_id == subject_person_id:
        return True
    return (
        _shares_circle(actor_person_id, subject_person_id)
        or _has_care_context(actor_person_id, subject_person_id)
        or _has_effective_access(actor_person_id, subject_person_id)
    )


@frappe.whitelist()
def check_access(actor_person_id: str, subject_person_id: str, domain: str, action: str):
    """Return only the resolved actor's authorization decision and safe reason."""
    actor = _actor(actor_person_id)
    return _check_access(actor, subject_person_id, domain, action)


@frappe.whitelist()
def get_person(person_id: str, actor_person_id: str | None = None):
    actor = _actor(actor_person_id)
    if not _can_discover_person(actor, person_id):
        _not_found("Person")
    person = frappe.get_doc("Person", person_id)
    return {
        "person_id": person.name,
        "full_name": person.full_name,
        "external_ref": person.external_ref,
    }


@frappe.whitelist()
def list_my_circles(actor_person_id: str | None = None):
    actor = _actor(actor_person_id)
    rows = frappe.get_all(
        "Circle Membership", filters={"person": actor}, fields=["circle"]
    )
    circles = []
    for row in rows:
        circle = frappe.get_doc("Circle", row["circle"])
        circles.append(
            {
                "circle_id": circle.name,
                "title": circle.title,
                "circle_type": circle.circle_type,
            }
        )
    return circles


@frappe.whitelist()
def list_circle_members(circle_id: str, actor_person_id: str | None = None):
    actor = _actor(actor_person_id)
    if not frappe.db.exists(
        "Circle Membership", {"circle": circle_id, "person": actor}
    ):
        _not_found("Circle")
    rows = frappe.get_all(
        "Circle Membership",
        filters={"circle": circle_id},
        fields=["person", "role_in_circle"],
    )
    return [
        {"person_id": row["person"], "role_in_circle": row.get("role_in_circle")}
        for row in rows
    ]


@frappe.whitelist()
def list_people_i_care_for(actor_person_id: str | None = None):
    actor = _actor(actor_person_id)
    return [
        {
            "person_id": row["subject_person"],
            "relationship_type": row["relationship_type"],
        }
        for row in _active_care_rows(actor)
    ]


@frappe.whitelist()
def get_access_to_person(
    subject_person_id: str, actor_person_id: str | None = None
):
    """Return only the resolved actor's effective actions for a discoverable Person."""
    actor = _actor(actor_person_id)
    if not _can_discover_person(actor, subject_person_id):
        _not_found("Person")
    access = {}
    for domain in sorted(DOMAINS):
        allowed = [
            action
            for action in ("VIEW", "CREATE", "UPDATE", "MANAGE")
            if _check_access(actor, subject_person_id, domain, action)["allow"]
        ]
        if allowed:
            access[domain] = allowed
    return {
        "actor_person_id": actor,
        "subject_person_id": subject_person_id,
        "access": access,
    }


@frappe.whitelist()
def get_care_dashboard(actor_person_id: str | None = None):
    actor = _actor(actor_person_id)
    return {
        "actor_person_id": actor,
        "circles": list_my_circles(actor),
        "caring_for": list_people_i_care_for(actor),
    }
