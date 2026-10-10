"""Finance's independent, fail-closed Home Control Plane permission check."""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Decision:
    allow: bool


class HomeFinanceAuthorizer:
    def __init__(self, base_url: str, api_key: str, api_secret: str, *, transport=None):
        if not all((base_url, api_key, api_secret)):
            raise ValueError("Home URL and machine credentials are required")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"token {api_key}:{api_secret}", "Accept": "application/json"},
            timeout=3.0,
            transport=transport,
        )

    def check_access(self, subject: str, domain: str, action: str, delegation: str | None = None) -> Decision:
        if not subject or domain != "FINANCE" or action not in {"VIEW", "CREATE"} or not delegation:
            return Decision(False)
        try:
            response = self.client.get(
                "/api/method/episteck_home.api.check_access",
                params={"subject_person_id": subject, "domain": domain, "action": action},
                headers={"X-Episteck-Delegation": delegation},
            )
            response.raise_for_status()
            return Decision(response.json()["message"].get("allow") is True)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return Decision(False)
