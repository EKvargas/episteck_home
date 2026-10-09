"""Trusted Frappe facts for a future private Knowledge mutation caller.

No method here is whitelisted. This loader does not possess Home-authority or
witness credentials and cannot itself activate a grant.
"""

from __future__ import annotations

from datetime import datetime

from .lane import ActivationRequest


def authenticated_person() -> str:
    import frappe
    from episteck_home.identity.actor import resolve_actor

    user = getattr(frappe.local, "episteck_delegated_user", None) or frappe.session.user
    if not user or user == "Guest" or frappe.db.get_value("User", user, "enabled") != 1:
        raise PermissionError("current authenticated human is required")
    return resolve_actor()


def current_person_grant(request: ActivationRequest, trusted_partition: str) -> bool:
    """Require current exact Person authority; legacy provenance alone grants nothing.

    Circle issuance remains closed until a typed authoritative Circle grant and
    stewardship loader exist. Circle membership's descriptive role is not proof.
    """
    import frappe

    if (type(trusted_partition) is not str or not trusted_partition
            or request.partition_id != trusted_partition
            or request.kind != "GRANT" or request.resource_type != "PERSON"
            or request.issuer_person_id != authenticated_person()):
        return False
    row = frappe.db.get_value("Consent Grant", request.source_grant_id,
                              ["actor_person", "subject_person", "domain", "actions",
                               "state", "valid_from", "valid_until"], as_dict=True)
    if not row or (
        row.actor_person != request.actor_person_id
        or row.subject_person != request.resource_id
        or row.domain != request.domain or row.state != "ACTIVE"
        or request.issuer_person_id != request.resource_id
    ):
        return False
    actions = frozenset(action.strip().upper() for action in
                        (row.actions or "").replace("\n", ",").split(",") if action.strip())
    if not request.actions or not request.actions.issubset(actions):
        return False
    now = frappe.utils.now_datetime()
    for value, before in ((row.valid_from, True), (row.valid_until, False)):
        if value:
            date = value if isinstance(value, datetime) else frappe.utils.get_datetime(value)
            if (before and now < date) or (not before and now > date):
                return False
    return bool(frappe.db.exists("Person", request.actor_person_id)
                and frappe.db.exists("Person", request.resource_id))
