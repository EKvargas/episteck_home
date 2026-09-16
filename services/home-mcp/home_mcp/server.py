"""Home Agent MCP tools backed exclusively by the Frappe Home Control Plane.

G1.6 TRUSTED ACTOR CONTRACT
---------------------------
No tool accepts ``actor_person_id``. The acting Person is resolved server-side by the
Control Plane from the authenticated human session carried in transport context. The
model therefore CANNOT choose, alter, or observe who it is acting as.

``subject_person_id`` and ``circle_id`` remain parameters — the person legitimately
asks about someone else — and every one of them is still gated by ``can_access``.

A deny, error, or missing-session result is TERMINAL. The agent may not retry with
altered parameters and may not call a downstream domain tool.
"""
from __future__ import annotations

import os

from fastmcp import FastMCP

from .client import HomeControlPlaneClient
from .context import NO_SESSION, current_delegation


mcp = FastMCP("episteck-home")
_client = HomeControlPlaneClient.from_env()


def _delegation() -> str | None:
    """Trusted human session for this request. Never a tool parameter."""
    return current_delegation()


@mcp.tool
def whoami() -> dict:
    """Report who the Control Plane resolved the signed-in person to be."""
    delegation = _delegation()
    if not delegation:
        return NO_SESSION
    return _client.whoami(delegation)


@mcp.tool
def get_person(person_id: str) -> dict:
    """Get a discoverable Person. The acting person comes from the signed-in session."""
    delegation = _delegation()
    if not delegation:
        return NO_SESSION
    return _client.get_person(person_id, delegation)


@mcp.tool
def list_my_circles() -> list | dict:
    """List circles belonging to the signed-in person."""
    delegation = _delegation()
    if not delegation:
        return NO_SESSION
    return _client.list_my_circles(delegation)


@mcp.tool
def list_circle_members(circle_id: str) -> list | dict:
    """List a circle roster only when the signed-in person may discover that circle."""
    delegation = _delegation()
    if not delegation:
        return NO_SESSION
    return _client.list_circle_members(circle_id, delegation)


@mcp.tool
def list_people_i_care_for() -> list | dict:
    """List active care relationships where the signed-in person is the caregiver."""
    delegation = _delegation()
    if not delegation:
        return NO_SESSION
    return _client.list_people_i_care_for(delegation)


@mcp.tool
def get_access_to_person(subject_person_id: str) -> dict:
    """List the signed-in person's effective access to a discoverable subject."""
    delegation = _delegation()
    if not delegation:
        return NO_SESSION
    return _client.get_access_to_person(subject_person_id, delegation)


@mcp.tool
def check_access(subject_person_id: str, domain: str, action: str = "VIEW") -> dict:
    """Ask canonical Home policy. On false/error, stop; never retry or call downstream."""
    delegation = _delegation()
    if not delegation:
        return {
            "allow": False,
            "reason": "no authenticated human session (fail closed)",
        }
    return _client.check_access(subject_person_id, domain, action, delegation)


@mcp.tool
def get_care_dashboard() -> dict:
    """Get the signed-in person's filtered circles and active care relationships."""
    delegation = _delegation()
    if not delegation:
        return NO_SESSION
    return _client.get_care_dashboard(delegation)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "9932")),
    )
