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
