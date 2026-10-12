"""Thin MCP adapter over FinanceService. The chat and the web use the same function.

No tool accepts an actor, a workspace, a token or SQL. The delegated human session is
read from the transport by ``app.session``; Home resolves the actor.
"""
from __future__ import annotations

import os

from fastmcp import FastMCP

from ..service import (
    AccessDenied, FeatureOff, FinanceService, PolicyUnavailable, SessionInvalid,
    UnsupportedValuation,
)
from ..session import current_delegation

_REFUSALS = (
    (SessionInvalid, "session_invalid"),
    (AccessDenied, "access_denied"),
    (PolicyUnavailable, "service_unavailable"),
    (FeatureOff, "feature_off"),
    (UnsupportedValuation, "unsupported_valuation_currency"),
)


def create_mcp(service: FinanceService) -> FastMCP:
    mcp = FastMCP("episteck-finance")

    @mcp.tool
    def finance_overview(valuation_currency: str | None = None) -> dict:
        """How much do we have and where? Per-currency, per-liquidity subtotals with each
        account's source and date. Optionally a dated EUR valuation (valuation_currency="EUR").
        Every figure you state must come from this tool's result in this turn."""
        try:
            return service.overview(current_delegation(), valuation_currency)
        except tuple(exc for exc, _ in _REFUSALS) as error:
            code = next(code for exc, code in _REFUSALS if isinstance(error, exc))
            return {"ok": False, "error": code}

    return mcp


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    from ..deps import build_service

    create_mcp(build_service()).run(
        transport="http", host="0.0.0.0", port=int(os.environ.get("MCP_PORT", "9936")))
