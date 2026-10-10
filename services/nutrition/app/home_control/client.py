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

OUTCOMES
--------
Every decision carries an ``outcome`` so the HTTP boundary can answer 401 / 403 / 503
rather than collapsing every refusal into one. Only ``allow`` decides access; the
outcome only explains a refusal:

    ALLOW            Home literally allowed, with a non-empty reason.
    DENY             Home literally denied (authoritative).
    SESSION_INVALID  Home rejected the credential or delegation (401/403), or there was
                     no delegation to send.
    UNAVAILABLE      Home could not give a complete, trustworthy answer: unreachable,
                     timed out, 5xx, malformed, or an allow that could not be verified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os

import httpx

DELEGATION_HEADER = "X-Episteck-Delegation"

logger = logging.getLogger("nutrition.home_control")

ALLOW = "ALLOW"
DENY = "DENY"
SESSION_INVALID = "SESSION_INVALID"
UNAVAILABLE = "UNAVAILABLE"
_OUTCOMES = frozenset({ALLOW, DENY, SESSION_INVALID, UNAVAILABLE})


@dataclass(frozen=True)
class AccessDecision:
    """A Home authorization result.

    ``outcome`` distinguishes WHY access was refused so the HTTP boundary can answer
    401 / 403 / 503. It is excluded from equality so existing ``(allow, reason)``
    comparisons stay valid; outcome tests assert it explicitly.
    """

    allow: bool
    reason: str
    outcome: str = field(default="", compare=False)

    def __post_init__(self):
        if not self.outcome:
            object.__setattr__(self, "outcome", ALLOW if self.allow else DENY)
        if self.outcome not in _OUTCOMES:
            raise ValueError("unknown authorization outcome")
        if self.allow != (self.outcome == ALLOW):
            raise ValueError("allow and outcome disagree")


_INDETERMINATE = AccessDecision(False, "authorization indeterminate (fail closed)", UNAVAILABLE)
_NO_SESSION = AccessDecision(False, "no authenticated human session (fail closed)", SESSION_INVALID)
# Home refused to resolve a human actor: invalid, expired, replayed or wrong-audience
# delegation, logged-out session, or (operator-visible via the log category) a broken
# Nutrition machine credential.
_SESSION_REJECTED = AccessDecision(False, "authorization indeterminate (fail closed)", SESSION_INVALID)


def _refused(category: str, decision: AccessDecision) -> AccessDecision:
    """Log one static category per refusal. Never an identity, token or Home reason."""
    logger.warning("home authorization not granted: %s", category)
    return decision


def _transport_refusal(response: httpx.Response) -> AccessDecision | None:
    if response.status_code in (401, 403):
        return _refused("home_rejected_credential_or_session", _SESSION_REJECTED)
    if response.status_code != 200:
        return _refused("home_unreachable", _INDETERMINATE)
    return None


def _well_formed_decision(response: httpx.Response) -> dict | None:
    """The decision object, or None when the body is not a complete decision.

    ``reason`` is REQUIRED as a non-empty string for the response to be complete. Its
    wording is never interpreted: only the boolean ``allow`` decides.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    decision = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(decision, dict) or type(decision.get("allow")) is not bool:
        return None
    reason = decision.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    return decision


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
            return _refused("invalid_request", _INDETERMINATE)
        if not delegation:
            return _refused("session_invalid", _NO_SESSION)
        try:
            response = self._client.get(
                "/api/method/episteck_home.api.check_access",
                params={"subject_person_id": subject_person_id, "domain": domain, "action": action},
                headers={DELEGATION_HEADER: delegation},
            )
        except (ValueError, httpx.InvalidURL):
            # An unusable credential (e.g. non-latin-1 header value) fails while the
            # request is built, so nothing was sent.
            return _refused("session_invalid", _NO_SESSION)
        except httpx.HTTPError:
            return _refused("home_unreachable", _INDETERMINATE)
        refusal = _transport_refusal(response)
        if refusal is not None:
            return refusal
        decision = _well_formed_decision(response)
        if decision is None:
            return _refused("home_malformed", _INDETERMINATE)
        if not decision["allow"]:
            return _refused("deny", AccessDecision(False, decision["reason"]))
        return AccessDecision(True, decision["reason"])

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

        EXACT RESPONSE COVERAGE
        -----------------------
        An allow is accepted only when the response proves it decided THE
        REQUIREMENTS WE SENT — not merely the right NUMBER of them. Counting alone
        would accept a response that allowed two permissions we never asked for, so
        each returned decision must match the requirement at its own position:

            sent[i] == (domain, action) == returned[i]

        ORDERING IS PART OF THE CONTRACT. ``check_access_many`` decides requirements
        in the order received and returns them in that order, so positional matching
        is exact and a reordered response is refused rather than re-sorted. Matching
        as an unordered set would be weaker for no benefit: it would accept a response
        that silently swapped which permission was allowed when the same pair appears
        with different decisions, and it would hide a server that had stopped
        preserving order — a change we want to fail loudly, not absorb.

        Every mismatch is INDETERMINATE (fail closed), never a silent allow.
        """
        if not subject_person_id or not requirements:
            return _refused("invalid_request", _INDETERMINATE)
        if any(not domain or not action for domain, action in requirements):
            return _refused("invalid_request", _INDETERMINATE)
        if not delegation:
            return _refused("session_invalid", _NO_SESSION)
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
        except (ValueError, httpx.InvalidURL):
            # An unusable credential (e.g. non-latin-1 header value) fails while the
            # request is built, so nothing was sent.
            return _refused("session_invalid", _NO_SESSION)
        except httpx.HTTPError:
            return _refused("home_unreachable", _INDETERMINATE)
        refusal = _transport_refusal(response)
        if refusal is not None:
            return refusal
        decision = _well_formed_decision(response)
        if decision is None:
            return _refused("home_malformed", _INDETERMINATE)
        reason = decision["reason"]
        # A denial needs no corroboration: refusing is always safe.
        if not decision["allow"]:
            return _refused("deny", AccessDecision(False, reason))
        # An allow must be proven against the requirements we actually sent.
        listed = decision.get("decisions")
        if not isinstance(listed, list) or len(listed) != len(requirements):
            return _refused("home_malformed", _INDETERMINATE)
        for (domain, action), item in zip(requirements, listed):
            # `item` is untrusted: a non-dict must yield a controlled refusal, not an
            # AttributeError from item.get(). Checked before any attribute use.
            if not isinstance(item, dict):
                return _refused("home_malformed", _INDETERMINATE)
            if item.get("domain") != domain or item.get("action") != action:
                return _refused("home_malformed", _INDETERMINATE)
            if item.get("allow") is not True:
                return _refused("deny", AccessDecision(False, reason))
        return AccessDecision(True, reason)
