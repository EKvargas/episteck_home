"""FastAPI — Episteck Nutrition internal API. Binds loopback only (uvicorn host set
at launch). No public exposure. Small, purposeful endpoints."""
from __future__ import annotations
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .deps import build_service

app = FastAPI(title="Episteck Nutrition", version="0.1.0")
svc = build_service()

class FoodItem(BaseModel):
    food_id: str
    grams: float

class ProfileIn(BaseModel):
    context: str = "GENERAL"
    preferences: str | None = None
    dislikes: str | None = None
    intolerances: str | None = None
    targets: dict[str, float] = {}
    target_source: str = "USER_CONFIGURED"

@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/profile/{person_id}")
def get_profile(person_id: str):
    p = svc.get_profile(person_id)
    if p is None: raise HTTPException(404, "no profile")
    return p

@app.put("/profile/{person_id}")
def put_profile(person_id: str, body: ProfileIn):
    return svc.upsert_profile(person_id, body.model_dump())

@app.post("/evaluate/meal")
def evaluate_meal(foods: list[FoodItem]):
    return svc.evaluate_meal([f.model_dump() for f in foods])

@app.get("/daily/{person_id}/{date}")
def daily(person_id: str, date: str):
    return {"intake": svc.daily_intake(person_id, date), "gap": svc.daily_gap(person_id, date)}

@app.post("/intake/{person_id}/planned")
def planned(person_id: str, date: str, foods: list[FoodItem], ref: str | None = None):
    return svc.record_planned(person_id, date, [f.model_dump() for f in foods], ref)

@app.post("/intake/{person_id}/actual")
def actual(person_id: str, date: str, foods: list[FoodItem]):
    return svc.record_actual(person_id, date, [f.model_dump() for f in foods])

@app.post("/intake/{person_id}/ate-as-planned")
def ate(person_id: str, date: str, planned_id: str):
    try: return svc.ate_as_planned(person_id, date, planned_id)
    except KeyError as e: raise HTTPException(404, str(e))

@app.post("/intake/propose-change")
def propose(foods: list[FoodItem]):
    return svc.propose_change([f.model_dump() for f in foods])

@app.get("/recipes/search")
def recipes(query: str):
    if not svc.mealie: raise HTTPException(503, "mealie not configured")
    return svc.mealie.search_recipes(query)

@app.get("/mealplan/{start}/{end}")
def mealplan(start: str, end: str):
    if not svc.mealie: raise HTTPException(503, "mealie not configured")
    return svc.mealie.get_meal_plan(start, end)


class PregnancyProfileIn(BaseModel):
    stage: str | None = None
    preferences: str = ""
    dislikes: str = ""
    intolerances: str = ""
    avoided_foods: str = ""
    user_goals: dict = {}

@app.post("/consent/{person_id}")
def set_consent(person_id: str, state: str = "GRANTED", note: str = ""):
    return svc.set_consent(person_id, state, note)

@app.get("/consent/{person_id}")
def get_consent(person_id: str):
    c = svc.get_consent(person_id)
    if c is None: raise HTTPException(404, "no consent record")
    return c

@app.post("/profile/{person_id}/pregnancy")
def create_pregnancy(person_id: str, body: PregnancyProfileIn):
    try:
        return svc.create_pregnancy_profile(person_id, stage=body.stage,
            preferences=body.preferences, dislikes=body.dislikes,
            intolerances=body.intolerances, avoided_foods=body.avoided_foods,
            user_goals=body.user_goals)
    except PermissionError as e:
        raise HTTPException(403, str(e))

@app.get("/food/search")
def food_search(query: str):
    hits = svc.provider.search_food(query)
    return [{"food_id": h.food_id, "name": h.name, "provider": h.food_id.split(":",1)[0]} for h in hits]

@app.get("/food/{food_id:path}")
def food_detail(food_id: str):
    rec = svc.provider.get_food(food_id)
    return {"food_id": rec.food_id, "name": rec.name, "source": rec.source,
            "nutrients_per_100g": {k: str(v) for k,v in rec.nutrients_per_100g.items()},
            "known_nutrients": sorted(rec.nutrients_per_100g.keys())}


class MealIn(BaseModel):
    label: str
    foods: list[FoodItem]

@app.post("/plan/{person_id}")
def plan_menu(person_id: str, meals: list[MealIn]):
    return svc.plan_menu(person_id, [{"label": m.label, "foods": [f.model_dump() for f in m.foods]} for m in meals])

@app.get("/gap-v2/{person_id}/{date}")
def gap_v2(person_id: str, date: str):
    return svc.daily_gap_v2(person_id, date)
