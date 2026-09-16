"""Stable, trusted-actor Home Control Plane business API (G1.6).

Domain services and the Home Agent call these methods rather than generic DocType
resources. Relationship and consent metadata is evaluated before sensitive records
are loaded.

TRUSTED ACTOR INVARIANT (G1.6)
------------------------------
``actor_person_id`` is NEVER a parameter of any method here. The acting Person is
derived server-side from validated authentication context:

    validated authentication -> Frappe User -> Person.linked_user -> actor

Neither ``actor_person_id`` nor ``User.name`` is ever a caller assertion. A caller
cannot express an actor, so actor substitution is not merely blocked — it is
unrepresentable. ``subject_person_id`` remains a parameter because the user is
legitimately asking about that person; it is still gated by ``can_access``.
"""
from __future__ import annotations

import frappe

from episteck_home.identity.actor import resolve_actor, resolve_principals
from episteck_home.policy.access import ACTIONS, DOMAINS
from episteck_home.policy.wrappers import check_access as _check_access


def _not_found(resource: str) -> None:
    """Return the same response for missing and undiscoverable resources."""
    frappe.throw(f"{resource} not found", frappe.DoesNotExistError)


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
def check_access(subject_person_id: str, domain: str, action: str):
    """Return the trusted actor's authorization decision and safe reason.

    The actor is resolved server-side; a caller cannot name one.
    """
    actor = resolve_actor()
    return _check_access(actor, subject_person_id, domain, action)


@frappe.whitelist()
def get_person(person_id: str):
    actor = resolve_actor()
    if not _can_discover_person(actor, person_id):
        _not_found("Person")
    person = frappe.get_doc("Person", person_id)
    return {
        "person_id": person.name,
        "full_name": person.full_name,
        "external_ref": person.external_ref,
    }


@frappe.whitelist()
def list_my_circles():
    actor = resolve_actor()
    return _circles_for(actor)


def _circles_for(actor: str) -> list[dict]:
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
def list_circle_members(circle_id: str):
    actor = resolve_actor()
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
def list_people_i_care_for():
    actor = resolve_actor()
    return _care_for(actor)


def _care_for(actor: str) -> list[dict]:
    return [
        {
            "person_id": row["subject_person"],
            "relationship_type": row["relationship_type"],
        }
        for row in _active_care_rows(actor)
    ]


@frappe.whitelist()
def get_access_to_person(subject_person_id: str):
    """Return only the trusted actor's effective actions for a discoverable Person."""
    actor = resolve_actor()
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
def get_care_dashboard():
    principals = resolve_principals()
    actor = principals.human_actor
    return {
        "actor_person_id": actor,
        "circles": _circles_for(actor),
        "caring_for": _care_for(actor),
    }


@frappe.whitelist()
def whoami():
    """Return the trusted actor and BOTH principals (dual-principal audit context).

    Exposes no consent or relationship data. Used to prove session -> User -> Person
    binding end to end without revealing anything a caller did not already have.
    """
    principals = resolve_principals()
    return {
        "actor_person_id": principals.human_actor,
        "principals": principals.audit(),
    }


#: Only these machine callers may read delegation diagnostics. The payload is
#: already identity-free, but this is operational introspection added for one
#: investigation — it should not be permanent surface for every authenticated user.
DIAGNOSTIC_CALLERS = frozenset(
    {
        "home-mcp-service@episteck.invalid",
        "nutrition-auth-service@episteck.invalid",
    }
)


@frappe.whitelist()
def delegation_diagnostics():
    """Report WHY the delegation hook did or did not bind, as static codes.

    Returns no identity, no token, no session id and no Person id — only the stage
    the hook reached and whether a delegated context exists. This exists because the
    hook fails closed and silently by design, which twice made a live defect
    invisible from outside: a timezone-skewed clock rejecting every token, and an
    unenforced replay claim accepting every repeat.

    Restricted to the known service callers. A human session has no use for it, and
    keeping the surface narrow costs nothing.
    """
    caller = getattr(frappe.local, "episteck_machine_caller", None) or frappe.session.user
    if caller not in DIAGNOSTIC_CALLERS:
        frappe.throw("not permitted", frappe.PermissionError)
    return {
        "stage": getattr(frappe.local, "episteck_delegation_stage", None),
        "denial_category": getattr(frappe.local, "episteck_denial_category", None),
        "delegated_context_present": bool(
            getattr(frappe.local, "episteck_delegated_user", None)
        ),
        "machine_caller_present": bool(
            getattr(frappe.local, "episteck_machine_caller", None)
        ),
    }
