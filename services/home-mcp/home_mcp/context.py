"""Trusted runtime context for Home MCP (G1.6).

The delegation token that proves *which human* we act for is carried by the MCP
transport — an HTTP request header set by the trusted runtime — and is read here,
OUTSIDE any model-controlled tool argument.

WHY THIS FILE EXISTS
--------------------
It is the seam that keeps bearer material away from the LLM. Tools call
``current_delegation()``; they never accept a token or an actor as a parameter, so the
model has no way to supply, alter, or observe either one.

If no delegation is present the value is ``None`` and every person-scoped tool fails
closed with a business-safe message. A missing human session is never an error the
model can route around.

WHY NO ContextVar
-----------------
An earlier revision of this module kept its own ``ContextVar`` with ``set_delegation``
and ``delegation_from_headers``. Nothing in production ever called them — the binding
from HTTP header to ContextVar was simply never written — so ``current_delegation()``
returned ``None`` on every request and every person-scoped tool was permanently
unusable.

Rather than add the missing setter, the ContextVar is gone. FastMCP already maintains
the per-request context we were trying to duplicate, and ``get_http_headers()`` reads
it directly. Verified on FastMCP 4.0.3 against a real HTTP server inside the deployed
image:

    with header     -> the exact token
    without header  -> None
    8 concurrent requests, 8 distinct tokens -> 8/8 correct, no bleed

One source of truth, owned by the transport, with no set/reset discipline for a future
change to get wrong.

WHY NOT include_all, AND WHY WE DO NOT TRUST THE DEFAULT EITHER
---------------------------------------------------------------
``include_all=True`` returns every header, including the machine credential and the
browser cookie — the precise material this seam exists to withhold — so it is never
used.

The default is safer but is **not a contract**. Measured directly:

    fastmcp 4.0.3 : "authorization" and "cookie" ARE stripped by default
    fastmcp 2.13  : they are NOT — both are returned to tool code

Same function, same call, opposite security behaviour across versions. The dependency
is pinned to ``4.0.3`` for exactly this reason, but a pin is a policy and this is a
security boundary, so ``_delegation_only()`` reads the ONE header it needs and
discards the rest. An upgrade that changes the default cannot widen what tool code can
see, because tool code never receives the dictionary.
"""
from __future__ import annotations

from fastmcp.server.dependencies import get_http_headers

DELEGATION_HEADER = "X-Episteck-Delegation"

# get_http_headers() lowercases header names, as HTTP treats them case-insensitively.
_DELEGATION_KEY = DELEGATION_HEADER.lower()


def _delegation_only() -> str | None:
    """Read exactly one header from the request context and drop everything else.

    Narrowing here rather than relying on the library's exclusion list is what keeps
    this independent of the FastMCP version in use.
    """
    try:
        # No include_all: never ask for credential headers in the first place.
        headers = get_http_headers()
    except Exception:
        # Documented never to raise, but a transport seam is the wrong place to
        # discover otherwise. An unreadable context is not an authenticated human.
        return None
    return headers.get(_DELEGATION_KEY)


def current_delegation() -> str | None:
    """The delegation token for this request, or None. Never model-supplied.

    Reads the live FastMCP request context. Outside an HTTP request — an in-process
    transport, a unit test, a stdio client — ``get_http_headers()`` returns ``{}``
    rather than raising, so this yields ``None`` and callers fail closed.
    """
    value = _delegation_only()
    return value.strip() if isinstance(value, str) and value.strip() else None


NO_SESSION = {
    "ok": False,
    "error": "no_authenticated_human_session",
    "detail": "Ask the person to sign in to Episteck Home; identity cannot be supplied here.",
}
