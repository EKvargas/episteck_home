"""REST boundary. No actor, workspace or SQL parameter exists anywhere on this API.

``GET /connect/callback`` is the only route nginx exposes publicly (ADR-0013). It needs no
delegation: the single-use ``state`` is its authority, and it never contacts the bank.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse

from .service import (
    AccessDenied, FeatureOff, FinanceService, PolicyUnavailable, SessionInvalid,
    UnsupportedValuation,
)

CallbackHandler = Callable[[str | None, str | None, str | None], bool]
_CALLBACK_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                     "X-Content-Type-Options": "nosniff"}
_GRANTED = ("Bank authorization received. Return to the terminal to finish connecting "
            "the account. You can close this window.\n")
_REFUSED = "Bank authorization was not completed. Nothing was changed. You can close this window.\n"
_INVALID = "This authorization link is invalid or has expired.\n"


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


def create_app(service: FinanceService, callback: CallbackHandler | None = None) -> FastAPI:
    app = FastAPI(title="Episteck Finance", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/overview")
    def overview(valuation_currency: str | None = None,
                 delegation: str | None = Depends(human_session)):
        return _authorized(lambda: service.overview(delegation, valuation_currency))

    if callback is not None:
        @app.get("/connect/callback", response_class=PlainTextResponse)
        def connect_callback(state: str | None = None, code: str | None = None,
                             error: str | None = None):
            # error_description is deliberately not read: bank text never reaches a log.
            if not callback(state, code, error):
                return PlainTextResponse(_INVALID, 400, headers=_CALLBACK_HEADERS)
            return PlainTextResponse(_REFUSED if error is not None else _GRANTED,
                                     headers=_CALLBACK_HEADERS)

    return app
