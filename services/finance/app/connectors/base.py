"""The one interface every bank/provider connector implements."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Protocol

from .. import domain

MAX_TEXT = 500
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")


class ErrorKind(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"        # owner must re-authorise or fix the subscription
    CONSENT_EXPIRED = "CONSENT_EXPIRED"    # PSD2 consent ended
    RATE_LIMITED = "RATE_LIMITED"          # provider or our own access budget says stop
    UNAVAILABLE = "UNAVAILABLE"            # network, 5xx, timeout: try next run
    MALFORMED = "MALFORMED"                # the answer cannot be trusted


class ConnectorError(Exception):
    """Typed failure. The message is the kind only: never a payload, URL or credential."""

    def __init__(self, kind: ErrorKind) -> None:
        super().__init__(kind.value)
        self.kind = kind


def sanitize_text(value: object, limit: int = MAX_TEXT) -> str:
    """Provider text is untrusted: drop control characters, collapse spaces, cap length."""
    if not isinstance(value, str):
        return ""
    text = _SPACES.sub(" ", _CONTROL.sub("", value)).strip()
    return text[:limit]


@dataclass(frozen=True)
class ProviderAccount:
    ref: str
    name: str
    currency: str
    institution: str


@dataclass(frozen=True)
class RawBalance:
    kind: domain.BalanceKind
    amount_minor: int
    currency: str
    as_of: datetime


@dataclass(frozen=True)
class RawMovement:
    provider_tx_id: str | None
    status: domain.MovementStatus
    booking_date: date | None
    value_date: date | None
    amount_minor: int
    currency: str
    counterparty_name: str
    counterparty_iban: str | None
    remittance: str


class Connector(Protocol):
    provider: domain.Provider

    def list_accounts(self) -> list[ProviderAccount]: ...

    def fetch_balances(self, account_ref: str) -> list[RawBalance]: ...

    def fetch_movements(self, account_ref: str, since: date | None) -> list[RawMovement]: ...
