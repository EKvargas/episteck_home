"""Fail-closed Home Control Plane client for svc-finance (H1 client).

Finance NEVER accepts an actor from any caller. It sends its own machine credential and
the opaque delegation; Home resolves the actor and returns it from ``authorize_batch``.

ONE REQUEST PER OPERATION. Delegations are single-use (Home ``identity/replay.py``), so a
second call on the same token is replay-denied. ``validate_batch`` proves the answer
covers exactly the requirements sent, in order; anything else is UNAVAILABLE.

Logs carry static category strings only: never a token, session id or Person id.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

import httpx

from app.authz import SESSION_INVALID, UNAVAILABLE, BatchDecision, Requirement, validate_batch

DELEGATION_HEADER = "X-Episteck-Delegation"
AUTHORIZE_BATCH_PATH = "/api/method/episteck_home.api.authorize_batch"

logger = logging.getLogger("finance.home_control")

_SESSION_INVALID = BatchDecision(SESSION_INVALID)
_UNAVAILABLE = BatchDecision(UNAVAILABLE)


def _refused(category: str, decision: BatchDecision) -> BatchDecision:
    logger.warning("home authorization not granted: %s", category)
    return decision


class HomeAuthorizer:
    """Satisfies ``app.authz.Authorizer``. The actor is never a parameter."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def from_credentials(cls, base_url: str, api_key: str, api_secret: str, *,
                         timeout_seconds: float = 3.0) -> "HomeAuthorizer":
        if not base_url or not api_key or not api_secret:
            raise ValueError("Home URL and machine credentials are required")
        return cls(httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"token {api_key}:{api_secret}",
                     "Accept": "application/json"},
            timeout=timeout_seconds,
        ))

    def authorize(self, delegation: str | None,
                  requirements: Sequence[Requirement]) -> BatchDecision:
        if not delegation:
            return _refused("session_invalid", _SESSION_INVALID)
        try:
            response = self._client.post(
                AUTHORIZE_BATCH_PATH,
                json={"requirements": [
                    {"subject": r.subject, "domain": r.domain, "action": r.action}
                    for r in requirements
                ]},
                headers={DELEGATION_HEADER: delegation},
            )
        except (ValueError, httpx.InvalidURL):
            # Unusable credential (e.g. non-latin-1 header): nothing was sent.
            return _refused("session_invalid", _SESSION_INVALID)
        except httpx.HTTPError:
            return _refused("home_unreachable", _UNAVAILABLE)

        if response.status_code in (401, 403):
            return _refused("home_rejected_credential_or_session", _SESSION_INVALID)
        if response.status_code != 200:
            return _refused("home_unavailable", _UNAVAILABLE)
        try:
            body = response.json()
            payload = body.get("message") if isinstance(body, dict) else None
        except ValueError:
            return _refused("home_malformed", _UNAVAILABLE)

        result = validate_batch(requirements, payload)
        if result.outcome != "ANSWERED":
            return _refused("home_malformed", _UNAVAILABLE)
        return result
