"""Confidential OAuth client for home.episteck.com (G1.6).

WHY A CONFIDENTIAL CLIENT
-------------------------
Live inspection of Frappe v15.99.0 found that PKCE cannot be REQUIRED: if a client
omits ``code_challenge`` entirely, ``validate_code`` falls through to ``return True``
and the code is accepted with no PKCE binding. The ``OAuth Client`` DocType has no
``public_client`` and no ``require_pkce`` field.

We therefore never create a public client. The BFF is confidential: the client secret
stays on the Nuremberg server, the authorization code never reaches a browser, and
this client ALWAYS sends S256 PKCE as defense in depth. The downgrade path is
unreachable because no public client exists (amendment A3).

Native/direct mobile OIDC stays deferred until upstream can enforce PKCE.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

# We send this unconditionally. "plain" is never used.
CODE_CHALLENGE_METHOD = "S256"


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str
    method: str = CODE_CHALLENGE_METHOD


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def new_pkce_pair() -> PkcePair:
    """Generate a fresh S256 PKCE pair. The verifier never leaves the server."""
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return PkcePair(verifier=verifier, challenge=challenge)


def compute_challenge(verifier: str) -> str:
    """S256 challenge for a verifier, matching Frappe's own computation."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def authorization_params(
    client_id: str,
    redirect_uri: str,
    pkce: PkcePair,
    state: str,
    scope: str = "openid all",
) -> dict:
    """Authorization-request parameters. PKCE is always present, always S256."""
    return {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "code_challenge": pkce.challenge,
        "code_challenge_method": CODE_CHALLENGE_METHOD,
    }


def token_request_params(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    """Token-exchange parameters. Runs server-side only; the secret never ships."""
    return {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }


def new_state() -> str:
    """CSRF state for the authorization request."""
    return secrets.token_urlsafe(32)
