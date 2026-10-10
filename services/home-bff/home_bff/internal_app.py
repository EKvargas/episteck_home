"""Internal-only fixed-runtime delegation mint application."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Response

from . import sessions
from .config import Settings
from .runtime import RUNTIME_ID
from .store import SessionStore, StoreUnavailableError

DELEGATION_HEADER = "X-Episteck-Delegation"

# H5: the agent gets a long-lived grant, so a runaway loop (or a stolen gateway
# identity) must not be able to mint without bound.
MINT_LIMIT_PER_MINUTE = 600

logger = logging.getLogger("home_bff")


class _MinuteLimiter:
    """Fixed-window counter. One process serves the mint, so memory is enough."""

    def __init__(self, limit: int, clock: Callable[[], float]) -> None:
        self._limit = limit
        self._clock = clock
        self._lock = threading.Lock()
        self._window = -1
        self._count = 0

    def allow(self) -> bool:
        window = int(self._clock()) // 60
        with self._lock:
            if window != self._window:
                self._window, self._count = window, 0
            if self._count >= self._limit:
                return False
            self._count += 1
            return True


def create_internal_app(
    settings: Settings,
    *,
    store: SessionStore | None = None,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    """Build the UDS-only mint app without any browser-facing routes."""
    app = FastAPI(
        title="Episteck Home BFF Internal Mint",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store or SessionStore(settings.store_path)
    limiter = _MinuteLimiter(MINT_LIMIT_PER_MINUTE, clock)

    def get_store() -> SessionStore:
        return app.state.store

    @app.post("/internal/mint", status_code=204)
    def mint_delegation(store: SessionStore = Depends(get_store)) -> Response:
        if not limiter.allow():
            # Static line only: nothing request- or identity-derived is logged.
            logger.warning("mint rate limit exceeded")
            raise HTTPException(429, "delegation mint rate limited")
        try:
            grant = store.resolve_runtime_grant(RUNTIME_ID)
            if grant is not None:
                if sessions.AUDIENCE_CONTROL_PLANE not in grant.allowed_audiences:
                    raise HTTPException(401, "no active runtime grant")
                home_session_id = grant.home_session_id
                store.touch_runtime_grant(RUNTIME_ID)
            elif settings.runtime_legacy_binding:
                session = store.resolve_runtime(RUNTIME_ID)
                if session is None:
                    raise HTTPException(401, "no active runtime binding")
                home_session_id = session.home_session_id
            else:
                raise HTTPException(401, "no active runtime grant")
        except StoreUnavailableError:
            raise HTTPException(503, "delegation mint unavailable") from None

        minted = sessions.mint_delegation(
            home_session_id,
            sessions.AUDIENCE_CONTROL_PLANE,
            settings.delegation_secret,
        )
        return Response(
            status_code=204,
            headers={
                DELEGATION_HEADER: minted.token,
                "Cache-Control": "no-store",
            },
        )

    return app
