# Home F3b Nutrition Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Home Hub server a safe, typed, single-call way to read one Person's Nutrition profile summary, delivered as three ordered PRs (F3b.1 Home, F3b.2 Nutrition, F3b.3 Hub).

**Architecture:** Home adds a subject-existence guard at its single policy function and accepts a `svc-nutrition` delegation only from Nutrition's machine credential, and only at the policy entry points. Nutrition classifies Home's answer into ALLOW / DENY / SESSION_INVALID / UNAVAILABLE and returns fixed 403 / 401 / 503 bodies. The Hub gets a pure, injectable loader that mints one delegation, makes one Nutrition call, and strictly maps the response to `DataEnvelope<ProfileSummary>`, plus a narrow pasta forward for port 9930.

**Tech Stack:** Frappe app (Python 3.11, pytest with a fake `frappe` module); FastAPI + httpx (pytest, `httpx.MockTransport`, `TestClient`); Next.js 16 / TypeScript (`node --test` with `--experimental-strip-types`); rootless Podman Quadlet with pasta.

**Spec:** `docs/superpowers/specs/2026-10-05-home-f3b-nutrition-adapter-design.md` (Rev 2). Read it before starting any task.

## Global Constraints

- No actor, domain, or action is accepted from any caller; the subject comes only from a validated `F3ActiveContext`.
- Exactly one delegation mint and one Home policy request per profile read.
- No decision or domain-data cache anywhere; `cache: 'no-store'` on every Hub fetch.
- Delegations never carry a Person ID, never reach a browser, envelope, log, URL query, or retry.
- Missing subject and unauthorized subject must be indistinguishable to callers: `{"allow": False, "reason": "no consent grant (fail closed)"}`.
- Nutrition response bodies: 401 `{"detail": "SESSION_INVALID"}`, 403 `{"detail": "ACCESS_DENIED"}`, 503 `{"detail": "SERVICE_UNAVAILABLE"}`, 404 `{"detail": "no profile"}`. No Home reason text in any body.
- `reason` is mandatory (non-empty string) for a Home decision to be well-formed; its wording is never interpreted.
- Site-config key: `home_nutrition_machine_user`. Audiences: `home-control-plane`, `svc-nutrition`.
- Hub env var: `HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930`. Quadlet network: `Network=pasta:-T,9933,-T,9930` (confirmed by R3 step 1 before merge).
- No production Persons, grants, profiles, or fixtures are created. Production deploys are run by the operator.
- F3b is independent of Knowledge/KAP and Ambient Bento; touch nothing in those areas.
- Commit messages follow `.claude/rules/git-and-branching.md` and end with the session trailer `Claude-Session: https://claude.ai/code/session_013mMVjRsZ3JmCrKYvM6shvf`.

## Review Focus

1. **Real pregnancy profile with string targets** — `targets` values like `"1000"` must map to `PRESENT`, not `INVALID_RESPONSE`. Pinned by Task 9's string-target test.
2. **`HOME_HUB_NUTRITION_BASE_URL` missing at build or start** — `next.config.ts` validates config during `npm run build`, so the Dockerfile builder stage must set it, and the runtime Quadlet must set it before the new image starts. Pinned by Task 8's Dockerfile and production-config tests and the R3 three-line diff rule.
3. **Existing `home-control-plane` delegations after F3b.1** (Hermes, Home MCP) — must still work for every Home method. Pinned by Task 4's "control-plane actor accepted by non-policy methods" test and the R1 regression step.
4. **BFF `/delegation` with extra fields or a different audience** — extra fields are ignored; a wrong or missing audience is `INVALID_RESPONSE` with no Nutrition call. Pinned by Task 10's mint tests.
5. **Home 401/403 caused by a broken Nutrition credential rather than the user** — surfaces as `SESSION_INVALID`, and the operator sees the `home_rejected_credential_or_session` log category. Pinned by Task 6's logging test.

## Branches and PRs

| PR | Branch | Base | Contains |
| --- | --- | --- | --- |
| F3b.1 | `feature/home-f3b1-subject-guard` | `feature/home-f3b-nutrition-adapter` (spec + plan commits) | Tasks 1–5; spec and plan land with it |
| F3b.2 | `feature/home-f3b2-nutrition-outcomes` | `origin/main` after F3b.1 merges | Tasks 6–7 |
| F3b.3 | `feature/home-f3b3-hub-nutrition-adapter` | `origin/main` after F3b.2 is deployed | Tasks 8–12 |

Each PR is opened only after its tasks pass locally. The next PR's live rollout starts only after the previous gate (R1, R2) passes.

## File map

**F3b.1 (Home, `apps/episteck_home/`)**
- Modify `episteck_home/policy/wrappers.py` — subject-existence guard and input validation order.
- Modify `episteck_home/identity/delegation.py` — `verify` accepts a set of audiences.
- Modify `episteck_home/identity/auth_hook.py` — caller-bound accepted audiences; record the bound audience.
- Modify `episteck_home/identity/actor.py` — `accept_audiences` on `resolve_principals`/`resolve_actor`; audience constants.
- Modify `episteck_home/api.py` — policy entry points accept `POLICY_AUDIENCES`.
- Create `tests/test_policy_boundary.py`; modify `tests/test_delegation.py`, `tests/test_auth_hook.py`, `tests/test_home_api_security.py`.
- Modify `docs/architecture/DEPLOYMENT.md`, `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md`.

**F3b.2 (Nutrition, `services/nutrition/`)**
- Modify `app/home_control/client.py` — outcome field, classification, logging.
- Modify `app/service.py` — typed refusal exceptions.
- Modify `app/main.py` — fixed HTTP mapping.
- Modify `tests/support.py`, `tests/test_home_control_client.py`; create `tests/test_policy_outcomes.py`.

**F3b.3 (Hub, `apps/home-hub/`, `deploy/home-hub/`)**
- Modify `src/integration/home/server-config.ts`, `src/integration/home/configuration.test.ts`, `test-support/verify-production-startup-config.mjs`, `test-support/verify-server-only-client-import.mjs`, `playwright.config.ts`, `Dockerfile` (builder-stage build variable).
- Create `src/integration/nutrition/profile-contract.ts` + `.test.ts`, `profile-loader.ts` + `.test.ts`, `profile.server.ts`.
- Modify `deploy/home-hub/svc-home-hub.container`, `deploy/home-hub/tests/test_home_hub_quadlet.py`, `deploy/home-hub/README.md`.

**Test commands**
- Home: from `apps/episteck_home`: `python -m pytest tests -q`
- Nutrition: from `services/nutrition`: `python -m pytest tests -q`
- Hub: from `apps/home-hub`: `npm test -- <file>`; full `npm test`, `npm run test:server-boundary`, `npm run test:startup-config`, `npm run build`
- Quadlet: from the repo root: `python -m pytest deploy/home-hub/tests -q`

---

# PR F3b.1 — Home subject-existence guard and audience binding

### Task 0: Create the F3b.1 branch

- [ ] **Step 1: Branch from the spec/plan branch**

```bash
cd C:/AIPROJECTS/episteck-delivery-workspace/.worktrees/home-f3b-nutrition-adapter
git fetch origin
git switch -c feature/home-f3b1-subject-guard
git log --oneline -3   # expect the spec and plan commits on top of 6d4e361
```

### Task 1: Subject-existence guard in the policy wrapper

**Files:**
- Modify: `apps/episteck_home/episteck_home/policy/wrappers.py`
- Modify: `apps/episteck_home/tests/test_home_api_security.py` (fake `utils.now_datetime`)
- Create: `apps/episteck_home/tests/test_policy_boundary.py`

**Interfaces:**
- Consumes: `policy.access.can_access`, `DOMAINS`, `ACTIONS`.
- Produces: `wrappers.check_access(actor_person_id, subject_person_id, domain, action) -> dict` (unchanged signature) and `wrappers._subject_exists(subject_person_id) -> bool`.

- [ ] **Step 1: Give the shared fake frappe a real clock**

In `tests/test_home_api_security.py`, add `from datetime import datetime` to the imports and extend the fake utils inside `_make_fake_frappe`:

```python
    fake.utils = SimpleNamespace(
        today=lambda: "2026-09-15",
        now=lambda: "2026-09-15 12:00:00",
        now_datetime=lambda: datetime(2026, 9, 15, 12, 0, 0),
    )
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_policy_boundary.py`:

```python
"""Home policy boundary: a positive decision requires a currently existing subject.

The guard lives in ``policy.wrappers.check_access``, the one function every Home
authorization path calls. A missing subject must be indistinguishable from an existing
subject with no consent, and an orphaned grant must never authorize.
"""
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.test_home_api_security import _make_fake_frappe

NOW = datetime(2026, 10, 6, 12, 0, 0)
NO_GRANT = {"allow": False, "reason": "no consent grant (fail closed)"}


def _grant(actor, subject, domain="NUTRITION", actions="VIEW", state="ACTIVE"):
    return {
        "actor_person": actor,
        "subject_person": subject,
        "domain": domain,
        "actions": actions,
        "state": state,
        "valid_from": None,
        "valid_until": None,
    }


@pytest.fixture
def policy(monkeypatch):
    fake = types.ModuleType("frappe")
    fake.people = {"PSN-ACTOR", "PSN-SUBJECT", "PSN-OTHER"}
    fake.grants = []
    fake.grant_loads = []
    fake.exists_calls = []
    fake.exists_error = None

    class _DB:
        def exists(self, doctype, name):
            assert doctype == "Person"
            fake.exists_calls.append(name)
            if fake.exists_error is not None:
                raise fake.exists_error
            return name if name in fake.people else None

    def get_all(doctype, filters=None, fields=None, **kwargs):
        assert doctype == "Consent Grant"
        fake.grant_loads.append(dict(filters))
        return [
            g for g in fake.grants
            if g["actor_person"] == filters["actor_person"]
            and g["subject_person"] == filters["subject_person"]
        ]

    fake.db = _DB()
    fake.get_all = get_all
    fake.utils = SimpleNamespace(now_datetime=lambda: NOW)
    fake.log_error = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "frappe", fake)
    sys.modules.pop("episteck_home.policy.wrappers", None)
    return importlib.import_module("episteck_home.policy.wrappers"), fake


def test_cross_subject_with_active_grant_allows(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")["allow"] is True


def test_cross_subject_without_grant_denies(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-OTHER", "NUTRITION", "VIEW") == NO_GRANT


def test_missing_subject_with_orphaned_grant_denies_without_loading_grants(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-GONE"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-GONE", "NUTRITION", "VIEW") == NO_GRANT
    assert fake.grant_loads == []


def test_missing_subject_is_indistinguishable_from_no_grant(policy):
    wrappers, _ = policy
    missing = wrappers.check_access("PSN-ACTOR", "PSN-GONE", "NUTRITION", "VIEW")
    existing = wrappers.check_access("PSN-ACTOR", "PSN-OTHER", "NUTRITION", "VIEW")
    assert missing == existing == NO_GRANT


def test_self_access_still_allows(policy):
    wrappers, _ = policy
    assert wrappers.check_access("PSN-ACTOR", "PSN-ACTOR", "NUTRITION", "VIEW")["allow"] is True


def test_subject_deleted_after_bootstrap_denies_on_the_next_check(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    assert wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")["allow"] is True
    fake.people.discard("PSN-SUBJECT")
    assert wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW") == NO_GRANT


def test_existence_lookup_failure_fails_closed(policy):
    wrappers, fake = policy
    fake.grants.append(_grant("PSN-ACTOR", "PSN-SUBJECT"))
    fake.exists_error = RuntimeError("db down")
    decision = wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")
    assert decision == {"allow": False, "reason": "policy error (fail closed)"}


def test_invalid_request_answer_does_not_reveal_existence(policy):
    wrappers, fake = policy
    missing = wrappers.check_access("PSN-ACTOR", "PSN-GONE", "NOT_A_DOMAIN", "VIEW")
    existing = wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NOT_A_DOMAIN", "VIEW")
    assert missing == existing
    assert missing["allow"] is False
    assert fake.exists_calls == []


def test_existence_is_checked_on_every_call(policy):
    wrappers, fake = policy
    wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")
    wrappers.check_access("PSN-ACTOR", "PSN-SUBJECT", "NUTRITION", "VIEW")
    assert fake.exists_calls == ["PSN-SUBJECT", "PSN-SUBJECT"]


# --- API level, with the real wrapper -------------------------------------


@pytest.fixture
def api_real_policy(monkeypatch):
    fake = _make_fake_frappe()
    monkeypatch.setitem(sys.modules, "frappe", fake)
    for module in (
        "episteck_home.policy.wrappers",
        "episteck_home.identity.actor",
        "episteck_home.identity.auth_hook",
        "episteck_home.api",
    ):
        sys.modules.pop(module, None)
    return importlib.import_module("episteck_home.api"), fake


def test_api_check_access_missing_subject_matches_no_grant(api_real_policy):
    api, _ = api_real_policy
    missing = api.check_access("PSN-GONE", "NUTRITION", "VIEW")
    existing = api.check_access("PSN-SUBJECT", "NUTRITION", "VIEW")
    assert missing == existing == NO_GRANT


def test_api_batch_missing_subject_has_no_positive_decision(api_real_policy):
    api, _ = api_real_policy
    requirements = [
        {"domain": "NUTRITION", "action": "VIEW"},
        {"domain": "NUTRITION", "action": "CREATE"},
    ]
    missing = api.check_access_many("PSN-GONE", requirements)
    existing = api.check_access_many("PSN-SUBJECT", requirements)
    assert missing["allow"] is False
    assert all(item["allow"] is False for item in missing["decisions"])
    assert missing == existing


def test_api_self_access_still_allows(api_real_policy):
    api, _ = api_real_policy
    assert api.check_access("PSN-ACTOR", "NUTRITION", "VIEW")["allow"] is True
```

- [ ] **Step 3: Run the tests to verify the guard tests fail**

Run: `python -m pytest tests/test_policy_boundary.py -v`
Expected: FAIL on `test_missing_subject_with_orphaned_grant_denies_without_loading_grants`, `test_subject_deleted_after_bootstrap_denies_on_the_next_check`, `test_existence_lookup_failure_fails_closed`, `test_existence_is_checked_on_every_call`, and `test_invalid_request_answer_does_not_reveal_existence` (no guard yet). The equality and API tests may already pass; they pin the contract.

- [ ] **Step 4: Implement the guard**

Replace the imports and `check_access` in `episteck_home/policy/wrappers.py`:

```python
from __future__ import annotations
import frappe
from .access import ACTIONS, DOMAINS, can_access, Grant

# The answer an EXISTING subject with no grants receives. A missing subject gets the
# same answer, so no caller can use authorization to learn whether a Person exists.
_NO_GRANT_REASON = "no consent grant (fail closed)"
```

```python
def _subject_exists(subject_person_id: str) -> bool:
    """Fresh read of the Person system of record. Never cached, not even per request."""
    return bool(frappe.db.exists("Person", subject_person_id))


def _is_valid_request(actor_person_id, subject_person_id, domain, action) -> bool:
    return (
        isinstance(actor_person_id, str) and bool(actor_person_id)
        and isinstance(subject_person_id, str) and bool(subject_person_id)
        and domain in DOMAINS
        and action in ACTIONS
    )


def check_access(actor_person_id: str, subject_person_id: str, domain: str, action: str) -> dict:
    """The one authorization entry point for the Control Plane. Fail-closed.

    Order matters:
      1. Invalid input is refused by the pure evaluator WITHOUT an existence lookup,
         so the invalid-input answer never depends on whether the subject exists.
      2. A positive decision requires that the subject Person exists now. A missing
         subject gets the same answer as an existing subject with no grants, and its
         grants are never loaded, so an orphaned grant cannot authorize.
      3. Grants are loaded and the pure evaluator decides.
    """
    try:
        now = frappe.utils.now_datetime().isoformat()
        if not _is_valid_request(actor_person_id, subject_person_id, domain, action):
            d = can_access(actor_person_id, subject_person_id, domain, action, grants=[], now=now)
            return {"allow": d.allow, "reason": d.reason}
        if not _subject_exists(subject_person_id):
            return {"allow": False, "reason": _NO_GRANT_REASON}
        grants = _load_grants(actor_person_id, subject_person_id)
        d = can_access(actor_person_id, subject_person_id, domain, action, grants=grants, now=now)
        return {"allow": d.allow, "reason": d.reason}
    except Exception as e:
        frappe.log_error(f"check_access error: {e}", "episteck_home.check_access")
        return {"allow": False, "reason": "policy error (fail closed)"}
```

- [ ] **Step 5: Run the boundary tests and the full Home suite**

Run: `python -m pytest tests/test_policy_boundary.py -v` → all PASS.
Run: `python -m pytest tests -q` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/episteck_home/episteck_home/policy/wrappers.py apps/episteck_home/tests/test_policy_boundary.py apps/episteck_home/tests/test_home_api_security.py
git commit -m "feat(home): require an existing subject before any allow"
```

### Task 2: `verify` accepts a set of audiences

**Files:**
- Modify: `apps/episteck_home/episteck_home/identity/delegation.py` (`verify`, lines ~94–150)
- Modify: `apps/episteck_home/tests/test_delegation.py`

**Interfaces:**
- Produces: `verify(token, *, secret, expected_issuer, expected_audience: str | frozenset[str] | set[str], now, seen_token_ids=None) -> VerificationResult`; `result.context.audience` is the token's audience.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_delegation.py`)

```python
NUTRITION = "svc-nutrition"
BOTH = frozenset({AUDIENCE, NUTRITION})


def test_audience_set_accepts_a_member():
    token = sign(_claims(aud=NUTRITION), SECRET)
    result = verify(token, secret=SECRET, expected_issuer=ISSUER, expected_audience=BOTH, now=NOW)
    assert result.valid
    assert result.context.audience == NUTRITION


def test_audience_set_rejects_a_non_member():
    token = sign(_claims(aud="svc-other"), SECRET)
    result = verify(token, secret=SECRET, expected_issuer=ISSUER, expected_audience=BOTH, now=NOW)
    assert not result.valid
    assert result.reason == "delegation audience mismatch (fail closed)"


def test_empty_audience_set_fails_closed():
    token = sign(_claims(), SECRET)
    result = verify(token, secret=SECRET, expected_issuer=ISSUER, expected_audience=frozenset(), now=NOW)
    assert not result.valid
    assert result.reason == "delegation unavailable (fail closed)"


def test_non_string_audience_claim_is_a_mismatch_not_an_error():
    token = sign(_claims(aud=[AUDIENCE]), SECRET)
    result = verify(token, secret=SECRET, expected_issuer=ISSUER, expected_audience=BOTH, now=NOW)
    assert not result.valid
    assert result.reason == "delegation audience mismatch (fail closed)"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_delegation.py -v -k "audience_set or empty_audience or non_string_audience"`
Expected: FAIL (a frozenset is not equal to the `aud` string; an empty set is truthy-false but the list-claim case may raise).

- [ ] **Step 3: Implement**

In `verify`, change the annotation to `expected_audience: str | frozenset[str] | set[str],` and replace the opening guard and the audience comparison:

```python
    allowed_audiences = (
        frozenset({expected_audience})
        if isinstance(expected_audience, str)
        else frozenset(expected_audience)
    )
    if (
        not token
        or not secret
        or not expected_issuer
        or not allowed_audiences
        or "" in allowed_audiences
    ):
        return _deny("delegation unavailable (fail closed)")
```

```python
    audience = claims["aud"]
    if not isinstance(audience, str) or audience not in allowed_audiences:
        return _deny("delegation audience mismatch (fail closed)")
```

Update the docstring with one line: "``expected_audience`` may be one audience or a set; the token's ``aud`` must be a member."

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_delegation.py -v` → PASS. Run: `python -m pytest tests -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/episteck_home/episteck_home/identity/delegation.py apps/episteck_home/tests/test_delegation.py
git commit -m "feat(home): let delegation verify accept a set of audiences"
```

### Task 3: Auth hook binds `svc-nutrition` only for Nutrition's machine caller

**Files:**
- Modify: `apps/episteck_home/episteck_home/identity/auth_hook.py`
- Modify: `apps/episteck_home/episteck_home/identity/actor.py` (constants only in this task)
- Modify: `apps/episteck_home/tests/test_auth_hook.py`

**Interfaces:**
- Consumes: Task 2's `verify(..., expected_audience=frozenset)`.
- Produces: `actor.CONTROL_PLANE_AUDIENCE = "home-control-plane"`, `actor.NUTRITION_AUDIENCE = "svc-nutrition"`; `frappe.local.episteck_delegation_audience` (`str | None`) set by the hook on every request.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_auth_hook.py`)

```python
NUTRITION_CALLER = "nutrition@example.invalid"


def _configure_nutrition_caller(fake):
    fake.conf["home_nutrition_machine_user"] = NUTRITION_CALLER


def test_nutrition_audience_binds_for_the_configured_nutrition_caller(hook):
    module, fake = hook
    _configure_nutrition_caller(fake)
    fake.session.user = NUTRITION_CALLER
    fake.headers["X-Episteck-Delegation"] = _token(aud="svc-nutrition", jti="tok-n1")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user == "person@example.invalid"
    assert fake.local.episteck_delegation_audience == "svc-nutrition"


def test_nutrition_audience_from_another_machine_caller_denies(hook):
    module, fake = hook
    _configure_nutrition_caller(fake)  # caller stays home-mcp@example.invalid
    fake.headers["X-Episteck-Delegation"] = _token(aud="svc-nutrition", jti="tok-n2")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_audience is None


def test_nutrition_audience_denies_when_nutrition_caller_is_not_configured(hook):
    module, fake = hook
    fake.session.user = NUTRITION_CALLER
    fake.headers["X-Episteck-Delegation"] = _token(aud="svc-nutrition", jti="tok-n3")
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_rejected_nutrition_token_does_not_burn_its_id(hook):
    module, fake = hook
    _configure_nutrition_caller(fake)
    fake.headers["X-Episteck-Delegation"] = _token(aud="svc-nutrition", jti="tok-n4")
    module.establish_delegated_context()  # presented by home-mcp: rejected
    assert fake.local.episteck_delegated_user is None
    fake.session.user = NUTRITION_CALLER
    module.establish_delegated_context()  # same token, right caller: still first use
    assert fake.local.episteck_delegated_user == "person@example.invalid"


def test_expired_nutrition_token_denies(hook):
    module, fake = hook
    _configure_nutrition_caller(fake)
    fake.session.user = NUTRITION_CALLER
    fake.headers["X-Episteck-Delegation"] = _token(
        aud="svc-nutrition", jti="tok-n5", iat=NOW - 600, exp=NOW - 1
    )
    module.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None


def test_control_plane_binding_records_its_audience(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(jti="tok-c1")
    module.establish_delegated_context()
    assert fake.local.episteck_delegation_audience == "home-control-plane"


def test_recorded_audience_is_reset_on_every_request(hook):
    module, fake = hook
    fake.headers["X-Episteck-Delegation"] = _token(jti="tok-c2")
    module.establish_delegated_context()
    fake.headers.clear()
    module.establish_delegated_context()
    assert fake.local.episteck_delegation_audience is None
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_auth_hook.py -v -k "nutrition or audience"`
Expected: FAIL (`episteck_delegation_audience` is never set; `svc-nutrition` never binds).

- [ ] **Step 3: Add audience constants to `actor.py`** (near the top, after imports)

```python
# Delegation audiences. A Nutrition-audience delegation binds only for Nutrition's own
# machine credential (auth_hook) and is accepted only by the policy entry points.
CONTROL_PLANE_AUDIENCE = "home-control-plane"
NUTRITION_AUDIENCE = "svc-nutrition"
```

- [ ] **Step 4: Implement in `auth_hook.py`**

Replace the local constant with an import and add the helper:

```python
from .actor import CONTROL_PLANE_AUDIENCE, NUTRITION_AUDIENCE
```

```python
def _accepted_audiences(machine_user: str) -> frozenset[str]:
    """Audiences this authenticated machine caller may present.

    Any machine caller may present a Control Plane delegation (unchanged G1.6). A
    Nutrition delegation binds only when presented by Nutrition's OWN machine user,
    named in site config; if that key is unset, it never binds.
    """
    audiences = {CONTROL_PLANE_AUDIENCE}
    nutrition_user = _config("home_nutrition_machine_user")
    if nutrition_user and machine_user == nutrition_user:
        audiences.add(NUTRITION_AUDIENCE)
    return frozenset(audiences)
```

In `_establish`, reset both values first:

```python
    frappe.local.episteck_delegated_user = None
    frappe.local.episteck_delegation_audience = None
```

Pass the per-caller set to `verify`:

```python
        expected_audience=_accepted_audiences(machine_user),
```

After `frappe.local.episteck_machine_caller = machine_user`, record the audience:

```python
    frappe.local.episteck_delegation_audience = context.audience
```

In `establish_delegated_context`'s `except` block, also set `frappe.local.episteck_delegation_audience = None`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_auth_hook.py -v` → PASS, including the unchanged `test_wrong_audience_denies`. Run: `python -m pytest tests -q` → PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/episteck_home/episteck_home/identity/auth_hook.py apps/episteck_home/episteck_home/identity/actor.py apps/episteck_home/tests/test_auth_hook.py
git commit -m "feat(home): bind svc-nutrition delegations to Nutrition's caller"
```

### Task 4: Only the policy entry points accept a Nutrition-audience actor

**Files:**
- Modify: `apps/episteck_home/episteck_home/identity/actor.py` (`resolve_principals`, `resolve_actor`)
- Modify: `apps/episteck_home/episteck_home/api.py` (`check_access`, `check_access_many`)
- Modify: `apps/episteck_home/tests/test_home_api_security.py`

**Interfaces:**
- Consumes: Task 3's constants and `frappe.local.episteck_delegation_audience`.
- Produces: `resolve_principals(*, accept_audiences: frozenset[str] = DEFAULT_AUDIENCES) -> Principals`, `resolve_actor(*, accept_audiences=...) -> str`, `actor.DEFAULT_AUDIENCES`, `actor.POLICY_AUDIENCES`.

- [ ] **Step 1: Make existing fixtures record the audience the hook would set**

In `_make_fake_frappe` (`tests/test_home_api_security.py`), extend `fake.local`:

```python
    fake.local = SimpleNamespace(
        episteck_delegated_user="person@example.invalid",
        episteck_machine_caller="home-mcp@example.invalid",
        episteck_delegation_audience="home-control-plane",
    )
```

Then run `grep -rn "episteck_delegated_user\s*=" apps/episteck_home/tests` and, for every fixture that sets a delegated user directly (not via the auth hook), also set `episteck_delegation_audience = "home-control-plane"`.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_home_api_security.py`)

```python
NON_POLICY_CALLS = {
    "get_person": lambda api: api.get_person("PSN-ACTOR"),
    "list_my_circles": lambda api: api.list_my_circles(),
    "list_circle_members": lambda api: api.list_circle_members("CIR-HOME"),
    "list_people_i_care_for": lambda api: api.list_people_i_care_for(),
    "get_access_to_person": lambda api: api.get_access_to_person("PSN-SUBJECT"),
    "get_care_dashboard": lambda api: api.get_care_dashboard(),
    "whoami": lambda api: api.whoami(),
}


@pytest.mark.parametrize("name", sorted(NON_POLICY_CALLS))
def test_nutrition_audience_actor_is_refused_outside_policy_entry_points(home_api, name):
    api, fake = home_api
    fake.local.episteck_delegation_audience = "svc-nutrition"
    with pytest.raises(FakePermissionError):
        NON_POLICY_CALLS[name](api)


@pytest.mark.parametrize("name", sorted(NON_POLICY_CALLS))
def test_control_plane_actor_is_still_accepted_by_non_policy_methods(home_api, name):
    api, _ = home_api
    NON_POLICY_CALLS[name](api)  # must not raise a permission error


def test_nutrition_audience_actor_is_accepted_by_check_access(home_api):
    api, fake = home_api
    fake.local.episteck_delegation_audience = "svc-nutrition"
    assert api.check_access("PSN-SUBJECT", "NUTRITION", "VIEW") == {
        "allow": False,
        "reason": "no grant",
    }


def test_nutrition_audience_actor_is_accepted_by_check_access_many(home_api):
    api, fake = home_api
    fake.local.episteck_delegation_audience = "svc-nutrition"
    result = api.check_access_many("PSN-SUBJECT", [{"domain": "NUTRITION", "action": "VIEW"}])
    assert result["allow"] is False
    assert len(result["decisions"]) == 1


def test_bound_delegated_user_without_recorded_audience_is_refused(home_api):
    api, fake = home_api
    del fake.local.episteck_delegation_audience
    with pytest.raises(FakePermissionError):
        api.check_access("PSN-SUBJECT", "NUTRITION", "VIEW")
```

If any `NON_POLICY_CALLS` entry needs extra fixture data to succeed under the control-plane case (for example `get_access_to_person` requiring discoverability), use an argument the fixture already supports (`PSN-SUBJECT` is a circle co-member and care subject of `PSN-ACTOR`).

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_home_api_security.py -v -k "audience"`
Expected: FAIL (`svc-nutrition` actors are currently accepted everywhere).

- [ ] **Step 4: Implement in `actor.py`**

```python
DEFAULT_AUDIENCES = frozenset({CONTROL_PLANE_AUDIENCE})
POLICY_AUDIENCES = frozenset({CONTROL_PLANE_AUDIENCE, NUTRITION_AUDIENCE})
```

In `resolve_principals`, change the signature to `def resolve_principals(*, accept_audiences: frozenset[str] = DEFAULT_AUDIENCES) -> Principals:` and add, right after `delegated_user` is read:

```python
    if delegated_user:
        audience = getattr(frappe.local, "episteck_delegation_audience", None)
        if audience not in accept_audiences:
            # A Nutrition-scoped delegation may drive one policy decision, nothing else.
            _mark_denial("actor.delegation_audience_not_accepted")
            _throw("delegation not accepted for this operation")
```

```python
def resolve_actor(*, accept_audiences: frozenset[str] = DEFAULT_AUDIENCES) -> str:
    """Return the trusted actor Person id. Never accepts a caller-supplied value."""
    return resolve_principals(accept_audiences=accept_audiences).human_actor
```

- [ ] **Step 5: Implement in `api.py`**

Add `POLICY_AUDIENCES` to the `episteck_home.identity.actor` import list. In `check_access` and `check_access_many`, replace `actor = resolve_actor()` with:

```python
    actor = resolve_actor(accept_audiences=POLICY_AUDIENCES)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_home_api_security.py -v` → PASS. Run: `python -m pytest tests -q` → PASS (includes `test_delegation_integration.py` and `test_replay_enforcement.py`, which go through the real hook).

- [ ] **Step 7: Commit**

```bash
git add apps/episteck_home/episteck_home/identity/actor.py apps/episteck_home/episteck_home/api.py apps/episteck_home/tests
git commit -m "feat(home): limit svc-nutrition actors to policy entry points"
```

### Task 5: F3b.1 documentation and PR

**Files:**
- Modify: `docs/architecture/DEPLOYMENT.md` ("Machine credentials" section)
- Modify: `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` (§5, after the request sequence)

- [ ] **Step 1: Document the config key** — append to "Machine credentials" in `DEPLOYMENT.md`:

```markdown
`[F3b]` Site config `home_nutrition_machine_user` names Nutrition's Frappe API User. Home
accepts a `svc-nutrition`-audience delegation only from that machine caller, and only at
`check_access`/`check_access_many`. If the key is unset, such delegations never bind.
```

- [ ] **Step 2: Record D1 in the architecture** — add under §5's request sequence:

```markdown
**F3b implementation note (D1, 2026-10-06):** as deployed by G1.6, Home verified every
delegation against `home-control-plane` only, so a `svc-nutrition` delegation could not
bind. F3b.1 makes Home accept `svc-nutrition` only from Nutrition's machine credential
and only at the policy entry points. See
`docs/superpowers/specs/2026-10-05-home-f3b-nutrition-adapter-design.md` D1–D3.
```

- [ ] **Step 3: Full suite, push, PR**

```bash
cd apps/episteck_home && python -m pytest tests -q && cd ../..
git add docs/architecture/DEPLOYMENT.md docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md
git commit -m "docs(home): record F3b audience binding and config key"
git push -u origin feature/home-f3b1-subject-guard
gh pr create --base main --title "feat(home): F3b.1 subject-existence guard and svc-nutrition binding" --body-file <prepared body per git-and-branching.md template, ending with the session URL>
```

## Rollout gate R1 (operator-run deploy; Claude runs read-only checks)

- [ ] Merge (squash). Wait for the episteck-deploy job (~5 min).
- [ ] Read-only: on `episteck-home`, SHA-256 of the five changed Home files equal the merge commit's blobs (`git show <sha>:<path> | sha256sum` locally vs `sha256sum` on the bench).
- [ ] Read-only `bench --site home.episteck.com execute episteck_home.policy.wrappers.check_access --kwargs "{'actor_person_id':'PSN-00013','subject_person_id':'PSN-00013','domain':'NUTRITION','action':'VIEW'}"` → allow; same with `subject_person_id='PSN-99999'` → `{"allow": false, "reason": "no consent grant (fail closed)"}`.
- [ ] Regression: operator asks the Home Agent (Hermes) for their own Nutrition access → allow (a `home-control-plane` delegation end to end).
- [ ] Operator identifies Nutrition's API username (the Frappe User whose `api_key` equals Nutrition's `HOME_API_KEY`; read the key only, never the secret) and runs `bench --site home.episteck.com set-config home_nutrition_machine_user <username>`. Read-only check that the key is set. Inert until F3b.3.
- **Stop and roll back** if any check fails: revert the merge via PR (the job redeploys), and remove the key.

---

# PR F3b.2 — Nutrition typed authorization outcomes

### Task 6: Outcome-classifying Home client

**Files:**
- Modify: `services/nutrition/app/home_control/client.py`
- Modify: `services/nutrition/tests/test_home_control_client.py`
- Modify: `services/nutrition/tests/support.py`

**Interfaces:**
- Produces: constants `ALLOW`, `DENY`, `SESSION_INVALID`, `UNAVAILABLE`; `AccessDecision(allow: bool, reason: str, outcome: str = "")`, where `outcome` defaults from `allow`, is excluded from equality, and raises `ValueError` if it disagrees with `allow`; logger `nutrition.home_control`.

- [ ] **Step 1: Branch**

```bash
git fetch origin && git switch -c feature/home-f3b2-nutrition-outcomes origin/main
```

- [ ] **Step 2: Write the failing tests** (append to `tests/test_home_control_client.py`; extend its import to `from app.home_control.client import ALLOW, DENY, SESSION_INVALID, UNAVAILABLE, AccessDecision, HomeControlPlaneClient`)

```python
# ==========================================================================
# F3b.2 outcome contract
# ==========================================================================


def _respond(status, body=None, *, content=None):
    def handler(request):
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=body)
    return handler


def _message(**decision):
    return {"message": decision}


@pytest.mark.parametrize(
    "handler, outcome",
    [
        (_respond(200, _message(allow=True, reason="self-access")), ALLOW),
        (_respond(200, _message(allow=False, reason="no consent grant (fail closed)")), DENY),
        (_respond(200, _message(allow=True)), UNAVAILABLE),
        (_respond(200, _message(allow=True, reason="")), UNAVAILABLE),
        (_respond(200, _message(allow=True, reason="   ")), UNAVAILABLE),
        (_respond(200, _message(allow=True, reason=7)), UNAVAILABLE),
        (_respond(200, _message(allow="true", reason="x")), UNAVAILABLE),
        (_respond(200, {"message": [True]}), UNAVAILABLE),
        (_respond(200, content=b"<html>not json</html>"), UNAVAILABLE),
        (_respond(401, {"exc_type": "AuthenticationError"}), SESSION_INVALID),
        (_respond(403, {"exc_type": "PermissionError"}), SESSION_INVALID),
        (_respond(404, {}), UNAVAILABLE),
        (_respond(500, {}), UNAVAILABLE),
        (_respond(502, {}), UNAVAILABLE),
    ],
)
def test_check_access_outcome_matrix(handler, outcome):
    counter = _Counter(handler)
    decision = _client(counter).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision.outcome == outcome
    assert decision.allow is (outcome == ALLOW)
    assert len(counter.requests) == 1


def test_unreachable_home_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("down", request=request)
    decision = _client(handler).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision.outcome == UNAVAILABLE


def test_timeout_is_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    decision = _client(handler).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert decision.outcome == UNAVAILABLE


def test_missing_delegation_is_session_invalid_without_a_request():
    counter = _Counter(_allow)
    decision = _client(counter).check_access("PSN-B", "NUTRITION", "VIEW", None)
    assert decision.outcome == SESSION_INVALID
    assert counter.requests == []


def test_missing_arguments_are_unavailable_without_a_request():
    counter = _Counter(_allow)
    decision = _client(counter).check_access("", "NUTRITION", "VIEW", SESSION)
    assert decision.outcome == UNAVAILABLE
    assert counter.requests == []


def test_reason_wording_never_changes_the_decision():
    deny_worded_like_allow = _respond(200, _message(allow=False, reason="self-access"))
    allow_worded_like_deny = _respond(200, _message(allow=True, reason="no consent grant (fail closed)"))
    assert _client(deny_worded_like_allow).check_access("PSN-B", "NUTRITION", "VIEW", SESSION).outcome == DENY
    assert _client(allow_worded_like_deny).check_access("PSN-B", "NUTRITION", "VIEW", SESSION).outcome == ALLOW


REQS = [("NUTRITION", "VIEW"), ("NUTRITION", "CREATE")]
COVERED = [
    {"domain": "NUTRITION", "action": "VIEW", "allow": True},
    {"domain": "NUTRITION", "action": "CREATE", "allow": True},
]


@pytest.mark.parametrize(
    "handler, outcome",
    [
        (_respond(200, _message(allow=True, reason="all requirements allowed", decisions=COVERED)), ALLOW),
        (_respond(200, _message(allow=False, reason="no matching active grant (fail closed)", decisions=[])), DENY),
        (_respond(200, _message(allow=True, decisions=COVERED)), UNAVAILABLE),
        (_respond(200, _message(allow=True, reason="all requirements allowed", decisions=COVERED[:1])), UNAVAILABLE),
        (_respond(403, {}), SESSION_INVALID),
        (_respond(503, {}), UNAVAILABLE),
    ],
)
def test_check_access_many_outcome_matrix(handler, outcome):
    counter = _Counter(handler)
    decision = _client(counter).check_access_many("PSN-B", REQS, SESSION)
    assert decision.outcome == outcome
    assert len(counter.requests) == 1


def test_access_decision_outcome_defaults_and_must_agree():
    assert AccessDecision(True, "x").outcome == ALLOW
    assert AccessDecision(False, "x").outcome == DENY
    with pytest.raises(ValueError):
        AccessDecision(True, "x", DENY)
    with pytest.raises(ValueError):
        AccessDecision(False, "x", ALLOW)


def test_refusal_logs_a_category_without_identity_or_reason(caplog):
    caplog.set_level("WARNING", logger="nutrition.home_control")
    handler = _respond(200, _message(allow=False, reason="no matching active grant (fail closed)"))
    _client(handler).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert "deny" in caplog.text
    assert "PSN-B" not in caplog.text
    assert SESSION not in caplog.text
    assert "no matching" not in caplog.text


def test_rejected_credential_or_session_has_its_own_log_category(caplog):
    caplog.set_level("WARNING", logger="nutrition.home_control")
    _client(_respond(403, {})).check_access("PSN-B", "NUTRITION", "VIEW", SESSION)
    assert "home_rejected_credential_or_session" in caplog.text
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_home_control_client.py -v -k "outcome or unreachable or timeout or missing or wording or logs or category"`
Expected: FAIL (`ImportError: cannot import name 'ALLOW'`).

- [ ] **Step 4: Implement the decision type and helpers** in `client.py` (keep the module docstring)

```python
from dataclasses import dataclass, field
import logging
import os

import httpx

DELEGATION_HEADER = "X-Episteck-Delegation"

logger = logging.getLogger("nutrition.home_control")

ALLOW = "ALLOW"
DENY = "DENY"
SESSION_INVALID = "SESSION_INVALID"
UNAVAILABLE = "UNAVAILABLE"
_OUTCOMES = frozenset({ALLOW, DENY, SESSION_INVALID, UNAVAILABLE})


@dataclass(frozen=True)
class AccessDecision:
    """A Home authorization result.

    ``outcome`` distinguishes WHY access was refused so the HTTP boundary can answer
    401 / 403 / 503. It is excluded from equality so existing ``(allow, reason)``
    comparisons stay valid; outcome tests assert it explicitly.
    """

    allow: bool
    reason: str
    outcome: str = field(default="", compare=False)

    def __post_init__(self):
        if not self.outcome:
            object.__setattr__(self, "outcome", ALLOW if self.allow else DENY)
        if self.outcome not in _OUTCOMES:
            raise ValueError("unknown authorization outcome")
        if self.allow != (self.outcome == ALLOW):
            raise ValueError("allow and outcome disagree")


_INDETERMINATE = AccessDecision(False, "authorization indeterminate (fail closed)", UNAVAILABLE)
_NO_SESSION = AccessDecision(False, "no authenticated human session (fail closed)", SESSION_INVALID)
# Home refused to resolve a human actor: invalid, expired, replayed or wrong-audience
# delegation, logged-out session, or (operator-visible via the log category) a broken
# Nutrition machine credential.
_SESSION_REJECTED = AccessDecision(False, "authorization indeterminate (fail closed)", SESSION_INVALID)


def _refused(category: str, decision: AccessDecision) -> AccessDecision:
    """Log one static category per refusal. Never an identity, token or Home reason."""
    logger.warning("home authorization not granted: %s", category)
    return decision


def _transport_refusal(response: httpx.Response) -> AccessDecision | None:
    if response.status_code in (401, 403):
        return _refused("home_rejected_credential_or_session", _SESSION_REJECTED)
    if response.status_code != 200:
        return _refused("home_unreachable", _INDETERMINATE)
    return None


def _well_formed_decision(response: httpx.Response) -> dict | None:
    """The decision object, or None when the body is not a complete decision.

    ``reason`` is REQUIRED as a non-empty string for the response to be complete. Its
    wording is never interpreted: only the boolean ``allow`` decides.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    decision = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(decision, dict) or type(decision.get("allow")) is not bool:
        return None
    reason = decision.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    return decision
```

- [ ] **Step 5: Replace the bodies of `check_access` and `check_access_many`** (keep their docstrings)

```python
    def check_access(self, subject_person_id, domain, action, delegation=None) -> AccessDecision:
        if not all((subject_person_id, domain, action)):
            return _refused("invalid_request", _INDETERMINATE)
        if not delegation:
            return _refused("session_invalid", _NO_SESSION)
        try:
            response = self._client.get(
                "/api/method/episteck_home.api.check_access",
                params={"subject_person_id": subject_person_id, "domain": domain, "action": action},
                headers={DELEGATION_HEADER: delegation},
            )
        except httpx.HTTPError:
            return _refused("home_unreachable", _INDETERMINATE)
        refusal = _transport_refusal(response)
        if refusal is not None:
            return refusal
        decision = _well_formed_decision(response)
        if decision is None:
            return _refused("home_malformed", _INDETERMINATE)
        if not decision["allow"]:
            return _refused("deny", AccessDecision(False, decision["reason"]))
        return AccessDecision(True, decision["reason"])

    def check_access_many(self, subject_person_id, requirements, delegation=None) -> AccessDecision:
        if not subject_person_id or not requirements:
            return _refused("invalid_request", _INDETERMINATE)
        if any(not domain or not action for domain, action in requirements):
            return _refused("invalid_request", _INDETERMINATE)
        if not delegation:
            return _refused("session_invalid", _NO_SESSION)
        try:
            response = self._client.post(
                "/api/method/episteck_home.api.check_access_many",
                json={
                    "subject_person_id": subject_person_id,
                    "requirements": [{"domain": d, "action": a} for d, a in requirements],
                },
                headers={DELEGATION_HEADER: delegation},
            )
        except httpx.HTTPError:
            return _refused("home_unreachable", _INDETERMINATE)
        refusal = _transport_refusal(response)
        if refusal is not None:
            return refusal
        decision = _well_formed_decision(response)
        if decision is None:
            return _refused("home_malformed", _INDETERMINATE)
        reason = decision["reason"]
        # A denial needs no corroboration: refusing is always safe.
        if not decision["allow"]:
            return _refused("deny", AccessDecision(False, reason))
        # An allow must be proven against the requirements we actually sent.
        listed = decision.get("decisions")
        if not isinstance(listed, list) or len(listed) != len(requirements):
            return _refused("home_malformed", _INDETERMINATE)
        for (domain, action), item in zip(requirements, listed):
            if not isinstance(item, dict):
                return _refused("home_malformed", _INDETERMINATE)
            if item.get("domain") != domain or item.get("action") != action:
                return _refused("home_malformed", _INDETERMINATE)
            if item.get("allow") is not True:
                return _refused("deny", AccessDecision(False, reason))
        return AccessDecision(True, reason)
```

- [ ] **Step 6: Align the test doubles with the real client**

In `tests/support.py`, import `SESSION_INVALID` and change every missing-delegation return to `AccessDecision(False, "no authenticated human session (fail closed)", SESSION_INVALID)`.

- [ ] **Step 7: Run the whole Nutrition suite and fix fixture fallout**

Run: `python -m pytest tests -q`
Expected: new tests PASS. If an existing test sends a top-level `allow: true` message **without** `reason`, it now yields `UNAVAILABLE`. Add `"reason": "all requirements allowed"` (batch) or `"reason": "grant NUTRITION/VIEW"` (single), which is what Home actually returns. Do not weaken the new rule. Re-run until green.

- [ ] **Step 8: Commit**

```bash
git add services/nutrition/app/home_control/client.py services/nutrition/tests
git commit -m "feat(nutrition): classify Home authorization outcomes"
```

### Task 7: Typed refusals in the service and fixed HTTP bodies

**Files:**
- Modify: `services/nutrition/app/service.py` (`_require_access`, `_require_all`, new exceptions)
- Modify: `services/nutrition/app/main.py` (`_authorized`)
- Create: `services/nutrition/tests/test_policy_outcomes.py`

**Interfaces:**
- Consumes: Task 6's `AccessDecision.outcome` and constants.
- Produces: `service.AccessDenied`, `service.SessionInvalid`, `service.PolicyUnavailable` (all `PermissionError`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_policy_outcomes.py`

```python
"""F3b.2: Nutrition answers 401 / 403 / 503 with fixed bodies and never reads on refusal."""
from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from app.home_control.client import SESSION_INVALID, UNAVAILABLE, AccessDecision
from app.providers.synthetic import SyntheticFoodProvider
from app.service import AccessDenied, NutritionService, PolicyUnavailable, SessionInvalid

SESSION = "delegation-token-outcomes"
HOME_REASON = "no matching active grant (fail closed)"
PROFILE = {"context": "GENERAL", "target_source": "USER_CONFIGURED", "targets": {"energy_kcal": 2000.0}}

DECISIONS = {
    "PSN-A": AccessDecision(True, "grant NUTRITION/VIEW"),
    "PSN-EMPTY": AccessDecision(True, "self-access"),
    "PSN-B": AccessDecision(False, HOME_REASON),
    "PSN-SESSION": AccessDecision(False, "authorization indeterminate (fail closed)", SESSION_INVALID),
    "PSN-DOWN": AccessDecision(False, "authorization indeterminate (fail closed)", UNAVAILABLE),
}


class ScriptedAuthorizer:
    """A fixed decision per subject; records every Home call."""

    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def check_access(self, subject, domain, action, delegation=None):
        self.calls.append((subject, domain, action, delegation))
        return self.decisions[subject]

    def check_access_many(self, subject, requirements, delegation=None):
        self.calls.append((subject, tuple(requirements), delegation))
        return self.decisions[subject]


class SpyRepository:
    def __init__(self, profiles):
        self.profiles = profiles
        self.reads = []

    def get_profile(self, person_id):
        self.reads.append(person_id)
        return self.profiles.get(person_id)


def _service():
    repo = SpyRepository({"PSN-A": PROFILE})
    authorizer = ScriptedAuthorizer(DECISIONS)
    return NutritionService(repo, SyntheticFoodProvider(), authorizer=authorizer), repo, authorizer


@pytest.mark.parametrize(
    "subject, error",
    [("PSN-B", AccessDenied), ("PSN-SESSION", SessionInvalid), ("PSN-DOWN", PolicyUnavailable)],
)
def test_service_refuses_each_non_allow_without_reading(subject, error):
    service, repo, authorizer = _service()
    with pytest.raises(error):
        service.get_profile(SESSION, subject)
    assert repo.reads == []
    assert len(authorizer.calls) == 1


def test_refusals_remain_permission_errors_for_the_mcp_boundary():
    assert issubclass(AccessDenied, PermissionError)
    assert issubclass(SessionInvalid, PermissionError)
    assert issubclass(PolicyUnavailable, PermissionError)


@pytest.fixture
def http(monkeypatch, tmp_path):
    monkeypatch.setenv("NUTRITION_DB", str(tmp_path / "nutrition.sqlite"))
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    service, repo, authorizer = _service()
    main.svc = service
    return TestClient(main.app, raise_server_exceptions=False), repo, authorizer


@pytest.mark.parametrize(
    "subject, status, body",
    [
        ("PSN-A", 200, PROFILE),
        ("PSN-EMPTY", 404, {"detail": "no profile"}),
        ("PSN-B", 403, {"detail": "ACCESS_DENIED"}),
        ("PSN-SESSION", 401, {"detail": "SESSION_INVALID"}),
        ("PSN-DOWN", 503, {"detail": "SERVICE_UNAVAILABLE"}),
    ],
)
def test_profile_route_contract(http, subject, status, body):
    client, repo, authorizer = http
    response = client.get(f"/profile/{subject}", headers={"X-Episteck-Delegation": SESSION})
    assert response.status_code == status
    assert response.json() == body
    assert HOME_REASON not in response.text
    assert "indeterminate" not in response.text
    assert repo.reads == ([subject] if status in (200, 404) else [])
    assert len(authorizer.calls) == 1


def test_cross_subject_denial_does_not_leak_or_read(http):
    client, repo, _ = http
    assert client.get("/profile/PSN-A", headers={"X-Episteck-Delegation": SESSION}).status_code == 200
    denied = client.get("/profile/PSN-B", headers={"X-Episteck-Delegation": SESSION})
    assert denied.status_code == 403
    assert denied.json() == {"detail": "ACCESS_DENIED"}
    assert repo.reads == ["PSN-A"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_policy_outcomes.py -v`
Expected: FAIL (`ImportError: cannot import name 'AccessDenied'`).

- [ ] **Step 3: Implement in `service.py`**

`service.py` does not import from `home_control` today (its `AccessAuthorizer` is a `Protocol`). Add `from .home_control.client import ALLOW, DENY, SESSION_INVALID, UNAVAILABLE, AccessDecision` after the existing relative imports; `client.py` does not import `service`, so there is no cycle. Add near the top-level definitions:

```python
class AccessDenied(PermissionError):
    """Home made a well-formed denial."""


class SessionInvalid(PermissionError):
    """No human actor could be established for the delegated session."""


class PolicyUnavailable(PermissionError):
    """Authorization could not be determined (Home unreachable or malformed)."""


_REFUSALS: dict[str, type[PermissionError]] = {
    DENY: AccessDenied,
    SESSION_INVALID: SessionInvalid,
    UNAVAILABLE: PolicyUnavailable,
}


def _refuse_unless_allowed(decision: AccessDecision) -> None:
    """Literal ALLOW only. Every other outcome raises its typed refusal."""
    if decision.allow and decision.outcome == ALLOW:
        return
    raise _REFUSALS.get(decision.outcome, PolicyUnavailable)(decision.reason)
```

In `_require_access` and `_require_all`, replace

```python
        if not decision.allow:
            raise PermissionError(decision.reason)
```

with

```python
        _refuse_unless_allowed(decision)
```

- [ ] **Step 4: Implement in `main.py`**

```python
from .service import AccessDenied, PolicyUnavailable, SessionInvalid
```

```python
def _authorized(operation: Callable[[], Any]):
    """Map refusals to fixed bodies. ``from None`` keeps Home's reason out of responses."""
    try:
        return operation()
    except SessionInvalid:
        raise HTTPException(401, "SESSION_INVALID") from None
    except PolicyUnavailable:
        raise HTTPException(503, "SERVICE_UNAVAILABLE") from None
    except (AccessDenied, PermissionError):
        raise HTTPException(403, "ACCESS_DENIED") from None
```

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest tests -q` → PASS. If an existing test asserted a 403 body containing reason text, update it to `{"detail": "ACCESS_DENIED"}` (the leak this PR removes).

- [ ] **Step 6: Commit, push, PR**

```bash
git add services/nutrition/app/service.py services/nutrition/app/main.py services/nutrition/tests/test_policy_outcomes.py services/nutrition/tests
git commit -m "feat(nutrition): return typed 401/403/503 authorization outcomes"
git push -u origin feature/home-f3b2-nutrition-outcomes
gh pr create --base main --title "feat(nutrition): F3b.2 typed authorization outcomes" --body-file <prepared body ending with the session URL>
```

## Rollout gate R2 (operator-run deploy; Claude runs read-only checks)

- [ ] Read-only discovery on `episteck-node1`: list `/home/svc-nutrition/.config/containers/systemd/*.container`; record each `Image=`, running image IDs, and restart counts.
- [ ] Clean host checkout of the merge SHA in `/tmp/episteck-home-f3b2-<sha>`; as `svc-nutrition`: `podman build -f services/nutrition/Dockerfile -t localhost/episteck-nutrition:<sha> .` from the checkout root. Record image ID and digest.
- [ ] Back up both Quadlets to `/var/backups/episteck/home-f3b2-<sha>/` (root `0700`); record SHA-256.
- [ ] Operator changes only the two `Image=` lines (diff = 2 lines), reloads, restarts both units.
- [ ] Verify: both active, `NRestarts=0`; `curl 127.0.0.1:9930/health` → 200; `curl 127.0.0.1:9930/profile/PSN-00013` (no delegation) → 401 `{"detail":"SESSION_INVALID"}`; listeners `127.0.0.1` 9930/9931 only; container logs since restart contain no `PSN-`, token, or bearer pattern.
- [ ] Regression: operator asks the Home Agent for their own Nutrition profile → works as before.
- **Rollback:** restore both saved Quadlets byte for byte, reload, restart, and re-run the health checks. The old image stays on the host.

---

# PR F3b.3 — Hub adapter and 9930 transport

### Task 8: `HOME_HUB_NUTRITION_BASE_URL` configuration

**Files:**
- Modify: `apps/home-hub/src/integration/home/server-config.ts`
- Modify: `apps/home-hub/src/integration/home/configuration.test.ts`
- Modify: `apps/home-hub/test-support/verify-production-startup-config.mjs`, `apps/home-hub/test-support/verify-server-only-client-import.mjs`, `apps/home-hub/playwright.config.ts`
- Modify: `apps/home-hub/Dockerfile` (builder stage) and `deploy/home-hub/tests/test_home_hub_quadlet.py` (Dockerfile test)

**Why the Dockerfile:** `next.config.ts` calls `getHomeHubServerConfiguration()` during `npm run build`, and the builder stage runs with `HOME_HUB_DATA_MODE=LIVE`. Without the new variable in the builder stage, the image build fails.

**Interfaces:**
- Produces: `HomeHubServerConfiguration.nutritionBaseUrl?: string` (origin string, e.g. `http://127.0.0.1:9930`).

- [ ] **Step 1: Branch**

```bash
git fetch origin && git switch -c feature/home-f3b3-hub-nutrition-adapter origin/main
```

- [ ] **Step 2: Write the failing tests** (append to `configuration.test.ts`)

```ts
const liveDev = {
  HOME_HUB_DATA_MODE: 'LIVE',
  HOME_HUB_BFF_BASE_URL: 'http://127.0.0.1:9933',
} as NodeJS.ProcessEnv;

test('LIVE configuration requires the Nutrition origin', () => {
  assert.throws(
    () => getHomeHubServerConfiguration(liveDev),
    /HOME_HUB_NUTRITION_BASE_URL is required/,
  );
});

test('LIVE configuration exposes the validated Nutrition origin', () => {
  const config = getHomeHubServerConfiguration({
    ...liveDev,
    HOME_HUB_NUTRITION_BASE_URL: 'http://127.0.0.1:9930',
  } as NodeJS.ProcessEnv);
  assert.equal(config.nutritionBaseUrl, 'http://127.0.0.1:9930');
});

test('production Nutrition origin must be loopback', () => {
  assert.throws(
    () => getHomeHubServerConfiguration({
      NODE_ENV: 'production',
      HOME_HUB_DATA_MODE: 'LIVE',
      HOME_HUB_BFF_BASE_URL: 'http://127.0.0.1:9933',
      HOME_HUB_PUBLIC_ORIGIN: 'https://bff.home.episteck.com',
      HOME_HUB_NUTRITION_BASE_URL: 'https://nutrition.example.com',
    } as NodeJS.ProcessEnv),
    /HOME_HUB_NUTRITION_BASE_URL must be a trusted HTTP origin/,
  );
});

test('MOCK configuration has no Nutrition origin', () => {
  const config = getHomeHubServerConfiguration({ HOME_HUB_DATA_MODE: 'MOCK' } as NodeJS.ProcessEnv);
  assert.equal(config.nutritionBaseUrl, undefined);
});
```

- [ ] **Step 3: Run to verify failure**

Run: `npm test -- src/integration/home/configuration.test.ts`
Expected: FAIL (no `nutritionBaseUrl`; no requirement).

- [ ] **Step 4: Implement** in `server-config.ts`

```ts
export interface HomeHubServerConfiguration {
  mode: EnvironmentMode;
  bffBaseUrl?: string;
  nutritionBaseUrl?: string;
  publicOrigin: string;
}
```

After `bffBaseUrl` is computed:

```ts
  const nutritionBaseUrl = mode === 'LIVE'
    ? configuredOrigin(env.HOME_HUB_NUTRITION_BASE_URL, 'HOME_HUB_NUTRITION_BASE_URL', production, true, true)
    : undefined;
```

Return `{ mode, bffBaseUrl, nutritionBaseUrl, publicOrigin }`.

- [ ] **Step 5: Add the variable wherever a LIVE env is constructed**

Add `HOME_HUB_NUTRITION_BASE_URL: 'http://127.0.0.1:9930'` next to every `HOME_HUB_BFF_BASE_URL` in `configuration.test.ts` LIVE fixtures (including the `valid` env object), `test-support/verify-production-startup-config.mjs`, `test-support/verify-server-only-client-import.mjs`, and `playwright.config.ts`. Check with `grep -rn "HOME_HUB_BFF_BASE_URL" apps/home-hub --include=*.ts --include=*.mjs | grep -v node_modules`: every LIVE occurrence has a matching Nutrition line (`bootstrap-loader.ts` and `server-config.ts` are code, not fixtures).

- [ ] **Step 6: Pin the build-time variable in the Dockerfile test**

In `deploy/home-hub/tests/test_home_hub_quadlet.py`, add to `test_home_hub_dockerfile_builds_standalone_with_build_dependencies_only`:

```python
    assert 'ARG HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930' in dockerfile
    assert 'HOME_HUB_NUTRITION_BASE_URL=${HOME_HUB_NUTRITION_BASE_URL}' in dockerfile
```

Run: `python -m pytest deploy/home-hub/tests -q -k dockerfile` → FAIL.

- [ ] **Step 7: Add the variable to the Dockerfile builder stage**

```dockerfile
FROM deps AS builder
ARG HOME_HUB_BFF_BASE_URL=http://127.0.0.1:9933
ARG HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930
ARG HOME_HUB_PUBLIC_ORIGIN=https://bff.home.episteck.com
ENV NODE_ENV=production \
    HOME_HUB_DATA_MODE=LIVE \
    HOME_HUB_BFF_BASE_URL=${HOME_HUB_BFF_BASE_URL} \
    HOME_HUB_NUTRITION_BASE_URL=${HOME_HUB_NUTRITION_BASE_URL} \
    HOME_HUB_PUBLIC_ORIGIN=${HOME_HUB_PUBLIC_ORIGIN} \
    NEXT_TELEMETRY_DISABLED=1
```

The runner stage is unchanged: the runtime value comes from the Quadlet (Task 12).

- [ ] **Step 8: Run**

Run: `npm test -- src/integration/home/configuration.test.ts` → PASS. Run: `npm run test:startup-config` → PASS. Run: `python -m pytest deploy/home-hub/tests -q -k dockerfile` → PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/home-hub/src/integration/home apps/home-hub/test-support apps/home-hub/playwright.config.ts apps/home-hub/Dockerfile deploy/home-hub/tests/test_home_hub_quadlet.py
git commit -m "feat(home-hub): require a loopback Nutrition origin in LIVE"
```

### Task 9: Strict profile contract

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/profile-contract.ts`
- Create: `apps/home-hub/src/integration/nutrition/profile-contract.test.ts`

**Interfaces:**
- Produces: `type ProfileSummary`, `class ProfileContractError extends Error`, `parseProfileWire(body: unknown): ProfileSummary` (always `presence: 'PRESENT'`), `isAbsentProfileBody(body: unknown): boolean`.

- [ ] **Step 1: Write the failing tests**

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isAbsentProfileBody, parseProfileWire, ProfileContractError } from './profile-contract.ts';

const general = { context: 'GENERAL', target_source: 'USER_CONFIGURED', targets: { energy_kcal: 2000, protein_g: 70.5 } };

test('maps a numeric-target profile to the three summary fields only', () => {
  assert.deepEqual(parseProfileWire(general), {
    presence: 'PRESENT', context: 'GENERAL', targetSource: 'USER_CONFIGURED', targetCount: 2,
  });
});

test('accepts the decimal-string targets that pregnancy profiles store', () => {
  const pregnancy = {
    context: 'PREGNANCY', target_source: 'REFERENCE_TARGET',
    targets: { calcium_mg: '1000', iron_mg: '27', folate_ug: '600', energy_kcal: '2300.5' },
    targets_detail: [{ secret: true }], preferences: 'no fish', dislikes: 'okra',
    explicit_intolerances: 'lactose', pregnancy_stage: 'T2',
  };
  const summary = parseProfileWire(pregnancy);
  assert.deepEqual(summary, { presence: 'PRESENT', context: 'PREGNANCY', targetSource: 'REFERENCE_TARGET', targetCount: 4 });
  assert.equal(JSON.stringify(summary).includes('fish'), false);
  assert.equal(JSON.stringify(summary).includes('lactose'), false);
});

test('an empty targets object is a valid present profile with zero targets', () => {
  assert.equal((parseProfileWire({ ...general, targets: {} }) as { targetCount: number }).targetCount, 0);
});

const invalid: Array<[string, unknown]> = [
  ['null body', null],
  ['array body', [general]],
  ['missing context', { target_source: 'X', targets: {} }],
  ['lowercase context', { ...general, context: 'general' }],
  ['overlong context', { ...general, context: 'A'.repeat(33) }],
  ['non-string target_source', { ...general, target_source: 3 }],
  ['missing targets', { context: 'GENERAL', target_source: 'X' }],
  ['array targets', { ...general, targets: [1, 2] }],
  ['non-finite target', { ...general, targets: { a: Number.POSITIVE_INFINITY } }],
  ['non-numeric string target', { ...general, targets: { a: '12abc' } }],
  ['overlong string target', { ...general, targets: { a: '1'.repeat(33) } }],
  ['object target', { ...general, targets: { a: { v: 1 } } }],
  ['too many targets', { ...general, targets: Object.fromEntries(Array.from({ length: 65 }, (_, i) => [`t${i}`, i])) }],
];

for (const [name, body] of invalid) {
  test(`rejects ${name}`, () => {
    assert.throws(() => parseProfileWire(body), ProfileContractError);
  });
}

test('recognizes only the exact absent-profile body', () => {
  assert.equal(isAbsentProfileBody({ detail: 'no profile' }), true);
  assert.equal(isAbsentProfileBody({ detail: 'Not Found' }), false);
  assert.equal(isAbsentProfileBody({ detail: 'no profile', extra: 1 }), false);
  assert.equal(isAbsentProfileBody(null), false);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/integration/nutrition/profile-contract.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `profile-contract.ts`

```ts
export type ProfileSummary =
  | { presence: 'PRESENT'; context: string; targetSource: string; targetCount: number }
  | { presence: 'ABSENT' };

export class ProfileContractError extends Error {}

const CODE = /^[A-Z_]{1,32}$/;
const NUMERIC = /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/;
const MAX_TARGETS = 64;
const MAX_TARGET_TEXT = 32;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object'
    && value !== null
    && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype;
}

function isTargetValue(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value);
  return typeof value === 'string'
    && value.length <= MAX_TARGET_TEXT
    && NUMERIC.test(value)
    && Number.isFinite(Number(value));
}

/**
 * Strict, minimizing mapper for Nutrition's GET /profile/{id} 200 body.
 * Reads exactly three facts; preferences, dislikes, intolerances, pregnancy fields and
 * any unknown field are never copied. Any violation rejects the whole payload.
 */
export function parseProfileWire(body: unknown): ProfileSummary {
  if (!isPlainObject(body)) throw new ProfileContractError('profile must be an object');
  const { context, target_source: targetSource, targets } = body;
  if (typeof context !== 'string' || !CODE.test(context)) throw new ProfileContractError('invalid context');
  if (typeof targetSource !== 'string' || !CODE.test(targetSource)) throw new ProfileContractError('invalid target source');
  if (!isPlainObject(targets)) throw new ProfileContractError('invalid targets');
  const keys = Object.keys(targets);
  if (keys.length > MAX_TARGETS) throw new ProfileContractError('too many targets');
  if (!keys.every((key) => isTargetValue(targets[key]))) throw new ProfileContractError('invalid target value');
  return { presence: 'PRESENT', context, targetSource, targetCount: keys.length };
}

/** True only for Nutrition's authorized no-profile body, exactly {"detail":"no profile"}. */
export function isAbsentProfileBody(body: unknown): boolean {
  return isPlainObject(body) && Object.keys(body).length === 1 && body.detail === 'no profile';
}
```

- [ ] **Step 4: Run** — `npm test -- src/integration/nutrition/profile-contract.test.ts` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub/src/integration/nutrition/profile-contract.ts apps/home-hub/src/integration/nutrition/profile-contract.test.ts
git commit -m "feat(home-hub): add strict Nutrition profile contract"
```

### Task 10: Single-mint, single-call profile loader

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/profile-loader.ts`
- Create: `apps/home-hub/src/integration/nutrition/profile-loader.test.ts`

**Interfaces:**
- Consumes: Task 9's `parseProfileWire`, `isAbsentProfileBody`, `ProfileSummary`; `DataEnvelope`, `SafeUIErrorCode`.
- Produces: `loadNutritionProfile(options: LoadNutritionProfileOptions): Promise<DataEnvelope<ProfileSummary>>`, where `LoadNutritionProfileOptions = { mode: 'MOCK' | 'LIVE'; personId: string; cookieValue: string | undefined; bffBaseUrl: string | undefined; nutritionBaseUrl: string | undefined; fetcher: typeof fetch }`.

- [ ] **Step 1: Write the failing tests**

```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadNutritionProfile, type LoadNutritionProfileOptions } from './profile-loader.ts';

type Call = { url: string; init: RequestInit | undefined };

function scripted(...responses: Array<Response | Error>) {
  const calls: Call[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const next = responses.shift();
    if (!next) throw new Error('unexpected extra request');
    if (next instanceof Error) throw next;
    return next;
  }) as typeof fetch;
  return { calls, fetcher };
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
const minted = () => json(200, { delegation: 'tok-opaque', audience: 'svc-nutrition', expires_at: 1 });
const PROFILE = { context: 'PREGNANCY', target_source: 'REFERENCE_TARGET', targets: { calcium_mg: '1000' }, preferences: 'private' };
const live = {
  mode: 'LIVE' as const,
  personId: 'PSN-00013',
  cookieValue: 'opaque-session',
  bffBaseUrl: 'http://127.0.0.1:9933',
  nutritionBaseUrl: 'http://127.0.0.1:9930',
};

test('authorized present profile: one mint, one Nutrition call, minimized data', async () => {
  const { calls, fetcher } = scripted(minted(), json(200, PROFILE));
  const result = await loadNutritionProfile({ ...live, fetcher });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'http://127.0.0.1:9933/delegation?audience=svc-nutrition');
  assert.equal(calls[0].init?.method, 'POST');
  assert.equal(calls[1].url, 'http://127.0.0.1:9930/profile/PSN-00013');
  assert.equal(calls[1].init?.method, 'GET');
  assert.deepEqual(result, {
    delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE',
    data: { presence: 'PRESENT', context: 'PREGNANCY', targetSource: 'REFERENCE_TARGET', targetCount: 1 },
  });
});

test('authorized absent profile maps to READY ABSENT, never zeros or mock', async () => {
  const { fetcher } = scripted(minted(), json(404, { detail: 'no profile' }));
  const result = await loadNutritionProfile({ ...live, fetcher });
  assert.equal(result.delivery, 'READY');
  assert.equal(result.environment, 'LIVE');
  assert.deepEqual(result.data, { presence: 'ABSENT' });
});

test('cookie goes only to the BFF; delegation only to Nutrition; both no-store and manual redirect', async () => {
  const { calls, fetcher } = scripted(minted(), json(200, PROFILE));
  const result = await loadNutritionProfile({ ...live, fetcher });
  const bffHeaders = calls[0].init?.headers as Record<string, string>;
  const nutritionHeaders = calls[1].init?.headers as Record<string, string>;
  assert.equal(bffHeaders.Cookie, 'episteck_home_session=opaque-session');
  assert.equal('X-Episteck-Delegation' in bffHeaders, false);
  assert.equal(nutritionHeaders['X-Episteck-Delegation'], 'tok-opaque');
  assert.equal('Cookie' in nutritionHeaders, false);
  for (const call of calls) {
    assert.equal(call.init?.cache, 'no-store');
    assert.equal(call.init?.redirect, 'manual');
  }
  assert.equal(JSON.stringify(result).includes('tok-opaque'), false);
});

test('subject is URL-encoded into the Nutrition path', async () => {
  const { calls, fetcher } = scripted(minted(), json(404, { detail: 'no profile' }));
  await loadNutritionProfile({ ...live, personId: 'PSN-A-1', fetcher });
  assert.equal(calls[1].url, 'http://127.0.0.1:9930/profile/PSN-A-1');
});

test('MOCK makes no network calls', async () => {
  const { calls, fetcher } = scripted();
  const result = await loadNutritionProfile({ ...live, mode: 'MOCK', fetcher });
  assert.equal(calls.length, 0);
  assert.equal(result.environment, 'MOCK');
});

const noNetwork: Array<[string, Partial<LoadNutritionProfileOptions>, string]> = [
  ['no cookie', { cookieValue: undefined }, 'SESSION_REQUIRED'],
  ['invalid person id', { personId: 'PSN/../x' }, 'INVALID_RESPONSE'],
  ['missing Nutrition origin', { nutritionBaseUrl: undefined }, 'NOT_CONFIGURED'],
  ['missing BFF origin', { bffBaseUrl: undefined }, 'NOT_CONFIGURED'],
];
for (const [name, override, code] of noNetwork) {
  test(`${name}: ${code} with no network call`, async () => {
    const { calls, fetcher } = scripted();
    const result = await loadNutritionProfile({ ...live, ...override, fetcher });
    assert.equal(calls.length, 0);
    assert.equal(result.errorCode, code);
    assert.equal(result.data, undefined);
  });
}

const mintFailures: Array<[string, Response | Error, string]> = [
  ['BFF 401 (expired or invalid session)', json(401, { detail: 'no active session' }), 'SESSION_INVALID'],
  ['BFF 500', json(500, {}), 'SERVICE_UNAVAILABLE'],
  ['BFF unreachable', new TypeError('fetch failed'), 'SERVICE_UNAVAILABLE'],
  ['BFF non-JSON', new Response('<html>', { status: 200 }), 'INVALID_RESPONSE'],
  ['BFF missing delegation', json(200, { audience: 'svc-nutrition' }), 'INVALID_RESPONSE'],
  ['BFF empty delegation', json(200, { delegation: '', audience: 'svc-nutrition' }), 'INVALID_RESPONSE'],
  ['BFF wrong audience', json(200, { delegation: 'tok', audience: 'home-control-plane' }), 'INVALID_RESPONSE'],
];
for (const [name, response, code] of mintFailures) {
  test(`mint failure (${name}) maps to ${code} and never calls Nutrition`, async () => {
    const { calls, fetcher } = scripted(response);
    const result = await loadNutritionProfile({ ...live, fetcher });
    assert.equal(calls.length, 1);
    assert.equal(result.errorCode, code);
    assert.equal(result.data, undefined);
  });
}

const nutritionOutcomes: Array<[string, Response | Error, string, string]> = [
  ['403 denial', json(403, { detail: 'ACCESS_DENIED' }), 'ACCESS_DENIED', 'DENIED'],
  ['401 invalid or expired delegation', json(401, { detail: 'SESSION_INVALID' }), 'SESSION_INVALID', 'INDETERMINATE'],
  ['503 policy unavailable', json(503, { detail: 'SERVICE_UNAVAILABLE' }), 'SERVICE_UNAVAILABLE', 'INDETERMINATE'],
  ['500 crash', json(500, {}), 'SERVICE_UNAVAILABLE', 'INDETERMINATE'],
  ['unreachable', new TypeError('fetch failed'), 'SERVICE_UNAVAILABLE', 'INDETERMINATE'],
  ['malformed 200', json(200, { context: 'general' }), 'INVALID_RESPONSE', 'INDETERMINATE'],
  ['non-JSON 200', new Response('<html>', { status: 200 }), 'INVALID_RESPONSE', 'INDETERMINATE'],
  ['route-missing 404', json(404, { detail: 'Not Found' }), 'INVALID_RESPONSE', 'INDETERMINATE'],
  ['unexpected 302', new Response(null, { status: 302 }), 'INVALID_RESPONSE', 'INDETERMINATE'],
];
for (const [name, response, code, authorization] of nutritionOutcomes) {
  test(`Nutrition ${name} maps to ${code} with no data`, async () => {
    const { calls, fetcher } = scripted(minted(), response);
    const result = await loadNutritionProfile({ ...live, fetcher });
    assert.equal(calls.length, 2);
    assert.equal(result.delivery, 'ERROR');
    assert.equal(result.errorCode, code);
    assert.equal(result.authorization, authorization);
    assert.equal(result.data, undefined);
  });
}
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/integration/nutrition/profile-loader.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `profile-loader.ts`

```ts
import type { DataEnvelope } from '../state/DataEnvelope';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode';
import { isAbsentProfileBody, parseProfileWire, type ProfileSummary } from './profile-contract.ts';

const NUTRITION_AUDIENCE = 'svc-nutrition';
const DELEGATION_HEADER = 'X-Episteck-Delegation';
const PERSON_ID = /^[A-Za-z0-9-]{1,64}$/;

export interface LoadNutritionProfileOptions {
  mode: 'MOCK' | 'LIVE';
  personId: string;
  cookieValue: string | undefined;
  bffBaseUrl: string | undefined;
  nutritionBaseUrl: string | undefined;
  fetcher: typeof fetch;
}

type Envelope = DataEnvelope<ProfileSummary>;

function ready(data: ProfileSummary, environment: 'MOCK' | 'LIVE'): Envelope {
  return { delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data };
}

function failed(errorCode: SafeUIErrorCode): Envelope {
  return {
    delivery: 'ERROR',
    authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE',
    freshness: 'UNKNOWN',
    environment: 'LIVE',
    errorCode,
  };
}

async function readJson(response: Response): Promise<{ ok: true; body: unknown } | { ok: false }> {
  try {
    return { ok: true, body: await response.json() };
  } catch {
    return { ok: false };
  }
}

/** One delegation for one Nutrition call. Never retried, logged, or returned. */
async function mintDelegation(
  options: LoadNutritionProfileOptions & { bffBaseUrl: string; cookieValue: string },
): Promise<{ token: string } | { error: SafeUIErrorCode }> {
  let response: Response;
  try {
    response = await options.fetcher(
      new URL(`/delegation?audience=${NUTRITION_AUDIENCE}`, options.bffBaseUrl).toString(),
      {
        method: 'POST',
        cache: 'no-store',
        redirect: 'manual',
        headers: { Accept: 'application/json', Cookie: `episteck_home_session=${options.cookieValue}` },
      },
    );
  } catch {
    return { error: 'SERVICE_UNAVAILABLE' };
  }
  if (response.status === 401) return { error: 'SESSION_INVALID' };
  if (response.status !== 200) return { error: 'SERVICE_UNAVAILABLE' };
  const parsed = await readJson(response);
  if (!parsed.ok || typeof parsed.body !== 'object' || parsed.body === null) return { error: 'INVALID_RESPONSE' };
  const { delegation, audience } = parsed.body as Record<string, unknown>;
  if (typeof delegation !== 'string' || delegation.length === 0 || audience !== NUTRITION_AUDIENCE) {
    return { error: 'INVALID_RESPONSE' };
  }
  return { token: delegation };
}

/**
 * Read one Person's Nutrition profile summary for the current session.
 * No actor, domain, or action input exists: Home derives the actor, Nutrition fixes
 * NUTRITION/VIEW, and the subject is the already-validated active context.
 */
export async function loadNutritionProfile(options: LoadNutritionProfileOptions): Promise<Envelope> {
  if (options.mode === 'MOCK') return ready({ presence: 'ABSENT' }, 'MOCK');
  if (!options.bffBaseUrl || !options.nutritionBaseUrl) return failed('NOT_CONFIGURED');
  if (!options.cookieValue) return failed('SESSION_REQUIRED');
  if (!PERSON_ID.test(options.personId)) return failed('INVALID_RESPONSE');

  const minted = await mintDelegation({
    ...options,
    bffBaseUrl: options.bffBaseUrl,
    cookieValue: options.cookieValue,
  });
  if ('error' in minted) return failed(minted.error);

  let response: Response;
  try {
    response = await options.fetcher(
      new URL(`/profile/${encodeURIComponent(options.personId)}`, options.nutritionBaseUrl).toString(),
      {
        method: 'GET',
        cache: 'no-store',
        redirect: 'manual',
        headers: { Accept: 'application/json', [DELEGATION_HEADER]: minted.token },
      },
    );
  } catch {
    return failed('SERVICE_UNAVAILABLE');
  }

  if (response.status === 403) return failed('ACCESS_DENIED');
  if (response.status === 401) return failed('SESSION_INVALID');
  if (response.status >= 500) return failed('SERVICE_UNAVAILABLE');
  if (response.status !== 200 && response.status !== 404) return failed('INVALID_RESPONSE');

  const parsed = await readJson(response);
  if (!parsed.ok) return failed('INVALID_RESPONSE');
  if (response.status === 404) {
    return isAbsentProfileBody(parsed.body) ? ready({ presence: 'ABSENT' }, 'LIVE') : failed('INVALID_RESPONSE');
  }
  try {
    return ready(parseProfileWire(parsed.body), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE');
  }
}
```

Note: the "no-network" order in the tests expects `NOT_CONFIGURED` to be checked before `SESSION_REQUIRED`. The `no cookie` case supplies both origins, so it still yields `SESSION_REQUIRED`.

- [ ] **Step 4: Run** — `npm test -- src/integration/nutrition/profile-loader.test.ts` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub/src/integration/nutrition/profile-loader.ts apps/home-hub/src/integration/nutrition/profile-loader.test.ts
git commit -m "feat(home-hub): add single-call Nutrition profile loader"
```

### Task 11: Server-only wrapper and boundary proof

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/profile.server.ts`
- Modify: `apps/home-hub/test-support/verify-server-only-client-import.mjs`

**Interfaces:**
- Consumes: `loadNutritionProfile`, `SERVER_CONFIGURATION`, `F3ActiveContext`.
- Produces: `readNutritionProfile(context: F3ActiveContext): Promise<DataEnvelope<ProfileSummary>>` (server-only; F3c consumes it).

- [ ] **Step 1: Extend the boundary probe first** so it fails while the module is missing

In `verify-server-only-client-import.mjs`, define

```js
const PROBES = [
  ['@/integration/home/bootstrap.server', 'getBootstrapForRequest'],
  ['@/integration/nutrition/profile.server', 'readNutritionProfile'],
];
```

Wrap the existing write-probe → `next build` → assert block in `for (const [modulePath, exportName] of PROBES) { ... }`, generating the client file as:

```js
`'use client';\nimport { ${exportName} } from '${modulePath}';\nexport function Probe() { return <button onClick={() => void ${exportName}()}>probe</button>; }\n`
```

Keep the existing assertion that the build fails because of the `server-only` import, so it applies to each probe. Clean up the probe directory after each iteration.

- [ ] **Step 2: Run to verify failure**

Run: `npm run test:server-boundary`
Expected: FAIL for the Nutrition probe, because the build error is "module not found" rather than the `server-only` violation the assertion requires.

- [ ] **Step 3: Implement** `profile.server.ts`

```ts
import 'server-only';
import { cookies } from 'next/headers';
import type { F3ActiveContext } from '../home/active-context';
import { SERVER_CONFIGURATION } from '../state/Environment.server';
import { loadNutritionProfile } from './profile-loader';

/** Server-only: read the active Person's Nutrition profile summary for this request. */
export async function readNutritionProfile(context: F3ActiveContext) {
  const cookieValue = SERVER_CONFIGURATION.mode === 'LIVE'
    ? (await cookies()).get('episteck_home_session')?.value
    : undefined;
  return loadNutritionProfile({
    mode: SERVER_CONFIGURATION.mode,
    personId: context.personId,
    cookieValue,
    bffBaseUrl: SERVER_CONFIGURATION.bffBaseUrl,
    nutritionBaseUrl: SERVER_CONFIGURATION.nutritionBaseUrl,
    fetcher: fetch,
  });
}
```

- [ ] **Step 4: Run** — `npm run test:server-boundary` → PASS. Then `npm test` and `npm run build` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub/src/integration/nutrition/profile.server.ts apps/home-hub/test-support/verify-server-only-client-import.mjs
git commit -m "feat(home-hub): add server-only Nutrition profile reader"
```

### Task 12: Quadlet, runbook, and PR

**Files:**
- Modify: `deploy/home-hub/svc-home-hub.container`
- Modify: `deploy/home-hub/tests/test_home_hub_quadlet.py`
- Modify: `deploy/home-hub/README.md` ("Pre-rollout VERIFY LIVE gate")

- [ ] **Step 1: Update the tests first**

In `test_hub_quadlet_publishes_only_loopback_and_uses_single_port_pasta`, rename it to `..._uses_narrow_pasta_forwards` and replace the network assertion:

```python
    assert 'Network=pasta:-T,9933,-T,9930' in QUADLET
    assert QUADLET.count('Network=') == 1
```

In `test_hub_quadlet_is_live_and_does_not_embed_upstream_secrets`, add:

```python
    assert 'HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930' in QUADLET
```

In `test_deployment_runbook_contains_unrun_live_isolation_proofs`, replace the last three assertions:

```python
    assert '--network pasta:-T,9933,-T,9930' in runbook
    assert '[9931,9932,9934]' in runbook
    assert '127.0.0.1:9930/health' in runbook
    assert 'HOST_PUBLIC_IP:9940' in runbook
```

Run: `python -m pytest deploy/home-hub/tests -q` → FAIL.

- [ ] **Step 2: Update the Quadlet**

```ini
Network=pasta:-T,9933,-T,9930
Environment=HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930
```

(Replace the existing `Network=` line; add the `Environment=` line after `HOME_HUB_BFF_BASE_URL`.)

- [ ] **Step 3: Update the runbook's VERIFY LIVE gate**

Change both probe commands to `--network pasta:-T,9933,-T,9930`. Change the blocked list to `const ports=[9931,9932,9934];`. Add a Nutrition reachability probe after the BFF one:

```bash
sudo -u svc-home-hub podman run --rm --network pasta:-T,9933,-T,9930 \
  --entrypoint node localhost/episteck-home-hub:COMMIT_SHA \
  -e 'fetch("http://127.0.0.1:9930/health").then(r => { console.log(r.status); process.exit(r.status === 200 ? 0 : 1) }).catch(() => process.exit(1))'
```

Update the "Expected" paragraph: BFF and Nutrition health return 200; 9931/9932/9934 refuse or time out; external `HOST_PUBLIC_IP:9930` and `:9940` cannot connect.

- [ ] **Step 4: Run all checks**

```bash
python -m pytest deploy/home-hub/tests -q
cd apps/home-hub && npm test && npm run test:server-boundary && npm run test:startup-config && npm run build && cd ../..
```

Expected: all PASS.

- [ ] **Step 5: Commit, then hold the PR until R3 step 1 passes**

```bash
git add deploy/home-hub
git commit -m "feat(home-hub): forward only BFF and Nutrition ports to the Hub"
git push -u origin feature/home-f3b3-hub-nutrition-adapter
```

Open the PR only after R3 step 1 proves the pasta form. If step 1 requires a different spelling, change the Quadlet, tests, and runbook to that exact form first.

## Rollout gate R3 (operator-run deploy; Claude runs read-only checks and throwaway probes)

- [ ] **1. Resolve pasta (before PR/merge).** As `svc-home-hub`, with the current image `localhost/episteck-home-hub:b1a3d5f…`, run the three runbook probes with `--network pasta:-T,9933,-T,9930` in throwaway `--rm` containers. Required: BFF 200, Nutrition 200, 9931/9932/9934 blocked. If they fail, **stop**: no merge, no rollout; return the evidence for a transport decision. `Network=host` is not a fallback.
- [ ] **2. Baseline.** Re-run the F3a baseline checks from the spec ("Pre-rollout baseline evidence"); the live Hub must still be the F3a image with an unchanged Quadlet hash.
- [ ] **3. Build.** Merge the PR; clean host checkout of the merge SHA; rootless build as `svc-home-hub`; repeat the step-1 probes with the **new** image.
- [ ] **4. Apply.** Back up the Quadlet to `/var/backups/episteck/home-f3b3-<sha>/`. Operator applies `Image=`, `Network=`, and `Environment=HOME_HUB_NUTRITION_BASE_URL` together; the diff against the backup must be exactly those three lines. Reload, restart.
- [ ] **5. Verify from the running Hub.** `podman exec` probes: 9933 200, 9930 200, 9931/9932/9934 blocked. Host `ss`: 9930/9933/9940 on `127.0.0.1` only. External direct `91.98.132.9:9930` and `:9940` time out. Anonymous `/app` 307 to login. Logged-in spot check: self default and stale → self (F3a).
- [ ] **6. Restart verification.** `systemctl --user restart svc-home-hub` once more; repeat step 5's container probes and the `/app` check; `NRestarts=0` beyond the deliberate restarts; logs free of `PSN-`, token, cookie, and bearer patterns.
- [ ] **7. Record evidence** in `deploy/home-hub/README.md` under "F3b live rollout (date)" in a follow-up docs PR.
- **Rollback (any failure in 3–6):** restore the saved Quadlet byte for byte, reload, restart; re-run step 5 expecting the old topology (9930 **blocked** from the Hub). The previous image stays on the host.

No end-to-end profile read is claimed in F3b; F3c makes the first live read.

---

## Self-review record

- **Spec coverage:**
  - Guard: Task 1. D1 audience: Tasks 2–4. Docs: Task 5. R1.
  - Outcome tables and rule R: Tasks 6–7. Logging: Task 6. R2.
  - Config: Task 8. Contract: Task 9. Loader: Task 10. Server wrapper: Task 11. Transport: Task 12. R3.
  - Pre-rollout F3a baseline: R3 step 2.
  - No gaps found.
- **Placeholders:** the PR body is referenced as "prepared body per template", which follows `.claude/rules/git-and-branching.md`. No other placeholders.
- **Type consistency:**
  - `accept_audiences`, `POLICY_AUDIENCES` and `DEFAULT_AUDIENCES` are used identically in Tasks 3–4.
  - `ALLOW/DENY/SESSION_INVALID/UNAVAILABLE` and `AccessDecision(allow, reason, outcome)` are used identically in Tasks 6–7.
  - `ProfileSummary`, `parseProfileWire`, `isAbsentProfileBody`, `loadNutritionProfile`, `LoadNutritionProfileOptions` and `nutritionBaseUrl` are used identically in Tasks 8–11.
- **Review Focus:** each of the five lines has a pinning test in its owning task (Task 9 string targets; Task 8 production config; Task 4 control-plane acceptance; Task 10 mint shape; Task 6 log category).
