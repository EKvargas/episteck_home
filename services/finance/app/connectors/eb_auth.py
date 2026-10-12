"""Enable Banking authorization: start (consent URL) and complete (code to session).

* The consent period requested is capped at the bank's ``maximum_consent_validity``; the
  stored ``consent_expires_at`` comes from the session response, not from what we asked.
* ``state`` is random, single-use and expires in 15 minutes. Only its SHA-256 is stored.
  Unknown, expired and reused states fail identically, and the code is never logged.
* Account UIDs are session-scoped, so the session map is hash -> uid and is REPLACED on
  every reauthorization. An account the bank returns that we did not link is counted and
  never linked silently; a linked account the bank no longer returns is counted as missing.

This module is service logic only. The public callback route is a Phase B change.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import domain
from ..store.repo import FinanceRepository
from .base import ConnectorError
from .enable_banking import EbClient

logger = logging.getLogger("finance.eb_auth")

STATE_TTL = timedelta(minutes=15)


class AuthorizationError(Exception):
    """Static message by design: the caller must not learn why."""

    def __init__(self) -> None:
        super().__init__("authorization could not be completed")


@dataclass(frozen=True)
class AuthorizationResult:
    connection_id: str
    consent_expires_at: datetime
    linked: int
    unexpected: int
    missing: int


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def start_authorization(client: EbClient, repo: FinanceRepository, workspace_id: str,
                        connection_id: str, *, aspsp_name: str, country: str,
                        redirect_url: str, requested_days: int, now: datetime) -> str:
    connection = next((c for c in repo.list_connections(workspace_id)
                       if c.id == connection_id), None)
    if connection is None or connection.provider is not domain.Provider.ENABLE_BANKING:
        raise AuthorizationError()
    try:
        banks = client.request("GET", "/aspsps", params={"country": country}).get("aspsps")
        bank = next((b for b in banks or [] if isinstance(b, dict) and b.get("name") == aspsp_name), None)
        maximum = bank.get("maximum_consent_validity") if bank else None
        if type(maximum) is not int or maximum <= 0:
            raise AuthorizationError()
        valid_until = now + min(timedelta(days=requested_days), timedelta(seconds=maximum))
        state = secrets.token_urlsafe(32)
        repo.create_oauth_state(_hash(state), workspace_id, connection_id,
                                connection.owner_person_id, now + STATE_TTL)
        response = client.request("POST", "/auth", json={
            "access": {"valid_until": valid_until.isoformat()},
            "aspsp": {"name": aspsp_name, "country": country},
            "state": state, "redirect_url": redirect_url, "psu_type": "personal"})
    except ConnectorError as error:
        logger.warning("authorization not started: %s", error.kind.value)
        raise AuthorizationError() from None
    url = response.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise AuthorizationError()
    return url


def complete_authorization(client: EbClient, repo: FinanceRepository, state: str, code: str,
                           *, now: datetime) -> AuthorizationResult:
    claimed = repo.consume_oauth_state(_hash(state), now)
    if claimed is None:
        logger.warning("authorization callback refused: invalid state")
        raise AuthorizationError()
    try:
        session = client.request("POST", "/sessions", json={"code": code})
        session_id = session["session_id"]
        valid_until = datetime.fromisoformat(session["access"]["valid_until"])
        returned = {a["identification_hash"]: a.get("uid") for a in session["accounts"]}
    except (ConnectorError, KeyError, TypeError, ValueError):
        logger.warning("authorization callback refused: code exchange failed")
        raise AuthorizationError() from None
    if not isinstance(session_id, str) or valid_until.tzinfo is None:
        raise AuthorizationError()
    linked_refs = {a.provider_account_ref for a in repo.list_accounts(claimed.workspace_id)
                   if a.connection_id == claimed.connection_id and a.provider_account_ref}
    mapping = {ref: uid for ref, uid in returned.items()
               if ref in linked_refs and isinstance(uid, str)}
    repo.activate_eb_session(claimed.workspace_id, claimed.connection_id, session_id,
                             valid_until, now, mapping)
    return AuthorizationResult(
        claimed.connection_id, valid_until, linked=len(mapping),
        unexpected=len([r for r in returned if r not in linked_refs]),
        missing=len(linked_refs - mapping.keys()))
