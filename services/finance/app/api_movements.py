"""REST routes for movements: the same service functions as the MCP tools (ADR-0011)."""
from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from .movements.service import MovementsService

logger = logging.getLogger("finance.api")


def create_movements_router(service: MovementsService) -> APIRouter:
    from .api import _authorized, human_session  # late: api includes this router

    router = APIRouter()

    def guarded(operation: Callable[[], dict]) -> JSONResponse:
        try:
            result = _authorized(operation)
        except HTTPException:
            raise
        except Exception as error:  # never str(error)
            logger.error("movements route failed: %s", type(error).__name__)
            return JSONResponse({"ok": False, "error": "internal_error"}, status_code=500)
        return JSONResponse(result, status_code=200 if result.get("ok") else 400)

    @router.get("/movements")
    def movements(text: str | None = None, amount: str | None = None,
                  account: str | None = None, direction: str | None = None,
                  since: str | None = None, until: str | None = None,
                  limit: str | None = None, delegation: str | None = Depends(human_session)):
        try:
            count: int | str | None = None if limit is None else int(limit)
        except ValueError:
            count = limit  # the service refuses it as bad_limit
        return guarded(lambda: service.movements(
            delegation, text, amount, account, direction, since, until, count))

    @router.get("/summary")
    def summary(period: str | None = None, delegation: str | None = Depends(human_session)):
        return guarded(lambda: service.summary(delegation, period))

    return router
