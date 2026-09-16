"""Fail-closed Home Control Plane client owned by svc-nutrition.

G1.6 INDEPENDENT AUTHORIZATION
-----------------------------
Nutrition NEVER accepts an ``actor_person_id`` from the Home Agent, the Home MCP, or
any client input. It sends only its OWN machine credential and the opaque delegated
session, and Home decides both who the human is and whether they may proceed.

This is what prevents a confused deputy: no upstream component can say "trust me, the
actor is PSN-00002". There is no actor value in this service at all, so none can be
asserted, forwarded, or confused.

    delegated session -> check_access(subject, NUTRITION, action)
                      -> Home derives the actor server-side
                      -> repository access only after literal ALLOW

ONE CALL PER OPERATION
----------------------
Exactly one delegated Home request per person-sensitive operation. Delegations are
single-use (``identity/replay.py``), so a second call on the same token is
replay-denied. An earlier ``resolve_actor()`` step made this client issue two requests
per operation; the first succeeded and the second was refused, breaking every
person-sensitive route. Its result was discarded by every caller, so removing it costs
nothing and restores the flow.
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

    def check_access(
        self,
        subject_person_id: str,
        domain: str,
        action: str,
        delegation: str | None = None,
    ) -> AccessDecision:
        """The ONLY delegated Home request an operation may make.

        Takes no actor: Home derives the human server-side from this service's machine
        credential plus the delegation, and has never accepted an actor argument.
        """
        if not all((subject_person_id, domain, action)):
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
