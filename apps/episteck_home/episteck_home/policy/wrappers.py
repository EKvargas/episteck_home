"""Frappe binding for the pure access policy. Loads ConsentGrants from the DB and
delegates the DECISION to policy.access.can_access (which stays pure + fail-closed)."""
from __future__ import annotations
import frappe
from .access import ACTIONS, DOMAINS, can_access, Grant

# The answer an EXISTING subject with no grants receives. A missing subject gets the
# same answer, so no caller can use authorization to learn whether a Person exists.
_NO_GRANT_REASON = "no consent grant (fail closed)"


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


def _subject_exists(subject_person_id: str) -> bool:
    """Fresh read of the Person system of record. Never cached, not even per request."""
    return bool(frappe.db.exists("Person", subject_person_id))


def _is_valid_request(actor_person_id, subject_person_id, domain, action) -> bool:
    return (
        isinstance(actor_person_id, str) and bool(actor_person_id)
        and isinstance(subject_person_id, str) and bool(subject_person_id)
        and domain in DOMAINS
        and action in ACTIONS
    )


def check_access(actor_person_id: str, subject_person_id: str, domain: str, action: str) -> dict:
    """The one authorization entry point for the Control Plane. Fail-closed.

    Order matters:
      1. Invalid input is refused by the pure evaluator WITHOUT an existence lookup,
         so the invalid-input answer never depends on whether the subject exists.
      2. A positive decision requires that the subject Person exists now. A missing
         subject gets the same answer as an existing subject with no grants, and its
         grants are never loaded, so an orphaned grant cannot authorize.
      3. Grants are loaded and the pure evaluator decides.
    """
    try:
        now = frappe.utils.now_datetime().isoformat()
        if not _is_valid_request(actor_person_id, subject_person_id, domain, action):
            d = can_access(actor_person_id, subject_person_id, domain, action, grants=[], now=now)
            return {"allow": d.allow, "reason": d.reason}
        if not _subject_exists(subject_person_id):
            return {"allow": False, "reason": _NO_GRANT_REASON}
        grants = _load_grants(actor_person_id, subject_person_id)
        d = can_access(actor_person_id, subject_person_id, domain, action, grants=grants, now=now)
        return {"allow": d.allow, "reason": d.reason}
    except Exception as e:
        frappe.log_error(f"check_access error: {e}", "episteck_home.check_access")
        return {"allow": False, "reason": "policy error (fail closed)"}
