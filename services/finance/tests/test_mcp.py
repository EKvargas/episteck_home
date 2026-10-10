from __future__ import annotations

import pytest

from finance_pilot.mcp import create_mcp
from test_pilot import FinancePilot, IsolatedAuthorizer, OWNER, ROSTER, message


@pytest.mark.asyncio
async def test_hermes_sees_only_two_message_id_tools(tmp_path):
    pilot = FinancePilot(tmp_path / "finance.sqlite", OWNER, IsolatedAuthorizer(), ROSTER)
    mcp = create_mcp(pilot)
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == {"record_finance_message", "answer_finance_question"}
    for tool in tools.values():
        assert set(tool.parameters["properties"]) == {"source_message_id"}


@pytest.mark.asyncio
async def test_tool_delegation_is_transport_only_and_denies_without_it(tmp_path, monkeypatch):
    pilot = FinancePilot(tmp_path / "finance.sqlite", OWNER, IsolatedAuthorizer(), ROSTER)
    pilot.receive(message("req-1", "sister", "Please send 5000 VES to Rosa."))
    import finance_pilot.mcp as module
    monkeypatch.setattr(module, "current_delegation", lambda: None)
    mcp = create_mcp(pilot)
    tool = next(tool for tool in await mcp.list_tools() if tool.name == "record_finance_message")
    assert tool.fn("req-1")["error"] == "access_denied"
    assert pilot.event_count("olin-session") == 0


@pytest.mark.asyncio
async def test_hermes_tool_records_source_id_without_sender_argument(tmp_path, monkeypatch):
    pilot = FinancePilot(tmp_path / "finance.sqlite", OWNER, IsolatedAuthorizer(), ROSTER)
    pilot.receive(message("req-1", "sister", "Please send 5000 VES to Rosa."))
    import finance_pilot.mcp as module
    monkeypatch.setattr(module, "current_delegation", lambda: "olin-session")
    tools = {tool.name: tool for tool in await create_mcp(pilot).list_tools()}
    result = tools["record_finance_message"].fn("req-1")
    assert result == {"status": "recorded", "kind": "request", "source_message_id": "req-1"}
    assert pilot.snapshot("olin-session")["requests"]["req-1"]["requester_id"] == ROSTER["sister"]


@pytest.mark.asyncio
async def test_inprocess_mcp_protocol_records_message(tmp_path, monkeypatch):
    from fastmcp import Client

    pilot = FinancePilot(tmp_path / "finance.sqlite", OWNER, IsolatedAuthorizer(), ROSTER)
    pilot.receive(message("req-1", "sister", "Please send 5000 VES to Rosa."))
    import finance_pilot.mcp as module
    monkeypatch.setattr(module, "current_delegation", lambda: "olin-session")
    async with Client(create_mcp(pilot)) as client:
        result = await client.call_tool("record_finance_message", {"source_message_id": "req-1"})
    assert not result.is_error
    assert pilot.snapshot("olin-session")["requests"]["req-1"]["ves_amount"] == "5000"
