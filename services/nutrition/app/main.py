"""FastAPI boundary for the internal Episteck Nutrition service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from nutrition_domain.profile import ProfileInvalid

from .deps import build_diary_service, build_profile_service, build_service
from .diary.service import BLS_ATTRIBUTION, DraftExpired, DraftNotFound, EntryNotFound, ProviderUnavailable
from .service import AccessDenied, PolicyUnavailable, SessionInvalid


app = FastAPI(title="Episteck Nutrition", version="0.3.0")
profile = build_profile_service()
svc = build_service(profile)
diary = build_diary_service(profile)

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
    """Map refusals to fixed bodies. ``from None`` keeps Home's reason out of responses."""
    try:
        return operation()
    except SessionInvalid:
        raise HTTPException(401, "SESSION_INVALID") from None
    except PolicyUnavailable:
        raise HTTPException(503, "SERVICE_UNAVAILABLE") from None
    except (AccessDenied, PermissionError):
        raise HTTPException(403, "ACCESS_DENIED") from None


class FoodItem(BaseModel):
    food_id: str
    grams: float


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/profile/{person_id}")
def get_profile(person_id: str, delegation: str | None = Depends(human_session)):
    view = _authorized(lambda: profile.get_profile_view(delegation, person_id))
    if view is None:
        raise HTTPException(404, "no profile")
    # The deployed Hub reads a flat ``targets`` map; the structured set moves to ``target_set``.
    body = {key: value for key, value in view.items() if key not in ("targets", "targets_flat")}
    body["targets"] = view["targets_flat"]
    body["target_set"] = view["targets"]
    return body


@app.post("/evaluate/meal")
def evaluate_meal(foods: list[FoodItem]):
    return svc.evaluate_meal([food.model_dump() for food in foods])


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
        "attribution": [BLS_ATTRIBUTION] if record.source == "BLS" else [],
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


# --------------------------------------------------------------------------
# Food diary
# --------------------------------------------------------------------------


def _diary_call(operation: Callable[[], Any]):
    """Run a diary operation: access refusals via ``_authorized``, diary errors here.

    ``from None`` keeps internal messages (which may echo food text) out of responses.
    """
    try:
        return _authorized(operation)
    except (DraftNotFound, EntryNotFound):
        raise HTTPException(404, "NOT_FOUND") from None
    except DraftExpired:
        raise HTTPException(409, "DRAFT_EXPIRED") from None
    except ProviderUnavailable:
        raise HTTPException(503, "PROVIDER_UNAVAILABLE") from None
    except ProfileInvalid as error:
        raise HTTPException(
            400, {"error": "INVALID_FIELD", "field": getattr(error, "field", None),
                  "reason": getattr(error, "reason", "INVALID")}
        ) from None
    except ValueError as error:
        # The field NAME only, never food text.
        raise HTTPException(
            400, {"error": "INVALID_ITEM", "field": getattr(error, "field", None)}
        ) from None


class DiaryItemIn(BaseModel):
    label: str
    food_id: str | None = None
    amount: str | int | float
    unit: str
    stated: bool = False
    grams_estimate: str | int | float | None = None


class ProposeIn(BaseModel):
    items: list[DiaryItemIn]
    consumed_at: str | None = None


class CorrectIn(BaseModel):
    items: list[DiaryItemIn]


class ModeIn(BaseModel):
    mode: str
    due_date: str | None = None


def _items(body) -> list[dict]:
    return [item.model_dump() for item in body.items]


@app.post("/diary/{person_id}/drafts")
def diary_propose(person_id: str, body: ProposeIn, delegation: str | None = Depends(human_session)):
    return _diary_call(
        lambda: diary.propose_intake(delegation, person_id, _items(body), body.consumed_at)
    )


@app.post("/diary/{person_id}/drafts/{draft_id}/confirm")
def diary_confirm(person_id: str, draft_id: str, delegation: str | None = Depends(human_session)):
    return _diary_call(lambda: diary.confirm_intake(delegation, person_id, draft_id))


@app.post("/diary/{person_id}/entries/{entry_id}/revisions")
def diary_correct(
    person_id: str, entry_id: str, body: CorrectIn, delegation: str | None = Depends(human_session)
):
    return _diary_call(
        lambda: diary.correct_intake(delegation, person_id, entry_id, _items(body))
    )


@app.post("/diary/{person_id}/entries/{entry_id}/void")
def diary_void(person_id: str, entry_id: str, delegation: str | None = Depends(human_session)):
    return _diary_call(lambda: diary.void_intake(delegation, person_id, entry_id))


@app.get("/diary/{person_id}/entries/{entry_id}")
def diary_entry(person_id: str, entry_id: str, delegation: str | None = Depends(human_session)):
    return _diary_call(lambda: diary.get_entry(delegation, person_id, entry_id))


@app.get("/diary/{person_id}/days/today")
def diary_today(person_id: str, delegation: str | None = Depends(human_session)):
    """Today in DIARY_TZ, so the caller never works out the local date itself."""
    return _diary_call(lambda: diary.get_day_summary(delegation, person_id))


@app.get("/diary/{person_id}/period")
def diary_period(
    person_id: str, start: str | None = None, end: str | None = None,
    delegation: str | None = Depends(human_session),
):
    """At most 31 days; the default is the last 7 days ending today."""
    return _diary_call(lambda: diary.get_period_summary(delegation, person_id, start, end))


@app.post("/diary/{person_id}/days/today/close")
def diary_close_today(person_id: str, delegation: str | None = Depends(human_session)):
    return _diary_call(lambda: diary.close_day(delegation, person_id))


@app.get("/diary/{person_id}/days/{date}")
def diary_day(person_id: str, date: str, delegation: str | None = Depends(human_session)):
    return _diary_call(lambda: diary.get_day_summary(delegation, person_id, date))


@app.post("/diary/{person_id}/days/{date}/close")
def diary_close(person_id: str, date: str, delegation: str | None = Depends(human_session)):
    return _diary_call(lambda: diary.close_day(delegation, person_id, date))


@app.put("/profile/{person_id}/mode")
def diary_mode(person_id: str, body: ModeIn, delegation: str | None = Depends(human_session)):
    return _diary_call(
        lambda: diary.set_mode(delegation, person_id, body.mode, body.due_date)
    )
