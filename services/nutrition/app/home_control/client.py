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

OPERATIONS NEEDING SEVERAL PERMISSIONS
--------------------------------------
Removing the second call is not enough on its own: some operations genuinely need more
than one permission. ``ate_as_planned`` reads a planned meal (VIEW) and then creates an
actual intake (CREATE), and it must not create one for a person whose plan it was not
allowed to read.

``check_access_many`` decides both in ONE delegated request. The constraint replay
protection imposes is on the number of REQUESTS, not the number of decisions, so this
satisfies it without weakening it. The alternative — asking for only CREATE, or
splitting into two requests — would either under-authorize or fail outright.
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

    def check_access_many(
        self,
        subject_person_id: str,
        requirements: list[tuple[str, str]],
        delegation: str | None = None,
    ) -> AccessDecision:
        """Authorize SEVERAL (domain, action) requirements in ONE delegated request.

        An operation that needs two permissions — ``ate_as_planned`` reads a plan and
        then creates intake — cannot make two ``check_access`` calls: the delegation is
        single-use, so the second is replay-denied. This asks Home once and gets one
        overall answer, with replay protection unchanged.

        Returns a single ``AccessDecision``: allow only when EVERY requirement allows.
        The per-requirement detail is used for the refusal reason; callers get a
        decision, not a permission list to interpret.
        """
        if not subject_person_id or not requirements:
            return _INDETERMINATE
        if any(not domain or not action for domain, action in requirements):
            return _INDETERMINATE
        if not delegation:
            return _NO_SESSION
        try:
            response = self._client.post(
                "/api/method/episteck_home.api.check_access_many",
                json={
                    "subject_person_id": subject_person_id,
                    "requirements": [
                        {"domain": domain, "action": action}
                        for domain, action in requirements
                    ],
                },
                headers={DELEGATION_HEADER: delegation},
            )
            response.raise_for_status()
            payload = response.json()
            decision = payload["message"]
            if not isinstance(decision, dict) or type(decision.get("allow")) is not bool:
                return _INDETERMINATE
            # The overall allow is authoritative, but it must not be trusted over a
            # decision list that disagrees with it: if any listed requirement denies,
            # this is a denial regardless of the summary flag.
            listed = decision.get("decisions")
            if isinstance(listed, list) and listed:
                if len(listed) != len(requirements):
                    return _INDETERMINATE
                if any(item.get("allow") is not True for item in listed):
                    return AccessDecision(
                        False,
                        str(decision.get("reason") or "Home Control Plane decision"),
                    )
            elif decision["allow"]:
                # An allow with no per-requirement detail cannot be verified.
                return _INDETERMINATE
            return AccessDecision(
                decision["allow"],
                str(decision.get("reason") or "Home Control Plane decision"),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return _INDETERMINATE
