"""Authenticated client for the Frappe Home Control Plane business API.

DUAL PRINCIPAL (G1.6)
---------------------
Every call carries two independent credentials:

  * ``Authorization: token <key>:<secret>`` — proves the MACHINE caller (this service)
  * ``X-Episteck-Delegation: <token>``      — proves WHICH HUMAN SESSION we act for

Frappe verifies the machine credential, then the auth hook verifies the delegation and
resolves the actor server-side. This client never sends, and cannot send, an
``actor_person_id``: the Control Plane has no such parameter.

The delegation token is supplied by the trusted runtime (the BFF) out of band. It is
never a tool parameter, never enters the model's context, and is never logged.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DELEGATION_HEADER = "X-Episteck-Delegation"


class MissingDelegationError(RuntimeError):
    """Raised when a person-scoped call is attempted with no human session."""


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

    def _call(self, method: str, params: dict[str, str], delegation: str | None) -> Any:
        # Fail closed: no human session means no person-scoped call is attempted.
        if not delegation:
            return {"ok": False, "error": "no_authenticated_human_session"}
        try:
            response = self._client.get(
                f"/api/method/episteck_home.api.{method}",
                params=params,
                headers={DELEGATION_HEADER: delegation},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or "message" not in payload:
                raise ValueError("missing Frappe message")
            return payload["message"]
        except httpx.HTTPStatusError as error:
            if error.response.status_code in {401, 403, 404}:
                return {"ok": False, "error": "not_authorized_or_not_found"}
            return {"ok": False, "error": "home_control_plane_unavailable"}
        except httpx.HTTPError:
            return {"ok": False, "error": "home_control_plane_unavailable"}
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_home_control_plane_response"}

    def whoami(self, delegation: str | None):
        return self._call("whoami", {}, delegation)

    def get_person(self, person_id: str, delegation: str | None):
        return self._call("get_person", {"person_id": person_id}, delegation)

    def list_my_circles(self, delegation: str | None):
        return self._call("list_my_circles", {}, delegation)

    def list_circle_members(self, circle_id: str, delegation: str | None):
        return self._call("list_circle_members", {"circle_id": circle_id}, delegation)

    def list_people_i_care_for(self, delegation: str | None):
        return self._call("list_people_i_care_for", {}, delegation)

    def get_access_to_person(self, subject_person_id: str, delegation: str | None):
        return self._call(
            "get_access_to_person",
            {"subject_person_id": subject_person_id},
            delegation,
        )

    def check_access(
        self,
        subject_person_id: str,
        domain: str,
        action: str,
        delegation: str | None,
    ) -> dict:
        result = self._call(
            "check_access",
            {
                "subject_person_id": subject_person_id,
                # Agent models commonly produce display casing (for example,
                # "Nutrition"). Canonicalizing casing is not an authorization
                # fallback: Frappe still validates the resulting exact domain and
                # action and remains the sole decision authority.
                "domain": str(domain).strip().upper(),
                "action": str(action).strip().upper(),
            },
            delegation,
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

    def get_care_dashboard(self, delegation: str | None):
        return self._call("get_care_dashboard", {}, delegation)
