"""REST routes for receivables: the same service, the same authorization, the same bodies.

Delegation comes from the ``X-Episteck-Delegation`` header only. ``POST /commands/{type}``
takes the tool's arguments as JSON plus an optional ``Idempotency-Key`` header, which
the service receives as ``client_key``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .receivables.service import ReceivablesService

logger = logging.getLogger("finance.api")

_STATUS = {
    "validation_error": 400, "clarification_needed": 400, "unknown_choice": 400,
    "unknown_pending": 400,
    "possible_duplicate": 409, "already_resolved": 409, "idempotency_conflict": 409,
    "already_linked": 409,
    "internal_error": 500,
}
# type -> (service method, required arguments, optional arguments)
_COMMANDS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "exchange": ("propose_exchange", ("total_usd", "lines"), ("evidence", "delivered_on")),
    "receipt": ("propose_receipt", ("payer", "amount", "currency", "kind"),
                ("received_on", "description")),
    "correction": ("propose_correction", ("exchange_ref", "lines", "reason"), ()),
    "forgive": ("propose_forgive", ("target", "reason"), ("amount",)),
    "opening": ("propose_opening", ("counterparty", "amount", "currency", "basis", "note"), ()),
    "counterparty": ("propose_counterparty", ("label", "kind"),
                     ("aliases", "pay_currency", "settles_to")),
    "reverse": ("propose_reverse", ("ref", "reason"), ()),
    "reallocate": ("propose_reallocate", ("receipt_ref", "allocations"), ()),
    "held_cash": ("mark_held_cash", ("counterparty", "amount", "currency"), ()),
}


def _invalid(field: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"ok": False, "error": "validation_error"}
    if field is not None:
        body["field"] = field
    return JSONResponse(body, status_code=400)


def _respond(result: dict) -> JSONResponse:
    """Service results pass through unchanged; a refusal result gets its HTTP status."""
    if result.get("ok") is False:
        return JSONResponse(result, status_code=_STATUS.get(result.get("error"), 400))
    return JSONResponse(result)


def create_receivables_router(service: ReceivablesService) -> APIRouter:
    from .api import _authorized, human_session  # late: api includes this router

    router = APIRouter()

    def guarded(operation: Callable[[], dict]) -> JSONResponse:
        try:
            return _respond(_authorized(operation))
        except HTTPException:
            raise
        except Exception as error:  # never str(error)
            logger.error("receivables route failed: %s", type(error).__name__)
            return JSONResponse({"ok": False, "error": "internal_error"}, status_code=500)

    @router.get("/receivables")
    def receivables(counterparty: str | None = None,
                    delegation: str | None = Depends(human_session)):
        return guarded(lambda: service.receivables(delegation, counterparty))

    @router.get("/exchanges")
    def exchanges(status: str | None = None, since: str | None = None,
                  delegation: str | None = Depends(human_session)):
        return guarded(lambda: service.exchanges(delegation, status, since))

    @router.get("/pending")
    def pending(for_delivery: bool = False, delegation: str | None = Depends(human_session)):
        return guarded(lambda: service.pending(delegation, for_delivery))

    @router.post("/commands/{type}")
    async def command(type: str, request: Request,
                      delegation: str | None = Depends(human_session),
                      idempotency_key: str | None = Header(default=None)):
        spec = _COMMANDS.get(type)
        if spec is None:
            raise HTTPException(404, "UNKNOWN_COMMAND")
        method, required, optional = spec
        body = await _json_object(request)
        if body is None:
            return _invalid()
        unknown = sorted(set(body) - set(required) - set(optional))
        if unknown:
            return _invalid(unknown[0])
        missing = [name for name in required if name not in body]
        if missing:
            return _invalid(missing[0])
        kwargs: dict[str, Any] = dict(body)
        if idempotency_key is not None:
            kwargs["client_key"] = idempotency_key
        return guarded(lambda: getattr(service, method)(delegation, **kwargs))

    @router.post("/pending/{code}/resolve")
    async def resolve(code: str, request: Request,
                      delegation: str | None = Depends(human_session)):
        body = await _json_object(request)
        if body is None or set(body) - {"choice", "details"}:
            return _invalid()
        if "choice" not in body:
            return _invalid("choice")
        return guarded(lambda: service.resolve(delegation, code, body["choice"],
                                               body.get("details")))

    return router


async def _json_object(request: Request) -> dict | None:
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None
