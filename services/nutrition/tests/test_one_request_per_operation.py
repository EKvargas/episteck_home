"""EVERY person-sensitive operation costs EXACTLY ONE delegated Home request (G1.6).

WHY THIS SUITE EXISTS
---------------------
Delegations are single-use. PR #9 removed a redundant ``resolve_actor`` call that made
every operation spend its delegation twice, and added tests for FOUR operations. Two
violations survived that sampling, because they are not in the service's authorization
helper at all — they are in how operations are COMPOSED:

    ate_as_planned()          VIEW then CREATE on the same delegation
    GET /daily/{person}/{date}  daily_intake() then daily_gap(), both authorizing

Sampling four operations cannot find a defect in the fifth. So this suite ENUMERATES —
it discovers the real entry points by walking the FastAPI route table and the MCP tool
module, and asserts the request count for each one it finds. An operation added later
is covered the day it is added; if the discovery itself breaks, the inventory tests
fail rather than silently covering nothing.

WHAT IS COUNTED
---------------
Delegated Home REQUESTS, not permissions. ``check_access_many`` decides several
requirements in one request, which is the entire point: replay protection constrains
requests, so an operation needing two permissions gets both in one.
"""
from __future__ import annotations

import importlib
import inspect
import sys

import pytest
from fastapi.testclient import TestClient

from app.diary.service import DiaryService
from app.profile.service import ProfileService
from app.store.profile_sqlite import SqliteProfileStore
from app.home_control.client import AccessDecision
from app.providers.synthetic import SyntheticFoodProvider
from app.service import NutritionService
from app.store.diary_sqlite import SqliteDiaryStore
from app.store.sqlite_repo import SqliteNutritionRepository

from tests.support import SESSION, AllowAllAuthorizer

SUBJECT = "PSN-SUBJECT"
DATE = "2026-09-17"
DELEGATION_HEADER = "X-Episteck-Delegation"


class ReplayAwareAuthorizer:
    """A double that behaves like production: each delegation works exactly once.

    Both entry points share one replay store, so an operation that calls
    ``check_access`` and then ``check_access_many`` (or either one twice) on the same
    token is refused exactly as production would refuse it.
    """

    def __init__(self, allow: bool = True):
        self.allow = allow
        self.spent: set[str] = set()
        self.home_calls = 0
        self.requirements: list[tuple] = []

    def _consume(self, delegation):
        self.home_calls += 1
        if not delegation:
            return AccessDecision(False, "no authenticated human session (fail closed)")
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
        self.requirements.append(tuple(requirements))
        denial = self._consume(delegation)
        if denial is not None:
            return denial
        return AccessDecision(self.allow, "allowed" if self.allow else "denied")


@pytest.fixture
def repo(tmp_path):
    return SqliteNutritionRepository(str(tmp_path / "n.sqlite"))


def _service(repo, authorizer):
    return NutritionService(repo, SyntheticFoodProvider(), authorizer=authorizer)


def _seed_planned(service, repo):
    """A planned record to convert, created outside the operation under test."""
    fresh = AllowAllAuthorizer()
    seeding = NutritionService(repo, SyntheticFoodProvider(), authorizer=fresh)
    return seeding.record_planned(
        "seed-token", SUBJECT, DATE, [{"food_id": "syn-yogurt", "grams": 100}]
    )["id"]


class ActionRecordingAuthorizer(AllowAllAuthorizer):
    """AllowAll that also records WHICH actions each Home request asked about."""

    def __init__(self):
        super().__init__()
        self.actions: list[str] = []

    def check_access(self, subject, domain, action, delegation=None):
        self.actions.append(action)
        return super().check_access(subject, domain, action, delegation)

    def check_access_many(self, subject, requirements, delegation=None):
        self.actions.extend(action for _, action in requirements)
        return super().check_access_many(subject, requirements, delegation)


COLA = {"label": "cola", "food_id": "syn-cola", "amount": 1, "unit": "small_glass"}


def _diary_service(db, authorizer):
    return DiaryService(
        SqliteDiaryStore(db), SyntheticFoodProvider(),
        ProfileService(SqliteProfileStore(db), authorizer=authorizer), authorizer=authorizer,
    )


def _seed_diary(db) -> dict:
    """A confirmed entry and a still-open draft, made outside the operation under test."""
    seeding = _diary_service(db, AllowAllAuthorizer())
    first = seeding.propose_intake("seed-token", SUBJECT, [COLA])
    entry = seeding.confirm_intake("seed-token", SUBJECT, first["draft_id"])["entry"]["id"]
    draft = seeding.propose_intake("seed-token", SUBJECT, [COLA])["draft_id"]
    return {"entry": entry, "draft": draft}


# ==========================================================================
# THE INVENTORY — every person-sensitive service operation
# ==========================================================================

#: Each entry invokes ONE business operation on the service. A person-sensitive
#: operation missing from here fails ``test_every_authorizing_service_method_is_covered``.
SERVICE_OPERATIONS = {
    "get_profile": lambda s, repo: s.get_profile(SESSION, SUBJECT),
    "upsert_profile": lambda s, repo: s.upsert_profile(
        SESSION, SUBJECT, {"context": "GENERAL"}
    ),
    "daily_intake": lambda s, repo: s.daily_intake(SESSION, SUBJECT, DATE),
    "daily_gap": lambda s, repo: s.daily_gap(SESSION, SUBJECT, DATE),
    "daily": lambda s, repo: s.daily(SESSION, SUBJECT, DATE),
    "daily_gap_v2": lambda s, repo: s.daily_gap_v2(SESSION, SUBJECT, DATE),
    "record_planned": lambda s, repo: s.record_planned(
        SESSION, SUBJECT, DATE, [{"food_id": "syn-yogurt", "grams": 50}]
    ),
    "record_actual": lambda s, repo: s.record_actual(
        SESSION, SUBJECT, DATE, [{"food_id": "syn-yogurt", "grams": 50}]
    ),
    "ate_as_planned": lambda s, repo: s.ate_as_planned(
        SESSION, SUBJECT, DATE, _seed_planned(s, repo)
    ),
    "create_pregnancy_profile": lambda s, repo: s.create_pregnancy_profile(
        SESSION, SUBJECT, stage="T2"
    ),
    "plan_menu": lambda s, repo: s.plan_menu(
        SESSION,
        SUBJECT,
        [{"label": "b", "foods": [{"food_id": "syn-yogurt", "grams": 40}]}],
    ),
    "get_meal_plan": lambda s, repo: s.get_meal_plan(SESSION, SUBJECT, DATE, DATE),
}


def _authorizing_service_methods() -> set[str]:
    """Public service methods that authorize, found in the SOURCE, not a list.

    This is what makes the suite exhaustive rather than a sample: adding a method that
    calls ``_require_access``/``_require_all`` without adding it to
    ``SERVICE_OPERATIONS`` fails the coverage test below.
    """
    import ast
    import pathlib

    from app import service as service_module

    tree = ast.parse(pathlib.Path(service_module.__file__).read_text(encoding="utf-8"))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "NutritionService"
    )
    found = set()
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        authorizes = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in {"_require_access", "_require_all"}
            for call in ast.walk(node)
        )
        if authorizes:
            found.add(node.name)
    return found


def test_every_authorizing_service_method_is_covered():
    """The inventory above must not drift from the code."""
    discovered = _authorizing_service_methods()
    assert discovered, "discovery found no authorizing methods — the walker is broken"
    missing = discovered - set(SERVICE_OPERATIONS)
    assert not missing, (
        f"person-sensitive operations with no one-request test: {sorted(missing)}"
    )
    stale = set(SERVICE_OPERATIONS) - discovered
    assert not stale, f"inventory lists methods that no longer authorize: {sorted(stale)}"


# ==========================================================================
# THE INVENTORY — every person-sensitive DIARY operation
# ==========================================================================

#: method -> (invocation, the exact actions its ONE Home request must ask about)
DIARY_OPERATIONS = {
    "propose_intake": (
        lambda d, ids: d.propose_intake(SESSION, SUBJECT, [COLA]), ["CREATE", "VIEW"]),
    "confirm_intake": (
        lambda d, ids: d.confirm_intake(SESSION, SUBJECT, ids["draft"]), ["CREATE", "VIEW"]),
    "correct_intake": (
        lambda d, ids: d.correct_intake(SESSION, SUBJECT, ids["entry"], [COLA]),
        ["UPDATE", "VIEW"]),
    "void_intake": (
        lambda d, ids: d.void_intake(SESSION, SUBJECT, ids["entry"]), ["UPDATE", "VIEW"]),
    "get_entry": (
        lambda d, ids: d.get_entry(SESSION, SUBJECT, ids["entry"]), ["VIEW"]),
    "get_day_summary": (
        lambda d, ids: d.get_day_summary(SESSION, SUBJECT, DATE), ["VIEW"]),
    "close_day": (
        lambda d, ids: d.close_day(SESSION, SUBJECT, DATE), ["UPDATE", "VIEW"]),
    "set_mode": (
        lambda d, ids: d.set_mode(SESSION, SUBJECT, "GENERAL"), ["UPDATE", "VIEW"]),
    "get_period_summary": (
        lambda d, ids: d.get_period_summary(SESSION, SUBJECT), ["VIEW"]),
}


def _authorizing_diary_methods() -> set[str]:
    """Public DiaryService methods that authorize, found in the SOURCE, not a list."""
    import ast
    import pathlib

    from app.diary import service as diary_module

    tree = ast.parse(pathlib.Path(diary_module.__file__).read_text(encoding="utf-8"))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DiaryService"
    )
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "_authorize"
            for call in ast.walk(node)
        )
    }


def test_every_authorizing_diary_method_is_covered():
    discovered = _authorizing_diary_methods()
    assert discovered, "discovery found no authorizing diary methods — the walker is broken"
    assert discovered == set(DIARY_OPERATIONS), (
        f"diary inventory drifted: missing {sorted(discovered - set(DIARY_OPERATIONS))}, "
        f"stale {sorted(set(DIARY_OPERATIONS) - discovered)}"
    )


@pytest.mark.parametrize("name", sorted(DIARY_OPERATIONS))
def test_one_home_request_per_diary_operation_with_its_planned_actions(tmp_path, name):
    db = str(tmp_path / "d.sqlite")
    ids = _seed_diary(db)
    authorizer = ActionRecordingAuthorizer()
    invoke, planned = DIARY_OPERATIONS[name]

    invoke(_diary_service(db, authorizer), ids)

    assert authorizer.home_calls == 1, (name, authorizer.home_calls)
    assert authorizer.actions == planned, (name, authorizer.actions)


@pytest.mark.parametrize("name", sorted(DIARY_OPERATIONS))
def test_every_diary_operation_survives_a_replay_aware_home(tmp_path, name):
    db = str(tmp_path / "d.sqlite")
    ids = _seed_diary(db)
    authorizer = ReplayAwareAuthorizer(allow=True)

    DIARY_OPERATIONS[name][0](_diary_service(db, authorizer), ids)  # must not raise

    assert authorizer.home_calls == 1, name


# ==========================================================================
# THE INVENTORY — every person-sensitive PROFILE operation
# ==========================================================================

PROFILE_WIRE = {"birth_date": "1986-03-10", "sex": "MALE", "height_cm": "180",
                "weight_kg": "82", "activity_pal": "1.6"}


def _profile_service(db, authorizer):
    return ProfileService(SqliteProfileStore(db), authorizer=authorizer)


def _seed_profile(db) -> dict:
    """An open draft, made outside the operation under test."""
    seeding = _profile_service(db, AllowAllAuthorizer())
    return {"draft": seeding.propose_profile("seed-token", SUBJECT, PROFILE_WIRE)["draft_id"]}


#: method -> (invocation, the exact actions its ONE Home request must ask about)
PROFILE_OPERATIONS = {
    "get_profile_view": (
        lambda p, ids: p.get_profile_view(SESSION, SUBJECT), ["VIEW"]),
    "propose_profile": (
        lambda p, ids: p.propose_profile(SESSION, SUBJECT, {"weight_kg": "80"}),
        ["UPDATE", "VIEW"]),
    "confirm_profile": (
        lambda p, ids: p.confirm_profile(SESSION, SUBJECT, ids["draft"]), ["UPDATE", "VIEW"]),
}


def _authorizing_profile_methods() -> set[str]:
    """Public ProfileService methods that authorize, found in the SOURCE, not a list."""
    import ast
    import pathlib

    from app.profile import service as profile_module

    tree = ast.parse(pathlib.Path(profile_module.__file__).read_text(encoding="utf-8"))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProfileService"
    )
    return {
        node.name
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "_authorize"
            for call in ast.walk(node)
        )
    }


def test_every_authorizing_profile_method_is_covered():
    discovered = _authorizing_profile_methods()
    assert discovered, "discovery found no authorizing profile methods — the walker is broken"
    assert discovered == set(PROFILE_OPERATIONS), (
        f"profile inventory drifted: missing {sorted(discovered - set(PROFILE_OPERATIONS))}, "
        f"stale {sorted(set(PROFILE_OPERATIONS) - discovered)}"
    )


@pytest.mark.parametrize("name", sorted(PROFILE_OPERATIONS))
def test_one_home_request_per_profile_operation_with_its_planned_actions(tmp_path, name):
    db = str(tmp_path / "p.sqlite")
    ids = _seed_profile(db)
    authorizer = ActionRecordingAuthorizer()
    invoke, planned = PROFILE_OPERATIONS[name]

    invoke(_profile_service(db, authorizer), ids)

    assert authorizer.home_calls == 1, (name, authorizer.home_calls)
    assert authorizer.actions == planned, (name, authorizer.actions)


@pytest.mark.parametrize("name", sorted(PROFILE_OPERATIONS))
def test_every_profile_operation_survives_a_replay_aware_home(tmp_path, name):
    db = str(tmp_path / "p.sqlite")
    ids = _seed_profile(db)
    authorizer = ReplayAwareAuthorizer(allow=True)

    PROFILE_OPERATIONS[name][0](_profile_service(db, authorizer), ids)  # must not raise

    assert authorizer.home_calls == 1, name


@pytest.mark.parametrize("name", sorted(SERVICE_OPERATIONS))
def test_one_home_request_per_service_operation(repo, name):
    """THE REGRESSION: every operation, not a sample of four."""
    authorizer = AllowAllAuthorizer()
    service = _service(repo, authorizer)

    SERVICE_OPERATIONS[name](service, repo)

    assert authorizer.home_calls == 1, (
        f"{name}: expected exactly 1 delegated Home request, "
        f"got {authorizer.home_calls}"
    )


@pytest.mark.parametrize("name", sorted(SERVICE_OPERATIONS))
def test_every_service_operation_survives_a_replay_aware_home(repo, name):
    """The real constraint: one delegation, single-use, must be enough.

    ``AllowAllAuthorizer`` counts calls but would happily allow a second one. This
    models production, where the second use of a token is refused — so an operation
    that authorizes twice raises PermissionError here.
    """
    authorizer = ReplayAwareAuthorizer(allow=True)
    service = _service(repo, authorizer)

    SERVICE_OPERATIONS[name](service, repo)  # must not raise

    assert authorizer.home_calls == 1, name


# ==========================================================================
# THE INVENTORY — every person-sensitive HTTP route
# ==========================================================================

#: path -> (method, kwargs) invoking exactly one business operation.
ROUTE_OPERATIONS = {
    "/profile/{person_id}": ("get", {"url": f"/profile/{SUBJECT}"}),
    "PUT /profile/{person_id}": (
        "put",
        {"url": f"/profile/{SUBJECT}", "json": {"context": "GENERAL"}},
    ),
    "/daily/{person_id}/{date}": ("get", {"url": f"/daily/{SUBJECT}/{DATE}"}),
    "/gap-v2/{person_id}/{date}": ("get", {"url": f"/gap-v2/{SUBJECT}/{DATE}"}),
    "/intake/{person_id}/planned": (
        "post",
        {
            "url": f"/intake/{SUBJECT}/planned",
            "params": {"date": DATE},
            "json": [{"food_id": "syn-yogurt", "grams": 50}],
        },
    ),
    "/intake/{person_id}/actual": (
        "post",
        {
            "url": f"/intake/{SUBJECT}/actual",
            "params": {"date": DATE},
            "json": [{"food_id": "syn-yogurt", "grams": 50}],
        },
    ),
    "/intake/{person_id}/ate-as-planned": (
        "post",
        {
            "url": f"/intake/{SUBJECT}/ate-as-planned",
            "params": {"date": DATE, "planned_id": "SEEDED"},
        },
    ),
    "/profile/{person_id}/pregnancy": (
        "post",
        {"url": f"/profile/{SUBJECT}/pregnancy", "json": {"stage": "T2"}},
    ),
    "/plan/{person_id}": (
        "post",
        {
            "url": f"/plan/{SUBJECT}",
            "json": [
                {"label": "b", "foods": [{"food_id": "syn-yogurt", "grams": 40}]}
            ],
        },
    ),
    "/mealplan/{start}/{end}": (
        "get",
        {"url": f"/mealplan/{DATE}/{DATE}", "params": {"subject_person_id": SUBJECT}},
    ),
    # ---- diary (ids in braces are filled from the seeded entry and draft) ----
    "/diary/{person_id}/drafts": (
        "post", {"url": f"/diary/{SUBJECT}/drafts", "json": {"items": [COLA]}}),
    "/diary/{person_id}/drafts/{draft_id}/confirm": (
        "post", {"url": f"/diary/{SUBJECT}/drafts/{{draft}}/confirm"}),
    "/diary/{person_id}/entries/{entry_id}/revisions": (
        "post",
        {"url": f"/diary/{SUBJECT}/entries/{{entry}}/revisions", "json": {"items": [COLA]}}),
    "/diary/{person_id}/entries/{entry_id}/void": (
        "post", {"url": f"/diary/{SUBJECT}/entries/{{entry}}/void"}),
    "/diary/{person_id}/entries/{entry_id}": (
        "get", {"url": f"/diary/{SUBJECT}/entries/{{entry}}"}),
    "/diary/{person_id}/days/{date}": ("get", {"url": f"/diary/{SUBJECT}/days/{DATE}"}),
    "/diary/{person_id}/days/today": ("get", {"url": f"/diary/{SUBJECT}/days/today"}),
    "/diary/{person_id}/days/{date}/close": (
        "post", {"url": f"/diary/{SUBJECT}/days/{DATE}/close"}),
    "/diary/{person_id}/days/today/close": (
        "post", {"url": f"/diary/{SUBJECT}/days/today/close"}),
    "/profile/{person_id}/mode": (
        "put", {"url": f"/profile/{SUBJECT}/mode", "json": {"mode": "GENERAL"}}),
    "/diary/{person_id}/period": ("get", {"url": f"/diary/{SUBJECT}/period"}),
}

#: diary route -> the DiaryService method it must reach (its actions are in DIARY_OPERATIONS)
DIARY_ROUTE_METHODS = {
    "/diary/{person_id}/drafts": "propose_intake",
    "/diary/{person_id}/drafts/{draft_id}/confirm": "confirm_intake",
    "/diary/{person_id}/entries/{entry_id}/revisions": "correct_intake",
    "/diary/{person_id}/entries/{entry_id}/void": "void_intake",
    "/diary/{person_id}/entries/{entry_id}": "get_entry",
    "/diary/{person_id}/days/{date}": "get_day_summary",
    "/diary/{person_id}/days/today": "get_day_summary",
    "/diary/{person_id}/days/{date}/close": "close_day",
    "/diary/{person_id}/days/today/close": "close_day",
    "/profile/{person_id}/mode": "set_mode",
    "/diary/{person_id}/period": "get_period_summary",
}

#: profile route -> the ProfileService method it must reach (actions are in PROFILE_OPERATIONS)
PROFILE_ROUTE_METHODS = {
    "/profile/{person_id}": "get_profile_view",
}


@pytest.fixture
def http(monkeypatch, tmp_path):
    """The real FastAPI app over a real service, with a counting authorizer."""
    monkeypatch.setenv("NUTRITION_DB", str(tmp_path / "http.sqlite"))
    monkeypatch.setenv("FOOD_PROVIDER", "synthetic")
    monkeypatch.setenv("HOME_CONTROL_PLANE_URL", "https://home.invalid")
    monkeypatch.setenv("HOME_API_KEY", "test-key")
    monkeypatch.setenv("HOME_API_SECRET", "test-secret")
    for name in ("app.mcp.server", "app.main", "app.deps", "app.session"):
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")

    repository = SqliteNutritionRepository(str(tmp_path / "http.sqlite"))
    authorizer = ActionRecordingAuthorizer()
    main.svc = NutritionService(
        repository, SyntheticFoodProvider(), authorizer=authorizer
    )
    main.diary = _diary_service(str(tmp_path / "http.sqlite"), authorizer)
    main.profile = _profile_service(str(tmp_path / "http.sqlite"), authorizer)
    planned_id = _seed_planned(main.svc, repository)
    main.seeded_diary = _seed_diary(str(tmp_path / "http.sqlite"))
    authorizer.home_calls = 0  # seeding is setup, not the operation under test
    authorizer.delegations.clear()
    authorizer.actions.clear()
    return main, authorizer, planned_id


def _person_sensitive_routes(app) -> set[str]:
    """Routes whose handler reaches an authorizing service method, from the SOURCE."""
    import ast
    import pathlib

    from app import main as main_module

    authorizing = (_authorizing_service_methods() | _authorizing_diary_methods()
                   | _authorizing_profile_methods())
    tree = ast.parse(pathlib.Path(main_module.__file__).read_text(encoding="utf-8"))
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [ast.unparse(d) for d in node.decorator_list]
        route = next((d for d in decorators if d.startswith("app.")), None)
        if route is None:
            continue
        calls = {
            call.func.attr
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in authorizing
        }
        if calls:
            verb = route.split("(")[0].split(".")[1].upper()
            path = route.split("'")[1] if "'" in route else route
            routes.add(f"{verb} {path}")
    return routes


def test_every_person_sensitive_route_is_covered(http):
    """The HTTP inventory must not drift either."""
    main, _, _ = http
    discovered = _person_sensitive_routes(main.app)
    assert discovered, "discovery found no person-sensitive routes"

    covered = set()
    for key in ROUTE_OPERATIONS:
        covered.add(key if key.startswith(("GET ", "PUT ", "POST ")) else f"GET {key}")
        covered.add(f"POST {key}")
        covered.add(f"PUT {key}")
        covered.add(key)

    normalized = set()
    for route in discovered:
        verb, path = route.split(" ", 1)
        normalized.add(path if f"{verb} {path}" not in ROUTE_OPERATIONS else f"{verb} {path}")

    missing = {
        route
        for route in discovered
        if route.split(" ", 1)[1] not in ROUTE_OPERATIONS
        and route not in ROUTE_OPERATIONS
    }
    assert not missing, f"person-sensitive routes with no one-request test: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(ROUTE_OPERATIONS))
def test_one_home_request_per_http_request(http, name):
    """One incoming HTTP request -> exactly one delegated Home request."""
    main, authorizer, planned_id = http
    verb, kwargs = ROUTE_OPERATIONS[name]
    kwargs = dict(kwargs)
    if kwargs.get("params", {}).get("planned_id") == "SEEDED":
        kwargs["params"] = {**kwargs["params"], "planned_id": planned_id}
    if "{" in kwargs["url"]:
        kwargs["url"] = kwargs["url"].format(**main.seeded_diary)

    client = TestClient(main.app, raise_server_exceptions=False)
    response = getattr(client, verb)(
        **kwargs, headers={DELEGATION_HEADER: SESSION}
    )

    assert response.status_code < 500, (name, response.status_code, response.text)
    assert authorizer.home_calls == 1, (
        f"{name}: expected exactly 1 delegated Home request, "
        f"got {authorizer.home_calls}"
    )
    if name in DIARY_ROUTE_METHODS:
        assert response.status_code == 200, (name, response.status_code, response.text)
        assert authorizer.actions == DIARY_OPERATIONS[DIARY_ROUTE_METHODS[name]][1], name
    if name in PROFILE_ROUTE_METHODS:
        # no profile yet is a 404, but the ONE Home request was still made
        assert response.status_code in (200, 404), (name, response.status_code, response.text)
        assert authorizer.actions == PROFILE_OPERATIONS[PROFILE_ROUTE_METHODS[name]][1], name


def test_every_diary_route_maps_to_a_diary_operation(http):
    main, _, _ = http
    discovered = {
        route.split(" ", 1)[1]
        for route in _person_sensitive_routes(main.app)
        if route.split(" ", 1)[1] in DIARY_ROUTE_METHODS
    }
    assert discovered == set(DIARY_ROUTE_METHODS), sorted(set(DIARY_ROUTE_METHODS) - discovered)
    assert set(DIARY_ROUTE_METHODS.values()) == set(DIARY_OPERATIONS)


def test_every_profile_route_maps_to_a_profile_operation(http):
    main, _, _ = http
    discovered = {
        route.split(" ", 1)[1]
        for route in _person_sensitive_routes(main.app)
        if route.split(" ", 1)[1] in PROFILE_ROUTE_METHODS
    }
    assert discovered == set(PROFILE_ROUTE_METHODS), sorted(set(PROFILE_ROUTE_METHODS) - discovered)
    # the other profile operations are agent-only (MCP); see PROFILE_TOOL_METHODS
    assert {"get_profile_view"} <= set(PROFILE_ROUTE_METHODS.values()) <= set(PROFILE_OPERATIONS)


# ==========================================================================
# THE INVENTORY — every person-sensitive MCP tool
# ==========================================================================


def _mcp_tools(mcp_server):
    """Tool functions across fastmcp versions (2.x wraps in .fn, 4.x does not)."""
    tools = {}
    for name, value in vars(mcp_server).items():
        if name.startswith("_"):
            continue
        fn = getattr(value, "fn", None)
        if fn is None and inspect.isfunction(value) and value.__module__ == mcp_server.__name__:
            fn = value
        if fn is not None and callable(fn):
            tools[name] = fn
    return tools


MCP_OPERATIONS = {
    "get_nutrition_profile": lambda t, pid: t["get_nutrition_profile"](SUBJECT),
    "get_pregnancy_profile": lambda t, pid: t["get_pregnancy_profile"](SUBJECT),
    "get_daily_nutrition_gap": lambda t, pid: t["get_daily_nutrition_gap"](SUBJECT, DATE),
    "record_planned_meal": lambda t, pid: t["record_planned_meal"](
        SUBJECT, DATE, [{"food_id": "syn-yogurt", "grams": 50}]
    ),
    "record_actual_intake": lambda t, pid: t["record_actual_intake"](
        SUBJECT, DATE, [{"food_id": "syn-yogurt", "grams": 50}]
    ),
    "ate_as_planned": lambda t, pid: t["ate_as_planned"](SUBJECT, DATE, pid),
    "plan_menu": lambda t, pid: t["plan_menu"](
        SUBJECT, [{"label": "b", "foods": [{"food_id": "syn-yogurt", "grams": 40}]}]
    ),
    "get_meal_plan": lambda t, pid: t["get_meal_plan"](SUBJECT, DATE, DATE),
    # ---- diary ----
    "propose_intake": lambda t, pid: t["propose_intake"](SUBJECT, [COLA]),
    "confirm_intake": lambda t, pid: t["confirm_intake"](SUBJECT, t["_ids"]["draft"]),
    "correct_intake": lambda t, pid: t["correct_intake"](SUBJECT, t["_ids"]["entry"], [COLA]),
    "void_intake": lambda t, pid: t["void_intake"](SUBJECT, t["_ids"]["entry"]),
    "get_diary_entry": lambda t, pid: t["get_diary_entry"](SUBJECT, t["_ids"]["entry"]),
    "get_day_summary": lambda t, pid: t["get_day_summary"](SUBJECT, DATE),
    "close_day": lambda t, pid: t["close_day"](SUBJECT, DATE),
    "set_nutrition_mode": lambda t, pid: t["set_nutrition_mode"](SUBJECT, "GENERAL"),
    "get_period_summary": lambda t, pid: t["get_period_summary"](SUBJECT),
    # ---- profile ----
    "propose_profile": lambda t, pid: t["propose_profile"](SUBJECT, {"weight_kg": "80"}),
    "confirm_profile": lambda t, pid: t["confirm_profile"](
        SUBJECT, t["_profile_ids"]["draft"]),
}

#: diary tool -> the DiaryService method it must reach
DIARY_TOOL_METHODS = {
    "propose_intake": "propose_intake",
    "confirm_intake": "confirm_intake",
    "correct_intake": "correct_intake",
    "void_intake": "void_intake",
    "get_diary_entry": "get_entry",
    "get_day_summary": "get_day_summary",
    "close_day": "close_day",
    "set_nutrition_mode": "set_mode",
    "get_period_summary": "get_period_summary",
}

#: profile tool -> the ProfileService method it must reach
PROFILE_TOOL_METHODS = {
    "get_nutrition_profile": "get_profile_view",
    "get_pregnancy_profile": "get_profile_view",
    "propose_profile": "propose_profile",
    "confirm_profile": "confirm_profile",
}


@pytest.fixture
def mcp(monkeypatch, tmp_path):
    monkeypatch.setenv("NUTRITION_DB", str(tmp_path / "mcp.sqlite"))
    monkeypatch.setenv("FOOD_PROVIDER", "synthetic")
    monkeypatch.setenv("HOME_CONTROL_PLANE_URL", "https://home.invalid")
    monkeypatch.setenv("HOME_API_KEY", "test-key")
    monkeypatch.setenv("HOME_API_SECRET", "test-secret")
    for name in ("app.mcp.server", "app.main", "app.deps", "app.session"):
        sys.modules.pop(name, None)
    mcp_server = importlib.import_module("app.mcp.server")
    session_module = importlib.import_module("app.session")

    repository = SqliteNutritionRepository(str(tmp_path / "mcp.sqlite"))
    authorizer = ActionRecordingAuthorizer()
    mcp_server._svc = NutritionService(
        repository, SyntheticFoodProvider(), authorizer=authorizer
    )
    mcp_server._diary = _diary_service(str(tmp_path / "mcp.sqlite"), authorizer)
    mcp_server._profile = _profile_service(str(tmp_path / "mcp.sqlite"), authorizer)
    planned_id = _seed_planned(mcp_server._svc, repository)
    diary_ids = _seed_diary(str(tmp_path / "mcp.sqlite"))
    authorizer.home_calls = 0
    authorizer.delegations.clear()
    authorizer.actions.clear()

    # The delegated session arrives by transport; supply it the way the seam reads it.
    monkeypatch.setattr(
        session_module, "current_delegation", lambda: SESSION, raising=False
    )
    monkeypatch.setattr(mcp_server, "current_delegation", lambda: SESSION)
    tools = _mcp_tools(mcp_server)
    tools["_ids"] = diary_ids
    tools["_profile_ids"] = _seed_profile(str(tmp_path / "mcp.sqlite"))
    return tools, authorizer, planned_id


def test_every_person_sensitive_mcp_tool_is_covered(mcp):
    """Any tool reaching an authorizing service method must be in MCP_OPERATIONS."""
    import ast
    import pathlib

    from app.mcp import server as mcp_module

    authorizing = (_authorizing_service_methods() | _authorizing_diary_methods()
                   | _authorizing_profile_methods())
    tree = ast.parse(pathlib.Path(mcp_module.__file__).read_text(encoding="utf-8"))
    discovered = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(ast.unparse(d).startswith("mcp.") for d in node.decorator_list):
            continue
        if any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in authorizing
            for call in ast.walk(node)
        ):
            discovered.add(node.name)

    assert discovered, "discovery found no person-sensitive MCP tools"
    missing = discovered - set(MCP_OPERATIONS)
    assert not missing, f"MCP tools with no one-request test: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(MCP_OPERATIONS))
def test_one_home_request_per_mcp_tool_call(mcp, name):
    """One tool call -> exactly one delegated Home request."""
    tools, authorizer, planned_id = mcp

    MCP_OPERATIONS[name](tools, planned_id)

    assert authorizer.home_calls == 1, (
        f"{name}: expected exactly 1 delegated Home request, "
        f"got {authorizer.home_calls}"
    )
    if name in DIARY_TOOL_METHODS:
        assert authorizer.actions == DIARY_OPERATIONS[DIARY_TOOL_METHODS[name]][1], name
    if name in PROFILE_TOOL_METHODS:
        assert authorizer.actions == PROFILE_OPERATIONS[PROFILE_TOOL_METHODS[name]][1], name


def test_every_diary_tool_maps_to_a_diary_operation(mcp):
    tools, _, _ = mcp
    assert set(DIARY_TOOL_METHODS) <= set(tools)
    assert set(DIARY_TOOL_METHODS.values()) == set(DIARY_OPERATIONS)


def test_every_profile_tool_maps_to_a_profile_operation(mcp):
    tools, _, _ = mcp
    assert set(PROFILE_TOOL_METHODS) <= set(tools)
    assert set(PROFILE_TOOL_METHODS.values()) == set(PROFILE_OPERATIONS)


# ==========================================================================
# The fixed operations specifically, and the shape of their one request
# ==========================================================================


def test_ate_as_planned_asks_for_view_and_create_in_one_request(repo):
    """Both permissions, one request — not CREATE alone, not two requests."""
    authorizer = AllowAllAuthorizer()
    service = _service(repo, authorizer)
    planned_id = _seed_planned(service, repo)
    authorizer.home_calls = 0
    authorizer.requirements.clear()

    service.ate_as_planned(SESSION, SUBJECT, DATE, planned_id)

    assert authorizer.home_calls == 1
    assert authorizer.requirements == [(("NUTRITION", "VIEW"), ("NUTRITION", "CREATE"))]


def test_ate_as_planned_denied_when_either_permission_is_refused(repo):
    """An overall allow requires EVERY requirement to allow."""

    class ViewOnly:
        def __init__(self):
            self.home_calls = 0

        def check_access(self, subject, domain, action, delegation=None):
            self.home_calls += 1
            return AccessDecision(action == "VIEW", "only VIEW granted")

        def check_access_many(self, subject, requirements, delegation=None):
            self.home_calls += 1
            allowed = all(action == "VIEW" for _, action in requirements)
            return AccessDecision(allowed, "only VIEW granted (fail closed)")

    authorizer = ViewOnly()
    seeded = _seed_planned(_service(repo, AllowAllAuthorizer()), repo)

    with pytest.raises(PermissionError):
        _service(repo, authorizer).ate_as_planned(SESSION, SUBJECT, DATE, seeded)
    assert authorizer.home_calls == 1


def test_ate_as_planned_authorizes_before_reading_the_plan(repo):
    """A denial must happen before any sensitive read."""
    seeded = _seed_planned(_service(repo, AllowAllAuthorizer()), repo)
    reads = {"count": 0}
    original = repo.list_intake

    def counting(*args, **kwargs):
        reads["count"] += 1
        return original(*args, **kwargs)

    repo.list_intake = counting

    from tests.support import DenyAllAuthorizer

    with pytest.raises(PermissionError):
        _service(repo, DenyAllAuthorizer()).ate_as_planned(
            SESSION, SUBJECT, DATE, seeded
        )
    assert reads["count"] == 0


def test_daily_composes_internally_rather_than_calling_authorized_methods(repo):
    """The /daily fix: one VIEW, then internal helpers — not two public calls."""
    authorizer = AllowAllAuthorizer()
    service = _service(repo, authorizer)

    result = service.daily(SESSION, SUBJECT, DATE)

    assert authorizer.home_calls == 1
    assert set(result) == {"intake", "gap"}
    # The composite must return what the two public methods would have returned.
    fresh_a, fresh_b = AllowAllAuthorizer(), AllowAllAuthorizer()
    assert result["intake"] == _service(repo, fresh_a).daily_intake(
        SESSION, SUBJECT, DATE
    )
    assert result["gap"] == _service(repo, fresh_b).daily_gap(SESSION, SUBJECT, DATE)


def test_daily_survives_a_single_use_delegation(repo):
    """The production symptom: the old composition was replay-denied."""
    authorizer = ReplayAwareAuthorizer(allow=True)
    _service(repo, authorizer).daily(SESSION, SUBJECT, DATE)
    assert authorizer.home_calls == 1


def test_the_old_daily_composition_would_be_replay_denied(repo):
    """Reverting /daily to two authorized calls reproduces the failure."""
    authorizer = ReplayAwareAuthorizer(allow=True)
    service = _service(repo, authorizer)

    service.daily_intake(SESSION, SUBJECT, DATE)  # spends the delegation
    with pytest.raises(PermissionError, match="replay"):
        service.daily_gap(SESSION, SUBJECT, DATE)


def test_the_old_ate_as_planned_composition_would_be_replay_denied(repo):
    """Reverting ate_as_planned to VIEW-then-CREATE reproduces the failure."""
    authorizer = ReplayAwareAuthorizer(allow=True)

    first = authorizer.check_access(SUBJECT, "NUTRITION", "VIEW", SESSION)
    assert first.allow
    second = authorizer.check_access(SUBJECT, "NUTRITION", "CREATE", SESSION)
    assert not second.allow
    assert "replay" in second.reason


# ==========================================================================
# Replay protection is not weakened
# ==========================================================================


def test_a_delegation_is_still_single_use_across_operations(repo):
    """Two operations on one token: the second is still refused."""
    authorizer = ReplayAwareAuthorizer(allow=True)
    service = _service(repo, authorizer)

    service.get_profile(SESSION, SUBJECT)
    with pytest.raises(PermissionError, match="replay"):
        service.daily(SESSION, SUBJECT, DATE)


def test_check_access_many_still_requires_a_session(repo):
    """No delegation is a denial, not a bypass into the multi-requirement path."""
    authorizer = AllowAllAuthorizer()
    seeded = _seed_planned(_service(repo, AllowAllAuthorizer()), repo)

    with pytest.raises(PermissionError):
        _service(repo, authorizer).ate_as_planned(None, SUBJECT, DATE, seeded)


def test_no_service_method_accepts_an_actor():
    """Unchanged by this PR, asserted so it stays that way."""
    forbidden = {"actor", "actor_person_id", "actor_id", "human_actor"}
    for name, fn in inspect.getmembers(NutritionService, inspect.isfunction):
        if name.startswith("_"):
            continue
        assert not (set(inspect.signature(fn).parameters) & forbidden), name


def test_require_all_takes_no_actor():
    params = set(inspect.signature(NutritionService._require_all).parameters)
    assert params == {"self", "delegation", "subject_person_id", "actions"}
