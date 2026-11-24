import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app.diary.service import (
    DiaryService, DraftExpired, DraftNotFound, EntryNotFound, ProviderUnavailable,
)
from app.providers.food_provider import FoodProvider, FoodRecord
from app.providers.synthetic import SyntheticFoodProvider
from app.service import AccessDenied
from app.store.diary_sqlite import SqliteDiaryStore
from app.profile.service import ProfileService
from app.store.profile_sqlite import SqliteProfileStore
from tests.support import AllowAllAuthorizer, DenyAllAuthorizer, RecordingAuthorizer

S = "delegation-token"
BLS_TEXT = "Datos: Max Rubner-Institut, BLS 4.0"
T = "2026-11-19T10:30:00+01:00"  # a little before the fixture clock (10:00Z)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeProvider(FoodProvider):
    def __init__(self, records=None):
        self.records = records or {}
        self.calls = []
        self.error = None

    def search_food(self, query):
        return []

    def get_food(self, food_id):
        self.calls.append(food_id)
        if self.error:
            raise self.error
        return self.records[food_id]

    def get_nutrients(self, food_id, quantity, unit):
        return {}


def fizz(sugar="10", **kw):
    return FoodRecord("f", "Fizz", {"sugars_total_g": Decimal(sugar)}, "SYNTHETIC", "v1",
                      category="en:sodas", **kw)


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "n.sqlite")
    clock = Clock(datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc))
    auth = AllowAllAuthorizer()
    store = SqliteDiaryStore(db)
    profiles = ProfileService(SqliteProfileStore(db), authorizer=auth, clock=clock)
    svc = DiaryService(store, SyntheticFoodProvider(), profiles, authorizer=auth, clock=clock)
    return svc, auth, clock, db, store, profiles


def with_provider(env, prov, authorizer=None):
    _, auth, clock, _, store, profiles = env
    return DiaryService(store, prov, profiles, authorizer=authorizer or auth, clock=clock)


def cola(amount=1, unit="small_glass", **kw):
    return {"label": "cola", "food_id": "syn-cola", "amount": amount, "unit": unit,
            "stated": False, **kw}


def gram_item(food_id, grams, label="x"):
    return {"label": label, "food_id": food_id, "amount": grams, "unit": "g", "stated": True}


def confirm(svc, items, consumed_at=T, person="p1"):
    d = svc.propose_intake(S, person, items, consumed_at=consumed_at)
    return svc.confirm_intake(S, person, d["draft_id"])


def draft_rows(db):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COUNT(*) FROM diary_draft").fetchone()[0]


def test_propose_then_confirm_counts_once(env):
    svc = env[0]
    d = svc.propose_intake(S, "p1", [cola()], consumed_at=T)
    assert d["items"][0]["free_sugars_g"] == "15.9" and d["day"]["day_status"] == "NO_ENTRIES"
    assert d["items"][0]["grams"] == "150.0" and d["attribution"] == []
    first = svc.confirm_intake(S, "p1", d["draft_id"])
    again = svc.confirm_intake(S, "p1", d["draft_id"])
    assert first["entry"]["id"] == again["entry"]["id"]
    assert again["day"]["free_sugars_known_g"] == "15.9"
    assert len(again["day"]["entries"]) == 1


def test_frozen_item_shape(env):
    item = env[0].propose_intake(S, "p1", [cola()], consumed_at=T)["items"][0]
    assert item["food_name"] == "Cola (synthetic)"
    assert item["conversion"]["method"] == "PRESET"
    assert item["free_sugar_class"] == "FREE" and item["free_sugar_map_version"] == "episteck-fs-2"
    assert item["facts"]["source"] == "SYNTHETIC" and item["facts"]["category"] == "en:sodas"
    assert item["facts"]["nutrients_per_100g"]["sugars_total_g"] == "10.6"
    assert item["facts"]["retrieved_at"].startswith("2026-11-19T10:00:00")


def test_draft_expires(env):
    svc, _, clock, _, store, _ = env
    d = svc.propose_intake(S, "p1", [cola()], consumed_at=T)
    clock.now += timedelta(hours=25)
    with pytest.raises(DraftExpired):
        svc.confirm_intake(S, "p1", d["draft_id"])
    assert store.list_entries("p1", "2026-11-19") == []


def test_expired_but_confirmed_draft_stays_idempotent(env):
    svc, _, clock, *_ = env
    d = svc.propose_intake(S, "p1", [cola()], consumed_at=T)
    first = svc.confirm_intake(S, "p1", d["draft_id"])
    clock.now += timedelta(hours=48)
    assert svc.confirm_intake(S, "p1", d["draft_id"])["entry"]["id"] == first["entry"]["id"]


def test_draft_never_counts_until_confirmed(env):
    svc = env[0]
    svc.propose_intake(S, "p1", [cola()], consumed_at=T)
    assert svc.get_day_summary(S, "p1", "2026-11-19")["day_status"] == "NO_ENTRIES"


def test_frozen_facts_survive_provider_change(env):
    prov = FakeProvider({"f": fizz("10")})
    svc = with_provider(env, prov)
    confirm(svc, [gram_item("f", 100)])
    prov.records["f"] = fizz("99")
    calls = len(prov.calls)
    assert svc.get_day_summary(S, "p1", "2026-11-19")["free_sugars_known_g"] == "10.0"
    assert len(prov.calls) == calls


def test_confirm_fetches_nothing(env):
    prov = FakeProvider({"f": fizz()})
    svc = with_provider(env, prov)
    d = svc.propose_intake(S, "p1", [gram_item("f", 1)], consumed_at=T)
    n = len(prov.calls)
    svc.confirm_intake(S, "p1", d["draft_id"])
    assert len(prov.calls) == n


def test_unknown_food_is_uncounted(env):
    svc = env[0]
    arepa = {"label": "arepa", "food_id": None, "amount": 1, "unit": "piece", "grams_estimate": 120}
    d = svc.propose_intake(S, "p1", [arepa], consumed_at=T)
    item = d["items"][0]
    assert (item["facts"], item["food_name"], item["free_sugar_class"], item["free_sugars_g"]) == (
        None, None, "UNKNOWN", None)
    assert item["grams"] == "120"
    svc.confirm_intake(S, "p1", d["draft_id"])
    day = svc.get_day_summary(S, "p1", "2026-11-19")
    assert (day["sugar_status"], day["items_uncounted"]) == ("PARTIAL", 1)
    assert day["free_sugars_known_g"] is None


def test_unclassified_food_is_partial_never_zero(env):
    svc = env[0]
    d = svc.propose_intake(S, "p1", [gram_item("syn-bread", 50)], consumed_at=T)
    assert d["items"][0]["free_sugar_class"] == "UNKNOWN" and d["items"][0]["free_sugars_g"] is None
    svc.confirm_intake(S, "p1", d["draft_id"])
    day = svc.get_day_summary(S, "p1", "2026-11-19")
    assert (day["sugar_status"], day["items_uncounted"]) == ("PARTIAL", 1)


def test_free_food_with_no_sugar_value_is_partial_never_zero(env):
    rec = FoodRecord("f", "Fizz", {"protein_g": Decimal("1")}, "SYNTHETIC", "v1", category="en:sodas")
    svc = with_provider(env, FakeProvider({"f": rec}))
    d = svc.propose_intake(S, "p1", [gram_item("f", 100)], consumed_at=T)
    item = d["items"][0]
    assert item["free_sugar_class"] == "FREE" and item["free_sugars_g"] is None
    svc.confirm_intake(S, "p1", d["draft_id"])
    day = svc.get_day_summary(S, "p1", "2026-11-19")
    assert (day["sugar_status"], day["items_uncounted"], day["free_sugars_known_g"]) == ("PARTIAL", 1, None)


def test_not_free_food_counts_zero(env):
    svc = env[0]
    d = svc.propose_intake(S, "p1", [gram_item("syn-apple", 150)], consumed_at=T)
    assert d["items"][0]["free_sugars_g"] == "0.0"
    svc.confirm_intake(S, "p1", d["draft_id"])
    assert svc.get_day_summary(S, "p1", "2026-11-19")["sugar_status"] == "KNOWN"


def test_day_total_is_sum_of_rounded_items(env):
    svc = env[0]
    a = gram_item("syn-orange-juice", 100)  # 8.4 each
    d = svc.propose_intake(S, "p1", [a, a, a], consumed_at=T)
    assert [i["free_sugars_g"] for i in d["items"]] == ["8.4"] * 3
    svc.confirm_intake(S, "p1", d["draft_id"])
    assert svc.get_day_summary(S, "p1", "2026-11-19")["free_sugars_known_g"] == "25.2"


def test_item_rounding_half_up(env):
    svc = with_provider(env, FakeProvider({"f": fizz("10.5")}))
    d = svc.propose_intake(S, "p1", [gram_item("f", 1)], consumed_at=T)
    assert d["items"][0]["free_sugars_g"] == "0.1"  # 0.105 -> 0.1
    d = svc.propose_intake(S, "p1", [gram_item("f", 5)], consumed_at=T)
    assert d["items"][0]["free_sugars_g"] == "0.5"  # 0.525 -> 0.5
    d = svc.propose_intake(S, "p1", [gram_item("f", 10)], consumed_at=T)
    assert d["items"][0]["free_sugars_g"] == "1.1"  # 1.05 -> 1.1 (half up, not half even)


def test_correction_keeps_revision(env):
    svc = env[0]
    e = confirm(svc, [cola()])["entry"]
    out = svc.correct_intake(S, "p1", e["id"], [cola(1, "large_glass")])
    assert out["day"]["free_sugars_known_g"] == "31.8"
    entry = svc.get_entry(S, "p1", e["id"])
    assert entry["rev"] == 2 and entry["day"] == "2026-11-19" and entry["consumed_at"] == T
    assert entry["mode"] == "GENERAL" and out["entry"]["rev"] == 2


def test_correction_reuses_frozen_facts(env):
    prov = FakeProvider({"f": fizz("10", density_g_per_ml=Decimal("1.5")),
                         "g": FoodRecord("g", "Pop", {"sugars_total_g": Decimal("5")}, "SYNTHETIC",
                                         "v1", category="en:sodas")})
    svc = with_provider(env, prov)
    item = {"label": "x", "food_id": "f", "amount": 1, "unit": "can", "stated": False}
    e = confirm(svc, [item])["entry"]
    prov.records["f"] = fizz("99")
    prov.calls.clear()
    out = svc.correct_intake(S, "p1", e["id"], [{**item, "amount": 2}])
    assert prov.calls == []
    # 2 cans = 660 ml x 1.5 g/ml (frozen density) = 990 g at the frozen 10 g/100 g
    assert out["entry"]["items"][0]["grams"] == "990.0"
    assert out["day"]["free_sugars_known_g"] == "99.0"
    svc.correct_intake(S, "p1", e["id"], [{**item, "amount": 2}, {**item, "food_id": "g"}])
    assert prov.calls == ["g"]


def test_correct_voided_or_missing_entry(env):
    svc = env[0]
    e = confirm(svc, [cola()])["entry"]
    svc.void_intake(S, "p1", e["id"])
    with pytest.raises(EntryNotFound):
        svc.correct_intake(S, "p1", e["id"], [cola()])
    with pytest.raises(EntryNotFound):
        svc.correct_intake(S, "p1", "missing", [cola()])


def test_other_person_cannot_touch_entry(env):
    svc = env[0]
    e = confirm(svc, [cola()])["entry"]
    for call in (lambda: svc.correct_intake(S, "p2", e["id"], [cola()]),
                 lambda: svc.void_intake(S, "p2", e["id"]),
                 lambda: svc.get_entry(S, "p2", e["id"])):
        with pytest.raises(EntryNotFound):
            call()
    assert svc.get_entry(S, "p1", e["id"])["voided"] is False


def test_void_excludes_entry(env):
    svc = env[0]
    e = confirm(svc, [cola()])["entry"]
    out = svc.void_intake(S, "p1", e["id"])
    assert out["entry"]["voided"] is True and out["day"]["day_status"] == "NO_ENTRIES"
    assert svc.void_intake(S, "p1", e["id"])["entry"]["voided"] is True
    assert svc.get_day_summary(S, "p1", "2026-11-19")["entries"] == []


def test_get_entry_missing(env):
    with pytest.raises(EntryNotFound):
        env[0].get_entry(S, "p1", "nope")


def test_close_day_marks_complete(env):
    svc, _, clock, *_ = env
    confirm(svc, [cola()])
    clock.now = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)
    assert svc.get_day_summary(S, "p1", "2026-11-19")["day_status"] == "OPEN"
    assert svc.close_day(S, "p1", "2026-11-19")["day_status"] == "COMPLETE"
    assert svc.get_day_summary(S, "p1", "2026-11-19")["day_status"] == "COMPLETE"


def test_close_future_day_rejected(env):
    svc = env[0]
    with pytest.raises(ValueError):
        svc.close_day(S, "p1", "2026-11-20")  # today in Berlin is 2026-11-19
    assert env[4].is_day_closed("p1", "2026-11-20") is False
    assert svc.close_day(S, "p1", "2026-11-19")["day_status"] == "NO_ENTRIES"


@pytest.mark.parametrize("bad", ["20261120", "2026-W47-5", "2026-13-01", "20-11-2026", "", "tomorrow"])  # None means today
def test_bad_day_rejected(env, bad):
    with pytest.raises(ValueError):
        env[0].get_day_summary(S, "p1", bad)
    with pytest.raises(ValueError):
        env[0].close_day(S, "p1", bad)


def test_late_evening_uses_berlin_date(env):
    svc = env[0]
    d1 = svc.propose_intake(S, "p1", [cola()], consumed_at="2026-11-18T23:30:00+01:00")
    d2 = svc.propose_intake(S, "p1", [cola()], consumed_at="2026-11-18T23:30:00Z")
    assert d1["day"]["date"] == "2026-11-18"
    assert d2["day"]["date"] == "2026-11-19"


def test_naive_consumed_at_is_berlin_time(env):
    svc = env[0]
    d = svc.propose_intake(S, "p1", [cola()], consumed_at="2026-07-01T23:30:00")
    assert d["day"]["date"] == "2026-07-01"
    e = svc.confirm_intake(S, "p1", d["draft_id"])["entry"]
    assert e["consumed_at"].endswith("+02:00")


def test_consumed_at_defaults_to_now(env):
    assert env[0].propose_intake(S, "p1", [cola()])["day"]["date"] == "2026-11-19"


def test_stated_must_be_a_real_boolean(env):
    for bad in ("false", "true", 1, None):
        with pytest.raises(ValueError):
            env[0].propose_intake(S, "p1", [cola(stated=bad)], consumed_at=T)
    d = env[0].propose_intake(S, "p1", [gram_item("syn-cola", 100)], consumed_at=T)
    assert d["items"][0]["conversion"]["method"] == "USER_STATED"
    d = env[0].propose_intake(S, "p1", [{k: v for k, v in cola().items() if k != "stated"}], consumed_at=T)
    assert d["items"][0]["conversion"]["method"] == "PRESET"


def test_bad_consumed_at(env):
    with pytest.raises(ValueError):
        env[0].propose_intake(S, "p1", [cola()], consumed_at="not a time")


def test_other_person_cannot_confirm(env):
    svc, _, _, _, store, _ = env
    d = svc.propose_intake(S, "p1", [cola()], consumed_at=T)
    with pytest.raises(DraftNotFound):
        svc.confirm_intake(S, "p2", d["draft_id"])
    with pytest.raises(DraftNotFound):
        svc.confirm_intake(S, "p1", "no-such-draft")
    assert store.list_entries("p1", "2026-11-19") == []


def test_provider_outage_stores_no_draft(env):
    db = env[3]
    prov = FakeProvider()
    svc = with_provider(env, prov)
    req = httpx.Request("GET", "http://food.invalid")
    for err in (httpx.ConnectError("down"), httpx.ReadTimeout("slow"),
                httpx.DecodingError("bad body"), httpx.TooManyRedirects("loop"),
                httpx.HTTPStatusError("e", request=req, response=httpx.Response(503, request=req)),
                httpx.HTTPStatusError("e", request=req, response=httpx.Response(429, request=req))):
        prov.error = err
        with pytest.raises(ProviderUnavailable):
            svc.propose_intake(S, "p1", [gram_item("f", 1)], consumed_at=T)
    assert draft_rows(db) == 0


def test_unknown_food_id_is_value_error(env):
    db = env[3]
    with pytest.raises(ValueError):
        env[0].propose_intake(S, "p1", [gram_item("nope", 1)])
    prov = FakeProvider()
    req = httpx.Request("GET", "http://x")
    prov.error = httpx.HTTPStatusError("nf", request=req, response=httpx.Response(404, request=req))
    with pytest.raises(ValueError):
        with_provider(env, prov).propose_intake(S, "p1", [gram_item("f", 1)])
    assert draft_rows(db) == 0


@pytest.mark.parametrize("items", [
    [], "x", [1], [cola()] * 31,
    [cola(label="")], [cola(label="   ")], [cola(label="a" * 121)], [cola(label=5)],
    [cola(unit=5)], [cola(amount="abc")], [cola(amount=0)], [cola(amount=-1)],
    [cola(unit="furlong")], [cola(amount=float("nan"))],
    [{"label": "a", "food_id": None, "amount": 1, "unit": "piece"}],  # no gram estimate
    [cola(grams_estimate="abc")],
])
def test_invalid_items_rejected(env, items):
    with pytest.raises(ValueError):
        env[0].propose_intake(S, "p1", items, consumed_at=T)
    assert draft_rows(env[3]) == 0


def test_each_operation_is_one_home_request(env):
    svc, auth, clock, *_ = env

    def one(fn, *a, **k):
        before = auth.home_calls
        out = fn(S, "p1", *a, **k)
        assert auth.home_calls == before + 1
        return out

    d = one(svc.propose_intake, [cola()], consumed_at=T)
    e = one(svc.confirm_intake, d["draft_id"])["entry"]
    one(svc.get_entry, e["id"])
    one(svc.correct_intake, e["id"], [cola(2)])
    one(svc.get_day_summary, "2026-11-20")
    one(svc.set_mode, "GENERAL")
    clock.now = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)
    one(svc.close_day, "2026-11-20")
    one(svc.void_intake, e["id"])


def test_actions_requested(env):
    auth = RecordingAuthorizer()
    svc = with_provider(env, SyntheticFoodProvider(), authorizer=auth)
    d = svc.propose_intake(S, "p1", [cola()], consumed_at=T)
    assert auth.requirements[-1] == (("NUTRITION", "CREATE"), ("NUTRITION", "VIEW"))
    e = svc.confirm_intake(S, "p1", d["draft_id"])["entry"]
    svc.get_entry(S, "p1", e["id"])
    assert auth.calls[-1] == ("p1", "NUTRITION", "VIEW")
    svc.void_intake(S, "p1", e["id"])
    assert auth.requirements[-1] == (("NUTRITION", "UPDATE"), ("NUTRITION", "VIEW"))
    assert set(auth.delegations) == {S}


def test_denied_creates_nothing(env):
    db, profiles = env[3], env[5]
    deny = DenyAllAuthorizer()
    prov = FakeProvider()
    svc = with_provider(env, prov, authorizer=deny)
    with pytest.raises(AccessDenied):
        svc.propose_intake(S, "p1", [cola()], consumed_at=T)
    with pytest.raises(AccessDenied):
        svc.set_mode(S, "p1", "PREGNANCY", "2027-05-20")
    assert draft_rows(db) == 0 and prov.calls == [] and profiles.version_on("p1", date(2026, 11, 19)) is None
    assert deny.home_calls == 2


def test_mode_stamp_and_trimester(env):
    svc = env[0]
    out = svc.set_mode(S, "p1", "PREGNANCY", "2027-05-20")
    assert out == {"mode": "PREGNANCY", "due_date": "2027-05-20", "trimester": 2, "version": 1}
    e = confirm(svc, [cola()], consumed_at="2026-11-19T10:00:00+01:00")
    assert e["entry"]["mode"] == "PREGNANCY"
    assert e["day"]["trimester"] == 2 and e["day"]["mode"] == "PREGNANCY"
    assert e["day"]["limit"]["value_g"] == "50"


def test_limit_shape(env):
    svc = env[0]
    day = svc.get_day_summary(S, "p1", "2026-11-19")
    lim = day["limit"]
    assert lim["rule_id"] and lim["origin"] == "INSTITUTIONAL_REFERENCE"
    assert lim["energy_basis_kcal"] == 2000 and set(lim["sources"][0]) == {"title", "url"}
    assert day["mode"] == "GENERAL" and day["trimester"] is None
    assert svc.get_day_summary(S, "p1", "2026-11-17")["limit"] is None  # before valid_from


def test_set_mode_writes_versions_and_validates(env):
    svc, profiles = env[0], env[5]
    today = date(2026, 11, 19)
    r = svc.set_mode(S, "p1", "PREGNANCY", "2027-05-20")
    assert r == {"mode": "PREGNANCY", "due_date": "2027-05-20", "trimester": 2, "version": 1}
    assert profiles.inputs_on("p1", today).due_date == date(2027, 5, 20)
    assert svc.set_mode(S, "p1", "GENERAL") == {"mode": "GENERAL", "due_date": None,
                                                "trimester": None, "version": 2}
    assert profiles.inputs_on("p1", today).due_date is None
    for args in [("LACTATION", None), ("GENERAL", "2027-05-20"), ("PREGNANCY", "soon"),
                 ("pregnancy", None)]:
        with pytest.raises(ValueError):
            svc.set_mode(S, "p1", *args)
    with pytest.raises(ValueError):
        svc.set_mode(S, "p1", "PREGNANCY", "20270520")


def test_set_mode_without_due_date(env):
    svc, profiles = env[0], env[5]
    svc.set_mode(S, "p9", "PREGNANCY")
    inputs = profiles.inputs_on("p9", date(2026, 11, 19))
    assert inputs.mode == "PREGNANCY" and inputs.due_date is None


def test_bls_item_adds_attribution(env):
    prov = FakeProvider({"bls:S1": FoodRecord("bls:S1", "Zuckerwasser", {"sugars_total_g": Decimal("10")},
                                              "BLS", "BLS 4.0", category="S")})
    svc = with_provider(env, prov)
    d = svc.propose_intake(S, "p1", [gram_item("bls:S1", 100)], consumed_at=T)
    assert d["attribution"] == [BLS_TEXT]
    day = svc.confirm_intake(S, "p1", d["draft_id"])["day"]
    assert day["attribution"] == [BLS_TEXT]
    assert svc.get_day_summary(S, "p1", "2026-11-20")["attribution"] == []


def test_day_entries_shape_and_order(env):
    svc = env[0]
    for t in ("2026-11-19T10:00:00+01:00", "2026-11-19T08:00:00+01:00"):
        confirm(svc, [cola()], consumed_at=t)
    day = svc.get_day_summary(S, "p1", "2026-11-19")
    assert [e["consumed_at"] for e in day["entries"]] == [
        "2026-11-19T08:00:00+01:00", "2026-11-19T10:00:00+01:00"]
    assert set(day["entries"][0]) == {"id", "consumed_at", "items"}
    assert day["items_total"] == 2 and day["free_sugars_known_g"] == "31.8"


def test_zero_source_serving_never_books_a_false_zero(env):
    prov = FakeProvider({"f": fizz("10", serving_g=Decimal("0"))})
    svc = with_provider(env, prov)
    item = {"label": "soda", "food_id": "f", "amount": 1, "unit": "serving"}
    with pytest.raises(ValueError):
        svc.propose_intake(S, "p1", [item], T)
    out = svc.propose_intake(S, "p1", [{**item, "grams_estimate": 330}], T)
    assert out["items"][0]["grams"] == "330"


# ---- final-review minors ----------------------------------------------------

def test_consumed_at_in_the_future_is_rejected(env):
    from app.diary.service import InvalidField
    svc, clock = env[0], env[2]
    now = clock.now
    ok = (now + timedelta(minutes=9)).isoformat()
    assert svc.propose_intake(S, "p1", [cola()], consumed_at=ok)["items"]
    late = (now + timedelta(minutes=11)).isoformat()
    with pytest.raises(InvalidField) as e:
        svc.propose_intake(S, "p1", [cola()], consumed_at=late)
    assert e.value.field == "consumed_at"
    with pytest.raises(ValueError):
        svc.propose_intake(S, "p1", [cola()], consumed_at="2026-11-20T10:00:00+01:00")


def test_non_json_provider_body_is_provider_unavailable(env):
    import json
    prov = FakeProvider()
    prov.error = json.JSONDecodeError("Expecting value", "<html>", 0)
    svc = with_provider(env, prov)
    with pytest.raises(ProviderUnavailable):
        svc.propose_intake(S, "p1", [gram_item("f", 1)], consumed_at=T)


def test_bls_database_error_is_provider_unavailable(env):
    prov = FakeProvider()
    prov.error = sqlite3.OperationalError("unable to open database file")
    svc = with_provider(env, prov)
    with pytest.raises(ProviderUnavailable):
        svc.propose_intake(S, "p1", [gram_item("f", 1)], consumed_at=T)


def test_day_defaults_to_today_in_the_diary_timezone(env):
    svc, clock = env[0], env[2]
    # 23:30Z on the 19th is already the 20th in Berlin
    clock.now = datetime(2026, 11, 19, 23, 30, tzinfo=timezone.utc)
    assert svc.get_day_summary(S, "p1")["date"] == "2026-11-20"
    assert svc.get_day_summary(S, "p1", None)["date"] == "2026-11-20"
    assert svc.close_day(S, "p1")["date"] == "2026-11-20"
    assert env[4].is_day_closed("p1", "2026-11-20") is True


def test_validation_errors_name_the_field_only(env):
    from app.diary.service import InvalidField
    svc = env[0]
    cases = [
        ({**cola(), "label": ""}, "label"),
        ({**cola(), "unit": 5}, "unit"),
        ({**cola(), "food_id": ""}, "food_id"),
        ({**cola(), "stated": "yes"}, "stated"),
        ({**cola(), "amount": "lots"}, "amount"),
        ({**cola(), "grams_estimate": "x"}, "grams_estimate"),
        ({**cola(), "food_id": "no-such-food"}, "food_id"),
    ]
    for item, field in cases:
        with pytest.raises(InvalidField) as e:
            svc.propose_intake(S, "p1", [item], consumed_at=T)
        assert e.value.field == field, item
        assert "cola" not in str(e.value).lower() or field == "label"
    with pytest.raises(InvalidField) as e:
        svc.get_day_summary(S, "p1", "not-a-date")
    assert e.value.field == "day"
    with pytest.raises(InvalidField) as e:
        svc.set_mode(S, "p1", "PREGNANCY", "soon")
    assert e.value.field == "due_date"
    with pytest.raises(InvalidField) as e:
        svc.set_mode(S, "p1", "LACTATION")
    assert e.value.field == "mode"
    with pytest.raises(InvalidField) as e:
        svc.propose_intake(S, "p1", "nope", consumed_at=T)
    assert e.value.field == "items"
    # a unit the table does not know is a plain portion error: no field
    with pytest.raises(ValueError) as e:
        svc.propose_intake(S, "p1", [cola(unit="bucket")], consumed_at=T)
    assert getattr(e.value, "field", None) is None


def test_unknown_food_id_is_still_invalid_item(env):
    from app.diary.service import InvalidField
    with pytest.raises(InvalidField) as e:
        env[0].propose_intake(S, "p1", [gram_item("syn-does-not-exist", 1)], consumed_at=T)
    assert e.value.field == "food_id"


def test_provider_parse_error_is_provider_unavailable(env):
    prov = FakeProvider()
    prov.error = KeyError("fdcId")
    with pytest.raises(ProviderUnavailable):
        with_provider(env, prov).propose_intake(S, "p1", [gram_item("f", 1)], consumed_at=T)
    assert draft_rows(env[3]) == 0


def test_fndds_cheesecake_and_black_coffee_get_free_sugars(env):
    cake = FoodRecord("usda:2707861", "Cheesecake, plain", {"sugars_total_g": Decimal("26.6")},
                      "USDA_FDC:Survey (FNDDS)", "2707861", category="Cakes and pies")
    coffee = FoodRecord("usda:2710375", "Coffee, brewed", {"sugars_total_g": Decimal("0.0")},
                        "USDA_FDC:Survey (FNDDS)", "2710375", category="Coffee")
    svc = with_provider(env, FakeProvider({"cake": cake, "coffee": coffee}))
    d = svc.propose_intake(S, "p1", [gram_item("cake", 80), gram_item("coffee", 240)], consumed_at=T)
    cake_item, coffee_item = d["items"]
    assert cake_item["free_sugar_class"] == "FREE" and cake_item["free_sugars_g"] == "21.3"
    assert coffee_item["free_sugar_class"] == "UNKNOWN" and coffee_item["free_sugars_g"] == "0.0"
    day = svc.confirm_intake(S, "p1", d["draft_id"])["day"]
    assert day["free_sugars_known_g"] == "21.3" and day["items_uncounted"] == 0
    assert day["sugar_status"] == "KNOWN"
