"""Home MCP tool-contract tests (G1.6).

The strongest guarantee in this stage: the model is never OFFERED a way to name an
actor. These tests assert that mechanically against the live tool schemas, so any
future regression that reintroduces an actor parameter fails the build.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("HOME_CONTROL_PLANE_URL", "https://home.invalid")
os.environ.setdefault("HOME_API_KEY", "test-key")
os.environ.setdefault("HOME_API_SECRET", "test-secret")

from home_mcp import context, server  # noqa: E402

EXPECTED_TOOLS = {
    "whoami",
    "get_person",
    "list_my_circles",
    "list_circle_members",
    "list_people_i_care_for",
    "get_access_to_person",
    "check_access",
    "get_care_dashboard",
}

# Anything that would let the model assert identity or carry credentials.
FORBIDDEN_PARAMETERS = {
    "actor_person_id",
    "actor",
    "actor_id",
    "user",
    "user_name",
    "username",
    "delegation",
    "token",
    "access_token",
    "bearer",
    "api_key",
    "api_secret",
    "session",
    "session_id",
}


async def _tools():
    return await server.mcp.get_tools()


@pytest.mark.asyncio
async def test_exposes_exactly_the_expected_business_tools():
    assert set(await _tools()) == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_no_tool_exposes_an_actor_or_credential_parameter():
    for name, tool in (await _tools()).items():
        properties = (tool.parameters or {}).get("properties", {}) or {}
        for parameter in properties:
            assert (
                parameter.lower() not in FORBIDDEN_PARAMETERS
            ), f"tool {name} must not expose parameter {parameter}"


@pytest.mark.asyncio
async def test_self_scoped_tools_take_no_parameters_at_all():
    """'My circles' is about the signed-in person; nothing to supply."""
    tools = await _tools()
    for name in ("whoami", "list_my_circles", "list_people_i_care_for", "get_care_dashboard"):
        properties = (tools[name].parameters or {}).get("properties", {}) or {}
        assert properties == {}, f"{name} must take no parameters"


@pytest.mark.asyncio
async def test_cross_person_tools_still_take_a_subject():
    """Subject stays: the person legitimately asks about someone else."""
    tools = await _tools()
    assert "subject_person_id" in (tools["check_access"].parameters or {})["properties"]
    assert "person_id" in (tools["get_person"].parameters or {})["properties"]
    assert "circle_id" in (tools["list_circle_members"].parameters or {})["properties"]


@pytest.mark.asyncio
async def test_no_tool_description_invites_supplying_an_actor():
    for name, tool in (await _tools()).items():
        description = (tool.description or "").lower()
        assert "actor_person_id" not in description, name


def test_delegation_is_read_from_transport_not_arguments():
    context.set_delegation(None)
    assert context.current_delegation() is None
    context.set_delegation("  tok-123  ")
    assert context.current_delegation() == "tok-123"
    context.set_delegation("   ")
    assert context.current_delegation() is None


def test_delegation_header_extraction_is_defensive():
    assert context.delegation_from_headers(None) is None
    assert context.delegation_from_headers({}) is None
    assert context.delegation_from_headers({"X-Episteck-Delegation": "t"}) == "t"
    assert context.delegation_from_headers({"x-episteck-delegation": "t"}) == "t"
    assert context.delegation_from_headers({"X-Episteck-Delegation": "  "}) is None


def test_person_scoped_tools_fail_closed_without_a_session():
    context.set_delegation(None)
    assert server.list_my_circles.fn() == context.NO_SESSION
    assert server.get_person.fn("PSN-1") == context.NO_SESSION
    decision = server.check_access.fn("PSN-1", "NUTRITION", "VIEW")
    assert decision["allow"] is False
