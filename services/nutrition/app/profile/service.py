"""Versioned personal profiles: authorized read, propose and confirm.

The three public methods each make one Home request. The internal helpers do not
authorize; their callers (the diary, REST and MCP layers) have already done so.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nutrition_domain.profile import (
    CHANGEABLE_FIELDS, ProfileInputs, ProfileInvalid, age_on, apply_changes,
    inputs_from_doc, inputs_to_doc, parse_changes, validate_inputs,
)
from nutrition_domain.profile_versions import VersionRef, version_in_force
from nutrition_domain.rules import trimester
from nutrition_domain.target_method import METHOD_V1, TargetSet, targets_for_day

from ..diary.service import DraftExpired, DraftNotFound
from ..service import AccessAuthorizer, _refuse_unless_allowed
from ..store.profile_sqlite import SqliteProfileStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def targets_json(ts: TargetSet) -> dict:
    """A TargetSet as JSON-safe data (Decimals as strings)."""
    return {
        "method": ts.method,
        "on": ts.day.isoformat(),
        "items": [
            {"nutrient": t.nutrient, "value": str(t.value), "display_value": t.display_value,
             "unit": t.unit, "kind": t.kind, "source_org": t.source_org,
             "source_ref": t.source_ref, "explanation": t.explanation}
            for t in ts.targets.values()
        ],
        "missing": [{"nutrient": n, "fields": list(f)} for n, f in ts.missing.items()],
    }


def _changed_fields(before: ProfileInputs | None, after: ProfileInputs) -> list[str]:
    base = before or ProfileInputs()
    return [f for f in CHANGEABLE_FIELDS if getattr(base, f) != getattr(after, f)]


def _refs(rows: list[dict]) -> list[VersionRef]:
    return [VersionRef(r["version"], date.fromisoformat(r["valid_from"]), r["origin"])
            for r in rows]


class ProfileService:
    def __init__(
        self,
        store: SqliteProfileStore,
        *,
        authorizer: AccessAuthorizer,
        tz: str = "Europe/Berlin",
        clock: Callable[[], datetime] = _utc_now,
        draft_ttl: timedelta = timedelta(hours=24),
    ):
        self._store = store
        self._authorizer = authorizer
        self._tz = ZoneInfo(tz)
        self._clock = clock
        self._ttl = draft_ttl

    # ---- authorization -------------------------------------------------
    def _authorize(self, delegation, subject_person_id: str, actions: list[str]) -> None:
        if len(actions) == 1:
            decision = self._authorizer.check_access(
                subject_person_id, "NUTRITION", actions[0], delegation)
        else:
            decision = self._authorizer.check_access_many(
                subject_person_id, [("NUTRITION", a) for a in actions], delegation)
        _refuse_unless_allowed(decision)

    # ---- internal helpers (no authorization) ---------------------------
    def today(self) -> date:
        return self._clock().astimezone(self._tz).date()

    def _row_on(self, person: str, day: date) -> dict | None:
        rows = self._store.list_versions(person)
        number = version_in_force(_refs(rows), day)
        return next((r for r in rows if r["version"] == number), None) if number else None

    def inputs_on(self, person: str, day: date) -> ProfileInputs | None:
        row = self._row_on(person, day)
        return inputs_from_doc(row["doc"]["inputs"]) if row else None

    def targets_on(self, person: str, day: date) -> TargetSet | None:
        row = self._row_on(person, day)
        if not row:
            return None
        return targets_for_day(inputs_from_doc(row["doc"]["inputs"]), day, method=row["method"])

    def version_on(self, person: str, day: date) -> int | None:
        row = self._row_on(person, day)
        return row["version"] if row else None

    def has_onboarded(self, person: str) -> bool:
        return any(r["origin"] == "PROFILE" for r in self._store.list_versions(person))

    def _doc(self, inputs: ProfileInputs, changed: list[str], valid_from: date) -> dict:
        return {"inputs": inputs_to_doc(inputs), "changed": changed,
                "targets_at_confirmation": targets_json(targets_for_day(inputs, valid_from))}

    def record_mode(self, person: str, mode: str, due_date: date | None) -> dict:
        today = self.today()
        latest = self._store.latest(person)
        base = inputs_from_doc(latest["doc"]["inputs"]) if latest else ProfileInputs()
        changes: dict = {"mode": mode, "due_date": due_date if mode == "PREGNANCY" else None}
        if mode == "PREGNANCY":
            changes["goal"] = None
        else:
            changes["pre_pregnancy_weight_kg"] = None
        new = replace(base, **changes)
        # A stale weight date must not block a mode switch; it is not what changes here.
        validate_inputs(replace(new, weight_measured_on=None), today)
        changed = ["mode", "due_date"]
        if base.goal is not None and new.goal is None:
            changed.append("goal")
        if base.pre_pregnancy_weight_kg is not None and new.pre_pregnancy_weight_kg is None:
            changed.append("pre_pregnancy_weight_kg")
        return self._store.append_version(
            person, self._doc(new, changed, today), today.isoformat(), "MODE", METHOD_V1)

    # ---- views ----------------------------------------------------------
    def _view(self, person: str, inputs: ProfileInputs, *, version: int | None,
              valid_from: date, origin: str, method: str, history: list[dict]) -> dict:
        today = self.today()
        ts = targets_for_day(inputs, today, method=method)
        due = inputs.due_date
        return {
            "person_id": person, "version": version, "valid_from": valid_from.isoformat(),
            "origin": origin, "mode": inputs.mode,
            "due_date": due.isoformat() if due else None,
            "trimester": trimester(due, today) if inputs.mode == "PREGNANCY" and due else None,
            "inputs": {
                "birth_date": inputs.birth_date.isoformat() if inputs.birth_date else None,
                "age": age_on(inputs.birth_date, today) if inputs.birth_date else None,
                "sex": inputs.sex.value if inputs.sex else None,
                "height_cm": None if inputs.height_cm is None else str(inputs.height_cm),
                "weight_kg": None if inputs.weight_kg is None else str(inputs.weight_kg),
                "weight_measured_on": (inputs.weight_measured_on.isoformat()
                                       if inputs.weight_measured_on else None),
                "activity_pal": None if inputs.activity_pal is None else str(inputs.activity_pal),
                "training_sessions_per_week": inputs.training_sessions_per_week,
                "training_note": inputs.training_note,
                "goal": inputs.goal.value if inputs.goal else None,
                "pre_pregnancy_weight_kg": (None if inputs.pre_pregnancy_weight_kg is None
                                            else str(inputs.pre_pregnancy_weight_kg)),
            },
            "food": {"preferences": inputs.preferences, "dislikes": inputs.dislikes,
                     "intolerances": inputs.intolerances},
            "targets": targets_json(ts),
            "history": history,
            # kept for the deployed Hub (profile-contract.ts)
            "context": inputs.mode, "target_source": "REFERENCE_TARGET",
            "targets_flat": {n: str(t.value) for n, t in ts.targets.items()},
        }

    @staticmethod
    def _history(rows: list[dict]) -> list[dict]:
        return [{"version": r["version"], "valid_from": r["valid_from"], "origin": r["origin"],
                 "changed": list(r["doc"].get("changed", []))} for r in rows]

    def view_of(self, person: str) -> dict | None:
        rows = self._store.list_versions(person)
        if not rows:
            return None
        number = version_in_force(_refs(rows), self.today())
        row = next((r for r in rows if r["version"] == number), rows[-1])
        return self._view(
            person, inputs_from_doc(row["doc"]["inputs"]), version=row["version"],
            valid_from=date.fromisoformat(row["valid_from"]), origin=row["origin"],
            method=row["method"], history=self._history(rows))

    # ---- public operations ---------------------------------------------
    def get_profile_view(self, delegation, subject_person_id: str) -> dict | None:
        self._authorize(delegation, subject_person_id, ["VIEW"])
        return self.view_of(subject_person_id)

    @staticmethod
    def _apply(latest_doc: dict | None, wire: dict, today: date):
        """Re-parse, apply and validate wire changes on a version doc."""
        if not wire:
            raise ProfileInvalid("changes")
        changes = parse_changes(wire)
        if "weight_kg" in changes and "weight_measured_on" not in changes:
            changes["weight_measured_on"] = today
        current = inputs_from_doc(latest_doc["inputs"]) if latest_doc else None
        new = apply_changes(current, changes)
        # The 90-day freshness rule applies only when this change touches the measurement.
        checked = new if "weight_measured_on" in changes else replace(new, weight_measured_on=None)
        validate_inputs(checked, today)
        return current, new

    def propose_profile(self, delegation, subject_person_id: str, changes: dict) -> dict:
        self._authorize(delegation, subject_person_id, ["UPDATE", "VIEW"])
        today = self.today()
        latest = self._store.latest(subject_person_id)
        current, new = self._apply(latest["doc"] if latest else None, changes, today)
        before = targets_for_day(current, today) if current else None
        expires_at = self._clock() + self._ttl
        draft = self._store.put_draft(subject_person_id, {"changes": dict(changes)}, expires_at)
        rows = self._store.list_versions(subject_person_id)
        view = self._view(subject_person_id, new, version=None, valid_from=today,
                          origin="PROFILE", method=METHOD_V1, history=self._history(rows))
        return {"draft_id": draft["id"], "expires_at": expires_at.isoformat(), "profile": view,
                "changed": _changed_fields(current, new),
                "targets_before": targets_json(before) if before else None,
                "targets_after": targets_json(targets_for_day(new, today))}

    def confirm_profile(self, delegation, subject_person_id: str, draft_id: str) -> dict:
        self._authorize(delegation, subject_person_id, ["UPDATE", "VIEW"])
        draft = self._store.get_draft(subject_person_id, draft_id)
        if draft is None:
            raise DraftNotFound(draft_id)
        if draft["version"] is None and datetime.fromisoformat(draft["expires_at"]) <= self._clock():
            raise DraftExpired(draft_id)
        today = self.today()

        def build(latest_doc: dict | None, draft_doc: dict) -> dict:
            current, new = self._apply(latest_doc, draft_doc["changes"], today)
            return self._doc(new, _changed_fields(current, new), today)

        try:
            _, created = self._store.confirm_draft(
                subject_person_id, draft_id, build, today.isoformat(), METHOD_V1)
        except LookupError as exc:
            raise DraftNotFound(draft_id) from exc
        return {"profile": self.view_of(subject_person_id), "created": created}
