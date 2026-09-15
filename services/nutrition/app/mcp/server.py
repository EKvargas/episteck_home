"""Business-only Nutrition MCP for the unprivileged Home Agent."""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from ..deps import build_service


mcp = FastMCP("episteck-nutrition")
_svc = build_service()


def _authorized(operation: Callable[[], Any]):
    try:
        return operation()
    except PermissionError as error:
        return {"allow": False, "error": "access_denied", "reason": str(error)}


@mcp.tool
def get_nutrition_profile(
    actor_person_id: str, subject_person_id: str
) -> dict:
    """Read a profile after Home authorizes this exact actor and subject."""
    return _authorized(
        lambda: _svc.get_profile(actor_person_id, subject_person_id)
        or {"error": "no profile"}
    )


@mcp.tool
def evaluate_meal(foods: list[dict]) -> dict:
    """Deterministically compute nutrient totals for confirmed food amounts."""
    return _svc.evaluate_meal(foods)


@mcp.tool
def get_daily_nutrition_gap(
    actor_person_id: str, subject_person_id: str, date: str
) -> dict:
    """Read target, consumed, and remaining nutrients after Home authorization."""
    return _authorized(
        lambda: _svc.daily_gap(actor_person_id, subject_person_id, date)
    )


@mcp.tool
def record_planned_meal(
    actor_person_id: str,
    subject_person_id: str,
    date: str,
    foods: list[dict],
    ref: str | None = None,
) -> dict:
    """Record intended intake after Home authorizes CREATE for actor and subject."""
    return _authorized(
        lambda: _svc.record_planned(
            actor_person_id, subject_person_id, date, foods, ref
        )
    )


@mcp.tool
def record_actual_intake(
    actor_person_id: str,
    subject_person_id: str,
    date: str,
    foods: list[dict],
) -> dict:
    """Record confirmed intake after Home authorizes CREATE for actor and subject."""
    return _authorized(
        lambda: _svc.record_actual(
            actor_person_id, subject_person_id, date, foods
        )
    )


@mcp.tool
def ate_as_planned(
    actor_person_id: str,
    subject_person_id: str,
    date: str,
    planned_id: str,
) -> dict:
    """Read a plan and create actual intake only after both Home decisions allow."""
    return _authorized(
        lambda: _svc.ate_as_planned(
            actor_person_id, subject_person_id, date, planned_id
        )
    )


@mcp.tool
def propose_meal_change(foods: list[dict]) -> dict:
    """Return a non-authoritative proposal that still requires user confirmation."""
    return _svc.propose_change(foods)


@mcp.tool
def search_recipes(query: str) -> list:
    """Search recipes through the credential-hiding Mealie adapter."""
    return _svc.mealie.search_recipes(query) if _svc.mealie else []


@mcp.tool
def get_meal_plan(
    actor_person_id: str,
    subject_person_id: str,
    start_date: str,
    end_date: str,
) -> list | dict:
    """Read the provider meal plan only after Home authorizes Nutrition VIEW."""
    return _authorized(
        lambda: _svc.get_meal_plan(
            actor_person_id, subject_person_id, start_date, end_date
        )
    )


@mcp.tool
def search_foods(query: str) -> list:
    """Search configured food databases without returning nutrient numbers."""
    hits = _svc.provider.search_food(query)
    return [
        {
            "food_id": hit.food_id,
            "name": hit.name,
            "provider": hit.food_id.split(":", 1)[0],
        }
        for hit in hits
    ]


@mcp.tool
def get_food_detail(food_id: str) -> dict:
    """Get source-labelled nutrients per 100g; absent nutrients remain unknown."""
    record = _svc.provider.get_food(food_id)
    return {
        "food_id": record.food_id,
        "name": record.name,
        "source": record.source,
        "nutrients_per_100g": {
            nutrient: str(value)
            for nutrient, value in record.nutrients_per_100g.items()
        },
        "known_nutrients": sorted(record.nutrients_per_100g),
    }


@mcp.tool
def get_pregnancy_profile(
    actor_person_id: str, subject_person_id: str
) -> dict:
    """Read a synthetic pregnancy profile only after Home authorization."""
    return _authorized(
        lambda: _svc.get_profile(actor_person_id, subject_person_id)
        or {"error": "no profile"}
    )


@mcp.tool
def plan_menu(
    actor_person_id: str, subject_person_id: str, meals: list[dict]
) -> dict:
    """Evaluate a proposed menu after Home authorizes Nutrition VIEW."""
    return _authorized(
        lambda: _svc.plan_menu(actor_person_id, subject_person_id, meals)
    )


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "9931")),
    )
