"""Trusted human session for svc-finance: the delegation header, read OUTSIDE any tool argument.

Same seam as services/nutrition/app/session.py. FastMCP maintains the per-request context
and ``get_http_headers()`` reads it, so there is no ContextVar and no setter to forget.
The default of that function strips ``authorization`` and ``cookie`` in fastmcp 4.0.3 but
not in 2.x, so this module reads the ONE header it needs and discards the rest: tool code
never receives the dictionary and an upgrade cannot widen what it can see.
"""
from __future__ import annotations

from fastmcp.server.dependencies import get_http_headers

DELEGATION_HEADER = "X-Episteck-Delegation"
_KEY = DELEGATION_HEADER.lower()


def current_delegation() -> str | None:
    """The delegated human session for this request, or None. Never model-supplied."""
    try:
        value = get_http_headers().get(_KEY)  # no include_all: never ask for credentials
    except Exception:
        return None  # an unreadable context is not an authenticated human
    return value.strip() if isinstance(value, str) and value.strip() else None
