from __future__ import annotations

import pytest

from app.home_control.client import AccessDecision
from app.providers.synthetic import SyntheticFoodProvider
from app.service import NutritionService
from app.store.sqlite_repo import SqliteNutritionRepository


ACTOR = "PSN-ACTOR"
SUBJECT = "PSN-SUBJECT"
# The delegated human session. Nutrition resolves ACTOR from it via Home; the actor
# is never supplied by a caller.
SESSION = "delegation-token-test"


class RecordingAuthorizer:
    """Home double: resolves the actor from the session, then decides access."""

    def __init__(self, allowed=(), actor=ACTOR):
        self.allowed = set(allowed)
        self.actor = actor
        self.calls = []
        self.resolutions = []

    def resolve_actor(self, delegation):
        self.resolutions.append(delegation)
        return self.actor if delegation else None

    def check_access(self, actor, subject, domain, action, delegation=None):
        request = (actor, subject, domain, action)
        self.calls.append(request)
        return AccessDecision(request in self.allowed, "allowed" if request in self.allowed else "denied")


class CountingRepository(SqliteNutritionRepository):
    def __init__(self, path):
        self.profile_reads = 0
        self.profile_writes = 0
        self.intake_reads = 0
        self.intake_writes = 0
        super().__init__(path)

    def get_profile(self, person_id):
        self.profile_reads += 1
        return super().get_profile(person_id)

    def upsert_profile(self, person_id, profile):
        self.profile_writes += 1
        return super().upsert_profile(person_id, profile)

    def list_intake(self, person_id, date, kind=None):
        self.intake_reads += 1
        return super().list_intake(person_id, date, kind)

    def add_intake(self, person_id, record):
        self.intake_writes += 1
        return super().add_intake(person_id, record)

    def reset_counts(self):
        self.profile_reads = 0
        self.profile_writes = 0
        self.intake_reads = 0
        self.intake_writes = 0


@pytest.fixture
def repo(tmp_path):
    repository = CountingRepository(str(tmp_path / "nutrition.sqlite"))
    repository.upsert_profile(SUBJECT, {"context": "GENERAL", "targets": {"protein_g": 60}})
    repository.reset_counts()
    return repository


def _service(repo, authorizer):
    return NutritionService(
        repo,
        SyntheticFoodProvider(),
        authorizer=authorizer,
    )


def test_denial_happens_before_profile_repository_read(repo):
    service = _service(repo, RecordingAuthorizer())
    with pytest.raises(PermissionError, match="denied"):
        service.get_profile(SESSION, SUBJECT)
    assert repo.profile_reads == 0


def test_valid_view_reads_only_after_exact_home_decision(repo):
    request = (ACTOR, SUBJECT, "NUTRITION", "VIEW")
    authorizer = RecordingAuthorizer({request})
    profile = _service(repo, authorizer).get_profile(SESSION, SUBJECT)
    assert profile["context"] == "GENERAL"
    assert authorizer.calls == [request]
    assert repo.profile_reads == 1


def test_wrong_subject_denies_before_profile_read(repo):
    authorizer = RecordingAuthorizer({(ACTOR, SUBJECT, "NUTRITION", "VIEW")})
    with pytest.raises(PermissionError):
        _service(repo, authorizer).get_profile(SESSION, "PSN-WRONG")
    assert repo.profile_reads == 0


def test_actor_comes_from_home_not_from_the_caller(repo):
    """A different session resolves to a different actor; the caller cannot choose."""
    authorizer = RecordingAuthorizer({(ACTOR, SUBJECT, "NUTRITION", "VIEW")}, actor="PSN-WRONG")
    with pytest.raises(PermissionError):
        _service(repo, authorizer).get_profile(SESSION, SUBJECT)
    # Home was asked about the actor IT resolved, never one supplied by the caller.
    assert authorizer.calls == [("PSN-WRONG", SUBJECT, "NUTRITION", "VIEW")]
    assert repo.profile_reads == 0


def test_no_session_denies_before_any_authorization_call(repo):
    authorizer = RecordingAuthorizer({(ACTOR, SUBJECT, "NUTRITION", "VIEW")})
    with pytest.raises(PermissionError, match="no authenticated human session"):
        _service(repo, authorizer).get_profile(None, SUBJECT)
    assert authorizer.calls == []
    assert repo.profile_reads == 0


def test_indeterminate_authorization_denies_before_sensitive_reads(repo):
    class IndeterminateAuthorizer:
        def resolve_actor(self, delegation):
            return ACTOR

        def check_access(self, actor, subject, domain, action, delegation=None):
            return AccessDecision(False, "authorization indeterminate (fail closed)")

    with pytest.raises(PermissionError, match="indeterminate"):
        _service(repo, IndeterminateAuthorizer()).daily_gap(SESSION, SUBJECT, "2026-09-15")
    assert repo.profile_reads == 0
    assert repo.intake_reads == 0


def test_legacy_consent_does_not_authorize(repo):
    repo.set_consent(SUBJECT, "NUTRITION", "GRANTED", "migration-only")
    with pytest.raises(PermissionError):
        _service(repo, RecordingAuthorizer()).get_profile(SESSION, SUBJECT)
    assert repo.profile_reads == 0


def test_denied_create_happens_before_intake_write(repo):
    service = _service(repo, RecordingAuthorizer())
    with pytest.raises(PermissionError):
        service.record_actual(
            SESSION,
            SUBJECT,
            "2026-09-15",
            [{"food_id": "syn-yogurt", "grams": 100}],
        )
    assert repo.intake_writes == 0


def test_authorized_create_uses_exact_nutrition_action(repo):
    request = (ACTOR, SUBJECT, "NUTRITION", "CREATE")
    authorizer = RecordingAuthorizer({request})
    record = _service(repo, authorizer).record_actual(
        SESSION,
        SUBJECT,
        "2026-09-15",
        [{"food_id": "syn-yogurt", "grams": 100}],
    )
    assert record["person_id"] == SUBJECT
    assert authorizer.calls == [request]
    assert repo.intake_writes == 1


def test_pregnancy_profile_uses_home_authorization_not_legacy_consent(repo):
    repo.set_consent(SUBJECT, "NUTRITION", "GRANTED", "migration-only")
    denied = _service(repo, RecordingAuthorizer())
    with pytest.raises(PermissionError):
        denied.create_pregnancy_profile(SESSION, SUBJECT)
    assert repo.profile_writes == 0

    request = (ACTOR, SUBJECT, "NUTRITION", "UPDATE")
    allowed = _service(repo, RecordingAuthorizer({request}))
    profile = allowed.create_pregnancy_profile(SESSION, SUBJECT, stage="synthetic")
    assert profile["context"] == "PREGNANCY"
    assert allowed.authorizer.calls == [request]
    assert repo.profile_writes == 1
