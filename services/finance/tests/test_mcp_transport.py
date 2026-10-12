"""The MCP adapter over a REAL FastMCP HTTP server (same reasoning as Nutrition's suite).

What is under test is the production tool and its header binding, not a copy of it.
"""
from __future__ import annotations

import asyncio
import inspect
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.mcp.server import create_mcp
from tests.support import FakeAuthorizer, seeded_service

HEADER = "X-Episteck-Delegation"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(service):
    mcp = create_mcp(service)
    port = _free_port()
    threading.Thread(
        target=lambda: mcp.run(transport="http", host="127.0.0.1", port=port), daemon=True
    ).start()
    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover
        pytest.fail("FastMCP server did not start")
    return url


def _call(url, headers, args=None):
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async def run():
        async with Client(StreamableHttpTransport(url, headers=headers)) as client:
            result = await client.call_tool("finance_overview", args or {}, raise_on_error=False)
            return result.data

    return asyncio.run(run())


def test_tool_reads_the_delegation_from_the_header_and_returns_the_overview(tmp_path):
    service, authz = seeded_service(tmp_path)
    url = _serve(service)
    data = _call(url, {HEADER: "tok-1", "Authorization": "Bearer machine", "Cookie": "s=1"})
    assert data["subtotals"][0]["amount"] == "1234.56"
    assert authz.calls[0][0] == "tok-1"


def test_mcp_and_rest_return_identical_overviews(tmp_path):
    service, _ = seeded_service(tmp_path)
    rest = TestClient(create_app(service)).get("/overview", headers={HEADER: "tok"}).json()
    mcp = _call(_serve(service), {HEADER: "tok"})
    assert mcp == rest


def test_missing_delegation_gives_a_typed_business_safe_refusal(tmp_path):
    service, authz = seeded_service(tmp_path)
    data = _call(_serve(service), {})
    assert data == {"ok": False, "error": "session_invalid"}
    assert authz.calls == []


def test_denial_does_not_leak_homes_reason(tmp_path):
    service, _ = seeded_service(tmp_path, FakeAuthorizer(allow={"SELF": False}))
    data = _call(_serve(service), {HEADER: "tok"})
    assert data == {"ok": False, "error": "access_denied"}


def test_the_tool_schema_has_no_actor_workspace_or_token_parameter(tmp_path):
    service, _ = seeded_service(tmp_path)
    mcp = create_mcp(service)
    tool = asyncio.run(mcp.get_tool("finance_overview"))
    assert set(tool.parameters.get("properties", {})) == {"valuation_currency"}
    assert {"actor", "workspace_id", "delegation", "token"}.isdisjoint(
        inspect.signature(tool.fn).parameters)
