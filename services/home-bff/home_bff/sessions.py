"""Home BFF session and delegation minting (G1.6).

The BFF is a CONFIDENTIAL OAuth client running on the Nuremberg EU node (amendment
A1). It holds the client secret and the user's OAuth tokens server-side. The browser
receives only an opaque ``Secure + HttpOnly + SameSite`` cookie (amendment A2).

For each agent turn the BFF mints a short-lived, single-audience delegation token that
proves WHICH HUMAN SESSION a downstream service acts for. The token carries no Person
id — only an opaque session id that the Control Plane resolves server-side.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass

# Audiences a delegation may be minted for. A token is valid at exactly one of them.
AUDIENCE_CONTROL_PLANE = "home-control-plane"
AUDIENCE_NUTRITION = "svc-nutrition"
KNOWN_AUDIENCES = frozenset({AUDIENCE_CONTROL_PLANE, AUDIENCE_NUTRITION})

ISSUER = "episteck-home-bff"

# Delegations live for a single agent turn, not a session (proposal §18 Q2).
DELEGATION_TTL_SECONDS = 120

# Cookie policy for the browser-facing session reference.
#
# ``samesite=lax`` is REQUIRED here, not a weakening of ``strict``: the cookie is set
# on the top-level GET redirect back from Frappe's authorization endpoint, and a
# strict cookie is withheld on that cross-site navigation, so the session would be
# invisible on the very next request. ``lax`` still blocks cross-site POST, and the
# cookie carries no authority of its own — it is an opaque lookup key.
COOKIE_NAME = "episteck_home_session"
COOKIE_MAX_AGE_SECONDS = 12 * 60 * 60
COOKIE_FLAGS = {
    "httponly": True,
    "secure": True,
    "samesite": "lax",
    "path": "/",
}


class UnknownAudienceError(ValueError):
    """Raised when a delegation is requested for an unrecognised audience."""


@dataclass(frozen=True)
class MintedDelegation:
    token: str
    token_id: str
    audience: str
    expires_at: int


def _b64url(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_session_id() -> str:
    """Opaque session id. Never derived from, and never revealing, a Person."""
    return secrets.token_urlsafe(32)


def mint_delegation(
    session_id: str,
    audience: str,
    secret: str,
    *,
    now: int | None = None,
    ttl_seconds: int = DELEGATION_TTL_SECONDS,
) -> MintedDelegation:
    """Mint a single-audience, short-lived delegation for one downstream call.

    The token asserts only "this request acts for session X". Who X *is* remains the
    Control Plane's decision, so the BFF cannot elevate or substitute an identity.
    """
    if audience not in KNOWN_AUDIENCES:
        raise UnknownAudienceError(audience)
    if not session_id or not secret:
        raise ValueError("session id and signing secret are required")

    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + ttl_seconds
    token_id = secrets.token_urlsafe(16)

    claims = {
        "iss": ISSUER,
        "aud": audience,
        "iat": issued_at,
        "exp": expires_at,
        "jti": token_id,
        "sid": session_id,
    }
    body = _b64url(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return MintedDelegation(
        token=f"{body}.{_b64url(signature)}",
        token_id=token_id,
        audience=audience,
        expires_at=expires_at,
    )


def redact(value: str | None) -> str:
    """Render a credential safe for logs. Never log the token itself."""
    if not value:
        return "<none>"
    return f"<redacted:{len(value)} chars>"
