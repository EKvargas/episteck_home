"""Trusted human session context for svc-nutrition (G1.6).

The delegated human session arrives via transport (an HTTP header set by the trusted
runtime), never as a tool argument or query parameter. Nutrition then resolves the
acting Person ITSELF against the Home Control Plane.

This is the seam that keeps the Home Agent from asserting an identity to Nutrition,
and keeps bearer material out of the model's context entirely.
"""
from __future__ import annotations

from contextvars import ContextVar

DELEGATION_HEADER = "X-Episteck-Delegation"

_delegation: ContextVar[str | None] = ContextVar("episteck_delegation", default=None)


def set_delegation(token: str | None) -> None:
    _delegation.set(token.strip() if isinstance(token, str) and token.strip() else None)


def current_delegation() -> str | None:
    """The delegated human session for this request, or None. Never model-supplied."""
    return _delegation.get()


NO_SESSION = {
    "allow": False,
    "error": "no_authenticated_human_session",
    "reason": "no authenticated human session (fail closed)",
}
