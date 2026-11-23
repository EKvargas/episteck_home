"""Home decides before any person data is read or stored.

These properties were first proven on the retired NutritionService profile and intake
operations. They now run against the operations that replaced them:
``ProfileService.get_profile_view`` (VIEW), ``ProfileService.propose_profile``
(UPDATE + VIEW) and ``NutritionService.plan_menu`` (VIEW, then the targets read).
"""
from __future__ import annotations

import pytest

from app import deps
from app.home_control.client import AccessDecision
from app.profile.service import ProfileService
from app.providers.synthetic import SyntheticFoodProvider
from app.service import NutritionService
from app.store.profile_sqlite import SqliteProfileStore
from app.store.sqlite_repo import SqliteNutritionRepository
from tests.support import AllowAllAuthorizer


ACTOR = "PSN-ACTOR"
SUBJECT = "PSN-SUBJECT"
# The delegated human session. Nutrition resolves ACTOR from it via Home; the actor
# is never supplied by a caller.
SESSION = "delegation-token-test"
WIRE = {"birth_date": "1986-03-10", "sex": "MALE", "height_cm": "180", "weight_kg": "82",
        "activity_pal": "1.6"}
UPDATE_AND_VIEW = [(SUBJECT, "NUTRITION", "UPDATE"), (SUBJECT, "NUTRITION", "VIEW")]


class RecordingAuthorizer:
    """Home double: ONE delegated decision per operation, with no actor argument.

    Home derives the human server-side from the delegation, so `allowed` is keyed on
    (subject, domain, action). An operation needing several actions asks for them in
    one ``check_access_many`` request, and is allowed only when every one is allowed.
    `home_calls` proves the single-use contract: a second call on one delegation would
    be replay-denied in production.
    """

    def __init__(self, allowed=()):
        self.allowed = set(allowed)
        self.calls = []
        self.delegations = []
        self.home_calls = 0

    def check_access(self, subject, domain, action, delegation=None):
        return self._decide(subject, [(domain, action)], delegation)

    def check_access_many(self, subject, requirements, delegation=None):
        return self._decide(subject, list(requirements), delegation)

    def _decide(self, subject, requirements, delegation):
        self.home_calls += 1
        self.delegations.append(delegation)
        if not delegation:
            return AccessDecision(False, "no authenticated human session (fail closed)")
        requests = [(subject, domain, action) for domain, action in requirements]
        self.calls.extend(requests)
        allowed = all(request in self.allowed for request in requests)
        return AccessDecision(allowed, "allowed" if allowed else "denied")


class CountingProfileStore(SqliteProfileStore):
    """Counts every read and write of person profile data."""

    def __init__(self, path):
        self.path = path
        self.reads = 0
        self.writes = 0
        super().__init__(path)

    def list_versions(self, person_id):
        self.reads += 1
        return super().list_versions(person_id)

    def latest(self, person_id):
        self.reads += 1
        return super().latest(person_id)

    def get_draft(self, person_id, draft_id):
        self.reads += 1
        return super().get_draft(person_id, draft_id)

    def put_draft(self, person_id, doc, expires_at):
        self.writes += 1
        return super().put_draft(person_id, doc, expires_at)

    def append_version(self, *args, **kwargs):
        self.writes += 1
        return super().append_version(*args, **kwargs)

    def confirm_draft(self, *args, **kwargs):
        self.writes += 1
        return super().confirm_draft(*args, **kwargs)

    def reset_counts(self):
        self.reads = 0
        self.writes = 0


@pytest.fixture
def store(tmp_path):
    profiles = CountingProfileStore(str(tmp_path / "nutrition.sqlite"))
    seeding = ProfileService(profiles, authorizer=AllowAllAuthorizer())
    draft = seeding.propose_profile("seed-token", SUBJECT, WIRE)["draft_id"]
    seeding.confirm_profile("seed-token", SUBJECT, draft)
    profiles.reset_counts()
    return profiles


def _profiles(store, authorizer):
    return ProfileService(store, authorizer=authorizer)


def _menu(store, authorizer):
    """plan_menu wired as deps wires it: the targets come from the same profile store."""
    return NutritionService(
        SyntheticFoodProvider(), authorizer=authorizer,
        targets_today=deps.targets_today_from(_profiles(store, authorizer)),
    )


def test_denial_happens_before_profile_store_read(store):
    service = _profiles(store, RecordingAuthorizer())
    with pytest.raises(PermissionError, match="denied"):
        service.get_profile_view(SESSION, SUBJECT)
    assert store.reads == 0


def test_valid_view_reads_only_after_exact_home_decision(store):
    request = (SUBJECT, "NUTRITION", "VIEW")
    authorizer = RecordingAuthorizer({request})
    profile = _profiles(store, authorizer).get_profile_view(SESSION, SUBJECT)
    assert profile["context"] == "GENERAL"
    assert authorizer.calls == [request]
    assert store.reads == 1


def test_wrong_subject_denies_before_profile_read(store):
    authorizer = RecordingAuthorizer({(SUBJECT, "NUTRITION", "VIEW")})
    with pytest.raises(PermissionError):
        _profiles(store, authorizer).get_profile_view(SESSION, "PSN-WRONG")
    assert store.reads == 0


def test_nutrition_never_sends_an_actor_to_home(store):
    """The caller cannot choose the actor, because no actor exists in this service.

    Previously Nutrition resolved an actor and forwarded it, and this test asserted
    that the forwarded value came from Home rather than the caller. The actor is now
    derived entirely inside Home, so the stronger property holds: Nutrition asks only
    about (subject, domain, action) and has nothing to substitute.
    """
    authorizer = RecordingAuthorizer({(SUBJECT, "NUTRITION", "VIEW")})
    _profiles(store, authorizer).get_profile_view(SESSION, SUBJECT)

    assert authorizer.calls == [(SUBJECT, "NUTRITION", "VIEW")]
    for call in authorizer.calls:
        assert not any("PSN-ACTOR" == part for part in call)
    assert authorizer.home_calls == 1, "exactly one delegated Home request"


def test_no_session_denies_before_any_authorization_call(store):
    authorizer = RecordingAuthorizer({(SUBJECT, "NUTRITION", "VIEW")})
    with pytest.raises(PermissionError, match="no authenticated human session"):
        _profiles(store, authorizer).get_profile_view(None, SUBJECT)
    assert authorizer.calls == []
    assert store.reads == 0


def test_indeterminate_authorization_denies_before_sensitive_reads(store):
    class IndeterminateAuthorizer:
        def check_access(self, subject, domain, action, delegation=None):
            return AccessDecision(False, "authorization indeterminate (fail closed)")

    with pytest.raises(PermissionError, match="indeterminate"):
        _menu(store, IndeterminateAuthorizer()).plan_menu(
            SESSION, SUBJECT, [{"label": "b", "foods": [{"food_id": "syn-yogurt", "grams": 40}]}])
    assert store.reads == 0  # the person's targets were never read


def test_plan_menu_reads_targets_only_after_exact_view_decision(store):
    request = (SUBJECT, "NUTRITION", "VIEW")
    authorizer = RecordingAuthorizer({request})
    plan = _menu(store, authorizer).plan_menu(
        SESSION, SUBJECT, [{"label": "b", "foods": [{"food_id": "syn-yogurt", "grams": 40}]}])
    assert "energy_kcal" in plan["gap_vs_reference"]
    assert authorizer.calls == [request]
    assert authorizer.home_calls == 1
    assert store.reads == 1


def test_legacy_consent_does_not_authorize(store):
    SqliteNutritionRepository(store.path).set_consent(SUBJECT, "NUTRITION", "GRANTED", "migration-only")
    with pytest.raises(PermissionError):
        _profiles(store, RecordingAuthorizer()).get_profile_view(SESSION, SUBJECT)
    assert store.reads == 0


def test_denied_update_happens_before_draft_write(store):
    service = _profiles(store, RecordingAuthorizer())
    with pytest.raises(PermissionError):
        service.propose_profile(SESSION, SUBJECT, {"weight_kg": "80"})
    assert store.writes == 0
    assert store.reads == 0


def test_authorized_update_uses_exact_nutrition_actions(store):
    authorizer = RecordingAuthorizer(UPDATE_AND_VIEW)
    proposal = _profiles(store, authorizer).propose_profile(SESSION, SUBJECT, {"weight_kg": "80"})
    assert proposal["profile"]["person_id"] == SUBJECT
    assert authorizer.calls == UPDATE_AND_VIEW
    assert authorizer.home_calls == 1
    assert store.writes == 1


def test_profile_change_uses_home_authorization_not_legacy_consent(store):
    SqliteNutritionRepository(store.path).set_consent(SUBJECT, "NUTRITION", "GRANTED", "migration-only")
    denied = _profiles(store, RecordingAuthorizer())
    with pytest.raises(PermissionError):
        denied.propose_profile(SESSION, SUBJECT, {"weight_kg": "80"})
    assert store.writes == 0

    authorizer = RecordingAuthorizer(UPDATE_AND_VIEW)
    allowed = _profiles(store, authorizer)
    proposal = allowed.propose_profile(SESSION, SUBJECT, {"weight_kg": "80"})
    assert proposal["profile"]["context"] == "GENERAL"
    assert authorizer.calls == UPDATE_AND_VIEW
    assert store.writes == 1
