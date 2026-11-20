"""Movement interpretation model: kinds, the facts read in bulk, and shared constants.

Interpretation is computed at read time from what the I2 receivables layer stores; nothing
here writes. ``InterpretationFacts`` is loaded by ``ReceivablesRepository.interpretation_facts``
with a fixed number of queries, whatever the number of movements.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from .. import domain
from ..receivables.model import Counterparty, Funding, MovementRoleKind, Receipt

PAIR_WINDOW_DAYS = 5
STALE_PENDING_DAYS = 5
DEFAULT_LOOKBACK_DAYS = 90
MAX_RANGE_DAYS = 400
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_MONTHS_BACK = 24
WHO_CHARS = 40
TEXT_CHARS = 80
TOP_SPENDING = 5
TEXT_MIN_CHARS = 2
TEXT_MAX_CHARS = 60


class Kind(str, Enum):
    OWN = "OWN"
    OWN_TRANSFER = "OWN_TRANSFER"
    EXCHANGE = "EXCHANGE"
    PARTNER_FAVOR = "PARTNER_FAVOR"
    FAMILY = "FAMILY"
    FAMILY_HELP = "FAMILY_HELP"
    FUND = "FUND"
    UNCLEAR = "UNCLEAR"


EXCLUDED_GROUPS = {
    Kind.OWN_TRANSFER: "own_transfers",
    Kind.EXCHANGE: "exchange",
    Kind.PARTNER_FAVOR: "partner_favor",
    Kind.FAMILY: "family",
    Kind.FUND: "fund",
}


@dataclass(frozen=True)
class Interpretation:
    kind: Kind
    about: str | None = None
    ref: str | None = None  # F<n>, R<n> or P<n>
    funding_id: str | None = None


@dataclass(frozen=True)
class HelpItem:
    source: str  # "exchange_help", "exchange_own" or "forgiven"
    currency: str
    amount_minor: int
    day: date
    about: str | None
    funding_ref: str | None


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str  # "YYYY-MM" or "YYYY"


@dataclass(frozen=True)
class InterpretationFacts:
    supersedes: Mapping[str, str]  # movement id -> the id it supersedes
    fundings: Mapping[str, Funding]  # root -> live funding
    receipts: Mapping[str, Receipt]  # root -> live BANK receipt
    roles: Mapping[str, MovementRoleKind]  # root -> live role
    questions: Mapping[str, str]  # root -> code of an open LINK_FUNDING / EXPLAIN_INCOMING
    partner_hashes: Mapping[str, str]
    own_hashes: frozenset[str]
    rules: Mapping[str, str]  # key hash -> counterparty id or IGNORE (newest live rule)
    counterparties: Mapping[str, Counterparty]
    person_names: Mapping[str, str]  # normalised label/alias -> id, PERSON counterparties

    def root(self, movement_id: str) -> str:
        current, seen = movement_id, {movement_id}
        while True:
            nxt = self.supersedes.get(current)
            if nxt is None or nxt in seen:
                return current
            seen.add(nxt)
            current = nxt


def movement_day(mv: domain.Movement) -> date | None:
    return mv.booking_date or mv.value_date


def is_stale_pending(mv: domain.Movement, today: date) -> bool:
    """PENDING for more than ``STALE_PENDING_DAYS`` days: the one rule (pairing, search line)."""
    day = movement_day(mv)
    return (mv.status is domain.MovementStatus.PENDING and day is not None
            and day < today - timedelta(days=STALE_PENDING_DAYS))
