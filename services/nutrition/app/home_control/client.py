"""Fail-closed Home Control Plane client owned by svc-nutrition."""
from __future__ import annotations

from dataclasses import dataclass
import os

import httpx


@dataclass(frozen=True)
class AccessDecision:
    allow: bool
    reason: str


_INDETERMINATE = AccessDecision(
    False, "authorization indeterminate (fail closed)"
)


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
        actor_person_id: str,
        subject_person_id: str,
        domain: str,
        action: str,
    ) -> AccessDecision:
        if not all((actor_person_id, subject_person_id, domain, action)):
            return _INDETERMINATE
        try:
            response = self._client.get(
                "/api/method/episteck_home.api.check_access",
                params={
                    "actor_person_id": actor_person_id,
                    "subject_person_id": subject_person_id,
                    "domain": domain,
                    "action": action,
                },
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
