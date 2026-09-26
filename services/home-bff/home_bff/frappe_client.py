"""Outbound calls from the BFF to the Frappe Home Control Plane (G1.6).

Three operations, all server-to-server:

  1. exchange an authorization code for tokens (confidential client + PKCE verifier)
  2. open a Home Delegated Session **as the human who just logged in**
  3. close that session on logout, and revoke the upstream token

Operations 2 and 3 use the user's own OAuth access token, never a service credential.
That is deliberate: the Control Plane derives the User from the token it validated, so
the BFF never names an identity. See ``identity/session.py`` for the other half.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from .oauth import token_request_params

# Frappe's stock OAuth2 endpoints.
TOKEN_PATH = "/api/method/frappe.integrations.oauth2.get_token"
REVOKE_PATH = "/api/method/frappe.integrations.oauth2.revoke_token"
AUTHORIZE_PATH = "/api/method/frappe.integrations.oauth2.authorize"

OPEN_SESSION_PATH = "/api/method/episteck_home.identity.session.open_session"
CLOSE_SESSION_PATH = "/api/method/episteck_home.identity.session.close_session"
WHOAMI_PATH = "/api/method/episteck_home.api.whoami"
GET_HOME_BOOTSTRAP_PATH = "/api/method/episteck_home.api.get_home_bootstrap"


class TokenExchangeError(RuntimeError):
    """The authorization code could not be exchanged. Always fail the login."""


class SessionOpenError(RuntimeError):
    """The Control Plane refused to open a delegated session (e.g. no Person)."""


class UpstreamRefused(RuntimeError):
    """The Control Plane definitively refused this session/user (401/403)."""


class UpstreamUnavailable(RuntimeError):
    """Transport failure, timeout, or the CP method is absent/overloaded/down."""


class UpstreamMalformed(RuntimeError):
    """The CP answered 200 but the body is not usable JSON with the expected shape."""


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int


class HomeOAuthClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url or not client_id or not client_secret:
            raise ValueError("Home base URL and confidential client credentials required")
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    @property
    def authorize_url(self) -> str:
        return f"{self._base_url}{AUTHORIZE_PATH}"

    def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> TokenSet:
        """Exchange an authorization code. The PKCE verifier is ALWAYS sent."""
        if not code or not code_verifier:
            raise TokenExchangeError("authorization code and verifier are required")

        params = token_request_params(
            client_id=self._client_id,
            client_secret=self._client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        try:
            response = self._client.post(TOKEN_PATH, data=params)
        except httpx.HTTPError as error:
            raise TokenExchangeError("token endpoint unreachable") from error

        if response.status_code != 200:
            # Never surface the upstream body: it can echo request parameters.
            raise TokenExchangeError(
                f"token exchange rejected (HTTP {response.status_code})"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise TokenExchangeError("token endpoint returned non-JSON") from error

        access_token = payload.get("access_token")
        if not access_token:
            raise TokenExchangeError("token response contained no access token")

        return TokenSet(
            access_token=access_token,
            refresh_token=payload.get("refresh_token"),
            expires_in=int(payload.get("expires_in") or 0),
        )

    def open_home_session(self, access_token: str, *, client: str = "bff-web") -> str:
        """Open a Home Delegated Session as the authenticated human.

        No user id is sent. The Control Plane resolves the User from this very token,
        which is what keeps the BFF unable to open a session for anyone else.
        """
        payload = self._as_user(
            access_token, OPEN_SESSION_PATH, {"client": client}
        )
        session_id = (payload or {}).get("session_id")
        if not session_id:
            raise SessionOpenError("Control Plane returned no session id")
        return session_id

    def close_home_session(self, access_token: str, home_session_id: str) -> bool:
        """Revoke the server-side session. Best effort; logout proceeds regardless."""
        try:
            payload = self._as_user(
                access_token, CLOSE_SESSION_PATH, {"session_id": home_session_id}
            )
        except SessionOpenError:
            return False
        return bool((payload or {}).get("closed"))

    def whoami(self, access_token: str) -> dict:
        """Resolve the trusted actor for this human session. Used for evidence."""
        return self._as_user(access_token, WHOAMI_PATH, None, method="GET") or {}

    def get_home_bootstrap(self, access_token: str, session_id: str) -> dict:
        """The single session-bound bootstrap read (§2/§3 Option B).

        Splits the previously-uniform SessionOpenError into three classes so the
        BFF can map each to a distinct HTTP status (§6): a definitive refusal
        (401/403) is not the same situation as the CP being unreachable, and
        neither is the same as the CP answering with something we cannot parse.
        """
        if not access_token:
            raise UpstreamRefused("no access token")
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = self._client.post(
                GET_HOME_BOOTSTRAP_PATH,
                data={"session_id": session_id},
                headers=headers,
            )
        except httpx.HTTPError as error:
            raise UpstreamUnavailable("Control Plane unreachable") from error

        if response.status_code in (401, 403):
            raise UpstreamRefused(
                f"Control Plane refused the session (HTTP {response.status_code})"
            )
        if response.status_code != 200:
            # 404/417 (method absent), 429 (rate limited), and any 5xx are all
            # "try again later" from the browser's perspective, not "you are
            # unauthorized" — §6 maps every one of these to 503, never 401.
            raise UpstreamUnavailable(
                f"Control Plane unavailable (HTTP {response.status_code})"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise UpstreamMalformed("Control Plane returned non-JSON") from error
        if not isinstance(body, dict) or "message" not in body:
            raise UpstreamMalformed("Control Plane response missing message envelope")
        message = body["message"]
        if not isinstance(message, dict):
            raise UpstreamMalformed("Control Plane message is not an object")
        return message

    def revoke_token(self, access_token: str) -> bool:
        """Revoke the upstream OAuth token so logout is not merely local."""
        try:
            response = self._client.post(
                REVOKE_PATH, data={"token": access_token}
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def _as_user(
        self,
        access_token: str,
        path: str,
        data: dict | None,
        *,
        method: str = "POST",
    ) -> dict | None:
        """Call the Control Plane with the HUMAN's bearer token, not a service key."""
        if not access_token:
            raise SessionOpenError("no access token")
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if method == "GET":
                response = self._client.get(path, headers=headers)
            else:
                response = self._client.post(path, data=data or {}, headers=headers)
        except httpx.HTTPError as error:
            raise SessionOpenError("Control Plane unreachable") from error

        if response.status_code != 200:
            # 403 here is the expected, correct outcome when the User has no linked
            # Person, or has two. Fail closed and say nothing more.
            raise SessionOpenError(
                f"Control Plane refused the session (HTTP {response.status_code})"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise SessionOpenError("Control Plane returned non-JSON") from error
        # Frappe wraps whitelisted returns in {"message": ...}
        return body.get("message") if isinstance(body, dict) else None

    def close(self) -> None:
        self._client.close()
