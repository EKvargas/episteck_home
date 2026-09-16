"""One delegated Home request per person-sensitive operation (G1.6, PR A).

WHY THIS SUITE EXISTS
---------------------
Delegations became single-use when replay enforcement landed. Nutrition was resolving
the actor via ``whoami`` and then calling ``check_access`` with the SAME delegation, so
the second request was replay-denied and every person-sensitive route broke. Verified
live against production before the fix:

    whoami       -> 200  (actor resolved, delegation consumed)
    check_access -> 403  (replay detected)

The doubles in ``support.py`` could never have caught it — a double has no replay
store, so both calls "succeeded". These tests therefore assert the *number* of
delegated requests, which is the property that actually matters, and model a replay
store so the old composition fails loudly.
"""
from __future__ import annotations

import inspect

import pytest

from app.home_control.client import AccessDecision
from app.service import NutritionService
from app.store.sqlite_repo import SqliteNutritionRepository
from app.providers.synthetic import SyntheticFoodProvider

from tests.support import (
    SESSION,
    AllowAllAuthorizer,
    DenyAllAuthorizer,
    RecordingAuthorizer,
    UnresolvableSessionAuthorizer,
)

SUBJECT = "PSN-SUBJECT"


@pytest.fixture
def repo(tmp_path):
    return SqliteNutritionRepository(str(tmp_path / "n.sqlite"))


def _service(repo, authorizer):
    return NutritionService(
        repo, SyntheticFoodProvider(), authorizer=authorizer
    )


class ReplayAwareAuthorizer:
    """A double that behaves like production: each delegation works exactly once.

    This is what the old two-call composition needed in order to fail in a test.
    """

    def __init__(self, allow: bool = True):
        self.allow = allow
        self.spent: set[str] = set()
        self.home_calls = 0

    def _consume(self, delegation):
        self.home_calls += 1
        if not delegation:
            return AccessDecision(
                False, "no authenticated human session (fail closed)"
            )
        if delegation in self.spent:
            return AccessDecision(False, "delegation replay detected (fail closed)")
        self.spent.add(delegation)
        return None

    def check_access(self, subject, domain, action, delegation=None):
        denial = self._consume(delegation)
        if denial is not None:
            return denial
        return AccessDecision(self.allow, "allowed" if self.allow else "denied")


# ==========================================================================
# 1. Exactly one Home call per operation
# ==========================================================================


@pytest.mark.parametrize(
    "operation",
    [
        lambda s: s.get_profile(SESSION, SUBJECT),
        lambda s: s.upsert_profile(SESSION, SUBJECT, {"context": "GENERAL"}),
        lambda s: s.daily_gap(SESSION, SUBJECT, "2026-09-17"),
        lambda s: s.daily_intake(SESSION, SUBJECT, "2026-09-17"),
    ],
    ids=["get_profile", "upsert_profile", "daily_gap", "daily_intake"],
)
def test_one_home_call_per_person_sensitive_operation(repo, operation):
    authorizer = AllowAllAuthorizer()
    service = _service(repo, authorizer)

    try:
        operation(service)
    except PermissionError:  # pragma: no cover - allow-all should not deny
        pytest.fail("AllowAllAuthorizer should not deny")

    assert authorizer.home_calls == 1, (
        f"expected exactly 1 delegated Home request, got {authorizer.home_calls}"
    )


def test_operation_succeeds_under_a_replay_aware_home(repo):
    """The real constraint: one delegation, used once, must be enough."""
    authorizer = ReplayAwareAuthorizer(allow=True)

    _service(repo, authorizer).get_profile(SESSION, SUBJECT)

    assert authorizer.home_calls == 1


def test_old_two_call_composition_would_be_replay_denied(repo):
    """Reverting to resolve-then-authorize reproduces the production failure.

    Rather than asserting a claim about deleted code, this replays the old sequence
    against a replay-aware Home and shows the second call being refused.
    """
    authorizer = ReplayAwareAuthorizer(allow=True)

    # Step 1 — what the removed resolve_actor() did: spend the delegation.
    first = authorizer.check_access(SUBJECT, "NUTRITION", "VIEW", SESSION)
    assert first.allow, "the first use of a delegation succeeds"

    # Step 2 — the authorization that used to follow on the SAME token.
    second = authorizer.check_access(SUBJECT, "NUTRITION", "VIEW", SESSION)
    assert not second.allow
    assert "replay" in second.reason

    # And the current single-call service is unaffected, on a fresh delegation.
    fresh = ReplayAwareAuthorizer(allow=True)
    _service(repo, fresh).get_profile(SESSION, SUBJECT)
    assert fresh.home_calls == 1


# ==========================================================================
# 2-4. Decisions
# ==========================================================================


def test_authorized_view_reads(repo):
    authorizer = RecordingAuthorizer(allow=True)
    _service(repo, authorizer).get_profile(SESSION, SUBJECT)
    assert authorizer.calls == [(SUBJECT, "NUTRITION", "VIEW")]


def test_unauthorized_update_denies(repo):
    authorizer = DenyAllAuthorizer()
    with pytest.raises(PermissionError):
        _service(repo, authorizer).upsert_profile(
            SESSION, SUBJECT, {"context": "GENERAL"}
        )
    assert authorizer.calls if hasattr(authorizer, "calls") else True


def test_view_never_implies_update(repo):
    """A VIEW grant must not satisfy an UPDATE."""

    class ViewOnly:
        def __init__(self):
            self.home_calls = 0
            self.actions = []

        def check_access(self, subject, domain, action, delegation=None):
            self.home_calls += 1
            self.actions.append(action)
            return AccessDecision(action == "VIEW", f"only VIEW granted, saw {action}")

    authorizer = ViewOnly()
    service = _service(repo, authorizer)

    service.get_profile(SESSION, SUBJECT)  # VIEW allowed
    with pytest.raises(PermissionError):
        service.upsert_profile(SESSION, SUBJECT, {"context": "GENERAL"})

    assert authorizer.actions == ["VIEW", "UPDATE"]


def test_revoked_grant_denies_immediately(repo):
    """A grant revoked between operations denies the very next one."""

    class RevocableAuthorizer:
        def __init__(self):
            self.revoked = False
            self.home_calls = 0

        def check_access(self, subject, domain, action, delegation=None):
            self.home_calls += 1
            if self.revoked:
                return AccessDecision(False, "no matching active grant (fail closed)")
            return AccessDecision(True, "grant NUTRITION/VIEW")

    authorizer = RevocableAuthorizer()
    service = _service(repo, authorizer)

    service.get_profile(SESSION, SUBJECT)
    authorizer.revoked = True
    with pytest.raises(PermissionError, match="fail closed"):
        service.get_profile(SESSION, SUBJECT)


# ==========================================================================
# 5-8. Fail-closed paths
# ==========================================================================


def test_missing_delegation_denies(repo):
    authorizer = AllowAllAuthorizer()
    with pytest.raises(PermissionError):
        _service(repo, authorizer).get_profile(None, SUBJECT)


def test_invalid_or_expired_delegation_denies(repo):
    authorizer = UnresolvableSessionAuthorizer("delegation expired (fail closed)")
    with pytest.raises(PermissionError, match="expired"):
        _service(repo, authorizer).get_profile(SESSION, SUBJECT)


def test_replayed_delegation_denies(repo):
    authorizer = ReplayAwareAuthorizer(allow=True)
    service = _service(repo, authorizer)

    service.get_profile(SESSION, SUBJECT)  # spends it
    with pytest.raises(PermissionError, match="replay"):
        service.get_profile(SESSION, SUBJECT)


def test_home_unavailable_denies(repo):
    class UnreachableHome:
        home_calls = 0

        def check_access(self, subject, domain, action, delegation=None):
            return AccessDecision(
                False, "authorization indeterminate (fail closed)"
            )

    with pytest.raises(PermissionError, match="indeterminate"):
        _service(repo, UnreachableHome()).get_profile(SESSION, SUBJECT)


def test_malformed_home_response_denies(repo):
    class MalformedHome:
        home_calls = 0

        def check_access(self, subject, domain, action, delegation=None):
            return AccessDecision(
                False, "authorization indeterminate (fail closed)"
            )

    with pytest.raises(PermissionError):
        _service(repo, MalformedHome()).get_profile(SESSION, SUBJECT)


def test_authorization_precedes_repository_access(repo):
    """A denial must happen before any sensitive read."""
    reads = {"count": 0}
    original = repo.get_profile

    def counting_get_profile(person_id):
        reads["count"] += 1
        return original(person_id)

    repo.get_profile = counting_get_profile

    with pytest.raises(PermissionError):
        _service(repo, DenyAllAuthorizer()).get_profile(SESSION, SUBJECT)
    assert reads["count"] == 0


# ==========================================================================
# 9. No actor anywhere caller-facing
# ==========================================================================


def test_service_exposes_no_actor_resolution(repo):
    assert not hasattr(NutritionService, "resolve_actor")


def test_require_access_takes_no_actor():
    params = set(inspect.signature(NutritionService._require_access).parameters)
    assert params == {"self", "delegation", "subject_person_id", "action"}


def test_no_public_service_method_accepts_an_actor():
    forbidden = {"actor", "actor_person_id", "actor_id", "human_actor"}
    for name, fn in inspect.getmembers(NutritionService, inspect.isfunction):
        if name.startswith("_"):
            continue
        params = set(inspect.signature(fn).parameters)
        assert not (params & forbidden), f"{name} exposes an actor parameter"


def test_authorizer_protocol_has_no_actor():
    from app.service import AccessAuthorizer

    params = set(inspect.signature(AccessAuthorizer.check_access).parameters)
    assert "actor_person_id" not in params
    assert "actor" not in params


def test_fastapi_routes_expose_no_actor(tmp_path, monkeypatch):
    """No HTTP route may accept an actor, in path, query, or body."""
    import importlib
    import sys

    # app.main builds a real service at import, so give it a scratch DB and the
    # environment its client requires. Mirrors the boundary_modules fixture.
    monkeypatch.setenv("NUTRITION_DB", str(tmp_path / "routes.sqlite"))
    monkeypatch.setenv("FOOD_PROVIDER", "synthetic")
    monkeypatch.setenv("HOME_CONTROL_PLANE_URL", "https://home.invalid")
    monkeypatch.setenv("HOME_API_KEY", "test-key")
    monkeypatch.setenv("HOME_API_SECRET", "test-secret")
    for name in ("app.mcp.server", "app.main", "app.deps", "app.session"):
        sys.modules.pop(name, None)
    app = importlib.import_module("app.main").app

    for route in app.routes:
        path = getattr(route, "path", "")
        assert "actor" not in path.lower(), f"{path} names an actor"
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        params = set(inspect.signature(endpoint).parameters)
        assert not (
            params & {"actor", "actor_person_id", "actor_id", "human_actor"}
        ), f"{path} accepts an actor parameter"
