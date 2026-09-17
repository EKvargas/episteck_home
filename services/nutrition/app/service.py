"""Nutrition service core with Home-authorized person data access.

All nutrient calculations remain deterministic. Every person-specific repository read
or write is preceded by an exact actor/subject/domain/action decision from the Home
Control Plane. Nutrition-local consent is not consulted.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from nutrition_domain import (
    ConfirmedFoodAmount,
    FoodFact,
    IntakeKind,
    IntakeProvenance,
    calculate_daily_gap,
    calculate_daily_intake,
    calculate_meal_nutrients,
    compare_to_targets,
)

from .providers.food_provider import FoodProvider
from .reference.pregnancy_targets import (
    pregnancy_targets_detailed,
    pregnancy_targets_map,
)
from .store.repository import NutritionRepository


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
        repo: NutritionRepository,
        provider: FoodProvider,
        mealie=None,
        *,
        authorizer: AccessAuthorizer,
    ):
        self.repo = repo
        self.provider = provider
        self.mealie = mealie
        self.authorizer = authorizer

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
        actor argument, and all twelve call sites here discarded the resolved value.

        The trusted-actor invariant is unchanged and arguably stronger: Nutrition
        still supplies only its own machine credential and the opaque delegation, and
        there is now no actor value in this service to assert, forward, or confuse.
        """
        decision = self.authorizer.check_access(
            subject_person_id, "NUTRITION", action, delegation
        )
        # Literal allow only: anything else — deny, malformed, indeterminate,
        # unreachable — is a refusal.
        if not decision.allow:
            raise PermissionError(decision.reason)

    def _require_all(
        self, delegation: str | None, subject_person_id: str, actions: list[str]
    ) -> None:
        """Authorize an operation needing SEVERAL permissions, still in ONE request.

        ``ate_as_planned`` reads a plan and then writes intake. Calling
        ``_require_access`` twice would spend the single-use delegation on the first
        and be replay-denied on the second, so the operation could never complete —
        the same class of defect as the removed ``resolve_actor`` step, one layer up.

        Asking for only CREATE would be the other wrong fix: it would let an actor
        write an intake derived from a plan they were not allowed to read.
        """
        decision = self.authorizer.check_access_many(
            subject_person_id,
            [("NUTRITION", action) for action in actions],
            delegation,
        )
        if not decision.allow:
            raise PermissionError(decision.reason)

    # --- profile ---
    def get_profile(self, delegation: str | None, subject_person_id: str):
        self._require_access(delegation, subject_person_id, "VIEW")
        return self.repo.get_profile(subject_person_id)

    def upsert_profile(
        self, delegation: str | None, subject_person_id: str, profile: dict
    ):
        self._require_access(delegation, subject_person_id, "UPDATE")
        return self.repo.upsert_profile(subject_person_id, profile)

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

    def _daily_intake(self, subject_person_id: str, date: str) -> dict:
        records = self.repo.list_intake(
            subject_person_id, date, kind=IntakeKind.ACTUAL.value
        )
        meals = [self._to_confirmed(record["foods"]) for record in records if record.get("foods")]
        totals = calculate_daily_intake(meals)
        return {nutrient: str(value) for nutrient, value in totals.items()}

    def daily_intake(
        self, delegation: str | None, subject_person_id: str, date: str
    ) -> dict:
        self._require_access(delegation, subject_person_id, "VIEW")
        return self._daily_intake(subject_person_id, date)

    def daily_gap(self, delegation: str | None, subject_person_id: str, date: str) -> dict:
        self._require_access(delegation, subject_person_id, "VIEW")
        return self._daily_gap(subject_person_id, date)

    def daily(self, delegation: str | None, subject_person_id: str, date: str) -> dict:
        """Intake AND gap for one day, authorized ONCE.

        The ``/daily`` route used to call ``daily_intake`` and then ``daily_gap``.
        Both are public and both authorize, so one HTTP request produced TWO delegated
        Home requests on the same single-use delegation — the second replay-denied.

        Composing at the service layer rather than the route is what keeps the rule
        enforceable: the authorization lives next to the data access it guards, and a
        future caller cannot reassemble the broken version by picking two public
        methods that each look correctly authorized on their own.
        """
        self._require_access(delegation, subject_person_id, "VIEW")
        return {
            "intake": self._daily_intake(subject_person_id, date),
            "gap": self._daily_gap(subject_person_id, date),
        }

    def _daily_gap(self, subject_person_id: str, date: str) -> dict:
        """Gap computation with NO authorization: callers must have authorized."""
        profile = self.repo.get_profile(subject_person_id) or {}
        targets = {
            nutrient: Decimal(str(value))
            for nutrient, value in (profile.get("targets") or {}).items()
        }
        consumed = {
            nutrient: Decimal(value)
            for nutrient, value in self._daily_intake(subject_person_id, date).items()
        }
        gap = calculate_daily_gap(consumed, targets)
        comparisons = compare_to_targets(consumed, targets)
        return {
            "targets": {nutrient: str(value) for nutrient, value in targets.items()},
            "consumed": {nutrient: str(value) for nutrient, value in consumed.items()},
            "gap": {nutrient: str(value) for nutrient, value in gap.items()},
            "detail": {
                nutrient: {
                    "target": str(comparison.target),
                    "consumed": str(comparison.consumed),
                    "remaining": str(comparison.remaining),
                    "percentage": str(comparison.percentage),
                }
                for nutrient, comparison in comparisons.items()
            },
        }

    # --- planned vs actual ---
    def record_planned(
        self,
        delegation: str | None,
        subject_person_id: str,
        date: str,
        foods: list[dict],
        ref: str | None = None,
    ):
        self._require_access(delegation, subject_person_id, "CREATE")
        return self.repo.add_intake(
            subject_person_id,
            {
                "date": date,
                "kind": IntakeKind.PLANNED.value,
                "foods": foods,
                "planned_meal_reference": ref,
                "provenance": IntakeProvenance.USER_CONFIRMED.value,
            },
        )

    def _record_actual(
        self,
        subject_person_id: str,
        date: str,
        foods: list[dict],
        provenance: str,
        ref: str | None,
    ):
        return self.repo.add_intake(
            subject_person_id,
            {
                "date": date,
                "kind": IntakeKind.ACTUAL.value,
                "foods": foods,
                "planned_meal_reference": ref,
                "provenance": provenance,
            },
        )

    def record_actual(
        self,
        delegation: str | None,
        subject_person_id: str,
        date: str,
        foods: list[dict],
        provenance: str = IntakeProvenance.USER_CONFIRMED.value,
        ref: str | None = None,
    ):
        self._require_access(delegation, subject_person_id, "CREATE")
        return self._record_actual(subject_person_id, date, foods, provenance, ref)

    def ate_as_planned(
        self,
        delegation: str | None,
        subject_person_id: str,
        date: str,
        planned_id: str,
    ):
        # BOTH permissions, ONE delegated request: this reads a plan and writes an
        # intake, and the delegation can only be spent once.
        self._require_all(delegation, subject_person_id, ["VIEW", "CREATE"])
        planned = [
            record
            for record in self.repo.list_intake(
                subject_person_id, date, IntakeKind.PLANNED.value
            )
            if record["id"] == planned_id
        ]
        if not planned:
            raise KeyError("planned record not found")
        record = planned[0]
        return self._record_actual(
            subject_person_id,
            date,
            record["foods"],
            IntakeProvenance.USER_CONFIRMED.value,
            record.get("planned_meal_reference") or planned_id,
        )

    def propose_change(self, foods: list[dict]) -> dict:
        """Return an AI proposal; callers must confirm before persistence."""
        return {
            "provenance": IntakeProvenance.AI_PROPOSAL.value,
            "foods": foods,
            "nutrients": self.evaluate_meal(foods),
            "requires_confirmation": True,
        }

    # --- pregnancy profile with authoritative reference targets ---
    def create_pregnancy_profile(
        self,
        delegation: str | None,
        subject_person_id: str,
        *,
        stage: str | None = None,
        preferences: str = "",
        dislikes: str = "",
        intolerances: str = "",
        avoided_foods: str = "",
        user_goals: dict | None = None,
    ):
        # This operation persists through an upsert and can replace an existing
        # profile, so UPDATE is the minimum safe action even when the first call
        # happens to create the row.
        self._require_access(delegation, subject_person_id, "UPDATE")
        profile = {
            "context": "PREGNANCY",
            "pregnancy_stage": stage,
            "preferences": preferences,
            "dislikes": dislikes,
            "explicit_intolerances": intolerances,
            "avoided_foods": avoided_foods,
            "user_goals": user_goals or {},
            "targets": {
                nutrient: str(value)
                for nutrient, value in pregnancy_targets_map().items()
            },
            "targets_detail": pregnancy_targets_detailed(),
            "target_source": "REFERENCE_TARGET",
        }
        return self.repo.upsert_profile(subject_person_id, profile)

    def daily_gap_v2(
        self, delegation: str | None, subject_person_id: str, date: str
    ) -> dict:
        self._require_access(delegation, subject_person_id, "VIEW")
        profile = self.repo.get_profile(subject_person_id) or {}
        targets = {
            nutrient: Decimal(str(value))
            for nutrient, value in (profile.get("targets") or {}).items()
        }
        records = self.repo.list_intake(subject_person_id, date, kind="ACTUAL")
        reported = set()
        for record in records:
            for food in record.get("foods", []):
                try:
                    reported |= set(
                        self.provider.get_food(food["food_id"]).nutrients_per_100g
                    )
                except Exception:
                    continue
        consumed = {
            nutrient: Decimal(value)
            for nutrient, value in self._daily_intake(subject_person_id, date).items()
        }
        result = {}
        for nutrient, target in targets.items():
            if nutrient not in reported:
                result[nutrient] = {
                    "target": str(target),
                    "consumed": None,
                    "remaining": None,
                    "percentage": None,
                    "status": "UNKNOWN",
                }
            else:
                consumed_value = consumed.get(nutrient, Decimal("0"))
                result[nutrient] = {
                    "target": str(target),
                    "consumed": str(consumed_value),
                    "remaining": str(target - consumed_value),
                    "percentage": str(
                        (consumed_value / target * 100) if target else Decimal("0")
                    ),
                    "status": "KNOWN",
                }
        return result

    # --- menu planning (deterministic evaluation; not medical optimization) ---
    def plan_menu(
        self,
        delegation: str | None,
        subject_person_id: str,
        candidate_meals: list[dict],
    ) -> dict:
        self._require_access(delegation, subject_person_id, "VIEW")
        profile = self.repo.get_profile(subject_person_id) or {}
        targets = {
            nutrient: Decimal(str(value))
            for nutrient, value in (profile.get("targets") or {}).items()
        }
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
            "disclaimer": "Plan constructed against configured DGE/EFSA reference targets and "
            "stated preferences. Not a medical recommendation.",
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
