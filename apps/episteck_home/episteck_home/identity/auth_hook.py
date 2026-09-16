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

TIME IS UTC, ALWAYS
-------------------
Delegation windows are compared in **epoch UTC**. ``frappe.utils.now_datetime()``
returns a NAIVE datetime in the site's timezone, so ``.timestamp()`` reinterprets it
as system-local time and silently shifts the clock by the site's UTC offset. On a
``Europe/Berlin`` site that is +7200 s, which is far beyond any token's 120 s lifetime,
so **every** delegation arrives "expired". Use ``time.time()`` — the minting side
(``home_bff.sessions``) already does.

FAIL CLOSED
-----------
Any anomaly leaves ``frappe.local.episteck_delegated_user`` unset, so
``resolve_principals()`` finds no human actor and denies. This hook never raises into
the request path and never widens access.

DIAGNOSTICS
-----------
Each exit records a static stage code via ``frappe.local.episteck_delegation_stage``
and, on anomalies, a sanitized log line. Stage codes are fixed strings: no token, no
session id, no Person id, no user name, no header, and no secret ever reaches a log.
"""
from __future__ import annotations

import time

import frappe

from .delegation import verify

DELEGATION_HEADER = "X-Episteck-Delegation"

# This Control Plane accepts delegations minted for it and no one else.
CONTROL_PLANE_AUDIENCE = "home-control-plane"

LOG_TITLE = "episteck_home.delegation"

# Every stage code is a compile-time constant. Nothing derived from a request, a
# credential, or an identity is ever appended to one.
STAGE_START = "delegation_hook.start"
STAGE_NO_TOKEN = "delegation_hook.no_token"
STAGE_MACHINE_GUEST = "delegation_hook.machine_guest"
STAGE_MACHINE_AUTHENTICATED = "delegation_hook.machine_authenticated"
STAGE_NOT_CONFIGURED = "delegation_hook.not_configured"
STAGE_VERIFY_INVALID = "delegation_hook.verify_invalid"
STAGE_VERIFY_VALID = "delegation_hook.verify_valid"
STAGE_SESSION_MISSING = "delegation_hook.session_missing"
STAGE_SESSION_FOUND = "delegation_hook.session_found"
STAGE_BOUND = "delegation_hook.bound"
STAGE_EXCEPTION = "delegation_hook.exception"


def _stage(code: str) -> None:
    """Record the last stage reached. Static codes only; never an identity."""
    frappe.local.episteck_delegation_stage = code


def _config(key: str) -> str | None:
    value = frappe.conf.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _now() -> int:
    """Epoch UTC. See TIME IS UTC above — never derive this from site-local time."""
    return int(time.time())


def establish_delegated_context() -> None:
    """Verify the delegation header and bind the human session. Never raises."""
    try:
        _establish()
    except Exception as error:
        # Defensive: a hook must never break authentication for everyone. But an
        # unexpected failure here previously vanished without trace, which made a
        # live defect invisible. Record the exception CLASS and a static stage code —
        # never the message, which could quote a token or a header.
        frappe.local.episteck_delegated_user = None
        _stage(f"{STAGE_EXCEPTION}:{type(error).__name__}")
        try:
            frappe.log_error(
                f"{STAGE_EXCEPTION}:{type(error).__name__}", LOG_TITLE
            )
        except Exception:
            # Logging must never be the thing that breaks authentication.
            pass


def _establish() -> None:
    frappe.local.episteck_delegated_user = None
    _stage(STAGE_START)

    token = frappe.get_request_header(DELEGATION_HEADER)
    if not token:
        # The overwhelmingly common case: an ordinary request with no delegation.
        _stage(STAGE_NO_TOKEN)
        return

    # A delegation is only meaningful for an already-authenticated machine caller.
    # An anonymous request may never bootstrap a human identity from a header.
    machine_user = frappe.session.user
    if not machine_user or machine_user == "Guest":
        _stage(STAGE_MACHINE_GUEST)
        return
    _stage(STAGE_MACHINE_AUTHENTICATED)

    secret = _config("home_delegation_secret")
    if not secret:
        # Misconfiguration, not an attack. Worth a log line: without it the site
        # denies every delegated request for a reason no response would reveal.
        _stage(STAGE_NOT_CONFIGURED)
        try:
            frappe.log_error(STAGE_NOT_CONFIGURED, LOG_TITLE)
        except Exception:
            pass
        return

    result = verify(
        token,
        secret=secret,
        expected_issuer=_config("home_delegation_issuer") or "episteck-home-bff",
        expected_audience=CONTROL_PLANE_AUDIENCE,
        now=_now(),
    )
    if not result.valid:
        # result.reason is a fixed phrase from delegation.py, never request-derived.
        _stage(f"{STAGE_VERIFY_INVALID}:{result.reason}")
        return
    _stage(STAGE_VERIFY_VALID)

    session_user = _user_for_session(result.context.session_id)
    if not session_user:
        _stage(STAGE_SESSION_MISSING)
        return
    _stage(STAGE_SESSION_FOUND)

    frappe.local.episteck_delegated_user = session_user
    frappe.local.episteck_machine_caller = machine_user
    _stage(STAGE_BOUND)


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
    # Site-local on BOTH sides deliberately: `expires_at` is written by
    # identity/session.py with frappe.utils.now_datetime(), so comparing it against
    # frappe.utils.now() is consistent. This is NOT the token clock — delegation
    # windows are epoch UTC (see _now and the module docstring). Two different
    # clocks, each internally consistent; do not "unify" them without moving both
    # sides of the stored value too.
    if expires_at and str(expires_at) <= frappe.utils.now():
        return None

    user = row.get("user")
    if not user:
        return None

    # A disabled User can never act, even with a live session record.
    if not frappe.db.get_value("User", user, "enabled"):
        return None

    return user
