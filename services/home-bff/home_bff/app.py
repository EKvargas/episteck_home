"""Episteck Home BFF — the browser's only entry point to Home identity (G1.6).

    browser  ->  /login  ->  Frappe authorization (the human types their password)
             ->  /callback (code + state)
             ->  server-side token exchange with PKCE verifier
             ->  Home Delegated Session opened AS that human
             ->  opaque cookie
             ->  /session, /whoami  (delegation minted per call)
             ->  /logout

WHAT THE BROWSER NEVER RECEIVES
-------------------------------
client secret, access token, refresh token, PKCE verifier, delegation signing
secret, delegation token, or ``actor_person_id``. The cookie is an opaque random
string that means nothing outside this service's store.

WHAT THE MODEL NEVER RECEIVES
-----------------------------
This service is not an MCP server and exposes no tools. The delegation it mints is
handed to the runtime, not to a prompt (proposal §H).
"""
from __future__ import annotations

import logging

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse

from . import sessions
from .config import Settings
from .frappe_client import (
    HomeOAuthClient,
    SessionOpenError,
    TokenExchangeError,
)
from .oauth import authorization_params, new_pkce_pair, new_state
from .store import SessionStore

logger = logging.getLogger("home_bff")

# Delegations are minted for exactly one downstream audience per call.
AUDIENCE_CONTROL_PLANE = sessions.AUDIENCE_CONTROL_PLANE


def create_app(
    settings: Settings,
    *,
    store: SessionStore | None = None,
    client: HomeOAuthClient | None = None,
) -> FastAPI:
    """Build the app. Dependencies are injectable so tests never touch the network."""
    app = FastAPI(title="Episteck Home BFF", version="0.1.0")

    app.state.settings = settings
    app.state.store = store or SessionStore(settings.store_path)
    app.state.client = client or HomeOAuthClient(
        settings.home_base_url, settings.client_id, settings.client_secret
    )

    def get_store() -> SessionStore:
        return app.state.store

    def get_client() -> HomeOAuthClient:
        return app.state.client

    # ------------------------------------------------------------------ health

    @app.get("/health")
    def health():
        """Liveness only. Reveals no configuration and no session data."""
        return {"status": "ok", "service": "home-bff"}

    # ------------------------------------------------------------------- login

    @app.get("/login")
    def login(store: SessionStore = Depends(get_store)):
        """Start an authorization-code login. All security state stays server-side."""
        store.purge_expired()

        pkce = new_pkce_pair()
        state = new_state()
        nonce = new_state()

        # The verifier is persisted here and NEVER put in the redirect. The browser
        # carries only `state`, which is an opaque lookup key with no authority.
        store.begin_transaction(
            state=state,
            code_verifier=pkce.verifier,
            nonce=nonce,
            redirect_uri=settings.redirect_uri,
        )

        params = authorization_params(
            client_id=settings.client_id,
            redirect_uri=settings.redirect_uri,
            pkce=pkce,
            state=state,
            scope=settings.scope,
        )
        params["nonce"] = nonce

        query = "&".join(f"{k}={_quote(v)}" for k, v in params.items())
        return RedirectResponse(
            f"{app.state.client.authorize_url}?{query}", status_code=302
        )

    # ---------------------------------------------------------------- callback

    @app.get("/callback")
    def callback(
        response: Response,
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
        store: SessionStore = Depends(get_store),
        client: HomeOAuthClient = Depends(get_client),
    ):
        if error:
            raise HTTPException(400, "authorization was denied")

        # 1+2. Validate state AND single-use in one atomic step. A replayed state
        # finds nothing, because consume_transaction deletes as it reads.
        transaction = store.consume_transaction(state or "")
        if transaction is None:
            raise HTTPException(400, "invalid or already-used authorization state")

        if not code:
            raise HTTPException(400, "authorization code missing")

        # 3+4. Server-side exchange, always with the verifier minted for THIS state.
        try:
            tokens = client.exchange_code(
                code=code,
                redirect_uri=transaction.redirect_uri,
                code_verifier=transaction.code_verifier,
            )
        except TokenExchangeError as exchange_error:
            logger.warning("token exchange failed: %s", exchange_error)
            raise HTTPException(400, "authorization could not be completed") from None

        # 6-9. The Control Plane resolves the User from the token and maps it to a
        # Person. Zero links, two links, or a disabled user all surface here as a
        # refusal — we never inspect or second-guess that decision.
        try:
            home_session_id = client.open_home_session(tokens.access_token)
        except SessionOpenError as session_error:
            logger.warning("home session refused: %s", session_error)
            raise HTTPException(
                403, "this account is not linked to a Home person"
            ) from None

        # 10+11. Opaque cookie only. Tokens stay in the server-side store.
        session = store.create_session(
            home_session_id=home_session_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

        result = JSONResponse({"status": "authenticated"})
        _set_session_cookie(result, session.session_id)
        return result

    # ----------------------------------------------------------------- logout

    @app.post("/logout")
    def logout(
        session_id: str | None = Cookie(default=None, alias=sessions.COOKIE_NAME),
        store: SessionStore = Depends(get_store),
        client: HomeOAuthClient = Depends(get_client),
    ):
        """Invalidate locally AND upstream. Always clears the cookie."""
        session = store.get_session(session_id)
        if session is not None:
            # Revoke the Home Delegated Session first: that is what denies the very
            # next delegated call even if a token is still cached somewhere.
            try:
                client.close_home_session(
                    session.access_token, session.home_session_id
                )
            except Exception:  # never let upstream failure block local logout
                logger.warning("upstream session close failed", exc_info=False)
            try:
                client.revoke_token(session.access_token)
            except Exception:
                logger.warning("upstream token revoke failed", exc_info=False)
            store.delete_session(session.session_id)

        result = JSONResponse({"status": "logged out"})
        _clear_session_cookie(result)
        return result

    # ---------------------------------------------------- delegated operations

    @app.get("/session")
    def session_status(
        session_id: str | None = Cookie(default=None, alias=sessions.COOKIE_NAME),
        store: SessionStore = Depends(get_store),
    ):
        """Is this browser session live? Returns no identity and no token."""
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(401, "no active session")
        return {"authenticated": True, "expires_at": session.expires_at}

    @app.get("/whoami")
    def whoami(
        session_id: str | None = Cookie(default=None, alias=sessions.COOKIE_NAME),
        store: SessionStore = Depends(get_store),
        client: HomeOAuthClient = Depends(get_client),
    ):
        """Prove the full trusted path end to end.

        The actor is resolved by the Control Plane from the delegation, never read
        from the cookie, a header, or anything the caller could choose.
        """
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(401, "no active session")
        try:
            return client.whoami(session.access_token)
        except SessionOpenError:
            # The Home session was revoked or the user unlinked: deny immediately.
            raise HTTPException(403, "session is no longer authorized") from None

    @app.post("/delegation")
    def mint_delegation(
        audience: str = Query(default=AUDIENCE_CONTROL_PLANE),
        session_id: str | None = Cookie(default=None, alias=sessions.COOKIE_NAME),
        store: SessionStore = Depends(get_store),
    ):
        """Mint a short-lived delegation for the trusted runtime.

        This is an internal, loopback-only endpoint for the agent runtime — it is not
        reachable from the public reverse proxy, and its output never enters a prompt.
        """
        session = store.get_session(session_id)
        if session is None:
            raise HTTPException(401, "no active session")
        try:
            minted = sessions.mint_delegation(
                session.home_session_id, audience, settings.delegation_secret
            )
        except sessions.UnknownAudienceError:
            raise HTTPException(400, "unknown audience") from None
        return {
            "delegation": minted.token,
            "audience": minted.audience,
            "expires_at": minted.expires_at,
        }

    return app


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        sessions.COOKIE_NAME,
        session_id,
        max_age=sessions.COOKIE_MAX_AGE_SECONDS,
        **sessions.COOKIE_FLAGS,
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        sessions.COOKIE_NAME,
        path=sessions.COOKIE_FLAGS["path"],
        secure=sessions.COOKIE_FLAGS["secure"],
        httponly=sessions.COOKIE_FLAGS["httponly"],
        samesite=sessions.COOKIE_FLAGS["samesite"],
    )
