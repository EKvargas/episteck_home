"""Delegated human context — PURE, FAIL-CLOSED verification.

This module verifies a short-lived delegation token that carries *which human session*
a machine caller is acting for. It is pure Python (no Frappe import) so the security
core is unit-testable in isolation, mirroring `policy/access.py`.

WHAT THIS IS NOT
----------------
This is NOT a caller assertion of identity. The token never carries a Person id, and
a verified token yields only an opaque *session id*. The Person is resolved server-side
from the authenticated Frappe User that the session id maps to. A plain trusted header
such as ``X-Actor-ID: PSN-123`` is explicitly forbidden (amendment A7).

DUAL PRINCIPAL (amendment A6)
-----------------------------
Every delegated sensitive request carries two independent principals:

    machine_caller  — proven by the Frappe API key on the Authorization header
    human_actor     — proven by this delegation token, resolved server-side

The machine credential never means "this service is Person X". Both are retained in
audit context.

HARD INVARIANTS (must always hold):
  - Bad signature -> DENY.
  - Wrong issuer -> DENY.
  - Wrong audience -> DENY (a token minted for one service is useless at another).
  - Expired (now >= exp) -> DENY.
  - Not yet valid (now < iat, beyond clock skew) -> DENY.
  - Missing/blank required claim -> DENY.
  - Replayed token id -> DENY **only if the caller passes a replay store**. This
    module is a pure validator and holds no state of its own; see the note on
    `seen_token_ids` below. Production single-use lives in `identity/replay.py`.
  - Malformed input of ANY kind -> DENY. Never raise into the request path.
  - A verified token yields a SESSION id, never a Person id.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass

# Claims every delegation token must carry. Absence of any one is fatal.
REQUIRED_CLAIMS = ("iss", "aud", "iat", "exp", "jti", "sid")

# Tolerance for clock drift between the BFF and the Control Plane, in seconds.
CLOCK_SKEW_SECONDS = 30

# Upper bound on token lifetime. A token minted with a longer window is rejected
# regardless of its exp, so a misconfigured issuer cannot widen the replay window.
MAX_LIFETIME_SECONDS = 300


@dataclass(frozen=True)
class DelegatedContext:
    """A verified delegation. `session_id` is opaque; it is NOT a Person id."""

    session_id: str
    token_id: str
    issuer: str
    audience: str
    expires_at: int


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    reason: str
    context: DelegatedContext | None = None


def _deny(reason: str) -> VerificationResult:
    return VerificationResult(False, reason, None)


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return urlsafe_b64decode(segment + padding)


def _b64url_encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def sign(payload: dict, secret: str) -> str:
    """Mint a delegation token. Used by the BFF and by tests, never by the agent."""
    body = _b64url_encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}"


def verify(
    token: str | None,
    *,
    secret: str | None,
    expected_issuer: str,
    expected_audience: str,
    now: int,
    seen_token_ids: set[str] | None = None,
) -> VerificationResult:
    """Verify a delegation token. Fail closed on every anomaly.

    ``seen_token_ids`` is a **test seam, not production replay protection.** It lets a
    test express replay semantics against this pure function with an injected set.

    It is NOT sufficient in production, and passing it would not make it so: a Python
    set lives in one worker's memory, so with several gunicorn workers a replayed
    token lands on a different worker and is accepted. Live validation confirmed this
    exactly — the same ``jti`` succeeded twice.

    **Production single-use is enforced by ``identity/replay.py``**, which makes one
    atomic ``SET NX EX`` claim in the shared Redis cache, and by ``auth_hook``, which
    calls it after this function has proven the token authentic. This module stays
    pure and has no cache dependency, so it remains testable in isolation.
    """
    if not token or not secret or not expected_issuer or not expected_audience:
        return _deny("delegation unavailable (fail closed)")

    try:
        body, _, provided_signature = token.partition(".")
        if not body or not provided_signature:
            return _deny("malformed delegation token (fail closed)")

        expected_signature = _b64url_encode(
            hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        )
        # Constant-time comparison: never leak signature bytes through timing.
        if not hmac.compare_digest(provided_signature, expected_signature):
            return _deny("invalid delegation signature (fail closed)")

        claims = json.loads(_b64url_decode(body))
        if not isinstance(claims, dict):
            return _deny("malformed delegation claims (fail closed)")
    except Exception:
        # Any decode/parse failure is a denial, never an exception into the request.
        return _deny("malformed delegation token (fail closed)")

    for claim in REQUIRED_CLAIMS:
        value = claims.get(claim)
        if value is None or (isinstance(value, str) and not value.strip()):
            return _deny("incomplete delegation context (fail closed)")

    if claims["iss"] != expected_issuer:
        return _deny("unexpected delegation issuer (fail closed)")

    # Audience binding: a token minted for one service must not work at another.
    if claims["aud"] != expected_audience:
        return _deny("delegation audience mismatch (fail closed)")

    issued_at, expires_at = claims["iat"], claims["exp"]
    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        return _deny("malformed delegation validity (fail closed)")
    if isinstance(issued_at, bool) or isinstance(expires_at, bool):
        return _deny("malformed delegation validity (fail closed)")

    if expires_at <= issued_at:
        return _deny("invalid delegation window (fail closed)")
    if expires_at - issued_at > MAX_LIFETIME_SECONDS:
        return _deny("delegation lifetime too long (fail closed)")
    if now >= expires_at:
        return _deny("delegation expired (fail closed)")
    if now + CLOCK_SKEW_SECONDS < issued_at:
        return _deny("delegation not yet valid (fail closed)")

    token_id = str(claims["jti"])
    if seen_token_ids is not None and token_id in seen_token_ids:
        return _deny("delegation replay detected (fail closed)")

    return VerificationResult(
        True,
        "delegation verified",
        DelegatedContext(
            session_id=str(claims["sid"]),
            token_id=token_id,
            issuer=str(claims["iss"]),
            audience=str(claims["aud"]),
            expires_at=expires_at,
        ),
    )
