"""FastAPI boundary for the internal Episteck Nutrition service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .deps import build_service


app = FastAPI(title="Episteck Nutrition", version="0.3.0")
svc = build_service()

DELEGATION_HEADER = "X-Episteck-Delegation"


def human_session(
    x_episteck_delegation: str | None = Header(default=None),
) -> str | None:
    """Trusted human session from transport, never a query/body parameter.

    G1.6: there is no ``delegation`` input anywhere on this API. Nutrition
    resolves the actor itself from this session against the Home Control Plane.
    """
    value = (x_episteck_delegation or "").strip()
    return value or None


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
def get_profile(person_id: str, delegation: str | None = Depends(human_session)):
    profile = _authorized(lambda: svc.get_profile(delegation, person_id))
    if profile is None:
        raise HTTPException(404, "no profile")
    return profile


@app.put("/profile/{person_id}")
def put_profile(person_id: str, body: ProfileIn, delegation: str | None = Depends(human_session)):
    return _authorized(
        lambda: svc.upsert_profile(delegation, person_id, body.model_dump())
    )


@app.post("/evaluate/meal")
def evaluate_meal(foods: list[FoodItem]):
    return svc.evaluate_meal([food.model_dump() for food in foods])


@app.get("/daily/{person_id}/{date}")
def daily(person_id: str, date: str, delegation: str | None = Depends(human_session)):
    """One delegated Home request, not two.

    This used to call ``daily_intake`` and ``daily_gap``; both authorize, so a single
    HTTP request spent the single-use delegation twice and the second was
    replay-denied. ``svc.daily`` authorizes VIEW once and composes internally.
    """
    return _authorized(lambda: svc.daily(delegation, person_id, date))


@app.post("/intake/{person_id}/planned")
def planned(
    person_id: str,
    date: str,
    foods: list[FoodItem],
    delegation: str | None = Depends(human_session),
    ref: str | None = None,
):
    return _authorized(
        lambda: svc.record_planned(
            delegation,
            person_id,
            date,
            [food.model_dump() for food in foods],
            ref,
        )
    )


@app.post("/intake/{person_id}/actual")
def actual(
    person_id: str, date: str, foods: list[FoodItem], delegation: str | None = Depends(human_session)
):
    return _authorized(
        lambda: svc.record_actual(
            delegation,
            person_id,
            date,
            [food.model_dump() for food in foods],
        )
    )


@app.post("/intake/{person_id}/ate-as-planned")
def ate(person_id: str, date: str, planned_id: str, delegation: str | None = Depends(human_session)):
    try:
        return _authorized(
            lambda: svc.ate_as_planned(
                delegation, person_id, date, planned_id
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
    start: str, end: str, subject_person_id: str, delegation: str | None = Depends(human_session)
):
    return _authorized(
        lambda: svc.get_meal_plan(
            delegation, subject_person_id, start, end
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
    person_id: str, body: PregnancyProfileIn, delegation: str | None = Depends(human_session)
):
    return _authorized(
        lambda: svc.create_pregnancy_profile(
            delegation,
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
def plan_menu(person_id: str, meals: list[MealIn], delegation: str | None = Depends(human_session)):
    candidates = [
        {
            "label": meal.label,
            "foods": [food.model_dump() for food in meal.foods],
        }
        for meal in meals
    ]
    return _authorized(
        lambda: svc.plan_menu(delegation, person_id, candidates)
    )


@app.get("/gap-v2/{person_id}/{date}")
def gap_v2(person_id: str, date: str, delegation: str | None = Depends(human_session)):
    return _authorized(
        lambda: svc.daily_gap_v2(delegation, person_id, date)
    )
