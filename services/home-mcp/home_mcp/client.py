"""Authenticated client for the Frappe Home Control Plane business API."""
from __future__ import annotations

import os
from typing import Any

import httpx


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

    def _call(self, method: str, params: dict[str, str]) -> Any:
        try:
            response = self._client.get(
                f"/api/method/episteck_home.api.{method}", params=params
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or "message" not in payload:
                raise ValueError("missing Frappe message")
            return payload["message"]
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {403, 404}:
                return {"ok": False, "error": "not_authorized_or_not_found"}
            return {"ok": False, "error": "home_control_plane_unavailable"}
        except httpx.HTTPError:
            return {"ok": False, "error": "home_control_plane_unavailable"}
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_home_control_plane_response"}

    def get_person(self, actor_person_id: str, person_id: str):
        return self._call(
            "get_person",
            {"actor_person_id": actor_person_id, "person_id": person_id},
        )

    def list_my_circles(self, actor_person_id: str):
        return self._call("list_my_circles", {"actor_person_id": actor_person_id})

    def list_circle_members(self, actor_person_id: str, circle_id: str):
        return self._call(
            "list_circle_members",
            {"actor_person_id": actor_person_id, "circle_id": circle_id},
        )

    def list_people_i_care_for(self, actor_person_id: str):
        return self._call(
            "list_people_i_care_for", {"actor_person_id": actor_person_id}
        )

    def get_access_to_person(self, actor_person_id: str, subject_person_id: str):
        return self._call(
            "get_access_to_person",
            {
                "actor_person_id": actor_person_id,
                "subject_person_id": subject_person_id,
            },
        )

    def check_access(
        self,
        actor_person_id: str,
        subject_person_id: str,
        domain: str,
        action: str = "VIEW",
    ) -> dict:
        result = self._call(
            "check_access",
            {
                "actor_person_id": actor_person_id,
                "subject_person_id": subject_person_id,
                "domain": domain,
                "action": action,
            },
        )
        if not isinstance(result, dict) or type(result.get("allow")) is not bool:
            return {
                "allow": False,
                "reason": "authorization indeterminate (fail closed)",
            }
        return {
            "allow": result["allow"],
            "reason": str(result.get("reason") or "Home Control Plane decision"),
        }

    def get_care_dashboard(self, actor_person_id: str):
        return self._call("get_care_dashboard", {"actor_person_id": actor_person_id})
