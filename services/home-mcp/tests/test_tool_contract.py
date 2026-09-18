"""Home MCP tool-contract tests (G1.6).

The strongest guarantee in this stage: the model is never OFFERED a way to name an
actor. These tests assert that mechanically against the live tool schemas, so any
future regression that reintroduces an actor parameter fails the build.

WHY THIS FILE WAS REWRITTEN (test truthfulness only, no runtime change)
----------------------------------------------------------------------
It was written against the FastMCP 2.x API while ``pyproject.toml`` pins
``fastmcp==4.0.3``, which produced two different failure modes:

1. LOUD — ``await mcp.get_tools()`` no longer exists in 4.x (it is
   ``await mcp.list_tools()``, returning a ``Sequence[Tool]`` rather than a dict).
   Six tests errored on the pinned version. They passed locally only because an
   older fastmcp happened to be installed.

2. SILENT, and worse — module-level lookups like ``getattr(server, name).fn``
   found NOTHING. In 4.0.3 ``@mcp.tool`` returns the PLAIN FUNCTION, so there is no
   ``.fn`` attribute to reach, and a loop written as
   ``if getattr(tool, "fn", None) is None: continue`` skipped every tool and passed
   while inspecting zero of them. Measured on 4.0.3: "tools reachable via .fn: 0".

The second mode is the dangerous one: a green suite asserting nothing about actor
and credential parameters. So discovery now goes through ``list_tools()`` — the
registry the model actually sees — and every schema test asserts a NON-ZERO,
EXPECTED tool count, so the suite cannot quietly stop testing anything again.

Note that the ``Tool`` objects returned by ``list_tools()`` DO carry ``.parameters``
and ``.fn``; it is only the module-level attribute lookup that is empty. The
assertions themselves were always right — they were simply never reached.
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


async def _tools() -> dict:
    """The live tool registry, keyed by name.

    ``list_tools()`` is the 4.x API and returns a ``Sequence[Tool]``; the dict is
    rebuilt here so the assertions below can address tools by name as before.
    This is the registry the MODEL sees, which is what these tests are about.
    """
    return {tool.name: tool for tool in await server.mcp.list_tools()}


def _properties(tool) -> dict:
    return (tool.parameters or {}).get("properties", {}) or {}


@pytest.mark.asyncio
async def test_tool_discovery_actually_finds_the_tools():
    """Guard against vacuous assertions in every test below.

    If discovery silently returns nothing — as the old ``.fn`` lookup did — the
    schema tests would iterate an empty collection and pass without checking a
    single tool. This test exists so that failure is impossible to miss.
    """
    tools = await _tools()
    assert len(tools) == len(EXPECTED_TOOLS) > 0, (
        f"expected {len(EXPECTED_TOOLS)} tools, discovered {len(tools)}: {sorted(tools)}"
    )
    # Each discovered tool must expose the schema these tests rely on.
    for name, tool in tools.items():
        assert tool.parameters is not None, f"{name} exposes no parameter schema"


@pytest.mark.asyncio
async def test_exposes_exactly_the_expected_business_tools():
    assert set(await _tools()) == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_no_tool_exposes_an_actor_or_credential_parameter():
    tools = await _tools()
    assert len(tools) == len(EXPECTED_TOOLS), "discovery must cover every tool"
    inspected = 0
    for name, tool in tools.items():
        for parameter in _properties(tool):
            inspected += 1
            assert (
                parameter.lower() not in FORBIDDEN_PARAMETERS
            ), f"tool {name} must not expose parameter {parameter}"
    # The cross-person tools carry subject parameters, so a zero here would mean no
    # schema was read at all rather than a genuinely parameterless tool set.
    assert inspected > 0, "no tool parameters were inspected"


@pytest.mark.asyncio
async def test_self_scoped_tools_take_no_parameters_at_all():
    """'My circles' is about the signed-in person; nothing to supply."""
    tools = await _tools()
    for name in ("whoami", "list_my_circles", "list_people_i_care_for", "get_care_dashboard"):
        assert name in tools, f"{name} was not discovered"
        assert _properties(tools[name]) == {}, f"{name} must take no parameters"


@pytest.mark.asyncio
async def test_cross_person_tools_still_take_a_subject():
    """Subject stays: the person legitimately asks about someone else."""
    tools = await _tools()
    assert "subject_person_id" in _properties(tools["check_access"])
    assert "person_id" in _properties(tools["get_person"])
    assert "circle_id" in _properties(tools["list_circle_members"])


@pytest.mark.asyncio
async def test_no_tool_description_invites_supplying_an_actor():
    tools = await _tools()
    assert len(tools) == len(EXPECTED_TOOLS), "discovery must cover every tool"
    for name, tool in tools.items():
        description = (tool.description or "").lower()
        assert "actor_person_id" not in description, name


@pytest.mark.asyncio
async def test_every_tool_function_is_reachable_for_inspection():
    """The signatures behind the schemas are inspectable, on any fastmcp version.

    The previous suite reached tool functions as ``getattr(server, name).fn``. On
    4.0.3 that attribute does not exist, so the loops skipped everything. Going
    through the registry yields a real callable for every tool.
    """
    import inspect

    tools = await _tools()
    checked = 0
    for name, tool in tools.items():
        function = getattr(tool, "fn", None)
        assert callable(function), f"{name} exposes no inspectable function"
        parameters = set(inspect.signature(function).parameters)
        assert not (
            parameters & FORBIDDEN_PARAMETERS
        ), f"{name} accepts {parameters & FORBIDDEN_PARAMETERS}"
        checked += 1
    assert checked == len(EXPECTED_TOOLS), f"only inspected {checked} tool functions"


def test_delegation_is_read_from_transport_not_arguments(monkeypatch):
    """The token comes from the live request context, never from a tool argument.

    Patched at the FastMCP seam rather than through a local setter: there is no
    setter any more, which is the point — the transport owns this value.
    """
    monkeypatch.setattr(context, "get_http_headers", lambda: {})
    assert context.current_delegation() is None

    monkeypatch.setattr(
        context, "get_http_headers", lambda: {"x-episteck-delegation": "  tok-123  "}
    )
    assert context.current_delegation() == "tok-123"

    monkeypatch.setattr(
        context, "get_http_headers", lambda: {"x-episteck-delegation": "   "}
    )
    assert context.current_delegation() is None


def test_delegation_lookup_is_defensive(monkeypatch):
    """Anything other than a usable string is no session."""
    for headers in ({}, {"x-episteck-delegation": None}, {"other": "x"}):
        monkeypatch.setattr(context, "get_http_headers", lambda h=headers: h)
        assert context.current_delegation() is None


def test_unreadable_request_context_fails_closed(monkeypatch):
    """get_http_headers is documented never to raise; if it does, deny anyway."""

    def boom():
        raise RuntimeError("no request context")

    monkeypatch.setattr(context, "get_http_headers", boom)
    assert context.current_delegation() is None


def _callable(name):
    """The underlying function for a tool, on any fastmcp version.

    2.x wraps a decorated tool in a FunctionTool exposing ``.fn``; 4.0.3 leaves the
    plain function in the module. ``getattr(x, "fn", x)`` handles both — the old
    ``.fn`` form raised AttributeError on the pinned version.
    """
    tool = getattr(server, name)
    function = getattr(tool, "fn", tool)
    assert callable(function), f"{name} is not callable"
    return function


def test_person_scoped_tools_fail_closed_without_a_session(monkeypatch):
    monkeypatch.setattr(context, "get_http_headers", lambda: {})
    assert _callable("list_my_circles")() == context.NO_SESSION
    assert _callable("get_person")("PSN-1") == context.NO_SESSION
    decision = _callable("check_access")("PSN-1", "NUTRITION", "VIEW")
    assert decision["allow"] is False
