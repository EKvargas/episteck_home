"""Business-only Nutrition MCP for the unprivileged Home Agent.

G1.6: no tool accepts ``actor_person_id``. Nutrition resolves the acting Person
INDEPENDENTLY from the delegated human session carried in transport context, so the
Home Agent cannot assert an identity to this service.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from ..deps import build_diary_service, build_service
from ..diary.service import DraftExpired, DraftNotFound, EntryNotFound, ProviderUnavailable
from ..session import NO_SESSION, current_delegation


mcp = FastMCP("episteck-nutrition")
_svc = build_service()
_diary = build_diary_service()


def _authorized(operation: Callable[[], Any]):
    try:
        return operation()
    except PermissionError as error:
        return {"allow": False, "error": "access_denied", "reason": str(error)}


def _session() -> str | None:
    """Trusted human session for this request. Never a tool parameter."""
    return current_delegation()


@mcp.tool
def get_nutrition_profile(
    subject_person_id: str
) -> dict:
    """Read a profile after Home authorizes this exact actor and subject."""
    return _authorized(
        lambda: _svc.get_profile(_session(), subject_person_id)
        or {"error": "no profile"}
    )


@mcp.tool
def evaluate_meal(foods: list[dict]) -> dict:
    """Deterministically compute nutrient totals for confirmed food amounts."""
    return _svc.evaluate_meal(foods)


@mcp.tool
def get_daily_nutrition_gap(
    subject_person_id: str, date: str
) -> dict:
    """Read target, consumed, and remaining nutrients after Home authorization."""
    return _authorized(
        lambda: _svc.daily_gap(_session(), subject_person_id, date)
    )


@mcp.tool
def record_planned_meal(
    subject_person_id: str,
    date: str,
    foods: list[dict],
    ref: str | None = None,
) -> dict:
    """Record intended intake after Home authorizes CREATE for actor and subject."""
    return _authorized(
        lambda: _svc.record_planned(_session(), subject_person_id, date, foods, ref)
    )


@mcp.tool
def record_actual_intake(
    subject_person_id: str,
    date: str,
    foods: list[dict],
) -> dict:
    """Record confirmed intake after Home authorizes CREATE for actor and subject."""
    return _authorized(
        lambda: _svc.record_actual(_session(), subject_person_id, date, foods)
    )


@mcp.tool
def ate_as_planned(
    subject_person_id: str,
    date: str,
    planned_id: str,
) -> dict:
    """Read a plan and create actual intake only after both Home decisions allow."""
    return _authorized(
        lambda: _svc.ate_as_planned(_session(), subject_person_id, date, planned_id)
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
    subject_person_id: str,
    start_date: str,
    end_date: str,
) -> list | dict:
    """Read the provider meal plan only after Home authorizes Nutrition VIEW."""
    return _authorized(
        lambda: _svc.get_meal_plan(_session(), subject_person_id, start_date, end_date)
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
    subject_person_id: str
) -> dict:
    """Read a synthetic pregnancy profile only after Home authorization."""
    return _authorized(
        lambda: _svc.get_profile(_session(), subject_person_id)
        or {"error": "no profile"}
    )


@mcp.tool
def plan_menu(
    subject_person_id: str, meals: list[dict]
) -> dict:
    """Evaluate a proposed menu after Home authorizes Nutrition VIEW."""
    return _authorized(
        lambda: _svc.plan_menu(_session(), subject_person_id, meals)
    )


def _diary_call(operation: Callable[[], Any]):
    """Access refusals keep the existing shape; diary errors become a bare code."""
    try:
        return _authorized(operation)
    except (DraftNotFound, EntryNotFound):
        return {"error": "NOT_FOUND"}
    except DraftExpired:
        return {"error": "DRAFT_EXPIRED"}
    except ProviderUnavailable:
        return {"error": "PROVIDER_UNAVAILABLE"}
    except ValueError:
        return {"error": "INVALID_ITEM"}


@mcp.tool
def propose_intake(
    subject_person_id: str, items: list[dict], consumed_at: str | None = None
) -> dict:
    """Draft what the person says they ate or drank. A draft never counts in the day totals.

    Call this first whenever the person reports food. Each item needs label, amount
    (a number or text) and unit (a gram or ml unit, or a portion name such as
    small_glass, glass, large_glass, cup, can, tablespoon, teaspoon). Add food_id when you
    know it from search_foods. Set stated=true only if the person gave the amount
    themselves, and grams_estimate if you must guess the weight. consumed_at is an
    ISO time and defaults to now. Show the person the returned items and the
    free-sugars figure, then call confirm_intake only after they say yes. Unknown
    sugar is null, never 0: free_sugars_known_g is the known sum and items_uncounted
    says how many items could not be counted. Show the returned attribution text.
    """
    return _diary_call(
        lambda: _diary.propose_intake(_session(), subject_person_id, items, consumed_at)
    )


@mcp.tool
def confirm_intake(subject_person_id: str, draft_id: str) -> dict:
    """Turn a draft into a real diary entry so it counts toward the day.

    Call this only after the person has clearly said yes to the draft. Repeating it
    for the same draft is safe. Drafts expire after 24 hours (error DRAFT_EXPIRED);
    propose again in that case.
    """
    return _diary_call(lambda: _diary.confirm_intake(_session(), subject_person_id, draft_id))


@mcp.tool
def correct_intake(subject_person_id: str, entry_id: str, items: list[dict]) -> dict:
    """Replace the items of a confirmed entry when the person corrects what they ate.

    Send the full corrected item list, in the same format as propose_intake. The
    earlier version is kept in the history; the day totals use the new one. Cannot
    correct an entry that was voided.
    """
    return _diary_call(
        lambda: _diary.correct_intake(_session(), subject_person_id, entry_id, items)
    )


@mcp.tool
def void_intake(subject_person_id: str, entry_id: str) -> dict:
    """Remove a confirmed entry from the day because it was a mistake.

    The entry stays in the history as voided and stops counting in the totals.
    """
    return _diary_call(lambda: _diary.void_intake(_session(), subject_person_id, entry_id))


@mcp.tool
def get_diary_entry(subject_person_id: str, entry_id: str) -> dict:
    """Read one confirmed diary entry with its items and frozen nutrient facts."""
    return _diary_call(lambda: _diary.get_entry(_session(), subject_person_id, entry_id))


@mcp.tool
def get_day_summary(subject_person_id: str, date: str) -> dict:
    """Read one day (YYYY-MM-DD, local date) with the confirmed entries and free sugars.

    Only confirmed entries count; drafts never do. free_sugars_known_g is the known
    sum against the daily limit; items_uncounted says how many items could not be
    counted. Unknown sugar is null, never 0.
    """
    return _diary_call(lambda: _diary.get_day_summary(_session(), subject_person_id, date))


@mcp.tool
def close_day(subject_person_id: str, date: str) -> dict:
    """Mark a day (YYYY-MM-DD) as finished and return its final summary.

    Call it only when the person says the day is done. A day that has not started
    yet cannot be closed.
    """
    return _diary_call(lambda: _diary.close_day(_session(), subject_person_id, date))


@mcp.tool
def set_nutrition_mode(
    subject_person_id: str, mode: str, due_date: str | None = None
) -> dict:
    """Set the person's mode to GENERAL or PREGNANCY.

    due_date (YYYY-MM-DD) is allowed only with PREGNANCY and gives the trimester.
    Call it only when the person tells you; never infer a pregnancy.
    """
    return _diary_call(
        lambda: _diary.set_mode(_session(), subject_person_id, mode, due_date)
    )


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("MCP_PORT", "9931")),
    )
