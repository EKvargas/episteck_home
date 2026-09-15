"""Fail-closed Home Control Plane client owned by svc-nutrition.

G1.6 INDEPENDENT ACTOR RESOLUTION
---------------------------------
Nutrition NEVER accepts an ``actor_person_id`` from the Home Agent, the Home MCP, or
any client input. It receives only the delegated human session and resolves the actor
ITSELF against the Home Control Plane, using its OWN machine credential.

This is what prevents a confused deputy: no upstream component can say "trust me, the
actor is PSN-00002". Two services resolving the same delegation independently must
arrive at the same actor, and neither can vouch for a human to the other.

    delegated session -> resolve_actor()  (Home decides who this is)
                      -> check_access(actor, subject, NUTRITION, action)
                      -> repository access only after literal ALLOW
"""
from __future__ import annotations

from dataclasses import dataclass
import os

import httpx

DELEGATION_HEADER = "X-Episteck-Delegation"


@dataclass(frozen=True)
class AccessDecision:
    allow: bool
    reason: str


_INDETERMINATE = AccessDecision(
    False, "authorization indeterminate (fail closed)"
)

_NO_SESSION = AccessDecision(
    False, "no authenticated human session (fail closed)"
)


class UnresolvedActorError(PermissionError):
    """Raised when no trusted actor can be resolved for a delegated session."""


class HomeControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        *,
        timeout_seconds: float = 3.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url or not api_key or not api_secret:
            raise ValueError("Home Control Plane URL and credentials are required")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"token {api_key}:{api_secret}",
                "Accept": "application/json",
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    @classmethod
    def from_env(cls) -> "HomeControlPlaneClient":
        return cls(
            os.environ["HOME_CONTROL_PLANE_URL"],
            os.environ["HOME_API_KEY"],
            os.environ["HOME_API_SECRET"],
            timeout_seconds=float(os.environ.get("HOME_API_TIMEOUT_SECONDS", "3")),
        )

    def resolve_actor(self, delegation: str | None) -> str | None:
        """Resolve the trusted actor for a delegated session. None on any doubt.

        Nutrition asks Home who the human is; it never accepts an asserted answer.
        """
        if not delegation:
            return None
        try:
            response = self._client.get(
                "/api/method/episteck_home.api.whoami",
                headers={DELEGATION_HEADER: delegation},
            )
            response.raise_for_status()
            actor = response.json()["message"]["actor_person_id"]
            if not isinstance(actor, str) or not actor.strip():
                return None
            return actor
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

    def check_access(
        self,
        actor_person_id: str,
        subject_person_id: str,
        domain: str,
        action: str,
        delegation: str | None = None,
    ) -> AccessDecision:
        if not all((actor_person_id, subject_person_id, domain, action)):
            return _INDETERMINATE
        if not delegation:
            return _NO_SESSION
        try:
            response = self._client.get(
                "/api/method/episteck_home.api.check_access",
                params={
                    "subject_person_id": subject_person_id,
                    "domain": domain,
                    "action": action,
                },
                headers={DELEGATION_HEADER: delegation},
            )
            response.raise_for_status()
            payload = response.json()
            decision = payload["message"]
            if not isinstance(decision, dict) or type(decision.get("allow")) is not bool:
                return _INDETERMINATE
            return AccessDecision(
                decision["allow"],
                str(decision.get("reason") or "Home Control Plane decision"),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return _INDETERMINATE
