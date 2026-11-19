"""Summarise one diary day. Missing is unknown, never zero (spec 6.10)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from nutrition_domain.rules import LimitRule


class DayStatus(str, Enum):
    NO_ENTRIES = "NO_ENTRIES"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"


class SugarStatus(str, Enum):
    NONE = "NONE"
    KNOWN = "KNOWN"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True)
class DaySummary:
    day: date
    day_status: DayStatus
    sugar_status: SugarStatus
    free_sugars_known_g: Decimal | None
    items_total: int
    items_uncounted: int
    limit: LimitRule | None


def summarize_day(
    day: date,
    item_free_sugars: Sequence[Decimal | None],
    closed: bool,
    limit: LimitRule | None,
) -> DaySummary:
    total = len(item_free_sugars)
    known = [v for v in item_free_sugars if v is not None]
    uncounted = total - len(known)
    if total == 0:
        day_status, sugar_status = DayStatus.NO_ENTRIES, SugarStatus.NONE
    else:
        day_status = DayStatus.COMPLETE if closed else DayStatus.OPEN
        sugar_status = SugarStatus.PARTIAL if uncounted else SugarStatus.KNOWN
    return DaySummary(
        day=day,
        day_status=day_status,
        sugar_status=sugar_status,
        free_sugars_known_g=sum(known, Decimal(0)) if known else None,
        items_total=total,
        items_uncounted=uncounted,
        limit=limit,
    )
