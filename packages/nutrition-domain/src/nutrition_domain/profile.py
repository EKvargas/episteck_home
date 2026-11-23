"""Personal profile inputs: typing, parsing, validation and JSON-safe documents.

Pure Python, no I/O. Errors carry the field name only, never the value.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class Goal(str, Enum):
    MAINTAIN = "MAINTAIN"
    LOSE_FAT = "LOSE_FAT"
    BUILD_MUSCLE = "BUILD_MUSCLE"
    PERFORMANCE = "PERFORMANCE"


ACTIVITY_LEVELS: tuple[Decimal, ...] = (Decimal("1.4"), Decimal("1.6"), Decimal("1.8"), Decimal("2.0"))

CHANGEABLE_FIELDS: tuple[str, ...] = (
    "birth_date", "sex", "height_cm", "weight_kg", "weight_measured_on", "activity_pal",
    "training_sessions_per_week", "training_note", "goal", "pre_pregnancy_weight_kg",
    "preferences", "dislikes", "intolerances",
)

_DATE_FIELDS = frozenset({"birth_date", "weight_measured_on"})
_DECIMAL_FIELDS = frozenset({"height_cm", "weight_kg", "activity_pal", "pre_pregnancy_weight_kg"})
_TEXT_LIMITS = {"training_note": 120, "preferences": 500, "dislikes": 500, "intolerances": 500}
_MODES = ("GENERAL", "PREGNANCY")


@dataclass(frozen=True)
class ProfileInputs:
    birth_date: date | None = None
    sex: Sex | None = None
    height_cm: Decimal | None = None
    weight_kg: Decimal | None = None
    weight_measured_on: date | None = None
    activity_pal: Decimal | None = None
    training_sessions_per_week: int | None = None
    training_note: str | None = None
    goal: Goal | None = None
    pre_pregnancy_weight_kg: Decimal | None = None
    preferences: str | None = None
    dislikes: str | None = None
    intolerances: str | None = None
    mode: str = "GENERAL"
    due_date: date | None = None


class ProfileInvalid(ValueError):
    """A refused profile input: the field name and a fixed reason code, never the value.

    Reasons: INVALID_FORMAT, OUT_OF_RANGE, UNDER_19, OVER_100, FUTURE_DATE,
    MEASUREMENT_TOO_OLD, NOT_ALLOWED_IN_MODE, UNKNOWN_FIELD, NO_CHANGES, TOO_LONG
    (INVALID when none applies).
    """

    def __init__(self, field: str, message: str | None = None, *, reason: str = "INVALID"):
        super().__init__(message or f"invalid {field}")
        self.field = field
        self.reason = reason


_FORMAT = "INVALID_FORMAT"
_RANGE = "OUT_OF_RANGE"
_MODE = "NOT_ALLOWED_IN_MODE"


def age_on(birth_date: date, on: date) -> int:
    return on.year - birth_date.year - ((on.month, on.day) < (birth_date.month, birth_date.day))


_NUMERIC_TEXT = re.compile(r"-?[0-9]{1,12}(?:[.,][0-9]{1,12})?")
_MAX_MAGNITUDE = 1_000_000


def _decimal(field: str, value: object) -> Decimal:
    if isinstance(value, bool):
        raise ProfileInvalid(field, reason=_FORMAT)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        if abs(value) > _MAX_MAGNITUDE:
            raise ProfileInvalid(field, reason=_RANGE)
        number = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ProfileInvalid(field, reason=_FORMAT)
        if abs(value) > _MAX_MAGNITUDE:
            raise ProfileInvalid(field, reason=_RANGE)
        number = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not _NUMERIC_TEXT.fullmatch(text):
            raise ProfileInvalid(field, reason=_FORMAT)
        number = Decimal(text.replace(",", "."))
    else:
        raise ProfileInvalid(field, reason=_FORMAT)
    if not number.is_finite():
        raise ProfileInvalid(field, reason=_FORMAT)
    if abs(number) > _MAX_MAGNITUDE:
        raise ProfileInvalid(field, reason=_RANGE)
    return number


def _integer(field: str, value: object) -> int:
    if isinstance(value, bool):
        raise ProfileInvalid(field, reason=_FORMAT)
    if isinstance(value, int):
        if abs(value) > _MAX_MAGNITUDE:
            raise ProfileInvalid(field, reason=_RANGE)
        return value
    number = _decimal(field, value)
    if number != number.to_integral_value():
        raise ProfileInvalid(field, reason=_FORMAT)
    return int(number)


def _date(field: str, value: object) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ProfileInvalid(field, reason=_FORMAT)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ProfileInvalid(field, reason=_FORMAT) from None


def _enum(field: str, cls: type[Enum], value: object):
    if isinstance(value, cls):
        return value
    try:
        return cls(value)
    except ValueError:
        raise ProfileInvalid(field, reason=_FORMAT) from None


def _text(field: str, value: object) -> str | None:
    if not isinstance(value, str):
        raise ProfileInvalid(field, reason=_FORMAT)
    text = value.strip()
    if len(text) > _TEXT_LIMITS[field]:
        raise ProfileInvalid(field, reason="TOO_LONG")
    return text or None


def parse_changes(raw: dict) -> dict[str, object]:
    """Wire values to typed values. None is kept: it clears the field."""
    changes: dict[str, object] = {}
    for key, value in raw.items():
        if key not in CHANGEABLE_FIELDS:
            raise ProfileInvalid(str(key), reason="UNKNOWN_FIELD")
        if value is None:
            changes[key] = None
        elif key in _DATE_FIELDS:
            changes[key] = _date(key, value)
        elif key in _DECIMAL_FIELDS:
            changes[key] = _decimal(key, value)
        elif key == "training_sessions_per_week":
            changes[key] = _integer(key, value)
        elif key == "sex":
            changes[key] = _enum(key, Sex, value)
        elif key == "goal":
            changes[key] = _enum(key, Goal, value)
        else:
            changes[key] = _text(key, value)
    return changes


def apply_changes(current: ProfileInputs | None, changes: dict[str, object]) -> ProfileInputs:
    for key in changes:
        if key not in CHANGEABLE_FIELDS:
            raise ProfileInvalid(str(key), reason="UNKNOWN_FIELD")
    return replace(current or ProfileInputs(), **changes)


def _in_range(field: str, value: Decimal | None, low: str, high: str) -> None:
    if value is not None and not (Decimal(low) <= value <= Decimal(high)):
        raise ProfileInvalid(field, reason=_RANGE)


def _check_birth_date(born: date, today: date) -> None:
    if born > today:
        raise ProfileInvalid("birth_date", reason="FUTURE_DATE")
    age = age_on(born, today)
    if age < 19:
        raise ProfileInvalid("birth_date", reason="UNDER_19")
    if age > 100:
        raise ProfileInvalid("birth_date", reason="OVER_100")


def validate_inputs(inputs: ProfileInputs, today: date) -> None:
    if inputs.mode not in _MODES:
        raise ProfileInvalid("mode", reason=_FORMAT)
    if inputs.birth_date is not None:
        _check_birth_date(inputs.birth_date, today)
    _in_range("height_cm", inputs.height_cm, "120", "230")
    _in_range("weight_kg", inputs.weight_kg, "30", "250")
    _in_range("pre_pregnancy_weight_kg", inputs.pre_pregnancy_weight_kg, "30", "250")
    measured = inputs.weight_measured_on
    if measured is not None and measured > today:
        raise ProfileInvalid("weight_measured_on", reason="FUTURE_DATE")
    if measured is not None and measured < today - timedelta(days=90):
        raise ProfileInvalid("weight_measured_on", reason="MEASUREMENT_TOO_OLD")
    if inputs.activity_pal is not None and inputs.activity_pal not in ACTIVITY_LEVELS:
        raise ProfileInvalid("activity_pal", reason=_RANGE)
    sessions = inputs.training_sessions_per_week
    if sessions is not None and not (0 <= sessions <= 14):
        raise ProfileInvalid("training_sessions_per_week", reason=_RANGE)
    if inputs.mode == "PREGNANCY":
        if inputs.goal is not None:
            raise ProfileInvalid("goal", reason=_MODE)
        if inputs.sex not in (None, Sex.FEMALE):
            raise ProfileInvalid("sex", reason=_MODE)
    else:
        if inputs.due_date is not None:
            raise ProfileInvalid("due_date", reason=_MODE)
        if inputs.pre_pregnancy_weight_kg is not None:
            raise ProfileInvalid("pre_pregnancy_weight_kg", reason=_MODE)


def inputs_to_doc(inputs: ProfileInputs) -> dict:
    doc: dict = {}
    for f in fields(ProfileInputs):
        value = getattr(inputs, f.name)
        if isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, date):
            value = value.isoformat()
        elif isinstance(value, Enum):
            value = value.value
        doc[f.name] = value
    return doc


def inputs_from_doc(doc: dict) -> ProfileInputs:
    values: dict[str, object] = {}
    for f in fields(ProfileInputs):
        value = doc.get(f.name)
        if value is None:
            continue
        if f.name in _DATE_FIELDS or f.name == "due_date":
            value = date.fromisoformat(value)
        elif f.name in _DECIMAL_FIELDS:
            value = Decimal(value)
        elif f.name == "sex":
            value = Sex(value)
        elif f.name == "goal":
            value = Goal(value)
        values[f.name] = value
    return ProfileInputs(**values)
