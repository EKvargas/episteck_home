"""Trusted runtime context for Home MCP (G1.6).

The delegation token that proves *which human* we act for is carried by the MCP
transport — an HTTP request header set by the trusted runtime (the BFF) — and is read
here, OUTSIDE any model-controlled tool argument.

WHY THIS FILE EXISTS
--------------------
It is the seam that keeps bearer material away from the LLM. Tools call
``current_delegation()``; they never accept a token or an actor as a parameter, so the
model has no way to supply, alter, or observe either one.

If no delegation is present the value is ``None`` and every person-scoped tool fails
closed with a business-safe message. A missing human session is never an error the
model can route around.
"""
from __future__ import annotations

from contextvars import ContextVar

DELEGATION_HEADER = "X-Episteck-Delegation"

# Set per request by the transport; never by a tool argument.
_delegation: ContextVar[str | None] = ContextVar("episteck_delegation", default=None)


def set_delegation(token: str | None) -> None:
    _delegation.set(token.strip() if isinstance(token, str) and token.strip() else None)


def current_delegation() -> str | None:
    """The delegation token for this request, or None. Never model-supplied."""
    return _delegation.get()


def delegation_from_headers(headers) -> str | None:
    """Extract the delegation token from transport headers, tolerating None."""
    if not headers:
        return None
    try:
        value = headers.get(DELEGATION_HEADER) or headers.get(
            DELEGATION_HEADER.lower()
        )
    except AttributeError:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


NO_SESSION = {
    "ok": False,
    "error": "no_authenticated_human_session",
    "detail": "Ask the person to sign in to Episteck Home; identity cannot be supplied here.",
}
