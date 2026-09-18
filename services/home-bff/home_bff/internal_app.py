"""Internal-only fixed-runtime delegation mint application."""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Response

from . import sessions
from .config import Settings
from .runtime import RUNTIME_ID
from .store import SessionStore, StoreUnavailableError

DELEGATION_HEADER = "X-Episteck-Delegation"


def create_internal_app(
    settings: Settings,
    *,
    store: SessionStore | None = None,
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

    def get_store() -> SessionStore:
        return app.state.store

    @app.post("/internal/mint", status_code=204)
    def mint_delegation(store: SessionStore = Depends(get_store)) -> Response:
        try:
            session = store.resolve_runtime(RUNTIME_ID)
        except StoreUnavailableError:
            raise HTTPException(503, "delegation mint unavailable") from None
        if session is None:
            raise HTTPException(401, "no active runtime binding")

        minted = sessions.mint_delegation(
            session.home_session_id,
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
