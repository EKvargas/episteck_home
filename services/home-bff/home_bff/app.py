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

import hmac
import logging

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse

from . import sessions
from .bootstrap import validate_bootstrap_response
from .config import Settings
from .frappe_client import (
    HomeOAuthClient,
    SessionOpenError,
    TokenExchangeError,
    UpstreamMalformed,
    UpstreamRefused,
    UpstreamUnavailable,
)
from .oauth import authorization_params, new_pkce_pair, new_state
from .runtime import RUNTIME_ID
from .store import SessionStore, StoreUnavailableError

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
    app = FastAPI(
        title="Episteck Home BFF",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

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
        login_binding = sessions.new_login_binding()

        # The verifier is persisted here and NEVER put in the redirect. The browser
        # carries only `state`, which is an opaque lookup key with no authority.
        store.begin_transaction(
            state=state,
            code_verifier=pkce.verifier,
            nonce=nonce,
            redirect_uri=settings.redirect_uri,
            login_binding_hash=sessions.hash_login_binding(login_binding),
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
        result = RedirectResponse(
            f"{app.state.client.authorize_url}?{query}", status_code=302
        )
        result.set_cookie(
            sessions.LOGIN_BINDING_COOKIE_NAME,
            login_binding,
            max_age=sessions.LOGIN_BINDING_MAX_AGE_SECONDS,
            **sessions.LOGIN_BINDING_COOKIE_FLAGS,
        )
        return result

    # ---------------------------------------------------------------- callback

    @app.get("/callback")
    def callback(
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
        login_binding: str | None = Cookie(
            default=None, alias=sessions.LOGIN_BINDING_COOKIE_NAME
        ),
        store: SessionStore = Depends(get_store),
        client: HomeOAuthClient = Depends(get_client),
    ):
        def _failure(status_code: int, detail: str) -> Response:
            """Every callback exit clears the binding cookie, success or failure."""
            failure = JSONResponse({"detail": detail}, status_code=status_code)
            _clear_login_binding_cookie(failure)
            return failure

        if error:
            return _failure(400, "authorization was denied")

        # 1+2. Validate state AND single-use in one atomic step. A replayed state
        # finds nothing, because consume_transaction deletes as it reads.
        transaction = store.consume_transaction(state or "")
        if transaction is None:
            return _failure(400, "invalid or already-used authorization state")

        # B3 / §9: the transaction is already consumed above regardless of outcome,
        # so a missing or mismatched binding still burns the state — it cannot be
        # retried by fixing just the cookie.
        presented_hash = sessions.hash_login_binding(login_binding or "")
        if not login_binding or not hmac.compare_digest(
            presented_hash, transaction.login_binding_hash
        ):
            return _failure(400, "login could not be verified")

        if not code:
            return _failure(400, "authorization code missing")

        # 3+4. Server-side exchange, always with the verifier minted for THIS state.
        try:
            tokens = client.exchange_code(
                code=code,
                redirect_uri=transaction.redirect_uri,
                code_verifier=transaction.code_verifier,
            )
        except TokenExchangeError as exchange_error:
            # Log the FAILURE CLASS, never the message: an upstream error can echo
            # request parameters, and this record is the one that persists.
            logger.warning(
                "token exchange failed (%s)", type(exchange_error).__name__
            )
            return _failure(400, "authorization could not be completed")

        # 6-9. The Control Plane resolves the User from the token and maps it to a
        # Person. Zero links, two links, or a disabled user all surface here as a
        # refusal — we never inspect or second-guess that decision.
        try:
            home_session_id = client.open_home_session(tokens.access_token)
        except SessionOpenError as session_error:
            # Same rule: class only. The refusal reason lives upstream, where it is
            # already recorded against an authenticated identity.
            logger.warning(
                "home session refused (%s)", type(session_error).__name__
            )
            return _failure(403, "this account is not linked to a Home person")

        # 10+11. Opaque cookie only. Tokens stay in the server-side store.
        session = store.create_session(
            home_session_id=home_session_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
        )

        try:
            binding = store.claim_runtime(RUNTIME_ID, session.session_id)
        except (ValueError, StoreUnavailableError):
            # A newly created session is not returned to the browser unless its
            # runtime claim reached a controlled outcome. If cleanup itself is
            # temporarily unavailable, the unreferenced session simply expires.
            try:
                store.delete_session(session.session_id)
            except StoreUnavailableError:
                pass
            return _failure(503, "runtime binding could not be completed")

        # ALREADY_BOUND is still success: the Home Hub session is valid, and agent
        # binding is orthogonal. `binding` is logged only as its static enum value,
        # never returned to the browser.
        logger.info("runtime binding outcome: %s", binding.value)

        result = Response(status_code=303, headers={"Location": "/app"})
        result.headers["Cache-Control"] = "no-store"
        result.headers["Referrer-Policy"] = "no-referrer"
        _set_session_cookie(result, session.session_id)
        _clear_login_binding_cookie(result)
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

    @app.get("/bootstrap")
    def bootstrap(
        session_id: str | None = Cookie(default=None, alias=sessions.COOKIE_NAME),
        store: SessionStore = Depends(get_store),
        client: HomeOAuthClient = Depends(get_client),
    ):
        """The single trusted-server read that answers "what can this viewer see".

        This signature has no identity-naming parameter of any kind (BFF-9): the
        ONLY identity input is the session cookie. Query strings, headers, and any
        request body are never inspected here, so nothing a caller sends can name
        a different person (BFF-8).
        """
        if session_id is None:
            return JSONResponse(
                {"error": "SESSION_REQUIRED"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        session = store.get_session(session_id)
        if session is None:
            return JSONResponse(
                {"error": "SESSION_INVALID"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        try:
            raw = client.get_home_bootstrap(session.access_token, session.home_session_id)
        except UpstreamRefused:
            # Read-only: a CP refusal never deletes the local session or runtime
            # binding. The CP is the authority; the next login replaces the cookie.
            return JSONResponse(
                {"error": "SESSION_INVALID"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        except UpstreamUnavailable:
            return JSONResponse(
                {"error": "SERVICE_UNAVAILABLE"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        except UpstreamMalformed:
            return JSONResponse(
                {"error": "INVALID_RESPONSE"},
                status_code=502,
                headers={"Cache-Control": "no-store"},
            )

        try:
            wire = validate_bootstrap_response(raw)
        except UpstreamMalformed:
            return JSONResponse(
                {"error": "INVALID_RESPONSE"},
                status_code=502,
                headers={"Cache-Control": "no-store"},
            )

        return JSONResponse(wire, headers={"Cache-Control": "no-store"})

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


def _clear_login_binding_cookie(response: Response) -> None:
    response.delete_cookie(
        sessions.LOGIN_BINDING_COOKIE_NAME,
        path=sessions.LOGIN_BINDING_COOKIE_FLAGS["path"],
        secure=sessions.LOGIN_BINDING_COOKIE_FLAGS["secure"],
        httponly=sessions.LOGIN_BINDING_COOKIE_FLAGS["httponly"],
        samesite=sessions.LOGIN_BINDING_COOKIE_FLAGS["samesite"],
    )
