"""Nutrition service core: meal evaluation and menu planning.

All nutrient calculations remain deterministic. Every person-specific read is preceded
by an exact actor/subject/domain/action decision from the Home Control Plane.
Nutrition-local consent is not consulted.

Intake lives in the food diary (``app/diary``) and profiles in versioned tables
(``app/profile``). The pre-diary intake model and the legacy profile writers were
retired; their ``profile`` and ``intake`` tables stay in the database, read only by
``SqliteProfileStore.migrate_legacy``.
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from nutrition_domain import (
    ConfirmedFoodAmount,
    FoodFact,
    IntakeProvenance,
    calculate_daily_gap,
    calculate_daily_intake,
    calculate_meal_nutrients,
)

from .home_control.client import ALLOW, DENY, SESSION_INVALID, UNAVAILABLE, AccessDecision
from .providers.food_provider import FoodProvider


class AccessDenied(PermissionError):
    """Home made a well-formed denial."""


class SessionInvalid(PermissionError):
    """No human actor could be established for the delegated session."""


class PolicyUnavailable(PermissionError):
    """Authorization could not be determined (Home unreachable or malformed)."""


_REFUSALS: dict[str, type[PermissionError]] = {
    DENY: AccessDenied,
    SESSION_INVALID: SessionInvalid,
    UNAVAILABLE: PolicyUnavailable,
}


def _refuse_unless_allowed(decision: AccessDecision) -> None:
    """Literal ALLOW only. Every other outcome raises its typed refusal."""
    if decision.allow and decision.outcome == ALLOW:
        return
    raise _REFUSALS.get(decision.outcome, PolicyUnavailable)(decision.reason)


class AccessAuthorizer(Protocol):
    """One delegated Home call per authorization. See ``_require_access``."""

    def check_access(
        self,
        subject_person_id: str,
        domain: str,
        action: str,
        delegation: str | None = None,
    ): ...

    def check_access_many(
        self,
        subject_person_id: str,
        requirements: list[tuple[str, str]],
        delegation: str | None = None,
    ): ...


class NutritionService:
    def __init__(
        self,
        provider: FoodProvider,
        mealie=None,
        *,
        authorizer: AccessAuthorizer,
        targets_today: Callable[[str], dict[str, Decimal]],
    ):
        """``targets_today(person)`` returns the person's targets in force today
        (nutrient -> Decimal), or ``{}`` when there are none. It must not authorize:
        the calling operation has already made its one Home request."""
        self.provider = provider
        self.mealie = mealie
        self.authorizer = authorizer
        self._targets_today = targets_today

    def _require_access(
        self, delegation: str | None, subject_person_id: str, action: str
    ) -> None:
        """Authorize this operation with EXACTLY ONE delegated Home request.

        WHY ONE CALL
        ------------
        This previously resolved the actor via ``whoami`` and then called
        ``check_access`` with the SAME delegation. Delegations are single-use
        (``identity/replay.py``), so the second call is replay-denied and every
        person-sensitive operation fails. Verified live against production:

            whoami       -> 200 (actor resolved)
            check_access -> 403 (replay detected)

        The actor step was also redundant. Home's ``check_access`` derives the human
        actor server-side from machine credential + delegation, it never accepted an
        actor argument, and every call site here discarded the resolved value.

        The trusted-actor invariant is unchanged and arguably stronger: Nutrition
        still supplies only its own machine credential and the opaque delegation, and
        there is now no actor value in this service to assert, forward, or confuse.
        """
        decision = self.authorizer.check_access(
            subject_person_id, "NUTRITION", action, delegation
        )
        # Literal allow only: anything else — deny, malformed, indeterminate,
        # unreachable — is a typed refusal.
        _refuse_unless_allowed(decision)

    # --- deterministic evaluation ---
    def _to_confirmed(self, foods: list[dict]) -> list[ConfirmedFoodAmount]:
        confirmed = []
        for food in foods:
            record = self.provider.get_food(food["food_id"])
            confirmed.append(
                ConfirmedFoodAmount(
                    FoodFact(
                        record.food_id,
                        record.nutrients_per_100g,
                        record.source,
                    ),
                    Decimal(str(food["grams"])),
                )
            )
        return confirmed

    def evaluate_meal(self, foods: list[dict]) -> dict:
        totals = calculate_meal_nutrients(self._to_confirmed(foods))
        return {nutrient: str(value) for nutrient, value in totals.items()}

    def propose_change(self, foods: list[dict]) -> dict:
        """Return an AI proposal; callers must confirm before persistence."""
        return {
            "provenance": IntakeProvenance.AI_PROPOSAL.value,
            "foods": foods,
            "nutrients": self.evaluate_meal(foods),
            "requires_confirmation": True,
        }

    # --- menu planning (deterministic evaluation; not medical optimization) ---
    def plan_menu(
        self,
        delegation: str | None,
        subject_person_id: str,
        candidate_meals: list[dict],
    ) -> dict:
        self._require_access(delegation, subject_person_id, "VIEW")
        targets = self._targets_today(subject_person_id)
        day_meals = [self._to_confirmed(meal["foods"]) for meal in candidate_meals]
        total = calculate_daily_intake(day_meals)
        gap = calculate_daily_gap(total, targets)
        return {
            "person_id": subject_person_id,
            "meals": [
                {"label": meal["label"], "foods": meal["foods"]}
                for meal in candidate_meals
            ],
            "day_total": {nutrient: str(value) for nutrient, value in total.items()},
            "gap_vs_reference": {
                nutrient: str(value) for nutrient, value in gap.items()
            },
            "disclaimer": "Plan compared against the person's targets in force today "
            "(DGE/EFSA reference values; energy and protein calculated from the profile). "
            "Not a medical recommendation.",
            "status": "PROPOSED",
        }

    def get_meal_plan(
        self,
        delegation: str | None,
        subject_person_id: str,
        start_date: str,
        end_date: str,
    ) -> list:
        self._require_access(delegation, subject_person_id, "VIEW")
        return self.mealie.get_meal_plan(start_date, end_date) if self.mealie else []
