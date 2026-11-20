"""MCP tools for receivables: thin adapters over ``ReceivablesService``.

No tool accepts an actor, a workspace, a token, an account or SQL. The delegated human
session comes from the transport (``current_delegation``). Money is a decimal string.
Docstrings are the model's only manual: keep them short and free of example figures.
"""
from __future__ import annotations

import logging

from pydantic import ConfigDict
# typing_extensions, not typing: the image runs Python 3.11, where pydantic refuses
# typing.TypedDict as a tool argument type.
from typing_extensions import TypedDict

from fastmcp import FastMCP

from ..receivables.service import ReceivablesService
from ..service import (
    AccessDenied, FeatureOff, PolicyUnavailable, SessionInvalid, UnsupportedValuation,
)
from ..session import current_delegation

logger = logging.getLogger("finance.mcp")


# extra=allow: a misspelt key reaches the service, which refuses it by name (it is never
# silently dropped, which would disable e.g. the VES duplicate check).
_KEEP_EXTRAS = ConfigDict(extra="allow")


class Line(TypedDict, total=False):
    __pydantic_config__ = _KEEP_EXTRAS
    payer: str  # a counterparty name or alias, or "owner"
    usd: str  # decimal string
    debt_currency: str
    beneficiary: str
    eur: str  # decimal string


class Evidence(TypedDict, total=False):
    __pydantic_config__ = _KEEP_EXTRAS
    partner: str
    ves_amount: str  # decimal string, copied as written
    ves_reference: str  # the partner's reference: the natural duplicate key
    date: str  # YYYY-MM-DD


class Allocation(TypedDict, total=False):
    __pydantic_config__ = _KEEP_EXTRAS
    exchange: str  # an exchange or item reference such as C1
    amount: str  # decimal string


class Details(TypedDict, total=False):
    __pydantic_config__ = _KEEP_EXTRAS
    counterparty: str  # who the money was from, when the answer is "other"
    remember: bool  # false: do not save a payer rule


_REFUSALS = (
    (SessionInvalid, "session_invalid"),
    (AccessDenied, "access_denied"),
    (PolicyUnavailable, "service_unavailable"),
    (FeatureOff, "feature_off"),
    (UnsupportedValuation, "unsupported_valuation_currency"),
)


class _ToolNameOnly(logging.Filter):
    """FastMCP logs rejected arguments with their values; keep the tool name only."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if message.startswith("Invalid arguments for tool"):
            record.msg = message.split(":", 1)[0] + ": arguments rejected"
            record.args = None
            record.exc_info = None
        return True


def quiet_invalid_arguments() -> None:
    log = logging.getLogger("fastmcp.server.server")
    if not any(isinstance(f, _ToolNameOnly) for f in log.filters):
        log.addFilter(_ToolNameOnly())


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
        """List recorded exchanges with their lines. status is OPEN or PAID; since is a
        start date (YYYY-MM-DD)."""
        return _call(service.exchanges, status, since)

    @mcp.tool
    def finance_pending(for_delivery: bool = False) -> dict:
        """Open questions for the owner, each with a code and its choices. for_delivery is
        only for the scheduled delivery job: it marks the items as sent, so never set it
        in a conversation."""
        return _call(service.pending, for_delivery)

    @mcp.tool
    def finance_explain(ref: str) -> dict:
        """History and corrections of one reference: an exchange (C<n>), receipt (R<n>),
        funding (F<n>), entry (E<n>) or pending code (P<n>). ref="ignored" lists payments
        the owner marked as not exchanges."""
        return _call(service.explain, ref)

    @mcp.tool
    def finance_record_exchange(total_usd: str, lines: list[Line],
                                evidence: Evidence | None = None,
                                delivered_on: str | None = None) -> dict:
        """Propose an exchange with the partner and how it splits per payer. This shows an
        echo; the owner must tap or answer before you call
        finance_resolve_pending(code, <the owner's answer>). Copy figures from a screenshot
        as written; always pass the partner's reference as evidence.ves_reference."""
        return _call(service.propose_exchange, total_usd, lines, evidence, delivered_on)

    @mcp.tool
    def finance_record_receipt(payer: str, amount: str, currency: str, kind: str,
                               received_on: str | None = None,
                               description: str | None = None) -> dict:
        """Propose that a person paid back in cash (kind CASH) or in goods (kind IN_KIND,
        which needs a description). Bank payments come from the bank sync, never record
        them here. This shows an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, <the owner's answer>)."""
        return _call(service.propose_receipt, payer, amount, currency, kind, received_on,
                     description)

    @mcp.tool
    def finance_resolve_pending(code: str, choice: str, details: Details | None = None) -> dict:
        """Answer an open item by its code with the owner's own choice, never your own
        guess: send 'yes' only after the owner tapped or said yes to the echo in this
        conversation. A possible duplicate takes only the owner's 'other' or 'same'."""
        return _call(service.resolve, code, choice, details)

    @mcp.tool
    def finance_mark_held_cash(counterparty: str, amount: str, currency: str) -> dict:
        """Record how much cash a person holds for us, as the owner states it (display
        only, no confirmation step)."""
        return _call(service.mark_held_cash, counterparty, amount, currency)

    @mcp.tool
    def finance_correct_exchange(exchange_ref: str, lines: list[Line], reason: str) -> dict:
        """Propose new lines for an existing exchange. This shows an echo; the owner must
        tap or answer before you call finance_resolve_pending(code, <the owner's answer>)."""
        return _call(service.propose_correction, exchange_ref, lines, None, reason)

    @mcp.tool
    def finance_reallocate(receipt_ref: str, allocations: list[Allocation]) -> dict:
        """Propose moving a receipt between exchanges. This shows an echo; the owner must
        tap or answer before you call finance_resolve_pending(code, <the owner's answer>)."""
        return _call(service.propose_reallocate, receipt_ref, allocations)

    @mcp.tool
    def finance_forgive(target: str, reason: str, amount: str | None = None) -> dict:
        """Propose forgiving all (or the given amount) of what a person owes; the reason is
        required. This shows an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, <the owner's answer>)."""
        return _call(service.propose_forgive, target, amount, reason)

    @mcp.tool
    def finance_setup_counterparty(label: str, kind: str, aliases: list[str] | None = None,
                                   pay_currency: str | None = None,
                                   settles_to: str | None = None) -> dict:
        """Propose a new counterparty of kind PERSON, FUND or EXCHANGE_PARTNER with its
        aliases; settles_to is the account where their payments arrive. This shows an echo;
        the owner must tap or answer before you call
        finance_resolve_pending(code, <the owner's answer>)."""
        return _call(service.propose_counterparty, label, kind, aliases, pay_currency,
                     settles_to)

    @mcp.tool
    def finance_record_opening(counterparty: str, amount: str, currency: str, basis: str,
                               note: str) -> dict:
        """Propose a starting balance the owner states; basis is APPROXIMATE or CONFIRMED.
        This shows an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, <the owner's answer>)."""
        return _call(service.propose_opening, counterparty, amount, currency, basis, note)

    @mcp.tool
    def finance_reverse(ref: str, reason: str) -> dict:
        """Propose undoing an exchange, receipt, rule or answer by its reference. This shows
        an echo; the owner must tap or answer before you call
        finance_resolve_pending(code, <the owner's answer>)."""
        return _call(service.propose_reverse, ref, reason)


__all__: list[str] = ["register_receivables_tools", "refusal_code", "quiet_invalid_arguments"]
