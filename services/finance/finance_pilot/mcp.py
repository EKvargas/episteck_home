"""Two business-safe Hermes tools for the local Finance pilot."""
from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from .core import FinancePilot


def current_delegation() -> str | None:
    try:
        value = get_http_headers().get("x-episteck-delegation")
    except Exception:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def create_mcp(pilot: FinancePilot) -> FastMCP:
    mcp = FastMCP("olin-finance-pilot")

    @mcp.tool
    def record_finance_message(source_message_id: str) -> dict:
        """Record a clear fact from an already ingested trusted message, or ask one question."""
        try:
            return pilot.record_message(current_delegation(), source_message_id)
        except PermissionError:
            return {"error": "access_denied"}

    @mcp.tool
    def answer_finance_question(source_message_id: str) -> dict:
        """Answer an owner's private debt question from an ingested message."""
        try:
            return pilot.answer_question(current_delegation(), source_message_id)
        except PermissionError:
            return {"error": "access_denied"}

    return mcp
