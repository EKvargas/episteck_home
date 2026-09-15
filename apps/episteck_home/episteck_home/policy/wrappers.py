"""Frappe binding for the pure access policy. Loads ConsentGrants from the DB and
delegates the DECISION to policy.access.can_access (which stays pure + fail-closed)."""
from __future__ import annotations
import frappe
from .access import can_access, Grant


def _load_grants(actor_person_id: str, subject_person_id: str) -> list[Grant]:
    rows = frappe.get_all(
        "Consent Grant",
        filters={"actor_person": actor_person_id, "subject_person": subject_person_id},
        fields=["actor_person", "subject_person", "domain", "actions", "state",
                "valid_from", "valid_until"],
    )
    grants = []
    for r in rows:
        acts = frozenset(a.strip().upper() for a in (r.get("actions") or "").replace("\n", ",").split(",") if a.strip())
        grants.append(Grant(
            actor_person_id=r["actor_person"], subject_person_id=r["subject_person"],
            domain=r["domain"], actions=acts, state=r["state"],
            valid_from=str(r["valid_from"]) if r.get("valid_from") else None,
            valid_until=str(r["valid_until"]) if r.get("valid_until") else None,
        ))
    return grants


def check_access(actor_person_id: str, subject_person_id: str, domain: str, action: str) -> dict:
    """The one authorization entry point for the Control Plane. Fail-closed."""
    try:
        grants = _load_grants(actor_person_id, subject_person_id)
        now = frappe.utils.now_datetime().isoformat()
        d = can_access(actor_person_id, subject_person_id, domain, action, grants=grants, now=now)
        return {"allow": d.allow, "reason": d.reason}
    except Exception as e:
        frappe.log_error(f"check_access error: {e}", "episteck_home.check_access")
        return {"allow": False, "reason": "policy error (fail closed)"}
