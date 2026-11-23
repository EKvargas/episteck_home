from datetime import date, datetime, timedelta, timezone

import pytest
from nutrition_domain.profile import ProfileInvalid

from app.diary.service import DraftExpired, DraftNotFound
from app.profile.service import ProfileService
from app.service import AccessDenied
from app.store.profile_sqlite import SqliteProfileStore
from tests.support import AllowAllAuthorizer, DenyAllAuthorizer

S = "delegation-token"

ERICK_WIRE = {"birth_date": "1986-03-10", "sex": "MALE", "height_cm": "180", "weight_kg": "82",
              "activity_pal": "1.6", "training_sessions_per_week": 3, "goal": "PERFORMANCE"}
ANA_WIRE = {"birth_date": "1992-06-01", "sex": "FEMALE", "height_cm": "165", "weight_kg": "60",
            "activity_pal": "1.4", "training_sessions_per_week": 0}


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    clock = Clock(datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc))
    auth = AllowAllAuthorizer()
    store = SqliteProfileStore(str(tmp_path / "n.sqlite"))
    svc = ProfileService(store, authorizer=auth, clock=clock)
    return svc, auth, clock, store


def _target(targets, nutrient):
    return next(t for t in targets["items"] if t["nutrient"] == nutrient)


def _onboard(env, person="PSN-E", wire=ERICK_WIRE):
    svc = env[0]
    p = svc.propose_profile(S, person, wire)
    return svc.confirm_profile(S, person, p["draft_id"])["profile"]


def test_onboarding_round_trip(env):
    svc, auth, *_ = env
    p = svc.propose_profile(S, "PSN-E", ERICK_WIRE)
    assert p["profile"]["version"] is None
    assert _target(p["targets_after"], "energy_kcal")["display_value"] == "3150"
    assert p["targets_before"] is None
    assert "birth_date" in p["changed"]
    assert svc.get_profile_view(S, "PSN-E") is None  # a draft saves nothing
    c = svc.confirm_profile(S, "PSN-E", p["draft_id"])
    assert c["created"] and c["profile"]["version"] == 1
    assert c["profile"]["valid_from"] == "2026-11-23"
    assert c["profile"]["inputs"]["age"] == 40
    assert c["profile"]["history"][0]["origin"] == "PROFILE"
    assert auth.requirements[-1] == (("NUTRITION", "UPDATE"), ("NUTRITION", "VIEW"))


def test_version_doc_keeps_targets_for_audit(env):
    _onboard(env)
    doc = env[3].latest("PSN-E")["doc"]
    assert set(doc) == {"inputs", "changed", "targets_at_confirmation"}
    assert doc["targets_at_confirmation"]["method"] == "episteck-targets-1"
    assert _target(doc["targets_at_confirmation"], "energy_kcal")["value"] == "3150.0"


def test_repeated_yes_is_idempotent(env):
    svc, *_, store = env
    p = svc.propose_profile(S, "PSN-E", ERICK_WIRE)
    first = svc.confirm_profile(S, "PSN-E", p["draft_id"])
    second = svc.confirm_profile(S, "PSN-E", p["draft_id"])
    assert first["created"] and not second["created"]
    assert second["profile"]["version"] == first["profile"]["version"] == 1
    assert len(store.list_versions("PSN-E")) == 1


def test_confirmed_draft_is_idempotent_even_after_expiry(env):
    svc, _, clock, store = env
    p = svc.propose_profile(S, "PSN-E", ERICK_WIRE)
    svc.confirm_profile(S, "PSN-E", p["draft_id"])
    clock.now += timedelta(hours=30)
    again = svc.confirm_profile(S, "PSN-E", p["draft_id"])
    assert not again["created"] and len(store.list_versions("PSN-E")) == 1


def test_expired_draft(env):
    svc, _, clock, store = env
    p = svc.propose_profile(S, "PSN-E", ERICK_WIRE)
    clock.now += timedelta(hours=25)
    with pytest.raises(DraftExpired):
        svc.confirm_profile(S, "PSN-E", p["draft_id"])
    assert store.list_versions("PSN-E") == []


def test_other_persons_draft_is_not_found(env):
    svc, *_, store = env
    p = svc.propose_profile(S, "PSN-E", ERICK_WIRE)
    with pytest.raises(DraftNotFound):
        svc.confirm_profile(S, "PSN-A", p["draft_id"])
    with pytest.raises(DraftNotFound):
        svc.confirm_profile(S, "PSN-E", "no-such-draft")
    assert store.list_versions("PSN-E") == []


def test_weight_change_dates_the_measurement_today(env):
    svc, _, clock, _ = env
    _onboard(env)
    clock.now += timedelta(days=2)
    p = svc.propose_profile(S, "PSN-E", {"weight_kg": "80"})
    assert p["profile"]["inputs"]["weight_kg"] == "80"
    assert p["profile"]["inputs"]["weight_measured_on"] == "2026-11-25"
    assert p["changed"] == ["weight_kg", "weight_measured_on"]
    assert p["targets_before"] is not None


def test_confirm_reapplies_changes_on_the_latest_version(env):
    svc, *_ = env
    _onboard(env, "PSN-A", ANA_WIRE)
    p = svc.propose_profile(S, "PSN-A", {"weight_kg": "80"})
    svc.record_mode("PSN-A", "PREGNANCY", date(2027, 5, 15))
    c = svc.confirm_profile(S, "PSN-A", p["draft_id"])
    assert c["profile"]["version"] == 3
    assert c["profile"]["mode"] == "PREGNANCY"  # the mode change is not undone
    assert c["profile"]["inputs"]["weight_kg"] == "80"
    assert c["profile"]["due_date"] == "2027-05-15"


def test_invalid_change_names_the_field(env):
    svc, *_, store = env
    with pytest.raises(ProfileInvalid) as e:
        svc.propose_profile(S, "PSN-E", {"height_cm": "300"})
    assert e.value.field == "height_cm"
    with pytest.raises(ProfileInvalid) as e:
        svc.propose_profile(S, "PSN-E", {})
    assert e.value.field == "changes"
    assert store.list_versions("PSN-E") == []


def test_confirm_revalidates_and_stores_nothing_on_failure(env):
    svc, *_, store = env
    _onboard(env, "PSN-A", ANA_WIRE)
    p = svc.propose_profile(S, "PSN-A", {"goal": "MAINTAIN"})
    svc.record_mode("PSN-A", "PREGNANCY", date(2027, 5, 15))  # a goal no longer fits
    with pytest.raises(ProfileInvalid) as e:
        svc.confirm_profile(S, "PSN-A", p["draft_id"])
    assert e.value.field == "goal"
    assert len(store.list_versions("PSN-A")) == 2
    assert store.get_draft("PSN-A", p["draft_id"])["version"] is None


def test_targets_on_follow_the_version_in_force(env):
    svc, _, clock, _ = env
    _onboard(env)
    clock.now += timedelta(days=2)
    p = svc.propose_profile(S, "PSN-E", {"weight_kg": "70"})
    svc.confirm_profile(S, "PSN-E", p["draft_id"])
    energy = lambda ts: ts.targets["energy_kcal"].value  # noqa: E731
    assert svc.version_on("PSN-E", date(2026, 11, 22)) == 1
    assert svc.version_on("PSN-E", date(2026, 11, 24)) == 1
    assert svc.version_on("PSN-E", date(2026, 11, 25)) == 2
    assert energy(svc.targets_on("PSN-E", date(2026, 11, 22))) == energy(
        svc.targets_on("PSN-E", date(2026, 11, 24)))
    assert energy(svc.targets_on("PSN-E", date(2026, 11, 25))) < energy(
        svc.targets_on("PSN-E", date(2026, 11, 24)))
    assert svc.inputs_on("PSN-E", date(2026, 11, 25)).weight_kg == 70
    assert svc.targets_on("PSN-NONE", date(2026, 11, 25)) is None


def test_same_day_mode_switch_after_onboarding_reaches_back(env):
    svc, *_ = env
    _onboard(env, "PSN-A", ANA_WIRE)
    svc.record_mode("PSN-A", "PREGNANCY", date(2027, 5, 15))  # same local day
    assert svc.inputs_on("PSN-A", date(2026, 11, 22)).mode == "PREGNANCY"
    assert svc.version_on("PSN-A", date(2026, 11, 22)) == 2


def test_has_onboarded_needs_a_profile_origin_version(env):
    svc, *_ = env
    assert not svc.has_onboarded("PSN-A")
    svc.record_mode("PSN-A", "GENERAL", None)
    assert not svc.has_onboarded("PSN-A")
    _onboard(env, "PSN-B")
    assert svc.has_onboarded("PSN-B")


def test_view_says_whether_the_person_is_onboarded(env):
    svc, *_ = env
    svc.record_mode("PSN-A", "PREGNANCY", date(2027, 5, 15))
    v = svc.get_profile_view(S, "PSN-A")
    assert v["origin"] == "MODE" and v["onboarded"] is False
    v = _onboard(env, "PSN-A", ANA_WIRE)
    assert v["onboarded"] is True and svc.get_profile_view(S, "PSN-A")["onboarded"] is True


def test_record_mode_pregnancy_clears_goal_and_general_clears_due_date(env):
    svc, *_ = env
    _onboard(env, "PSN-A", {**ANA_WIRE, "goal": "MAINTAIN"})
    row = svc.record_mode("PSN-A", "PREGNANCY", date(2027, 5, 15))
    assert row["origin"] == "MODE" and row["method"] == "episteck-targets-1"
    assert row["doc"]["changed"] == ["mode", "due_date", "goal"]
    v = svc.view_of("PSN-A")
    assert v["mode"] == "PREGNANCY" and v["inputs"]["goal"] is None and v["trimester"] == 2
    svc.record_mode("PSN-A", "GENERAL", None)
    v = svc.view_of("PSN-A")
    assert v["mode"] == "GENERAL" and v["due_date"] is None and v["trimester"] is None
    assert [h["origin"] for h in v["history"]] == ["PROFILE", "MODE", "MODE"]


def test_view_keeps_the_keys_the_deployed_hub_reads(env):
    v = _onboard(env)
    assert v["context"] == "GENERAL" and v["target_source"] == "REFERENCE_TARGET"
    assert v["targets_flat"]["energy_kcal"] == "3150.0"
    assert v["targets"]["method"] == "episteck-targets-1" and v["targets"]["on"] == "2026-11-23"
    assert v["food"] == {"preferences": None, "dislikes": None, "intolerances": None}


def test_denied_reads_and_writes_store_nothing(env):
    svc, _, clock, store = env
    deny = ProfileService(store, authorizer=DenyAllAuthorizer(), clock=clock)
    with pytest.raises(AccessDenied):
        deny.propose_profile(S, "PSN-E", ERICK_WIRE)
    with pytest.raises(AccessDenied):
        deny.get_profile_view(S, "PSN-E")
    p = svc.propose_profile(S, "PSN-E", ERICK_WIRE)
    with pytest.raises(AccessDenied):
        deny.confirm_profile(S, "PSN-E", p["draft_id"])
    assert store.list_versions("PSN-E") == []
    assert store.get_draft("PSN-E", p["draft_id"])["version"] is None


def test_unrelated_change_ignores_a_stale_weight_measurement(env):
    svc, _, clock, store = env
    _onboard(env)
    clock.now += timedelta(days=120)
    p = svc.propose_profile(S, "PSN-E", {"intolerances": "lactosa"})
    c = svc.confirm_profile(S, "PSN-E", p["draft_id"])
    assert c["profile"]["version"] == 2
    assert c["profile"]["inputs"]["weight_measured_on"] == "2026-11-23"
    assert store.latest("PSN-E")["doc"]["inputs"]["weight_measured_on"] == "2026-11-23"
    assert c["profile"]["food"]["intolerances"] == "lactosa"


def test_stale_measurement_date_given_explicitly_is_refused(env):
    svc, _, clock, _ = env
    _onboard(env)
    clock.now += timedelta(days=120)
    with pytest.raises(ProfileInvalid) as e:
        svc.propose_profile(S, "PSN-E", {"weight_measured_on": "2026-11-23"})
    assert e.value.field == "weight_measured_on"
