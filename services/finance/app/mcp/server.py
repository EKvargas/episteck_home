"""Thin MCP adapter over FinanceService. The chat and the web use the same function.

No tool accepts an actor, a workspace, a token or SQL. The delegated human session is
read from the transport by ``app.session``; Home resolves the actor.
"""
from __future__ import annotations

import os

from fastmcp import FastMCP

from ..receivables.service import ReceivablesService
from ..service import FinanceService
from ..session import current_delegation
from .receivables_tools import (
    quiet_invalid_arguments, refusal_code, register_receivables_tools,
)


def create_mcp(service: FinanceService,
               receivables: ReceivablesService | None = None) -> FastMCP:
    quiet_invalid_arguments()
    mcp = FastMCP("episteck-finance")

    @mcp.tool
    def finance_overview(valuation_currency: str | None = None) -> dict:
        """How much do we have and where? Per-currency, per-liquidity subtotals with each
        account's source and date. Optionally a dated EUR valuation (valuation_currency="EUR").
        Every figure you state must come from this tool's result in this turn."""
        try:
            return service.overview(current_delegation(), valuation_currency)
        except Exception as error:
            code = refusal_code(error)
            if code is None:
                raise
            return {"ok": False, "error": code}

    if receivables is not None:
        register_receivables_tools(mcp, receivables)
    return mcp


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    from ..deps import build_receivables_service, build_service

    create_mcp(build_service(), build_receivables_service()).run(
        transport="http", host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "9936")))
