"""Enable Banking authorization: start (consent URL), receive (public callback), complete.

* The consent period requested is capped at the bank's ``maximum_consent_validity``; the
  stored ``consent_expires_at`` comes from the session response, not from what we asked.
* ``state`` is random, single-use and expires in 15 minutes. Only its SHA-256 is stored.
  Unknown, expired and reused states fail identically, and the code is never logged.
* The public callback only consumes the state and keeps the code for the operator's
  command (``app.connect``), which holds the application key and exchanges it. The API
  process that serves the callback never sees a provider credential (ADR-0013).
* Account UIDs are session-scoped, so the session map is hash -> uid and is REPLACED on
  every reauthorization. It keeps every returned account, so an account linked after the
  first consent needs no second SCA. Linking is still the owner's step (``link-account``):
  an account without an account row is never read. Linked accounts the bank no longer
  returns are counted as missing.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from .. import domain
from ..store.repo import FinanceRepository, ReceivedCallback
from .base import ConnectorError, sanitize_text
from .enable_banking import EbClient

logger = logging.getLogger("finance.eb_auth")

STATE_TTL = timedelta(minutes=15)
_STATE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")  # what secrets.token_urlsafe produces
_CODE = re.compile(r"^[\x21-\x7e]{1,2048}$")      # printable ASCII, no spaces
_MAX_ERROR = 256
_ISO = re.compile(r"^[A-Z]{3}$")


class AuthorizationError(Exception):
    """Static message by design: the caller must not learn why."""

    def __init__(self) -> None:
        super().__init__("authorization could not be completed")


@dataclass(frozen=True)
class StartedAuthorization:
    url: str
    state_hash: str  # what the operator's command waits for; the state itself never leaves


@dataclass(frozen=True)
class OfferedAccount:
    ref: str       # stable identification_hash, the value for ``link-account --provider-ref``
    label: str     # product, or the cash account type; never the holder's name
    currency: str
    linked: bool


@dataclass(frozen=True)
class AuthorizationResult:
    connection_id: str
    consent_expires_at: datetime
    linked: int
    unexpected: int
    missing: int
    accounts: tuple[OfferedAccount, ...] = ()


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def start_authorization(client: EbClient, repo: FinanceRepository, workspace_id: str,
                        connection_id: str, *, aspsp_name: str, country: str,
                        redirect_url: str, requested_days: int,
                        now: datetime) -> StartedAuthorization:
    connection = next((c for c in repo.list_connections(workspace_id)
                       if c.id == connection_id), None)
    if connection is None or connection.provider is not domain.Provider.ENABLE_BANKING:
        raise AuthorizationError()
    repo.purge_callbacks(now - STATE_TTL)
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
    return StartedAuthorization(url, _hash(state))


def receive_callback(repo: FinanceRepository, state: str | None, *, code: str | None,
                     error: str | None, now: datetime) -> bool:
    """The public redirect: exactly ``state`` plus ``code`` (granted) or ``error`` (refused).

    Never contacts the bank. A malformed request consumes nothing; a well-formed one
    consumes the state even when the bank reports a refusal, so the link cannot be reused.
    """
    granted = isinstance(code, str) and bool(_CODE.match(code)) and error is None
    refused = (code is None and isinstance(error, str) and 0 < len(error) <= _MAX_ERROR)
    if not (isinstance(state, str) and _STATE.match(state)) or not (granted or refused):
        logger.warning("authorization callback refused: malformed")
        return False
    if not repo.record_callback(_hash(state), code if granted else None, now):
        logger.warning("authorization callback refused: invalid state")
        return False
    logger.info("authorization callback received: %s", "granted" if granted else "refused")
    return True


def _offered(account: dict, linked_refs: set[str]) -> OfferedAccount:
    currency = account.get("currency")
    label = (sanitize_text(account.get("product"), 60)
             or sanitize_text(account.get("cash_account_type"), 60))
    ref = account["identification_hash"]
    return OfferedAccount(ref, label,
                          currency if isinstance(currency, str) and _ISO.match(currency) else "",
                          linked=ref in linked_refs)


def complete_authorization(client: EbClient, repo: FinanceRepository,
                           received: ReceivedCallback | None, *,
                           now: datetime) -> AuthorizationResult:
    if received is None or received.code is None:
        logger.warning("authorization not completed: refused at the bank")
        raise AuthorizationError()
    linked_refs = {a.provider_account_ref for a in repo.list_accounts(received.workspace_id)
                   if a.connection_id == received.connection_id and a.provider_account_ref}
    try:
        session = client.request("POST", "/sessions", json={"code": received.code})
        session_id = session["session_id"]
        valid_until = datetime.fromisoformat(session["access"]["valid_until"])
        returned = [a for a in session["accounts"]
                    if isinstance(a.get("identification_hash"), str)]
        offered = tuple(_offered(a, linked_refs) for a in returned)
    except (ConnectorError, KeyError, TypeError, ValueError, AttributeError):
        logger.warning("authorization not completed: code exchange failed")
        raise AuthorizationError() from None
    if not isinstance(session_id, str) or valid_until.tzinfo is None:
        raise AuthorizationError()
    mapping = {a["identification_hash"]: a["uid"] for a in returned
               if isinstance(a.get("uid"), str)}
    repo.activate_eb_session(received.workspace_id, received.connection_id, session_id,
                             valid_until, now, mapping)
    logger.info("authorization completed for a connection")
    return AuthorizationResult(
        received.connection_id, valid_until,
        linked=len(linked_refs & mapping.keys()),
        unexpected=len([r for r in mapping if r not in linked_refs]),
        missing=len(linked_refs - mapping.keys()), accounts=offered)
