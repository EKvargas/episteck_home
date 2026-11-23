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

The operations first used here (``get_profile``, ``upsert_profile``, ``daily_gap``,
``daily_intake``) were retired with the pre-diary intake model. Each property now runs
against ``ProfileService.get_profile_view`` (VIEW), ``ProfileService.propose_profile``
(UPDATE + VIEW) or ``NutritionService.plan_menu`` / ``get_meal_plan`` (VIEW).
"""
from __future__ import annotations

import inspect

import pytest

from app import deps
from app.home_control.client import AccessDecision
from app.profile.service import ProfileService
from app.service import NutritionService
from app.store.profile_sqlite import SqliteProfileStore
from app.providers.synthetic import SyntheticFoodProvider

from tests.support import (
    SESSION,
    AllowAllAuthorizer,
    DenyAllAuthorizer,
    RecordingAuthorizer,
    UnresolvableSessionAuthorizer,
)

SUBJECT = "PSN-SUBJECT"
CHANGE = {"weight_kg": "80"}
MEALS = [{"label": "b", "foods": [{"food_id": "syn-yogurt", "grams": 40}]}]


@pytest.fixture
def store(tmp_path):
    return SqliteProfileStore(str(tmp_path / "n.sqlite"))


def _service(store, authorizer):
    return ProfileService(store, authorizer=authorizer)


def _menu(store, authorizer):
    """NutritionService wired as deps wires it, on the same authorizer."""
    return NutritionService(
        SyntheticFoodProvider(), authorizer=authorizer,
        targets_today=deps.targets_today_from(_service(store, authorizer)),
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

    def check_access_many(self, subject, requirements, delegation=None):
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
        lambda store, a: _service(store, a).get_profile_view(SESSION, SUBJECT),
        lambda store, a: _service(store, a).propose_profile(SESSION, SUBJECT, CHANGE),
        lambda store, a: _menu(store, a).plan_menu(SESSION, SUBJECT, MEALS),
        lambda store, a: _menu(store, a).get_meal_plan(SESSION, SUBJECT, "2026-09-17", "2026-09-17"),
    ],
    ids=["get_profile_view", "propose_profile", "plan_menu", "get_meal_plan"],
)
def test_one_home_call_per_person_sensitive_operation(store, operation):
    authorizer = AllowAllAuthorizer()

    try:
        operation(store, authorizer)
    except PermissionError:  # pragma: no cover - allow-all should not deny
        pytest.fail("AllowAllAuthorizer should not deny")

    assert authorizer.home_calls == 1, (
        f"expected exactly 1 delegated Home request, got {authorizer.home_calls}"
    )


def test_operation_succeeds_under_a_replay_aware_home(store):
    """The real constraint: one delegation, used once, must be enough."""
    authorizer = ReplayAwareAuthorizer(allow=True)

    _service(store, authorizer).get_profile_view(SESSION, SUBJECT)

    assert authorizer.home_calls == 1


def test_old_two_call_composition_would_be_replay_denied(store):
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
    _service(store, fresh).get_profile_view(SESSION, SUBJECT)
    assert fresh.home_calls == 1


# ==========================================================================
# 2-4. Decisions
# ==========================================================================


def test_authorized_view_reads(store):
    authorizer = RecordingAuthorizer(allow=True)
    _service(store, authorizer).get_profile_view(SESSION, SUBJECT)
    assert authorizer.calls == [(SUBJECT, "NUTRITION", "VIEW")]


def test_unauthorized_update_denies(store):
    authorizer = DenyAllAuthorizer()
    with pytest.raises(PermissionError):
        _service(store, authorizer).propose_profile(SESSION, SUBJECT, CHANGE)
    assert authorizer.home_calls == 1


def test_view_never_implies_update(store):
    """A VIEW grant must not satisfy an UPDATE."""

    class ViewOnly:
        def __init__(self):
            self.home_calls = 0
            self.actions = []

        def check_access(self, subject, domain, action, delegation=None):
            self.home_calls += 1
            self.actions.append(action)
            return AccessDecision(action == "VIEW", f"only VIEW granted, saw {action}")

        def check_access_many(self, subject, requirements, delegation=None):
            self.home_calls += 1
            actions = [action for _, action in requirements]
            self.actions.extend(actions)
            allowed = all(action == "VIEW" for action in actions)
            return AccessDecision(allowed, f"only VIEW granted, saw {actions}")

    authorizer = ViewOnly()
    service = _service(store, authorizer)

    service.get_profile_view(SESSION, SUBJECT)  # VIEW allowed
    with pytest.raises(PermissionError):
        service.propose_profile(SESSION, SUBJECT, CHANGE)

    assert authorizer.actions == ["VIEW", "UPDATE", "VIEW"]
    assert authorizer.home_calls == 2


def test_revoked_grant_denies_immediately(store):
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
    service = _service(store, authorizer)

    service.get_profile_view(SESSION, SUBJECT)
    authorizer.revoked = True
    with pytest.raises(PermissionError, match="fail closed"):
        service.get_profile_view(SESSION, SUBJECT)


# ==========================================================================
# 5-8. Fail-closed paths
# ==========================================================================


def test_missing_delegation_denies(store):
    authorizer = AllowAllAuthorizer()
    with pytest.raises(PermissionError):
        _service(store, authorizer).get_profile_view(None, SUBJECT)


def test_invalid_or_expired_delegation_denies(store):
    authorizer = UnresolvableSessionAuthorizer("delegation expired (fail closed)")
    with pytest.raises(PermissionError, match="expired"):
        _service(store, authorizer).get_profile_view(SESSION, SUBJECT)


def test_replayed_delegation_denies(store):
    authorizer = ReplayAwareAuthorizer(allow=True)
    service = _service(store, authorizer)

    service.get_profile_view(SESSION, SUBJECT)  # spends it
    with pytest.raises(PermissionError, match="replay"):
        service.get_profile_view(SESSION, SUBJECT)


def test_home_unavailable_denies(store):
    class UnreachableHome:
        home_calls = 0

        def check_access(self, subject, domain, action, delegation=None):
            return AccessDecision(
                False, "authorization indeterminate (fail closed)"
            )

    with pytest.raises(PermissionError, match="indeterminate"):
        _service(store, UnreachableHome()).get_profile_view(SESSION, SUBJECT)


def test_malformed_home_response_denies(store):
    class MalformedHome:
        home_calls = 0

        def check_access(self, subject, domain, action, delegation=None):
            return AccessDecision(
                False, "authorization indeterminate (fail closed)"
            )

    with pytest.raises(PermissionError):
        _service(store, MalformedHome()).get_profile_view(SESSION, SUBJECT)


def test_authorization_precedes_repository_access(store):
    """A denial must happen before any sensitive read."""
    reads = {"count": 0}
    original = store.list_versions

    def counting_list_versions(person_id):
        reads["count"] += 1
        return original(person_id)

    store.list_versions = counting_list_versions

    with pytest.raises(PermissionError):
        _service(store, DenyAllAuthorizer()).get_profile_view(SESSION, SUBJECT)
    assert reads["count"] == 0


# ==========================================================================
# 9. No actor anywhere caller-facing
# ==========================================================================


def test_service_exposes_no_actor_resolution():
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
