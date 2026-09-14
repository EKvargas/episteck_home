"""Planned-vs-actual intake semantics. Planned and actual never overwrite each other.
Only USER_CONFIRMED actual intake is authoritative. Mirrors Nutrition Intake DocType.
"""
from __future__ import annotations
from enum import Enum


class IntakeKind(str, Enum):
    PLANNED = "PLANNED"
    ACTUAL = "ACTUAL"


class IntakeSource(str, Enum):
    PLANNED_MEAL = "PLANNED_MEAL"
    RECIPE = "RECIPE"
    FOOD = "FOOD"
    MANUAL = "MANUAL"


class IntakeStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHANGED = "CHANGED"
    SKIPPED = "SKIPPED"


class IntakeProvenance(str, Enum):
    USER_CONFIRMED = "USER_CONFIRMED"
    AI_PROPOSAL = "AI_PROPOSAL"


def is_authoritative_actual(kind: IntakeKind, provenance: IntakeProvenance) -> bool:
    return kind == IntakeKind.ACTUAL and provenance == IntakeProvenance.USER_CONFIRMED
