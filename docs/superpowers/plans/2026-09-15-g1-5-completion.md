# Stage G1.5 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Stage G1.5 by delivering actor-aware Home business APIs, a thin Home MCP adapter, centralized Nutrition authorization, Knowledge/ContextBundle contracts, synthetic live validation, and current architecture documentation.

**Architecture:** Frappe Home remains the only Home Control Plane and canonical consent authority. An unprivileged Home MCP adapter and `svc-nutrition` call its business API over Tailscale with machine credentials hidden from `home-agent`; every sensitive retrieval is preceded by actor-aware authorization. Knowledge remains dependency-free contracts only.

**Tech Stack:** Python 3.11+, Frappe 15, FastMCP, FastAPI, httpx, pytest, rootless Podman/Quadlet, Hermes, Tailscale.

**Spec:** `docs/architecture/ARCHITECTURE.md`, `SECURITY_AND_CONSENT.md`, `KNOWLEDGE.md`, `DATA_OWNERSHIP.md`, ADR-0001, ADR-0006, ADR-0007, ADR-0008, and the approved 2026-09-15 execution design.

## Global Constraints

- Do not create `svc-home-core`; Frappe Home remains the canonical Control Plane.
- All validation data is synthetic; do not begin G2 or create real family/pregnancy data.
- Explicit `actor_person_id` is permitted only for synthetic G1.5; authoritative actor/session binding is a hard G2 blocker.
- Authorization must occur before sensitive retrieval.
- Home Agent receives business-safe MCP tools only and never receives Frappe credentials or consent-mutation tools.
- Nutrition authorization fails closed on unavailable, malformed, unknown, wrong actor, wrong subject, wrong domain, expired, or revoked decisions.
- Nutrition-local consent may remain only as migration/audit data after cutover and must not influence authorization.
- Do not install Mem0, Graphiti, RAGFlow, PostgreSQL/pgvector, or Docling.
- Application changes flow branch -> PR -> `main`; never edit the deployed Frappe app directly.

---

### Task 1: Actor-aware Home Core API

**Files:**
- Modify: `apps/episteck_home/episteck_home/api.py`
- Create: `apps/episteck_home/tests/test_home_api_security.py`

**Interfaces:**
- Consumes: Frappe session user, `home_control_plane_service_users`, Person/Circle/Care/Consent metadata.
- Produces: actor-aware `check_access`, `get_person`, `list_my_circles`, `list_circle_members`, `list_people_i_care_for`, `get_access_to_person`, `get_care_dashboard`.

- [ ] **Step 1: Write failing API security tests**

```python
def test_get_person_denies_unrelated_before_loading_person(fake_frappe):
    with pytest.raises(fake_frappe.DoesNotExistError):
        api.get_person("PSN-OTHER", actor_person_id="PSN-ACTOR")
    assert fake_frappe.loaded_person_ids == []

def test_machine_actor_requires_allowlisted_unlinked_user(fake_frappe):
    fake_frappe.session.user = "unknown-service@example.invalid"
    with pytest.raises(fake_frappe.PermissionError):
        api.list_my_circles(actor_person_id="PSN-ACTOR")

def test_list_circle_members_requires_actor_membership(fake_frappe):
    with pytest.raises(fake_frappe.DoesNotExistError):
        api.list_circle_members("CIR-OTHER", actor_person_id="PSN-ACTOR")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `$env:PYTHONPATH='apps/episteck_home'; python -m pytest apps/episteck_home/tests/test_home_api_security.py -q`

Expected: FAIL because actor-aware arguments and pre-retrieval visibility enforcement do not exist.

- [ ] **Step 3: Implement minimal actor and discovery enforcement**

```python
def _actor(actor_person_id: str | None = None) -> str:
    user = frappe.session.user
    linked_person = frappe.db.get_value("Person", {"linked_user": user}, "name")
    if linked_person:
        if actor_person_id and actor_person_id != linked_person:
            frappe.throw("actor mismatch", frappe.PermissionError)
        return linked_person
    allowed_users = set(frappe.conf.get("home_control_plane_service_users") or [])
    if user not in allowed_users or not actor_person_id:
        frappe.throw("actor binding required", frappe.PermissionError)
    if not frappe.db.exists("Person", actor_person_id):
        _not_found()
    return actor_person_id

def get_person(person_id: str, actor_person_id: str | None = None):
    actor = _actor(actor_person_id)
    if not _can_discover_person(actor, person_id):
        _not_found()
    person = frappe.get_doc("Person", person_id)
    return {"person_id": person.name, "full_name": person.full_name,
            "external_ref": person.external_ref}
```

Use only relationship/grant metadata to determine visibility before loading Person data. Require actor membership before retrieving a circle's member list. Filter care relationships to the actor before returning them.

- [ ] **Step 4: Run focused and Home policy tests**

Run: `$env:PYTHONPATH='apps/episteck_home'; python -m pytest apps/episteck_home/tests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/episteck_home/episteck_home/api.py apps/episteck_home/tests/test_home_api_security.py
git commit -m "feat(home): enforce actor-aware business API visibility"
```

### Task 2: Thin Home MCP adapter

**Files:**
- Create: `services/home-mcp/pyproject.toml`
- Create: `services/home-mcp/Dockerfile`
- Create: `services/home-mcp/home_mcp/__init__.py`
- Create: `services/home-mcp/home_mcp/client.py`
- Create: `services/home-mcp/home_mcp/server.py`
- Create: `services/home-mcp/tests/test_client.py`

**Interfaces:**
- Consumes: `HOME_CONTROL_PLANE_URL`, `HOME_API_KEY`, `HOME_API_SECRET`.
- Produces: exactly seven business MCP tools; no consent mutation, raw HTTP, SQL, filesystem, or credentials.

- [ ] **Step 1: Write failing client contract tests**

```python
def test_get_person_sends_actor_and_person(mock_transport):
    client = HomeControlPlaneClient(
        "https://home.episteck.com", "api-key", "api-secret", transport=mock_transport
    )
    result = client.get_person("PSN-ACTOR", "PSN-SUBJECT")
    assert result == {"person_id": "PSN-SUBJECT", "full_name": "Synthetic"}

def test_transport_failure_returns_safe_error(mock_transport):
    client = HomeControlPlaneClient(
        "https://home.episteck.com", "api-key", "api-secret", transport=mock_transport
    )
    result = client.list_my_circles("PSN-ACTOR")
    assert result == {"ok": False, "error": "home_control_plane_unavailable"}
```

- [ ] **Step 2: Run and verify RED**

Run: `$env:PYTHONPATH='services/home-mcp'; python -m pytest services/home-mcp/tests -q`

Expected: FAIL because `home_mcp` does not exist.

- [ ] **Step 3: Implement the Frappe RPC client and seven MCP tools**

```python
@mcp.tool
def get_person(actor_person_id: str, person_id: str) -> dict:
    return _client.get_person(actor_person_id, person_id)

@mcp.tool
def list_my_circles(actor_person_id: str) -> dict:
    return _client.list_my_circles(actor_person_id)

@mcp.tool
def list_circle_members(actor_person_id: str, circle_id: str) -> dict:
    return _client.list_circle_members(actor_person_id, circle_id)

@mcp.tool
def list_people_i_care_for(actor_person_id: str) -> dict:
    return _client.list_people_i_care_for(actor_person_id)

@mcp.tool
def get_access_to_person(actor_person_id: str, subject_person_id: str) -> dict:
    return _client.get_access_to_person(actor_person_id, subject_person_id)

@mcp.tool
def check_access(actor_person_id: str, subject_person_id: str, domain: str, action: str = "VIEW") -> dict:
    return _client.check_access(actor_person_id, subject_person_id, domain, action)

@mcp.tool
def get_care_dashboard(actor_person_id: str) -> dict:
    return _client.get_care_dashboard(actor_person_id)
```

- [ ] **Step 4: Run Home MCP tests**

Run: `$env:PYTHONPATH='services/home-mcp'; python -m pytest services/home-mcp/tests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/home-mcp
git commit -m "feat(home-mcp): expose business-safe Control Plane tools"
```

### Task 3: Dedicated Nutrition Home authorization client

**Files:**
- Create: `services/nutrition/app/home_control/__init__.py`
- Create: `services/nutrition/app/home_control/client.py`
- Create: `services/nutrition/tests/test_home_control_client.py`
- Modify: `services/nutrition/app/deps.py`

**Interfaces:**
- Produces: `AccessDecision(allow, reason)` and `HomeControlPlaneClient.check_access(actor, subject, domain, action)`.
- Consumes: the same Frappe RPC contract through a Nutrition-owned client.

- [ ] **Step 1: Write fail-closed client tests**

```python
@pytest.mark.parametrize("payload", [{}, {"message": {}}, {"message": {"allow": "yes"}}])
def test_malformed_decision_denies(payload):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    decision = HomeControlPlaneClient("https://home", "key", "secret", transport=transport).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW"
    )
    assert decision.allow is False

def test_timeout_denies():
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)
    decision = HomeControlPlaneClient(
        "https://home", "key", "secret", transport=httpx.MockTransport(timeout)
    ).check_access("PSN-A", "PSN-B", "NUTRITION", "VIEW")
    assert decision.allow is False

def test_http_error_denies():
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    decision = HomeControlPlaneClient("https://home", "key", "secret", transport=transport).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW"
    )
    assert decision.allow is False

def test_valid_allow_is_accepted():
    payload = {"message": {"allow": True, "reason": "grant NUTRITION/VIEW"}}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    decision = HomeControlPlaneClient("https://home", "key", "secret", transport=transport).check_access(
        "PSN-A", "PSN-B", "NUTRITION", "VIEW"
    )
    assert decision == AccessDecision(True, "grant NUTRITION/VIEW")
```

- [ ] **Step 2: Run and verify RED**

Run: `$env:PYTHONPATH='services/nutrition'; python -m pytest services/nutrition/tests/test_home_control_client.py -q`

Expected: FAIL because the client does not exist.

- [ ] **Step 3: Implement the minimal client**

```python
@dataclass(frozen=True)
class AccessDecision:
    allow: bool
    reason: str

def check_access(self, actor_person_id: str, subject_person_id: str,
                 domain: str, action: str) -> AccessDecision:
    try:
        response = self._client.get(
            "/api/method/episteck_home.api.check_access",
            params={"actor_person_id": actor_person_id,
                    "subject_person_id": subject_person_id,
                    "domain": domain, "action": action},
        )
        response.raise_for_status()
        decision = response.json()["message"]
        if type(decision.get("allow")) is not bool:
            raise ValueError("malformed authorization decision")
        return AccessDecision(decision["allow"], str(decision.get("reason", "")))
    except Exception:
        return AccessDecision(False, "authorization indeterminate (fail closed)")
```

- [ ] **Step 4: Run client tests**

Run: `$env:PYTHONPATH='services/nutrition'; python -m pytest services/nutrition/tests/test_home_control_client.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/nutrition/app/home_control services/nutrition/app/deps.py services/nutrition/tests/test_home_control_client.py
git commit -m "feat(nutrition): add fail-closed Home authorization client"
```

### Task 4: Cut Nutrition over before sensitive repository access

**Files:**
- Modify: `services/nutrition/app/service.py`
- Modify: `services/nutrition/app/main.py`
- Modify: `services/nutrition/app/mcp/server.py`
- Modify: `services/nutrition/app/store/repository.py`
- Modify: `services/nutrition/app/store/sqlite_repo.py`
- Modify: `services/nutrition/tests/test_service.py`
- Modify: `services/nutrition/tests/test_stage_f.py`
- Create: `services/nutrition/tests/test_authorization.py`

**Interfaces:**
- Every person-specific service method consumes `actor_person_id` and `subject_person_id`.
- Legacy consent records remain queryable for migration/audit but never affect access.

- [ ] **Step 1: Write failing authorization-order and denial tests**

```python
def test_denial_happens_before_profile_repository_read(spy_repo, denying_authorizer):
    with pytest.raises(PermissionError):
        service.get_profile("PSN-ACTOR", "PSN-SUBJECT")
    assert spy_repo.profile_reads == 0

@pytest.mark.parametrize(
    ("actor", "subject"),
    [("PSN-WRONG", "PSN-SUBJECT"), ("PSN-ACTOR", "PSN-WRONG")],
)
def test_cross_person_wrong_pair_denies(actor, subject, repo, scoped_authorizer):
    service = NutritionService(repo, SyntheticFoodProvider(), authorizer=scoped_authorizer)
    with pytest.raises(PermissionError):
        service.get_profile(actor, subject)

def test_legacy_consent_does_not_authorize(repo, denying_authorizer):
    repo.set_consent("PSN-SUBJECT", "NUTRITION", "GRANTED", "legacy")
    service = NutritionService(repo, SyntheticFoodProvider(), authorizer=denying_authorizer)
    with pytest.raises(PermissionError):
        service.get_profile("PSN-ACTOR", "PSN-SUBJECT")
```

- [ ] **Step 2: Run and verify RED**

Run: `$env:PYTHONPATH='packages/nutrition-domain/src;services/nutrition'; python -m pytest services/nutrition/tests/test_authorization.py -q`

Expected: FAIL because person-specific operations are not actor-aware.

- [ ] **Step 3: Add `_require_access` and authorize each sensitive method first**

```python
def _require_access(self, actor_person_id: str, subject_person_id: str, action: str) -> None:
    decision = self.authorizer.check_access(actor_person_id, subject_person_id, "NUTRITION", action)
    if not decision.allow:
        raise PermissionError(decision.reason)
```

Use VIEW for reads/planning and CREATE/UPDATE for mutations. Private calculation helpers may use already-authorized data but must not expose an unauthenticated public path.

- [ ] **Step 4: Update FastAPI and MCP inputs**

All person-specific routes/tools require explicit actor and subject. Remove consent mutation from MCP (none exists) and make the old FastAPI mutation return a deprecation response; keep read-only legacy consent inspection for migration.

- [ ] **Step 5: Run all Nutrition tests**

Run: `$env:PYTHONPATH='packages/nutrition-domain/src;services/nutrition'; python -m pytest services/nutrition/tests packages/nutrition-domain/tests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/nutrition packages/nutrition-domain/tests
git commit -m "feat(nutrition): centralize person access in Home Control Plane"
```

### Task 5: Pure Knowledge and ContextBundle contracts

**Files:**
- Create: `packages/home-contracts/pyproject.toml`
- Create: `packages/home-contracts/src/episteck_home_contracts/__init__.py`
- Create: `packages/home-contracts/src/episteck_home_contracts/knowledge.py`
- Create: `packages/home-contracts/src/episteck_home_contracts/context.py`
- Create: `packages/home-contracts/tests/test_knowledge.py`
- Create: `packages/home-contracts/tests/test_context.py`

**Interfaces:**
- Produces: `KnowledgeScope`, `KnowledgeEpisode`, `KnowledgeClaim`, `KnowledgeProvenance`, `KnowledgeStatus`, `ContextBundle` and source/reference authorization contracts.

- [ ] **Step 1: Write failing invariant tests**

```python
def test_hypothesis_confirmation_requires_explicit_confirmation_episode(hypothesis):
    with pytest.raises(ValueError, match="confirmation episode"):
        hypothesis.confirm("claim-confirmed", "", "PSN-ACTOR")

def test_claim_preserves_source_episode_and_provenance(hypothesis):
    confirmed = hypothesis.confirm("claim-confirmed", "episode-confirmation", "PSN-ACTOR")
    assert confirmed.provenance is KnowledgeProvenance.USER_CONFIRMED
    assert confirmed.source_episode_id == "episode-confirmation"
    assert confirmed.supersedes_claim_id == hypothesis.claim_id

def test_context_bundle_rejects_unauthorized_sensitive_context():
    context = StructuredDomainReference("PSN-B", "NUTRITION", "svc-nutrition", "profile", "PSN-B")
    with pytest.raises(ValueError, match="authorization"):
        ContextBundle(actor_person_id="PSN-A", subject_person_ids=("PSN-B",),
                      structured_domain_context=(context,))

def test_structured_truth_is_referenced_by_owner_and_record_id():
    reference = StructuredDomainReference("PSN-B", "NUTRITION", "svc-nutrition", "profile", "PSN-B")
    assert reference.owner_service == "svc-nutrition"
    assert reference.record_id == "PSN-B"
```

- [ ] **Step 2: Run and verify RED**

Run: `$env:PYTHONPATH='packages/home-contracts/src'; python -m pytest packages/home-contracts/tests -q`

Expected: FAIL because the package does not exist.

- [ ] **Step 3: Implement frozen enums/dataclasses and validation**

```python
class KnowledgeProvenance(str, Enum):
    USER_EXPLICIT = "USER_EXPLICIT"
    USER_CONFIRMED = "USER_CONFIRMED"
    IMPORTED_SOURCE = "IMPORTED_SOURCE"
    PROFESSIONAL_PROVIDED = "PROFESSIONAL_PROVIDED"
    SYSTEM_OBSERVED = "SYSTEM_OBSERVED"
    AI_HYPOTHESIS = "AI_HYPOTHESIS"
    AI_SUMMARY = "AI_SUMMARY"
    DERIVED = "DERIVED"

class KnowledgeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISPUTED = "DISPUTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
```

Model structured truth using source references, never durable copies. Require authorization evidence for every sensitive subject/domain represented in a ContextBundle.

- [ ] **Step 4: Run contract tests**

Run: `$env:PYTHONPATH='packages/home-contracts/src'; python -m pytest packages/home-contracts/tests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/home-contracts
git commit -m "feat(knowledge): formalize governance and ContextBundle contracts"
```

### Task 6: Documentation and deployment contract

**Files:**
- Modify: `docs/architecture/ARCHITECTURE.md`
- Modify: `docs/architecture/SECURITY_AND_CONSENT.md`
- Modify: `docs/architecture/KNOWLEDGE.md`
- Modify: `docs/architecture/DEPLOYMENT.md`
- Modify: `docs/architecture/ROADMAP.md`
- Modify: `docs/architecture/STATUS.md`
- Modify: `README.md`

**Interfaces:**
- Documents deployed truth, the actor-binding G2 blocker, sole authorization authority, credential boundaries, contracts, and verification commands.

- [ ] **Step 1: Update documentation from implementation evidence**

Record that explicit synthetic actors are G1.5-only. State that no real data may reach Home Agent until authenticated sessions are authoritatively bound to allowed actors. Mark Nutrition-local consent as migration/audit-only and list the Home MCP/runtime flow.

- [ ] **Step 2: Verify documentation consistency**

Run: `rg -n "PLANNED cutover|install in progress|to build|Nutrition currently has its own consent" docs/architecture`

Expected: no stale statements about completed G1.5 work.

- [ ] **Step 3: Verify forbidden runtime dependencies are absent**

Run: `rg -n -i "mem0|graphiti|ragflow|pgvector|docling" --glob 'pyproject.toml' --glob 'Dockerfile' --glob 'requirements*.txt' .`

Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/architecture
git commit -m "docs(architecture): record completed G1.5 security boundaries"
```

### Task 7: Review, PR, merge, and deployment

**Files:** Runtime provisioning only; do not edit `/home/frappe/frappe-bench/apps/episteck_home`.

**Interfaces:**
- Ashburn deployment consumes GitHub `main` through the existing deploy job.
- Nuremberg runs rootless Home MCP and rebuilt Nutrition containers from the merged SHA.

- [ ] **Step 1: Run full local verification**

Run all four suites plus `python -m compileall` for changed Python packages.

- [ ] **Step 2: Review the complete diff against requirements**

Run: `git diff --check origin/main HEAD`, `git status --short`, and inspect `git diff origin/main HEAD`.

- [ ] **Step 3: Push branch, open PR, and merge to `main`**

Use the repository PR workflow without force push or history rewriting.

- [ ] **Step 4: Provision least-privilege machine users and secrets**

Create separate Home MCP and Nutrition authorization API users with no DocType mutation permissions. Allowlist their usernames in Home site configuration. Store generated credentials only in owner-readable Nuremberg secret files; never print them or expose them to `home-agent`.

- [ ] **Step 5: Deploy through the approved flows**

Wait for the Ashburn GitHub-main deploy job; migrate if required. Build Nuremberg images from the merged SHA, install rootless Quadlets, map `home.episteck.com` to the Ashburn Tailscale IP, and restart only the affected user services.

### Task 8: Synthetic live and conversational validation

**Files:**
- Modify after measurements: `docs/architecture/STATUS.md`

**Interfaces:**
- Synthetic actor `PSN-00002` may view synthetic subject `PSN-00001` Nutrition only.
- Actual Home Agent invokes Home and Nutrition MCP tools.

- [ ] **Step 1: Verify live MCP tool inventory and secret isolation**

Confirm seven Home tools, actor-aware Nutrition tools, no consent mutation tool, and that `home-agent` cannot read either Frappe credential file.

- [ ] **Step 2: Run live allow/deny matrix**

Prove valid NUTRITION:VIEW allows; MIND, revoked grant, wrong actor, wrong subject, wrong domain, and unreachable/indeterminate Control Plane deny. Confirm repository reads remain zero in the automated pre-retrieval denial test.

- [ ] **Step 3: Run actual Home Agent conversations**

Ask the six required questions using explicit synthetic actor context. Confirm denial is respected without attempted escalation. Then perform a synthetic cross-person Nutrition read through Home Agent -> Nutrition MCP -> Home check_access -> Nutrition.

- [ ] **Step 4: Measure latency**

Capture Nuremberg -> Home API latency, `check_access` latency, and representative authorized Nutrition request latency. Do not add caching.

- [ ] **Step 5: Record final evidence and commit**

```bash
git add docs/architecture/STATUS.md
git commit -m "docs(status): record G1.5 live validation"
git push
```

- [ ] **Step 6: Final verification**

Run full tests from the final tree, confirm deployed SHA/configuration, confirm only synthetic IDs exist, and produce the requested 19-point final report. Stop before G2.
