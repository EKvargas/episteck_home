"""Allocation planner: exact subset of the oldest lines, else FIFO."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

from .model import EXACT_SUBSET_LIMIT, AllocationMethod


@dataclass(frozen=True)
class OpenLine:
    line_id: str
    outstanding_minor: int
    order: int


@dataclass(frozen=True)
class AllocationPlan:
    method: AllocationMethod
    parts: tuple[tuple[str, int], ...]
    remainder_minor: int


def plan_allocation(
    amount_minor: int, lines: Sequence[OpenLine], limit: int = EXACT_SUBSET_LIMIT
) -> AllocationPlan:
    if amount_minor <= 0:
        raise ValueError("amount must be positive")
    ordered = sorted((ln for ln in lines if ln.outstanding_minor > 0), key=lambda ln: ln.order)

    best: tuple[OpenLine, ...] | None = None
    best_key: tuple[int, ...] | None = None
    head = ordered[:limit]
    for size in range(1, len(head) + 1):
        for combo in combinations(head, size):
            if sum(ln.outstanding_minor for ln in combo) != amount_minor:
                continue
            key = tuple(ln.order for ln in combo)
            if best_key is None or key < best_key:
                best, best_key = combo, key
    if best is not None:
        return AllocationPlan(
            AllocationMethod.AUTO_EXACT,
            tuple((ln.line_id, ln.outstanding_minor) for ln in best),
            0,
        )

    left = amount_minor
    parts: list[tuple[str, int]] = []
    for ln in ordered:
        if left == 0:
            break
        take = min(left, ln.outstanding_minor)
        parts.append((ln.line_id, take))
        left -= take
    return AllocationPlan(AllocationMethod.AUTO_FIFO, tuple(parts), left)
