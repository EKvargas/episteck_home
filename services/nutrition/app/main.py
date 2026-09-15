"""FastAPI boundary for the internal Episteck Nutrition service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .deps import build_service


app = FastAPI(title="Episteck Nutrition", version="0.2.0")
svc = build_service()


def _authorized(operation: Callable[[], Any]):
    try:
        return operation()
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


class FoodItem(BaseModel):
    food_id: str
    grams: float


class ProfileIn(BaseModel):
    context: str = "GENERAL"
    preferences: str | None = None
    dislikes: str | None = None
    intolerances: str | None = None
    targets: dict[str, float] = Field(default_factory=dict)
    target_source: str = "USER_CONFIGURED"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/profile/{person_id}")
def get_profile(person_id: str, actor_person_id: str):
    profile = _authorized(lambda: svc.get_profile(actor_person_id, person_id))
    if profile is None:
        raise HTTPException(404, "no profile")
    return profile


@app.put("/profile/{person_id}")
def put_profile(person_id: str, body: ProfileIn, actor_person_id: str):
    return _authorized(
        lambda: svc.upsert_profile(actor_person_id, person_id, body.model_dump())
    )


@app.post("/evaluate/meal")
def evaluate_meal(foods: list[FoodItem]):
    return svc.evaluate_meal([food.model_dump() for food in foods])


@app.get("/daily/{person_id}/{date}")
def daily(person_id: str, date: str, actor_person_id: str):
    return _authorized(
        lambda: {
            "intake": svc.daily_intake(actor_person_id, person_id, date),
            "gap": svc.daily_gap(actor_person_id, person_id, date),
        }
    )


@app.post("/intake/{person_id}/planned")
def planned(
    person_id: str,
    date: str,
    foods: list[FoodItem],
    actor_person_id: str,
    ref: str | None = None,
):
    return _authorized(
        lambda: svc.record_planned(
            actor_person_id,
            person_id,
            date,
            [food.model_dump() for food in foods],
            ref,
        )
    )


@app.post("/intake/{person_id}/actual")
def actual(
    person_id: str, date: str, foods: list[FoodItem], actor_person_id: str
):
    return _authorized(
        lambda: svc.record_actual(
            actor_person_id,
            person_id,
            date,
            [food.model_dump() for food in foods],
        )
    )


@app.post("/intake/{person_id}/ate-as-planned")
def ate(person_id: str, date: str, planned_id: str, actor_person_id: str):
    try:
        return _authorized(
            lambda: svc.ate_as_planned(
                actor_person_id, person_id, date, planned_id
            )
        )
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@app.post("/intake/propose-change")
def propose(foods: list[FoodItem]):
    return svc.propose_change([food.model_dump() for food in foods])


@app.get("/recipes/search")
def recipes(query: str):
    if not svc.mealie:
        raise HTTPException(503, "mealie not configured")
    return svc.mealie.search_recipes(query)


@app.get("/mealplan/{start}/{end}")
def mealplan(
    start: str, end: str, actor_person_id: str, subject_person_id: str
):
    return _authorized(
        lambda: svc.get_meal_plan(
            actor_person_id, subject_person_id, start, end
        )
    )


class PregnancyProfileIn(BaseModel):
    stage: str | None = None
    preferences: str = ""
    dislikes: str = ""
    intolerances: str = ""
    avoided_foods: str = ""
    user_goals: dict = Field(default_factory=dict)


@app.post("/profile/{person_id}/pregnancy")
def create_pregnancy(
    person_id: str, body: PregnancyProfileIn, actor_person_id: str
):
    return _authorized(
        lambda: svc.create_pregnancy_profile(
            actor_person_id,
            person_id,
            stage=body.stage,
            preferences=body.preferences,
            dislikes=body.dislikes,
            intolerances=body.intolerances,
            avoided_foods=body.avoided_foods,
            user_goals=body.user_goals,
        )
    )


@app.get("/food/search")
def food_search(query: str):
    hits = svc.provider.search_food(query)
    return [
        {
            "food_id": hit.food_id,
            "name": hit.name,
            "provider": hit.food_id.split(":", 1)[0],
        }
        for hit in hits
    ]


@app.get("/food/{food_id:path}")
def food_detail(food_id: str):
    record = svc.provider.get_food(food_id)
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


class MealIn(BaseModel):
    label: str
    foods: list[FoodItem]


@app.post("/plan/{person_id}")
def plan_menu(person_id: str, meals: list[MealIn], actor_person_id: str):
    candidates = [
        {
            "label": meal.label,
            "foods": [food.model_dump() for food in meal.foods],
        }
        for meal in meals
    ]
    return _authorized(
        lambda: svc.plan_menu(actor_person_id, person_id, candidates)
    )


@app.get("/gap-v2/{person_id}/{date}")
def gap_v2(person_id: str, date: str, actor_person_id: str):
    return _authorized(
        lambda: svc.daily_gap_v2(actor_person_id, person_id, date)
    )
