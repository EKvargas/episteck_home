"""Finance domain vocabulary. Pure types, no I/O.

Money is ``int`` minor units plus an ISO currency. Facts (balance observations,
movements) are frozen: a correction is a new fact, never an edit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class AccountType(str, Enum):
    CURRENT = "CURRENT"
    SAVINGS = "SAVINGS"
    BROKER_CASH = "BROKER_CASH"
    SECURITIES = "SECURITIES"
    EMPLOYEE_PLAN = "EMPLOYEE_PLAN"
    CASH = "CASH"


class Liquidity(str, Enum):
    AVAILABLE = "AVAILABLE"
    INVESTED = "INVESTED"
    RESTRICTED = "RESTRICTED"


class BalanceAuthority(str, Enum):
    PROVIDER = "PROVIDER"
    LEDGER = "LEDGER"
    EVIDENCE_SNAPSHOT = "EVIDENCE_SNAPSHOT"


class Provider(str, Enum):
    ENABLE_BANKING = "ENABLE_BANKING"
    SIMPLEFIN = "SIMPLEFIN"
    FILE_IMPORT = "FILE_IMPORT"


class ConnectionStatus(str, Enum):
    OK = "OK"
    REAUTH_DUE = "REAUTH_DUE"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    FAILING = "FAILING"
    PAUSED = "PAUSED"


class BalanceKind(str, Enum):
    BOOKED = "BOOKED"
    AVAILABLE = "AVAILABLE"
    VALUATION = "VALUATION"


class MovementStatus(str, Enum):
    PENDING = "PENDING"
    BOOKED = "BOOKED"


class WorkspaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    kind: str  # PERSONAL | HOUSEHOLD
    status: WorkspaceStatus


@dataclass(frozen=True)
class Connection:
    id: str
    workspace_id: str
    provider: Provider
    owner_person_id: str
    status: ConnectionStatus
    consent_expires_at: datetime | None = None
    last_success_at: datetime | None = None


@dataclass(frozen=True)
class Account:
    id: str
    workspace_id: str
    owner_person_ids: tuple[str, ...]
    institution: str
    type: AccountType
    currency: str
    liquidity: Liquidity
    balance_authority: BalanceAuthority
    movement_authority: Provider
    preferred_balance_kind: BalanceKind
    freshness_sla_hours: int
    connection_id: str | None = None
    provider_account_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.owner_person_ids:
            raise ValueError("an account needs at least one owner")


@dataclass(frozen=True)
class BalanceObservation:
    id: str
    workspace_id: str
    account_id: str
    amount_minor: int
    currency: str
    kind: BalanceKind
    as_of: datetime
    observed_at: datetime
    source_ref: str

    def __post_init__(self) -> None:
        if type(self.amount_minor) is not int:
            raise TypeError("amount_minor must be an int (minor units)")


@dataclass(frozen=True)
class Movement:
    id: str
    workspace_id: str
    account_id: str
    provider_tx_id: str | None
    fingerprint: str
    status: MovementStatus
    booking_date: date | None
    value_date: date | None
    amount_minor: int
    currency: str
    counterparty_name: str
    counterparty_iban_hash: str | None
    remittance: str
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.amount_minor) is not int:
            raise TypeError("amount_minor must be an int (minor units)")
