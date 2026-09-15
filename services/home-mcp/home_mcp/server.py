"""Home Agent MCP tools backed exclusively by the Frappe Home Control Plane."""
from __future__ import annotations

import os

from fastmcp import FastMCP

from .client import HomeControlPlaneClient


mcp = FastMCP("episteck-home")
_client = HomeControlPlaneClient.from_env()


@mcp.tool
def get_person(actor_person_id: str, person_id: str) -> dict:
    """Get a discoverable Person. G1.5 actor ids must be explicit synthetic ids."""
    return _client.get_person(actor_person_id, person_id)


@mcp.tool
def list_my_circles(actor_person_id: str) -> list | dict:
    """List circles belonging to the explicit synthetic acting Person."""
    return _client.list_my_circles(actor_person_id)


@mcp.tool
def list_circle_members(actor_person_id: str, circle_id: str) -> list | dict:
    """List a circle roster only when the acting Person may discover that circle."""
    return _client.list_circle_members(actor_person_id, circle_id)


@mcp.tool
def list_people_i_care_for(actor_person_id: str) -> list | dict:
    """List active care relationships where the acting Person is the caregiver."""
    return _client.list_people_i_care_for(actor_person_id)


@mcp.tool
def get_access_to_person(actor_person_id: str, subject_person_id: str) -> dict:
    """List only this actor's effective access to a discoverable subject Person."""
    return _client.get_access_to_person(actor_person_id, subject_person_id)


@mcp.tool
def check_access(
    actor_person_id: str,
    subject_person_id: str,
    domain: str,
    action: str = "VIEW",
) -> dict:
    """Ask canonical Home policy. On false/error, stop; never retry or call downstream."""
    return _client.check_access(actor_person_id, subject_person_id, domain, action)


@mcp.tool
def get_care_dashboard(actor_person_id: str) -> dict:
    """Get the acting Person's filtered circles and active care relationships."""
    return _client.get_care_dashboard(actor_person_id)


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "9932")),
    )
