"""Internal-only fixed-runtime delegation mint application."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Response

from . import sessions
from .config import Settings
from .runtime import PRIMARY_RUNTIME_ID
from .store import SessionStore, StoreUnavailableError

DELEGATION_HEADER = "X-Episteck-Delegation"
# Set only by the gateway mint subrequest; the BFF trusts it because the mint socket is
# internal and every mint location drops the client request headers.
RUNTIME_HEADER = "X-Runtime-ID"

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
    limiters = {
        rid: _MinuteLimiter(MINT_LIMIT_PER_MINUTE, clock) for rid in settings.runtime_ids
    }

    def get_store() -> SessionStore:
        return app.state.store

    @app.post("/internal/mint", status_code=204)
    def mint_delegation(
        store: SessionStore = Depends(get_store),
        runtime_id: str | None = Header(default=None, alias=RUNTIME_HEADER, include_in_schema=False),
    ) -> Response:
        if runtime_id not in limiters:
            # Missing, empty or unknown: never defaults to the primary runtime, and the
            # raw header value is never logged.
            logger.warning("mint refused: unknown runtime")
            raise HTTPException(401, "no active runtime grant")
        if not limiters[runtime_id].allow():
            # Static line only: nothing request- or identity-derived is logged.
            logger.warning("mint rate limit exceeded")
            raise HTTPException(429, "delegation mint rate limited")
        try:
            grant = store.resolve_runtime_grant(runtime_id)
            if grant is not None:
                if sessions.AUDIENCE_CONTROL_PLANE not in grant.allowed_audiences:
                    raise HTTPException(401, "no active runtime grant")
                home_session_id = grant.home_session_id
                store.touch_runtime_grant(runtime_id)
            elif settings.runtime_legacy_binding and runtime_id == PRIMARY_RUNTIME_ID:
                session = store.resolve_runtime(runtime_id)
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

    @app.post("/internal/mint_finance", status_code=204)
    def mint_finance_delegation(
        store: SessionStore = Depends(get_store),
        runtime_id: str | None = Header(default=None, alias=RUNTIME_HEADER, include_in_schema=False),
    ) -> Response:
        # Finance is a separate audience on a separate gateway location. It is minted
        # ONLY from a runtime grant that names svc-finance: the legacy browser binding
        # carries no audience scope, so it never authorizes Finance.
        # Only the owner's runtime may ever hold a Finance delegation.
        if runtime_id != PRIMARY_RUNTIME_ID:
            logger.warning("mint refused: unknown runtime")
            raise HTTPException(401, "no active runtime grant")
        if not limiters[PRIMARY_RUNTIME_ID].allow():
            logger.warning("mint rate limit exceeded")
            raise HTTPException(429, "delegation mint rate limited")
        try:
            grant = store.resolve_runtime_grant(PRIMARY_RUNTIME_ID)
            if grant is None or sessions.AUDIENCE_FINANCE not in grant.allowed_audiences:
                raise HTTPException(401, "no active runtime grant")
            home_session_id = grant.home_session_id
            store.touch_runtime_grant(PRIMARY_RUNTIME_ID)
        except StoreUnavailableError:
            raise HTTPException(503, "delegation mint unavailable") from None

        minted = sessions.mint_delegation(
            home_session_id,
            sessions.AUDIENCE_FINANCE,
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
