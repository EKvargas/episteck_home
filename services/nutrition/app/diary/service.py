"""Ana's food diary: drafts, confirmed entries, corrections and day summaries.

Facts about a food are resolved once, when a draft is made, and copied unchanged into
the entry, so a later change in a food database never moves a past day. Every public
method authorizes with exactly one Home request before it reads or writes anything.
Logging, if added, must carry ids and statuses only, never food text.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from nutrition_domain.day_summary import summarize_day
from nutrition_domain.free_sugars import FREE_SUGAR_MAP_VERSION, FreeSugarClass, classify, item_free_sugars_g
from nutrition_domain.portions import to_grams
from nutrition_domain.rules import effective_limit, trimester

from ..providers.food_provider import FoodProvider, FoodRecord
from ..service import AccessAuthorizer, _refuse_unless_allowed

MODES = ("GENERAL", "PREGNANCY")
BLS_ATTRIBUTION = "Datos: Max Rubner-Institut, BLS 4.0"
MAX_ITEMS = 30
MAX_LABEL = 120
_ONE_DECIMAL = Decimal("0.1")


class DraftNotFound(LookupError):
    """No such draft for this person (also for someone else's draft)."""


class EntryNotFound(LookupError):
    """No such entry for this person, or a voided entry was corrected."""


class DraftExpired(Exception):
    """The draft is older than its time to live and was never confirmed."""


class ProviderUnavailable(Exception):
    """The food provider could not be reached or refused to answer."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _one_decimal(value: Decimal) -> Decimal:
    return value.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{field} must be a number") from None
    if not d.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return d


_DAY_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_day(day: Any, field: str = "day") -> date:
    """Strict YYYY-MM-DD (date.fromisoformat alone also accepts 20261120 and week dates)."""
    if not isinstance(day, str) or not _DAY_FORMAT.match(day):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(day)
    except ValueError:
        raise ValueError(f"{field} must be YYYY-MM-DD") from None


def _parse_item(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("each item must be an object")
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > MAX_LABEL:
        raise ValueError(f"label must be 1 to {MAX_LABEL} characters")
    unit = raw.get("unit")
    if not isinstance(unit, str):
        raise ValueError("unit must be text")
    food_id = raw.get("food_id")
    if food_id is not None and (not isinstance(food_id, str) or not food_id.strip()):
        raise ValueError("food_id must be text or null")
    stated = raw.get("stated", False)
    if not isinstance(stated, bool):
        raise ValueError("stated must be true or false")
    estimate = raw.get("grams_estimate")
    return {
        "label": label.strip(),
        "food_id": food_id,
        "amount": _decimal(raw.get("amount"), "amount"),
        "unit": unit,
        "stated": stated,
        "grams_estimate": None if estimate is None else _decimal(estimate, "grams_estimate"),
    }


def _num(value: Any) -> str:
    return str(value)


def _opt_dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


class DiaryService:
    def __init__(
        self,
        store,
        provider: FoodProvider,
        profiles,
        *,
        authorizer: AccessAuthorizer,
        tz: str = "Europe/Berlin",
        clock: Callable[[], datetime] = _utc_now,
        draft_ttl: timedelta = timedelta(hours=24),
    ):
        self._store = store
        self._provider = provider
        self._profiles = profiles
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

    # ---- profile / mode ------------------------------------------------
    def _profile(self, person: str) -> dict:
        return self._profiles.get_profile(person) or {}

    @staticmethod
    def _mode_of(profile: dict) -> str:
        return "PREGNANCY" if profile.get("context") == "PREGNANCY" else "GENERAL"

    @staticmethod
    def _due_of(profile: dict) -> date | None:
        try:
            return date.fromisoformat(profile.get("due_date"))
        except (TypeError, ValueError):
            return None

    def _today(self) -> date:
        return self._clock().astimezone(self._tz).date()

    # ---- food resolution -----------------------------------------------
    def _fetch(self, food_id: str) -> FoodRecord:
        try:
            return self._provider.get_food(food_id)
        except LookupError:  # KeyError included
            raise ValueError("unknown food_id") from None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError("unknown food_id") from None
            raise ProviderUnavailable("food provider unavailable") from None
        except httpx.RequestError:  # transport, decoding, redirect loops
            raise ProviderUnavailable("food provider unavailable") from None

    def _facts_for(self, food_id: str) -> tuple[str, dict]:
        rec = self._fetch(food_id)
        return rec.name, {
            "nutrients_per_100g": {k: str(v) for k, v in rec.nutrients_per_100g.items()},
            "source": rec.source,
            "provider_version": rec.provider_version,
            "category": rec.category,
            "retrieved_at": self._clock().astimezone(timezone.utc).isoformat(),
            # Kept so a correction can convert portions without asking the provider again.
            "serving_g": None if rec.serving_g is None else str(rec.serving_g),
            "density_g_per_ml": None if rec.density_g_per_ml is None else str(rec.density_g_per_ml),
        }

    def _freeze(self, item: dict, food_name: str | None, facts: dict | None) -> dict:
        conv = to_grams(
            item["amount"], item["unit"], stated=item["stated"],
            serving_g=_opt_dec(facts.get("serving_g") if facts is not None else None),
            density_g_per_ml=_opt_dec(facts.get("density_g_per_ml") if facts is not None else None),
            grams_estimate=item["grams_estimate"],
        )
        cls, sugars = FreeSugarClass.UNKNOWN, None
        if facts is not None:
            cls = classify(facts["source"], facts["category"], name=food_name)
            nutrients = {k: Decimal(v) for k, v in facts["nutrients_per_100g"].items()}
            raw = item_free_sugars_g(cls, nutrients, conv.grams)
            sugars = None if raw is None else str(_one_decimal(raw))
        return {
            "label": item["label"],
            "food_id": item["food_id"],
            "food_name": food_name,
            "amount": _num(item["amount"]),
            "unit": item["unit"],
            "grams": str(conv.grams),
            "conversion": {"method": conv.method.value, "detail": conv.detail,
                           "table_version": conv.table_version},
            "facts": facts,
            "free_sugar_class": cls.value,
            "free_sugar_map_version": FREE_SUGAR_MAP_VERSION,
            "free_sugars_g": sugars,
        }

    def _freeze_items(self, raw_items: Any, known: dict[str, tuple[str, dict]] | None = None) -> list[dict]:
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= MAX_ITEMS:
            raise ValueError(f"items must be a list of 1 to {MAX_ITEMS}")
        items = [_parse_item(r) for r in raw_items]
        cache: dict[str, tuple[str, dict]] = dict(known or {})
        frozen = []
        for item in items:
            fid = item["food_id"]
            if fid is None:
                frozen.append(self._freeze(item, None, None))
                continue
            if fid not in cache:
                cache[fid] = self._facts_for(fid)
            name, facts = cache[fid]
            frozen.append(self._freeze(item, name, facts))
        return frozen

    # ---- consumed_at / day ---------------------------------------------
    def _parse_consumed_at(self, consumed_at: str | None) -> datetime:
        if consumed_at is None:
            return self._clock().astimezone(self._tz)
        try:
            dt = datetime.fromisoformat(consumed_at)
        except (TypeError, ValueError):
            raise ValueError("consumed_at must be an ISO 8601 date and time") from None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self._tz)
        return dt

    # ---- day summary ---------------------------------------------------
    def _day(self, person: str, day: date) -> dict:
        profile = self._profile(person)
        mode = self._mode_of(profile)
        due = self._due_of(profile)
        entries = self._store.list_entries(person, day.isoformat())
        items = [i for e in entries for i in e["items"]]
        summary = summarize_day(
            day, [_opt_dec(i["free_sugars_g"]) for i in items],
            self._store.is_day_closed(person, day.isoformat()), effective_limit(day, mode))
        lim = summary.limit
        total = summary.free_sugars_known_g
        return {
            "date": day.isoformat(),
            "mode": mode,
            "trimester": trimester(due, day) if mode == "PREGNANCY" and due else None,
            "day_status": summary.day_status.value,
            "sugar_status": summary.sugar_status.value,
            "free_sugars_known_g": None if total is None else str(_one_decimal(total)),
            "items_total": summary.items_total,
            "items_uncounted": summary.items_uncounted,
            "limit": None if lim is None else {
                "rule_id": lim.rule_id, "version": lim.version, "value_g": str(lim.value_g),
                "basis": lim.basis, "energy_basis_kcal": lim.energy_basis_kcal,
                "origin": lim.origin,
                "sources": [{"title": s.title, "url": s.url} for s in lim.sources],
                "adaptation": lim.adaptation,
            },
            "entries": [{"id": e["id"], "consumed_at": e["consumed_at"], "items": e["items"]}
                        for e in entries],
            "attribution": _attribution(items),
        }

    # ---- public API ----------------------------------------------------
    def propose_intake(self, delegation, subject_person_id: str, items: list[dict],
                       consumed_at: str | None = None) -> dict:
        self._authorize(delegation, subject_person_id, ["CREATE", "VIEW"])
        when = self._parse_consumed_at(consumed_at)
        frozen = self._freeze_items(items)
        day = when.astimezone(self._tz).date()
        expires = self._clock() + self._ttl
        doc = {"items": frozen, "day": day.isoformat(), "consumed_at": when.isoformat()}
        draft = self._store.put_draft(subject_person_id, doc, expires)
        return {
            "draft_id": draft["id"],
            "expires_at": expires.astimezone(timezone.utc).isoformat(),
            "items": frozen,
            "attribution": _attribution(frozen),
            "day": self._day(subject_person_id, day),
        }

    def confirm_intake(self, delegation, subject_person_id: str, draft_id: str) -> dict:
        self._authorize(delegation, subject_person_id, ["CREATE", "VIEW"])
        draft = self._store.get_draft(subject_person_id, draft_id)
        if draft is None:
            raise DraftNotFound("draft not found")
        if draft["entry_id"]:  # a repeated "sí" is idempotent, even after expiry
            entry = self._store.get_entry(subject_person_id, draft["entry_id"])
        else:
            if self._clock() >= datetime.fromisoformat(draft["expires_at"]):
                raise DraftExpired("draft expired")
            entry_doc = {
                "items": draft["items"], "day": draft["day"], "consumed_at": draft["consumed_at"],
                "mode": self._mode_of(self._profile(subject_person_id)),
                "confirmed_at": self._clock().astimezone(timezone.utc).isoformat(),
            }
            try:
                entry, _ = self._store.confirm_draft(subject_person_id, draft_id, entry_doc)
            except LookupError:
                raise DraftNotFound("draft not found") from None
        return {"entry": entry, "day": self._day(subject_person_id, _parse_day(entry["day"]))}

    def correct_intake(self, delegation, subject_person_id: str, entry_id: str,
                       items: list[dict]) -> dict:
        self._authorize(delegation, subject_person_id, ["UPDATE", "VIEW"])
        old = self._store.get_entry(subject_person_id, entry_id)
        if old is None or old["voided"]:
            raise EntryNotFound("entry not found")
        known = {i["food_id"]: (i["food_name"], i["facts"]) for i in old["items"]
                 if i["food_id"] and i["facts"] is not None}
        doc = {"items": self._freeze_items(items, known), "day": old["day"],
               "consumed_at": old["consumed_at"], "mode": old["mode"],
               "confirmed_at": old["confirmed_at"]}
        try:
            entry = self._store.add_revision(subject_person_id, entry_id, doc)
        except LookupError:
            raise EntryNotFound("entry not found") from None
        return {"entry": entry, "day": self._day(subject_person_id, _parse_day(entry["day"]))}

    def void_intake(self, delegation, subject_person_id: str, entry_id: str) -> dict:
        self._authorize(delegation, subject_person_id, ["UPDATE", "VIEW"])
        try:
            entry = self._store.void_entry(subject_person_id, entry_id)
        except LookupError:
            raise EntryNotFound("entry not found") from None
        return {"entry": entry, "day": self._day(subject_person_id, _parse_day(entry["day"]))}

    def get_entry(self, delegation, subject_person_id: str, entry_id: str) -> dict:
        self._authorize(delegation, subject_person_id, ["VIEW"])
        entry = self._store.get_entry(subject_person_id, entry_id)
        if entry is None:
            raise EntryNotFound("entry not found")
        return entry

    def get_day_summary(self, delegation, subject_person_id: str, day: str) -> dict:
        self._authorize(delegation, subject_person_id, ["VIEW"])
        return self._day(subject_person_id, _parse_day(day))

    def close_day(self, delegation, subject_person_id: str, day: str) -> dict:
        self._authorize(delegation, subject_person_id, ["UPDATE", "VIEW"])
        d = _parse_day(day)
        if d > self._today():
            raise ValueError("a day that has not started cannot be closed")
        self._store.close_day(subject_person_id, d.isoformat(), self._clock())
        return self._day(subject_person_id, d)

    def set_mode(self, delegation, subject_person_id: str, mode: str,
                 due_date: str | None = None) -> dict:
        self._authorize(delegation, subject_person_id, ["UPDATE", "VIEW"])
        if mode not in MODES:
            raise ValueError("mode must be GENERAL or PREGNANCY")
        due = None
        if due_date is not None:
            if mode != "PREGNANCY":
                raise ValueError("due_date is only allowed with PREGNANCY")
            due = _parse_day(due_date, "due_date")
        stored = self._profile(subject_person_id)
        if not stored:
            # Same shape ProfileIn gives; the Hub profile view rejects a profile without
            # targets or target_source.
            stored = {"preferences": None, "dislikes": None, "intolerances": None,
                      "targets": {}, "target_source": "USER_CONFIGURED"}
        profile = {**stored, "context": mode,
                   "due_date": due.isoformat() if due else None}
        self._profiles.upsert_profile(subject_person_id, profile)
        return {"mode": mode, "due_date": profile["due_date"],
                "trimester": trimester(due, self._today()) if due else None}


def _attribution(items: list[dict]) -> list[str]:
    shown_from_bls = any(i["facts"] and i["facts"]["source"] == "BLS" for i in items)
    return [BLS_ATTRIBUTION] if shown_from_bls else []
