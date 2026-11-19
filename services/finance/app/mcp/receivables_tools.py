"""MCP tools for receivables: thin adapters over ``ReceivablesService``.

No tool accepts an actor, a workspace, a token, an account or SQL. The delegated human
session comes from the transport (``current_delegation``). Money is a decimal string.
Docstrings are the model's only manual: keep them short and free of example figures.
"""
from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..receivables.service import ReceivablesService
from ..service import (
    AccessDenied, FeatureOff, PolicyUnavailable, SessionInvalid, UnsupportedValuation,
)
from ..session import current_delegation

logger = logging.getLogger("finance.mcp")

_REFUSALS = (
    (SessionInvalid, "session_invalid"),
    (AccessDenied, "access_denied"),
    (PolicyUnavailable, "service_unavailable"),
    (FeatureOff, "feature_off"),
    (UnsupportedValuation, "unsupported_valuation_currency"),
)


def refusal_code(error: Exception) -> str | None:
    return next((code for exc, code in _REFUSALS if isinstance(error, exc)), None)


def _call(method, *args, **kwargs) -> dict:
    """One service call with the caller's delegation; refusals become typed results."""
    try:
        return method(current_delegation(), *args, **kwargs)
    except Exception as error:  # never str(error): it may hold labels or figures
        code = refusal_code(error)
        if code is None:
            logger.error("receivables tool failed: %s", type(error).__name__)
            code = "internal_error"
        return {"ok": False, "error": code}


def register_receivables_tools(mcp: FastMCP, service: ReceivablesService) -> None:
    @mcp.tool
    def finance_receivables(counterparty: str | None = None) -> dict:
        """Who owes what: debts per person, held funds and the exchange partner, optionally
        for one counterparty. Every figure you state must come from this tool's result."""
        return _call(service.receivables, counterparty)

    @mcp.tool
    def finance_exchanges(status: str | None = None, since: str | None = None) -> dict:
        """List recorded exchanges with their lines and state; filter by status or by a
        start date (YYYY-MM-DD)."""
        return _call(service.exchanges, status, since)

    @mcp.tool
    def finance_pending(for_delivery: bool = False) -> dict:
        """Open questions for the owner, each with a code and numbered or named choices.
        for_delivery=true returns only those due now and marks them as sent."""
        return _call(service.pending, for_delivery)

    @mcp.tool
    def finance_explain(ref: str) -> dict:
        """History and corrections of one reference (an exchange, receipt, entry or pending
        code). ref="ignored" lists payments the owner marked as not exchanges."""
        return _call(service.explain, ref)

    @mcp.tool
    def finance_record_exchange(total_usd: str, lines: list[dict], evidence: dict | None = None,
                                delivered_on: str | None = None) -> dict:
        """Propose an exchange with the partner and how it splits per payer (lines of
        payer and usd). This shows an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, 'yes'). Copy figures from a screenshot as written."""
        return _call(service.propose_exchange, total_usd, lines, evidence, delivered_on)

    @mcp.tool
    def finance_record_receipt(payer: str, amount: str, currency: str, kind: str,
                               received_on: str | None = None,
                               description: str | None = None) -> dict:
        """Propose that a person paid back (kind CASH, BANK or IN_KIND). This shows an echo;
        the owner must tap or answer before you call finance_resolve_pending(code, 'yes')."""
        return _call(service.propose_receipt, payer, amount, currency, kind, received_on,
                     description)

    @mcp.tool
    def finance_resolve_pending(code: str, choice: str, details: dict | None = None) -> dict:
        """Answer an open item by its code with the owner's own choice. Send 'yes' only after
        the owner tapped or said yes to the echo in this conversation, never on your own."""
        return _call(service.resolve, code, choice, details)

    @mcp.tool
    def finance_mark_held_cash(counterparty: str, amount: str, currency: str) -> dict:
        """Record how much cash a person currently holds for us (display only, no
        confirmation step)."""
        return _call(service.mark_held_cash, counterparty, amount, currency)

    @mcp.tool
    def finance_correct_exchange(exchange_ref: str, lines: list[dict], reason: str) -> dict:
        """Propose new lines for an existing exchange. This shows an echo; the owner must
        tap or answer before you call finance_resolve_pending(code, 'yes')."""
        return _call(service.propose_correction, exchange_ref, lines, None, reason)

    @mcp.tool
    def finance_reallocate(receipt_ref: str, allocations: list[dict]) -> dict:
        """Propose moving a receipt between exchanges (allocations of exchange and amount).
        This shows an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, 'yes')."""
        return _call(service.propose_reallocate, receipt_ref, allocations)

    @mcp.tool
    def finance_forgive(target: str, amount: str | None = None,
                        reason: str | None = None) -> dict:
        """Propose forgiving all or part of what a person owes. This shows an echo; the
        owner must tap or answer before you call finance_resolve_pending(code, 'yes')."""
        return _call(service.propose_forgive, target, amount, reason)

    @mcp.tool
    def finance_setup_counterparty(label: str, kind: str, aliases: list[str] | None = None,
                                   pay_currency: str | None = None,
                                   settles_to: str | None = None) -> dict:
        """Propose a new person, fund or partner with its aliases. This shows an echo; the
        owner must tap or answer before you call finance_resolve_pending(code, 'yes')."""
        return _call(service.propose_counterparty, label, kind, aliases, pay_currency,
                     settles_to)

    @mcp.tool
    def finance_record_opening(counterparty: str, amount: str, currency: str, basis: str,
                               note: str) -> dict:
        """Propose a starting balance stated by the owner, with its basis and a note. This
        shows an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, 'yes')."""
        return _call(service.propose_opening, counterparty, amount, currency, basis, note)

    @mcp.tool
    def finance_reverse(ref: str, reason: str) -> dict:
        """Propose undoing an exchange, receipt, rule or answer by its reference. This shows
        an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, 'yes')."""
        return _call(service.propose_reverse, ref, reason)


__all__: list[Any] = ["register_receivables_tools", "refusal_code"]
