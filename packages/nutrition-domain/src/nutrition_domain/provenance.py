"""Target provenance — where a nutrient target came from and how authoritative it is.
Mirrors Nutrition Profile.target_source. AI_SUGGESTION is never authoritative alone.
"""
from __future__ import annotations
from enum import Enum


class TargetSource(str, Enum):
    REFERENCE_TARGET = "REFERENCE_TARGET"
    USER_CONFIGURED = "USER_CONFIGURED"
    PROFESSIONAL_PROVIDED = "PROFESSIONAL_PROVIDED"
    AI_SUGGESTION = "AI_SUGGESTION"


AUTHORITATIVE_SOURCES = frozenset(
    {TargetSource.REFERENCE_TARGET, TargetSource.USER_CONFIGURED, TargetSource.PROFESSIONAL_PROVIDED}
)


def is_authoritative(source: TargetSource) -> bool:
    return source in AUTHORITATIVE_SOURCES
