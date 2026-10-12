"""REST boundary. No actor, workspace or SQL parameter exists anywhere on this API."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException

from .service import (
    AccessDenied, FeatureOff, FinanceService, PolicyUnavailable, SessionInvalid,
    UnsupportedValuation,
)


def human_session(x_episteck_delegation: str | None = Header(default=None)) -> str | None:
    """Trusted human session from transport, never a query or body parameter."""
    value = (x_episteck_delegation or "").strip()
    return value or None


def _authorized(operation: Callable[[], Any]):
    """Fixed refusal bodies; ``from None`` keeps Home's reason out of every response."""
    try:
        return operation()
    except SessionInvalid:
        raise HTTPException(401, "SESSION_INVALID") from None
    except PolicyUnavailable:
        raise HTTPException(503, "SERVICE_UNAVAILABLE") from None
    except AccessDenied:
        raise HTTPException(403, "ACCESS_DENIED") from None
    except FeatureOff:
        raise HTTPException(409, "FEATURE_OFF") from None
    except UnsupportedValuation:
        raise HTTPException(400, "UNSUPPORTED_VALUATION_CURRENCY") from None


def create_app(service: FinanceService) -> FastAPI:
    app = FastAPI(title="Episteck Finance", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/overview")
    def overview(valuation_currency: str | None = None,
                 delegation: str | None = Depends(human_session)):
        return _authorized(lambda: service.overview(delegation, valuation_currency))

    return app
