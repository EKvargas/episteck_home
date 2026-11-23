"""Which profile version is in force on a given day (pure, no I/O)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

ORIGINS = ("PROFILE", "MODE", "MIGRATED")


@dataclass(frozen=True)
class VersionRef:
    version: int
    valid_from: date
    origin: str


def version_in_force(versions: Sequence[VersionRef], day: date) -> int | None:
    ordered = sorted(versions, key=lambda v: (v.valid_from, v.version))
    profile = [v for v in ordered if v.origin == "PROFILE"]
    if profile:
        first = profile[0].valid_from
        if day < first:
            return max(v.version for v in profile if v.valid_from == first)
    eligible = [v for v in ordered if v.valid_from <= day]
    return eligible[-1].version if eligible else None
