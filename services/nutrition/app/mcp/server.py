"""Episteck Nutrition MCP — high-level BUSINESS tools for the Home Agent.
Exposes ONLY business capabilities. Never exposes SQL, Mealie credentials,
arbitrary HTTP, filesystem, or service secrets. All nutrient numbers come from
the deterministic service, never fabricated by the model.
"""
from __future__ import annotations
from fastmcp import FastMCP
from ..deps import build_service

mcp = FastMCP("episteck-nutrition")
_svc = build_service()

@mcp.tool
def get_nutrition_profile(person_id: str) -> dict:
    """Return the person's nutrition profile (targets, preferences, provenance)."""
    return _svc.get_profile(person_id) or {"error": "no profile"}

@mcp.tool
def evaluate_meal(foods: list[dict]) -> dict:
    """Deterministically compute nutrient totals for a set of foods.
    foods = [{"food_id": str, "grams": number}]."""
    return _svc.evaluate_meal(foods)

@mcp.tool
def get_daily_nutrition_gap(person_id: str, date: str) -> dict:
    """Target vs consumed vs remaining vs percentage per nutrient for a date."""
    return _svc.daily_gap(person_id, date)

@mcp.tool
def record_planned_meal(person_id: str, date: str, foods: list[dict], ref: str = None) -> dict:
    """Record an intended meal (planned intake)."""
    return _svc.record_planned(person_id, date, foods, ref)

@mcp.tool
def record_actual_intake(person_id: str, date: str, foods: list[dict]) -> dict:
    """Record confirmed actual consumption."""
    return _svc.record_actual(person_id, date, foods)

@mcp.tool
def ate_as_planned(person_id: str, date: str, planned_id: str) -> dict:
    """Confirm the planned meal was eaten as-is (copies planned->actual, no re-entry)."""
    return _svc.ate_as_planned(person_id, date, planned_id)

@mcp.tool
def propose_meal_change(foods: list[dict]) -> dict:
    """Return a PROPOSAL for a changed meal. NOT authoritative — user must confirm
    before it becomes actual intake."""
    return _svc.propose_change(foods)

@mcp.tool
def search_recipes(query: str) -> list:
    """Search recipes via Mealie (through the Episteck adapter)."""
    return _svc.mealie.search_recipes(query) if _svc.mealie else []

@mcp.tool
def get_meal_plan(start_date: str, end_date: str) -> list:
    """Read the Mealie meal plan for a date range."""
    return _svc.mealie.get_meal_plan(start_date, end_date) if _svc.mealie else []

@mcp.tool
def search_foods(query: str) -> list:
    """Search real food databases (USDA primary, Open Food Facts secondary).
    Returns [{food_id, name, provider}]. Nutrient numbers are NOT here — call evaluate_meal."""
    hits = _svc.provider.search_food(query)
    return [{"food_id": h.food_id, "name": h.name, "provider": h.food_id.split(":",1)[0]} for h in hits]

@mcp.tool
def get_food_detail(food_id: str) -> dict:
    """Nutrient composition per 100g for a food, with source provenance. Missing nutrients
    are simply absent (unknown != zero)."""
    rec = _svc.provider.get_food(food_id)
    return {"food_id": rec.food_id, "name": rec.name, "source": rec.source,
            "nutrients_per_100g": {k: str(v) for k,v in rec.nutrients_per_100g.items()},
            "known_nutrients": sorted(rec.nutrients_per_100g.keys())}

@mcp.tool
def get_pregnancy_profile(person_id: str) -> dict:
    """Return the pregnancy nutrition profile incl. authoritative reference targets and
    their provenance (DGE/EFSA). Requires the person to have granted consent."""
    p = _svc.get_profile(person_id)
    if not p: return {"error": "no profile"}
    return p

if __name__ == "__main__":
    import os
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("MCP_PORT","9931")))
