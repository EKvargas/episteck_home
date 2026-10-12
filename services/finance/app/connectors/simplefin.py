"""SimpleFIN Bridge connector (protocol v2, https://www.simplefin.org/protocol.html).

* A setup token is base64 of a claim URL; POSTing to it yields the Access URL, which
  embeds Basic Auth credentials. That URL is a secret: it lives in a mode-600 file, is
  split into a URL and an Authorization header here, and never appears in logs, errors
  or ``repr``.
* Amounts and balances arrive as STRINGS; timestamps are unix epoch seconds. A custom
  currency (a URL) is refused, never guessed.
* Rate limits and the history window are not in the spec and are measured live.
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
from datetime import date, datetime, timezone
from urllib.parse import unquote, urlsplit

import httpx

from .. import domain
from ..money import EXPONENTS, parse_amount
from .base import (
    ConnectorError, ErrorKind, ProviderAccount, RawBalance, RawMovement, sanitize_text,
)

logger = logging.getLogger("finance.simplefin")

_ISO = re.compile(r"^[A-Z]{3}$")
_AUTH_CODES = ("gen.auth", "con.auth")
TIMEOUT_SECONDS = 20.0


class TokenAlreadyClaimed(Exception):
    """The setup token is unknown or already claimed (the spec warns of possible compromise)."""


def claim(setup_token: str, *, transport: httpx.BaseTransport | None = None) -> str:
    try:
        claim_url = base64.b64decode(setup_token.strip(), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        raise ValueError("setup token is not valid base64") from None
    parts = urlsplit(claim_url)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("setup token does not decode to an https URL")
    try:
        response = httpx.Client(transport=transport, timeout=TIMEOUT_SECONDS).post(claim_url)
    except httpx.HTTPError:
        raise ConnectorError(ErrorKind.UNAVAILABLE) from None
    if response.status_code == 403:
        logger.warning("simplefin setup token rejected: unknown or already claimed")
        raise TokenAlreadyClaimed("setup token rejected (possible compromise: re-issue it)")
    if response.status_code != 200 or not response.text.strip():
        raise ConnectorError(ErrorKind.UNAVAILABLE)
    return response.text.strip()


def _currency(value: object) -> str:
    if not isinstance(value, str) or not _ISO.match(value) or value not in EXPONENTS:
        raise ConnectorError(ErrorKind.MALFORMED)
    return value


def _money(value: object, currency: str) -> int:
    if not isinstance(value, str):
        raise ConnectorError(ErrorKind.MALFORMED)
    try:
        return parse_amount(value, currency)
    except (ValueError, TypeError):
        raise ConnectorError(ErrorKind.MALFORMED) from None


def _utc(epoch: object) -> datetime:
    if type(epoch) is not int or epoch <= 0:
        raise ConnectorError(ErrorKind.MALFORMED)
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class SimpleFinConnector:
    provider = domain.Provider.SIMPLEFIN

    def __init__(self, access_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        parts = urlsplit(access_url)
        if parts.scheme != "https" or not parts.hostname or not parts.username or parts.password is None:
            raise ValueError("access URL must be https with embedded credentials")
        port = f":{parts.port}" if parts.port else ""
        self._host = parts.hostname
        self._base = f"https://{parts.hostname}{port}{parts.path.rstrip('/')}"
        self._client = httpx.Client(
            auth=(unquote(parts.username), unquote(parts.password)),
            transport=transport, timeout=TIMEOUT_SECONDS)

    def __repr__(self) -> str:
        return f"<SimpleFinConnector host={self._host}>"

    # --- HTTP ---------------------------------------------------------------------
    def _get(self, params: dict[str, str]) -> dict:
        try:
            response = self._client.get(f"{self._base}/accounts", params={"version": "2", **params})
        except httpx.HTTPError:
            raise ConnectorError(ErrorKind.UNAVAILABLE) from None
        status = response.status_code
        if status in (401, 402, 403):
            raise ConnectorError(ErrorKind.AUTH_REQUIRED)
        if status == 429:
            raise ConnectorError(ErrorKind.RATE_LIMITED)
        if status != 200:
            raise ConnectorError(ErrorKind.UNAVAILABLE)
        try:
            body = response.json()
        except ValueError:
            raise ConnectorError(ErrorKind.MALFORMED) from None
        if not isinstance(body, dict):
            raise ConnectorError(ErrorKind.MALFORMED)
        return body

    def _account(self, body: dict, ref: str) -> dict:
        accounts = body.get("accounts")
        errlist = body.get("errlist") or []
        if not isinstance(accounts, list) or not isinstance(errlist, list):
            raise ConnectorError(ErrorKind.MALFORMED)
        account = next((a for a in accounts if isinstance(a, dict) and a.get("id") == ref), None)
        conn_id = account.get("conn_id") if account else None
        relevant = [
            e for e in errlist if isinstance(e, dict) and (
                e.get("account_id") == ref
                or (e.get("conn_id") is not None and e.get("conn_id") == conn_id)
                or (e.get("conn_id") is None and e.get("account_id") is None))
        ]
        if any(str(e.get("code", "")).startswith(_AUTH_CODES) for e in relevant):
            raise ConnectorError(ErrorKind.AUTH_REQUIRED)
        if relevant:
            raise ConnectorError(ErrorKind.UNAVAILABLE)
        if account is None:
            raise ConnectorError(ErrorKind.UNAVAILABLE if errlist else ErrorKind.MALFORMED)
        return account

    # --- Connector ----------------------------------------------------------------
    def list_accounts(self) -> list[ProviderAccount]:
        body = self._get({"balances-only": "1"})
        names = {c.get("conn_id"): c.get("name", "") for c in body.get("connections") or []
                 if isinstance(c, dict)}
        out = []
        for account in body.get("accounts") or []:
            if not isinstance(account, dict):
                continue
            try:
                currency = _currency(account.get("currency"))
            except ConnectorError:
                logger.warning("simplefin account skipped: unsupported currency")
                continue
            out.append(ProviderAccount(
                str(account.get("id")), sanitize_text(account.get("name"), 100), currency,
                sanitize_text(names.get(account.get("conn_id")), 100)))
        return out

    def fetch_balances(self, account_ref: str) -> list[RawBalance]:
        account = self._account(
            self._get({"balances-only": "1", "account": account_ref}), account_ref)
        currency = _currency(account.get("currency"))
        as_of = _utc(account.get("balance-date"))
        balances = [RawBalance(domain.BalanceKind.BOOKED,
                               _money(account.get("balance"), currency), currency, as_of)]
        if account.get("available-balance") is not None:
            balances.append(RawBalance(domain.BalanceKind.AVAILABLE,
                                       _money(account["available-balance"], currency),
                                       currency, as_of))
        return balances

    def fetch_movements(self, account_ref: str, since: date | None) -> list[RawMovement]:
        params = {"pending": "1", "account": account_ref}
        if since is not None:
            midnight = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
            params["start-date"] = str(int(midnight.timestamp()))
        account = self._account(self._get(params), account_ref)
        currency = _currency(account.get("currency"))
        movements = []
        for tx in account.get("transactions") or []:
            if not isinstance(tx, dict) or not isinstance(tx.get("id"), str):
                raise ConnectorError(ErrorKind.MALFORMED)
            posted = tx.get("posted")
            if type(posted) is not int or posted < 0:
                raise ConnectorError(ErrorKind.MALFORMED)
            pending = tx.get("pending") is True or posted == 0
            booking = _utc(posted).date() if posted > 0 else None
            transacted = tx.get("transacted_at")
            value_date = _utc(transacted).date() if type(transacted) is int and transacted > 0 else booking
            movements.append(RawMovement(
                provider_tx_id=tx["id"],
                status=domain.MovementStatus.PENDING if pending else domain.MovementStatus.BOOKED,
                booking_date=booking, value_date=value_date,
                amount_minor=_money(tx.get("amount"), currency), currency=currency,
                counterparty_name="", counterparty_iban=None,
                remittance=sanitize_text(tx.get("description"))))
        return movements
