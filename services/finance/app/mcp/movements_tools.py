"""MCP tools for movements: thin read-only adapters over ``MovementsService``.

No tool accepts an actor, a workspace, a token or SQL. The delegated human session comes
from the transport. Docstrings are the model's only manual: no example figures.
"""
from __future__ import annotations

import logging

from fastmcp import FastMCP

from ..movements.service import MovementsService
from ..session import current_delegation
from .receivables_tools import refusal_code

logger = logging.getLogger("finance.mcp")


def _call(method, *args, **kwargs) -> dict:
    """One service call with the caller's delegation; refusals become typed results."""
    try:
        return method(current_delegation(), *args, **kwargs)
    except Exception as error:  # never str(error): it may hold labels or figures
        code = refusal_code(error)
        if code is None:
            logger.error("movements tool failed: %s", type(error).__name__)
            code = "internal_error"
        return {"ok": False, "error": code}


def register_movements_tools(mcp: FastMCP, service: MovementsService) -> None:
    @mcp.tool
    def finance_movements(text: str | None = None, amount: str | None = None,
                          account: str | None = None, direction: str | None = None,
                          since: str | None = None, until: str | None = None,
                          limit: int | None = None) -> dict:
        """Search bank movements of the visible accounts by text, amount, account, direction (in or out) and dates (YYYY-MM-DD, default the last 90 days). Each line says what it is for Finance. Accounts without descriptions are found by amount and date only. Every figure you state must come from this tool's result."""
        return _call(service.movements, text, amount, account, direction, since, until, limit)

    @mcp.tool
    def finance_summary(period: str | None = None) -> dict:
        """Own income, own spending (family help included and broken down by person) and net per currency for a month (YYYY-MM, default this month) or a year (YYYY), with what was set aside and whether the data is complete. Every figure you state must come from this tool's result."""
        return _call(service.summary, period)
