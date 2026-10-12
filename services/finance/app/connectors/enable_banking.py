"""Enable Banking (PSD2 AIS) connector.

Facts this relies on (docs checked 2026-10-10, see the I1 plan):
* ``uid`` of an account is SESSION-scoped; ``identification_hash`` is stable across
  sessions. Finance stores the hash as the account reference and keeps a per-session
  hash -> uid map (``SessionInfo``).
* Unattended ("background") fetches carry NO PSU headers; many banks allow only 4 per
  day per account. We never send PSU headers: faking user presence would misrepresent the
  request. A bank that demands them is reported as UNAVAILABLE.
* Over the bank limit the API answers 429 ``ASPSP_RATE_LIMIT_EXCEEDED``.

The 4-per-day budget is enforced HERE, locally, before anything is sent. It counts every
data request (balances and each transactions page), which is the conservative reading;
whether a bank counts per call or per sync is measured live and the cap is configuration.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import httpx

from .. import domain
from ..money import EXPONENTS, parse_amount
from ..store.repo import FinanceRepository
from .base import (
    ConnectorError, ErrorKind, ProviderAccount, RawBalance, RawMovement, sanitize_text,
)
from .eb_jwt import JwtSigner

logger = logging.getLogger("finance.enable_banking")

BASE_URL = "https://api.enablebanking.com"
TIMEOUT_SECONDS = 25.0
MAX_PAGES = 5
DEFAULT_CAP = 4
WINDOW = timedelta(hours=24)

_BOOKED_TYPES = ("CLBD", "ITBD", "OPBD")
_AVAILABLE_TYPES = ("CLAV", "ITAV", "OPAV")
_STATUS = {"BOOK": domain.MovementStatus.BOOKED, "PDNG": domain.MovementStatus.PENDING}
_CONSENT_ENDED = {"EXPIRED_SESSION"}
_NEEDS_OWNER = {"CLOSED_SESSION", "REVOKED_SESSION", "ACCESS_DENIED"}


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    accounts: Mapping[str, str]  # stable identification_hash -> session uid


class Budget(Protocol):
    def allow(self, ref: str) -> bool: ...
    def record(self, ref: str) -> None: ...
    def block(self, ref: str) -> None: ...


class RepoBudget:
    """Rolling-24h unattended-access budget per provider account, persisted in SQLite."""

    def __init__(self, repo: FinanceRepository, workspace_id: str, *, cap: int = DEFAULT_CAP,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._repo, self._ws, self._cap, self._clock = repo, workspace_id, cap, clock

    def allow(self, ref: str) -> bool:
        since = self._clock() - WINDOW
        if self._repo.count_accesses(ref, since, "BLOCK"):
            return False
        return self._repo.count_accesses(ref, since, "ACCESS") < self._cap

    def record(self, ref: str) -> None:
        self._repo.record_access(self._ws, ref, self._clock(), "ACCESS")

    def block(self, ref: str) -> None:
        self._repo.record_access(self._ws, ref, self._clock(), "BLOCK")


def _kind_for(status: int, body: object) -> ErrorKind:
    code = body.get("error") if isinstance(body, dict) else None
    if status == 429:
        if code == "PSU_HEADER_NOT_PROVIDED":
            logger.warning("enable banking: bank requires PSU headers (not sent)")
            return ErrorKind.UNAVAILABLE
        return ErrorKind.RATE_LIMITED
    if code in _CONSENT_ENDED:
        return ErrorKind.CONSENT_EXPIRED
    if status in (401, 403) or code in _NEEDS_OWNER:
        return ErrorKind.AUTH_REQUIRED
    if code == "PSU_HEADER_NOT_PROVIDED":
        logger.warning("enable banking: bank requires PSU headers (not sent)")
    return ErrorKind.UNAVAILABLE


class EbClient:
    """Authenticated HTTP. Every failure becomes a payload-free ConnectorError."""

    def __init__(self, signer: JwtSigner, *, base_url: str = BASE_URL,
                 transport: httpx.BaseTransport | None = None) -> None:
        self._signer = signer
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=TIMEOUT_SECONDS)

    def request(self, method: str, path: str, *, params: dict | None = None,
                json: dict | None = None) -> dict:
        try:
            response = self._http.request(
                method, path, params=params, json=json,
                headers={"Authorization": f"Bearer {self._signer.token()}"})
        except httpx.HTTPError:
            raise ConnectorError(ErrorKind.UNAVAILABLE) from None
        if response.status_code != 200:
            try:
                body = response.json()
            except ValueError:
                body = None
            raise ConnectorError(_kind_for(response.status_code, body))
        try:
            body = response.json()
        except ValueError:
            raise ConnectorError(ErrorKind.MALFORMED) from None
        if not isinstance(body, dict):
            raise ConnectorError(ErrorKind.MALFORMED)
        return body


def _currency(value: object) -> str:
    if not isinstance(value, str) or value not in EXPONENTS:
        raise ConnectorError(ErrorKind.MALFORMED)
    return value


def _amount(node: object) -> tuple[int, str]:
    if not isinstance(node, dict) or not isinstance(node.get("amount"), str):
        raise ConnectorError(ErrorKind.MALFORMED)
    currency = _currency(node.get("currency"))
    try:
        return parse_amount(node["amount"], currency), currency
    except (ValueError, TypeError):
        raise ConnectorError(ErrorKind.MALFORMED) from None


def _when(balance: dict, fallback: datetime) -> datetime:
    stamp = balance.get("last_change_date_time")
    try:
        if isinstance(stamp, str):
            parsed = datetime.fromisoformat(stamp)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        ref = balance.get("reference_date")
        if isinstance(ref, str):
            return datetime.combine(date.fromisoformat(ref), datetime.min.time(), timezone.utc)
    except ValueError:
        raise ConnectorError(ErrorKind.MALFORMED) from None
    return fallback  # the bank gave no date: the fetch time is the honest as-of


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        raise ConnectorError(ErrorKind.MALFORMED) from None


class EnableBankingConnector:
    provider = domain.Provider.ENABLE_BANKING

    def __init__(self, client: EbClient, session: SessionInfo, budget: Budget, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._client, self._session, self._budget, self._clock = client, session, budget, clock

    def __repr__(self) -> str:
        return "<EnableBankingConnector>"

    def list_accounts(self) -> list[ProviderAccount]:
        return []  # accounts come from the authorization session, not from a data call

    def _uid(self, ref: str) -> str:
        uid = self._session.accounts.get(ref)
        if uid is None:
            raise ConnectorError(ErrorKind.AUTH_REQUIRED)  # not in the current session
        return uid

    def _data(self, ref: str, path: str, params: dict | None = None) -> dict:
        if not self._budget.allow(ref):
            raise ConnectorError(ErrorKind.RATE_LIMITED)  # refused locally, nothing sent
        self._budget.record(ref)  # every attempt counts, successful or not
        try:
            return self._client.request("GET", path, params=params)
        except ConnectorError as error:
            if error.kind is ErrorKind.RATE_LIMITED:
                self._budget.block(ref)  # the bank itself said stop: wait out the window
            raise

    def fetch_balances(self, account_ref: str) -> list[RawBalance]:
        uid = self._uid(account_ref)
        body = self._data(account_ref, f"/accounts/{uid}/balances")
        rows = body.get("balances")
        if not isinstance(rows, list):
            raise ConnectorError(ErrorKind.MALFORMED)
        now = self._clock()
        out: list[RawBalance] = []
        for kind, types in ((domain.BalanceKind.BOOKED, _BOOKED_TYPES),
                            (domain.BalanceKind.AVAILABLE, _AVAILABLE_TYPES)):
            for balance_type in types:  # priority order
                row = next((r for r in rows if isinstance(r, dict)
                            and r.get("balance_type") == balance_type), None)
                if row is not None:
                    minor, currency = _amount(row.get("balance_amount"))
                    out.append(RawBalance(kind, minor, currency, _when(row, now)))
                    break
        if not out:
            raise ConnectorError(ErrorKind.MALFORMED)
        return out

    def fetch_movements(self, account_ref: str, since: date | None) -> list[RawMovement]:
        uid = self._uid(account_ref)
        movements: list[RawMovement] = []
        key: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, str] = {}
            if since is not None:
                params["date_from"] = since.isoformat()
            if key:
                params["continuation_key"] = key
            body = self._data(account_ref, f"/accounts/{uid}/transactions", params)
            rows = body.get("transactions")
            if not isinstance(rows, list):
                raise ConnectorError(ErrorKind.MALFORMED)
            movements += [m for m in (self._movement(r) for r in rows) if m is not None]
            key = body.get("continuation_key") if isinstance(body.get("continuation_key"), str) else None
            if not key:
                break
        return movements

    @staticmethod
    def _movement(row: object) -> RawMovement | None:
        if not isinstance(row, dict):
            raise ConnectorError(ErrorKind.MALFORMED)
        status = _STATUS.get(row.get("status"))
        if status is None:
            return None  # cancelled, rejected, scheduled, held: not a fact we record
        minor, currency = _amount(row.get("transaction_amount"))
        indicator = row.get("credit_debit_indicator")
        if indicator not in ("DBIT", "CRDT"):
            raise ConnectorError(ErrorKind.MALFORMED)
        minor = -abs(minor) if indicator == "DBIT" else abs(minor)
        party, account = ("creditor", "creditor_account") if indicator == "DBIT" else (
            "debtor", "debtor_account")
        name = (row.get(party) or {}).get("name") if isinstance(row.get(party), dict) else None
        iban = (row.get(account) or {}).get("iban") if isinstance(row.get(account), dict) else None
        info = row.get("remittance_information")
        remittance = " ".join(str(i) for i in info) if isinstance(info, list) else ""
        tx_id = row.get("transaction_id") or row.get("entry_reference")
        return RawMovement(
            provider_tx_id=tx_id if isinstance(tx_id, str) else None, status=status,
            booking_date=_date(row.get("booking_date")), value_date=_date(row.get("value_date")),
            amount_minor=minor, currency=currency, counterparty_name=sanitize_text(name, 200),
            counterparty_iban=iban if isinstance(iban, str) else None,
            remittance=sanitize_text(remittance))
