"""Home Delegated Session lifecycle (G1.6).

WHY THIS IS SELF-SERVICE
------------------------
The BFF must turn "a human just completed OAuth" into a server-side session record
that later delegation tokens can point at. The obvious implementation — let the BFF
say *which* User the session is for — would reintroduce exactly the assertion G1.6
exists to remove: a caller naming an identity.

So these methods take **no user parameter at all**. The BFF calls them with the
user's own freshly-minted OAuth access token, so Frappe authenticates the human
itself and ``frappe.session.user`` *is* the answer. The BFF cannot create a session
for anyone but the person who just logged in, even if it wanted to, and it needs no
elevated credential to do so.

    OAuth access token (the human's)  ->  frappe.session.user  ->  session row

``ignore_permissions`` is used for the write because the DocType is System Manager
only by design: a Website User must be able to open *their own* session without
being granted table-level rights to everyone's. The identity being written is never
caller-supplied, so this is not a privilege escalation — it is the narrowest possible
self-service seam.
"""
from __future__ import annotations

import frappe

DOCTYPE = "Home Delegated Session"

# A browser login lasts a working day. Delegations minted against it stay short-lived
# (120 s) — this bounds the *session*, not the token.
SESSION_TTL_SECONDS = 12 * 60 * 60

STATUS_ACTIVE = "Active"
STATUS_REVOKED = "Revoked"


def _require_human() -> str:
    """The authenticated user, which is never a caller assertion."""
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw("authentication required", frappe.PermissionError)
    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw("user is disabled", frappe.PermissionError)
    return user


@frappe.whitelist()
def open_session(client: str | None = None) -> dict:
    """Open a delegated session for the CALLER. Takes no user parameter.

    Returns the opaque session id, which becomes the ``sid`` claim of delegation
    tokens. The caller learns nothing about any other session.
    """
    user = _require_human()

    doc = frappe.get_doc(
        {
            "doctype": DOCTYPE,
            "user": user,
            "status": STATUS_ACTIVE,
            "expires_at": frappe.utils.add_to_date(
                frappe.utils.now_datetime(), seconds=SESSION_TTL_SECONDS
            ),
            "client": (client or "bff-web")[:140],
        }
    )
    # See module docstring: the identity written here is the authenticated caller,
    # never an argument.
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {"session_id": doc.name, "expires_at": str(doc.expires_at)}


@frappe.whitelist()
def close_session(session_id: str) -> dict:
    """Revoke a session. A caller may only close a session that is their own.

    Ownership is checked against the authenticated user, so possessing a session id
    is not sufficient to revoke someone else's session.
    """
    user = _require_human()
    if not session_id:
        frappe.throw("session id is required", frappe.ValidationError)

    owner = frappe.db.get_value(DOCTYPE, session_id, "user")
    if owner != user:
        # Same response for "not yours" and "does not exist": revealing which is
        # which would turn this into a session-id oracle.
        return {"closed": False}

    frappe.db.set_value(
        DOCTYPE,
        session_id,
        {"status": STATUS_REVOKED, "revoked_at": frappe.utils.now_datetime()},
        update_modified=False,
    )
    frappe.db.commit()
    return {"closed": True}
