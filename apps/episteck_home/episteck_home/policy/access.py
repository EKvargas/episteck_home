"""Central authorization policy for Episteck Home — PURE, FAIL-CLOSED.

This module is the single authorization decision point:
    can_access(actor, subject, domain, action) -> Decision(allow: bool, reason)

It is pure Python (no Frappe import) so it is unit-testable in isolation. The Frappe
layer (see wrappers.py) loads ConsentGrants + relationships from the DB and calls this.

HARD INVARIANTS (must always hold):
  - Membership in the same Circle NEVER authorizes.
  - A CareRelationship NEVER authorizes by itself.
  - A revoked or expired grant -> DENY.
  - Unknown / unavailable state -> DENY (fail closed).
  - One domain grant never implies another.
  - Action is scoped: VIEW < CREATE/UPDATE < MANAGE is NOT assumed; a grant lists the
    exact actions it permits. (A MANAGE grant is treated as permitting all lesser
    actions only when it explicitly enumerates them; by default match exact action or
    an explicit "*"/MANAGE-implies rule set below.)
  - Self-access: actor == subject is allowed for that person's own data.
"""
from __future__ import annotations
from dataclasses import dataclass, field

DOMAINS = frozenset({
    "NUTRITION", "HEALTH", "CALENDAR", "DOCUMENTS", "FINANCE", "MIND", "HOUSEHOLD", "KNOWLEDGE",
})
ACTIONS = frozenset({"VIEW", "CREATE", "UPDATE", "MANAGE"})

# MANAGE implies the lesser actions on the SAME domain (explicit, documented).
_MANAGE_IMPLIES = {"MANAGE": {"VIEW", "CREATE", "UPDATE", "MANAGE"}}


@dataclass(frozen=True)
class Grant:
    """A consent grant loaded from the Control Plane. Times are ISO strings or None."""
    actor_person_id: str
    subject_person_id: str
    domain: str
    actions: frozenset            # e.g. {"VIEW"} or {"VIEW","UPDATE"} or {"MANAGE"}
    state: str                    # "ACTIVE" | "REVOKED" | anything else -> not usable
    valid_from: str | None = None
    valid_until: str | None = None


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str


def _grant_covers_action(grant: Grant, action: str) -> bool:
    if action in grant.actions:
        return True
    # MANAGE (if explicitly granted) implies lesser actions
    if "MANAGE" in grant.actions and action in _MANAGE_IMPLIES["MANAGE"]:
        return True
    return False


def _grant_active(grant: Grant, now: str | None) -> bool:
    if grant.state != "ACTIVE":
        return False
    if now is not None:
        if grant.valid_from is not None and now < grant.valid_from:
            return False
        if grant.valid_until is not None and now > grant.valid_until:
            return False
    return True


def can_access(actor_person_id: str | None,
               subject_person_id: str | None,
               domain: str | None,
               action: str | None,
               grants: list[Grant] | None,
               now: str | None = None) -> Decision:
    """Fail-closed authorization decision. `grants` are the ConsentGrants relevant to
    (actor, subject) as loaded by the caller; None or [] -> only self-access can pass."""
    # fail closed on any malformed input
    if not actor_person_id or not subject_person_id or domain not in DOMAINS or action not in ACTIONS:
        return Decision(False, "invalid or unknown request (fail closed)")

    # self-access: a person may act on their own data
    if actor_person_id == subject_person_id:
        return Decision(True, "self-access")

    if not grants:
        return Decision(False, "no consent grant (fail closed)")

    for g in grants:
        if g.actor_person_id != actor_person_id or g.subject_person_id != subject_person_id:
            continue
        if g.domain != domain:
            continue  # one domain never implies another
        if not _grant_active(g, now):
            continue  # revoked/expired/not-yet-valid
        if _grant_covers_action(g, action):
            return Decision(True, f"grant {domain}/{action}")
    return Decision(False, "no matching active grant (fail closed)")
