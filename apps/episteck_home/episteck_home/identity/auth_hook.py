"""Frappe auth_hook: establish delegated human context server-side (G1.6).

Runs inside ``frappe.auth.validate_auth`` for every request, AFTER Frappe has
authenticated the machine caller via its API key. It verifies the delegation token and
maps the opaque session id to a Frappe User through the ``Home Delegated Session``
DocType.

WHY A DOCTYPE LOOKUP AND NOT A CLAIM
------------------------------------
The token carries only an opaque session id. The User is read from a server-side
record that the BFF created at login. This is what makes revocation and logout
immediate: revoking the session record denies the very next call, even if the
attacker still holds a syntactically valid, unexpired token.

FAIL CLOSED
-----------
Any anomaly leaves ``frappe.local.episteck_delegated_user`` unset, so
``resolve_principals()`` finds no human actor and denies. This hook never raises into
the request path and never widens access.
"""
from __future__ import annotations

import frappe

from .delegation import verify

DELEGATION_HEADER = "X-Episteck-Delegation"

# This Control Plane accepts delegations minted for it and no one else.
CONTROL_PLANE_AUDIENCE = "home-control-plane"


def _config(key: str) -> str | None:
    value = frappe.conf.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def establish_delegated_context() -> None:
    """Verify the delegation header and bind the human session. Never raises."""
    try:
        _establish()
    except Exception:
        # Defensive: a hook must never break authentication for everyone.
        frappe.local.episteck_delegated_user = None


def _establish() -> None:
    frappe.local.episteck_delegated_user = None

    token = frappe.get_request_header(DELEGATION_HEADER)
    if not token:
        return

    # A delegation is only meaningful for an already-authenticated machine caller.
    # An anonymous request may never bootstrap a human identity from a header.
    machine_user = frappe.session.user
    if not machine_user or machine_user == "Guest":
        return

    result = verify(
        token,
        secret=_config("home_delegation_secret"),
        expected_issuer=_config("home_delegation_issuer") or "episteck-home-bff",
        expected_audience=CONTROL_PLANE_AUDIENCE,
        now=int(frappe.utils.now_datetime().timestamp()),
    )
    if not result.valid:
        return

    session_user = _user_for_session(result.context.session_id)
    if not session_user:
        return

    frappe.local.episteck_delegated_user = session_user
    frappe.local.episteck_machine_caller = machine_user


def _user_for_session(session_id: str) -> str | None:
    """Map an opaque session id to a User via an ACTIVE server-side session record."""
    rows = frappe.get_all(
        "Home Delegated Session",
        filters={"name": session_id, "status": "Active"},
        fields=["user", "expires_at"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    if len(rows) != 1:
        return None

    row = rows[0]
    expires_at = row.get("expires_at")
    if expires_at and str(expires_at) <= frappe.utils.now():
        return None

    user = row.get("user")
    if not user:
        return None

    # A disabled User can never act, even with a live session record.
    if not frappe.db.get_value("User", user, "enabled"):
        return None

    return user
