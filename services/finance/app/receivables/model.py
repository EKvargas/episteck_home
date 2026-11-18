"""Receivables vocabulary. Pure types, no I/O. Money is ``int`` minor units plus an ISO currency.

Human refs: ``C<n>`` exchange, ``F<n>`` funding, ``R<n>`` receipt, ``E<n>`` entry, ``P<n>`` pending.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from fractions import Fraction
from typing import Any

# Sentinels
OWNER = "OWNER"
CASH_ABROAD = "CASH_ABROAD"

# Constants (exact, from the design spec)
NOTICE_BAND = Fraction(3, 100)  # ratio (3 %), vs ECB; compare with fx.deviation()
LINK_BAND = Fraction(8, 100)  # ratio (8 %), vs ECB; compare with fx.deviation()
EUR_ADJUST_TOLERANCE_MINOR = 100  # 1,00 EUR
FUND_ALERT_DEFAULT_MINOR = 50000  # 500 USD
HIGH_VALUE_USD_MINOR = 50000  # 500 USD or equivalent
EXACT_SUBSET_LIMIT = 16
RESURFACE_AFTER = timedelta(hours=20)
CRON_TIMES_UTC = ("06:35", "18:35")


class CounterpartyKind(str, Enum):
    PERSON = "PERSON"
    EXCHANGE_PARTNER = "EXCHANGE_PARTNER"
    FUND = "FUND"


class Opening(str, Enum):
    UNKNOWN = "UNKNOWN"
    APPROXIMATE = "APPROXIMATE"
    CONFIRMED = "CONFIRMED"


class EntryKind(str, Enum):
    CHARGE = "CHARGE"
    PAYMENT = "PAYMENT"
    OPENING = "OPENING"
    ADJUSTMENT = "ADJUSTMENT"
    FORGIVE = "FORGIVE"
    REVERSAL = "REVERSAL"


class ReceiptKind(str, Enum):
    BANK = "BANK"
    CASH = "CASH"
    IN_KIND = "IN_KIND"


class Verification(str, Enum):
    BANK_POSTED = "BANK_POSTED"
    OWNER_CONFIRMED = "OWNER_CONFIRMED"


class AllocationMethod(str, Enum):
    AUTO_EXACT = "AUTO_EXACT"
    AUTO_FIFO = "AUTO_FIFO"
    OWNER = "OWNER"


class PendingKind(str, Enum):
    LINK_FUNDING = "LINK_FUNDING"
    PREVIOUS_UNPAID = "PREVIOUS_UNPAID"
    EXPLAIN_INCOMING = "EXPLAIN_INCOMING"
    CONFIRM = "CONFIRM"
    REVIEW_OPENING = "REVIEW_OPENING"
    INFO = "INFO"


class MovementRoleKind(str, Enum):
    EXCHANGE_FUNDING = "EXCHANGE_FUNDING"
    RECEIVABLE_PAYMENT = "RECEIVABLE_PAYMENT"
    FUND_DEPOSIT = "FUND_DEPOSIT"
    NOT_EXCHANGE = "NOT_EXCHANGE"


@dataclass(frozen=True)
class Counterparty:
    id: str
    workspace_id: str
    kind: CounterpartyKind
    label: str
    status: str
    pay_currency: str | None = None
    settles_to: str | None = None
    opening: Opening | None = None
    alert_below_minor: int | None = None


@dataclass(frozen=True)
class Exchange:
    id: str
    workspace_id: str
    number: int
    partner_id: str
    total_usd_minor: int
    delivered_on: date
    created_at: datetime
    ves_amount_minor: int | None = None
    ves_reference_hash: str | None = None


@dataclass(frozen=True)
class ExchangeLine:
    id: str
    exchange_id: str
    version: int
    position: int
    payer_id: str
    usd_minor: int
    debt_currency: str
    beneficiary_note: str | None = None
    eur_override_minor: int | None = None


@dataclass(frozen=True)
class Funding:
    """A set of partner payments funding exchanges.

    ``movement_ids`` read back from the store are ROOT movement ids (a BOOKED successor is
    stored and returned as the PENDING movement it supersedes), deduplicated.
    """

    id: str
    workspace_id: str
    number: int
    movement_ids: tuple[str, ...]
    exchange_ids: tuple[str, ...]
    eur_minor: int
    usd_minor: int
    created_at: datetime


@dataclass(frozen=True)
class LedgerEntry:
    id: str
    workspace_id: str
    number: int
    counterparty_id: str
    currency: str
    amount_minor: int
    kind: EntryKind
    effective_on: date
    source_ref: str
    note: str = ""
    basis: str | None = None
    reverses_id: str | None = None


@dataclass(frozen=True)
class Receipt:
    id: str
    workspace_id: str
    number: int
    kind: ReceiptKind
    payer_id: str
    currency: str
    amount_minor: int
    received_on: date
    verification: Verification
    movement_id: str | None = None
    description: str = ""


@dataclass(frozen=True)
class Allocation:
    id: str
    workspace_id: str
    receipt_id: str
    line_id: str
    amount_minor: int
    method: AllocationMethod


@dataclass(frozen=True)
class PendingItem:
    code: str
    workspace_id: str
    kind: PendingKind
    requires_answer: bool
    options: tuple[str, ...]
    payload: dict[str, Any]
    dedupe_key: str
    created_at: datetime
    delivered_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None
    snooze_until: datetime | None = None
