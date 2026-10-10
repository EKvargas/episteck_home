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

import math

import frappe

from .actor import resolve_principals

DOCTYPE = "Home Delegated Session"

# A browser login lasts a working day. Delegations minted against it stay short-lived
# (120 s) — this bounds the *session*, not the token.
SESSION_TTL_SECONDS = 12 * 60 * 60

STATUS_ACTIVE = "Active"
STATUS_REVOKED = "Revoked"

# H5 agent runtime grant: a long-lived session whose ``client`` names the runtime.
RUNTIME_CLIENT_PREFIX = "agent-runtime:"
DEFAULT_RUNTIME_IDS = ("home-agent-primary",)
DEFAULT_MAX_DAYS = 90


def _require_human() -> str:
    """The authenticated user, which is never a caller assertion."""
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw("authentication required", frappe.PermissionError)
    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw("user is disabled", frappe.PermissionError)
    return user


def _require_single_linked_person(user: str) -> None:
    """``open_session``-only: refuse before a session row is created (B2).

    ``close_session`` deliberately does NOT call this. A session must remain
    closable even after its User is later unlinked from Person — unlinking
    denies future *use* (``get_home_bootstrap`` / delegated access), not
    cleanup of a session that already exists.
    """
    people = frappe.get_all(
        "Person", filters={"linked_user": user}, fields=["name"], limit_page_length=0
    )
    if len(people) != 1:
        frappe.throw("no linked person", frappe.PermissionError)


@frappe.whitelist()
def open_session(client: str | None = None) -> dict:
    """Open a delegated session for the CALLER. Takes no user parameter.

    Returns the opaque session id, which becomes the ``sid`` claim of delegation
    tokens. The caller learns nothing about any other session.
    """
    user = _require_human()
    _require_single_linked_person(user)

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


# ------------------------------------------------------------ runtime grant (H5)


def _conf_list(key: str, default: tuple[str, ...]) -> list[str]:
    """Site-config list. Unset -> default; set but malformed -> empty (deny)."""
    value = frappe.conf.get(key)
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _max_grant_days() -> int:
    """Unset -> 90. Set but malformed -> 0, which rejects every ttl (fail closed).

    ``bench set-config`` stores a plain string unless ``-p`` is passed, so a digit
    string is honoured rather than silently replaced by the default.
    """
    value = frappe.conf.get("home_runtime_grant_max_days")
    if value is None:
        return DEFAULT_MAX_DAYS
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value >= 1 else 0
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 6:
        return int(value)
    return 0


def _parse_ttl_days(value, max_days: int) -> int:
    """Integer 1..max_days. Accepts an HTTP form string of digits; nothing else."""
    if isinstance(value, bool):
        days = None
    elif isinstance(value, int):
        days = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        days = int(value)
    else:
        days = None
    if days is None or days < 1 or days > max_days:
        frappe.throw("ttl_days is out of range", frappe.ValidationError)
    return days


# POST only: a bare whitelist accepts GET, and Frappe checks CSRF only for unsafe
# methods, so a cross-site link could otherwise rotate (revoke) the live grant.
@frappe.whitelist(methods=["POST"])
def open_runtime_grant(runtime_id: str, ttl_days) -> dict:
    """Grant an agent runtime the CALLER's identity for ``ttl_days``. No user parameter.

    Same self-service seam as ``open_session``: the authenticated human is the only
    possible owner, so a machine credential (no linked Person) can never create one.
    Two extra controls: the runtime must be listed in ``home_runtime_ids`` and the
    caller in ``home_runtime_grantees`` (absent or empty denies everyone). Any previous
    Active grant of the same user and runtime is revoked (rotation).
    """
    user = _require_human()
    _require_single_linked_person(user)
    if runtime_id not in _conf_list("home_runtime_ids", DEFAULT_RUNTIME_IDS):
        frappe.throw("runtime not allowed", frappe.PermissionError)
    if user not in _conf_list("home_runtime_grantees", ()):
        frappe.throw("not allowed to grant a runtime", frappe.PermissionError)
    days = _parse_ttl_days(ttl_days, _max_grant_days())

    client = f"{RUNTIME_CLIENT_PREFIX}{runtime_id}"[:140]
    now = frappe.utils.now_datetime()
    try:
        previous = frappe.get_all(
            DOCTYPE,
            filters={"user": user, "client": client, "status": STATUS_ACTIVE},
            fields=["name"],
            limit_page_length=0,
        )
        for row in previous:
            frappe.db.set_value(
                DOCTYPE,
                row["name"],
                {"status": STATUS_REVOKED, "revoked_at": now},
                update_modified=False,
            )
        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "user": user,
                "status": STATUS_ACTIVE,
                "expires_at": frappe.utils.add_to_date(now, days=days),
                "client": client,
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    return {"session_id": doc.name, "expires_at": str(doc.expires_at)}


@frappe.whitelist(methods=["POST"])
def close_runtime_grant(session_id: str) -> dict:
    """Revoke a runtime grant. Only its owner can; non-grants are never closed here."""
    user = _require_human()
    if not session_id:
        frappe.throw("session id is required", frappe.ValidationError)

    owner = frappe.db.get_value(DOCTYPE, session_id, "user")
    client = frappe.db.get_value(DOCTYPE, session_id, "client") or ""
    if owner != user or not client.startswith(RUNTIME_CLIENT_PREFIX):
        # Same answer for "not yours", "not a grant" and "does not exist".
        return {"closed": False}

    frappe.db.set_value(
        DOCTYPE,
        session_id,
        {"status": STATUS_REVOKED, "revoked_at": frappe.utils.now_datetime()},
        update_modified=False,
    )
    frappe.db.commit()
    return {"closed": True}


#: Machine callers allowed to read the grant status (the Home MCP service only).
RUNTIME_STATUS_CALLERS = frozenset({"home-mcp-service@episteck.invalid"})


@frappe.whitelist()
def get_runtime_grant_status() -> dict:
    """Expiry of the grant behind THIS delegated call. Returns no identifier.

    Callable only with a control-plane delegation presented by the Home MCP service.
    The session in use comes from the auth hook's request-local state, never from a
    parameter, so a caller cannot ask about any session but its own.
    """
    principals = resolve_principals()  # control-plane audience only; fails closed
    if not principals.is_delegated or principals.machine_caller not in RUNTIME_STATUS_CALLERS:
        frappe.throw("not permitted", frappe.PermissionError)
    session_id = getattr(frappe.local, "episteck_delegated_session_id", None)
    if not session_id:
        frappe.throw("not permitted", frappe.PermissionError)

    client = frappe.db.get_value(DOCTYPE, session_id, "client") or ""
    if not client.startswith(RUNTIME_CLIENT_PREFIX):
        return {"granted": False}

    expires_at = frappe.db.get_value(DOCTYPE, session_id, "expires_at")
    if isinstance(expires_at, str):
        expires_at = frappe.utils.get_datetime(expires_at)
    # Both sides are site-local (see auth_hook._user_for_session): same clock.
    remaining = (expires_at - frappe.utils.now_datetime()).total_seconds()
    return {
        "granted": True,
        "expires_at": str(expires_at),
        "days_left": max(0, math.ceil(remaining / 86400)),
    }
