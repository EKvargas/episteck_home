# Nutrition R1 · Plan 2: Per-person agent runtimes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a second agent, `home-agent-ana`, act as Ana and only as Ana, while the owner's agent and Finance keep working exactly as today.

**Architecture:**
- **Agent identity.** The agent's identity comes from the gateway port the call arrived on: 9934 is the owner's agent and 9937 is Ana's. The firewall ties each port to one Linux uid. nginx stamps `X-Runtime-ID` on the mint subrequest, and the caller can never set it.
- **BFF.** The BFF mints for the runtime named by that header. Grants record an opaque reference to the person who granted them, and each person sees, grants and revokes only their own agents.
- **Home.** Home decides per runtime who may grant it.

**Tech Stack:** Python 3.11, FastAPI, httpx, SQLite (stdlib), Frappe (whitelisted methods, site config only), nginx, nftables, pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-nutrition-release-1-design.md`, section 6.3 (also 6.1, 7 "Authorization", 8 item 3). This is plan 2 of 4. Plan 1 (diary backend) is merged (#136). Plan 3 covers Ana's agent, onboarding, the "Hoy" page and the production rollout. Plan 4 covers step B.

## Global Constraints

- **Runtime ids:** exactly `home-agent-primary` (the owner's agent) and `home-agent-ana` (Ana's). Ana's Linux user is `home-agent-ana`. The owner's Hermes uid stays `1003`.
- **Gateway ports:**
  - `127.0.0.1:9934` serves the owner's agent: home, nutrition and finance routes.
  - `127.0.0.1:9937` serves Ana's agent: `/gateway/home/` and `/gateway/nutrition/` only. It has **no Finance route**.
- **Runtime header:** the BFF reads the runtime from `X-Runtime-ID`, which only the nginx mint subrequest sets. Each mint location keeps `proxy_pass_request_headers off`.
- **Missing or unknown runtime:** returns 401 and **never** falls back to `home-agent-primary`.
- **Finance:** `/internal/mint_finance` mints only for `home-agent-primary`.
- **Grant audiences:**
  - `home-agent-primary` keeps `{"home-control-plane", "svc-nutrition", "svc-finance"}`, unchanged.
  - Every other runtime gets exactly `{"home-control-plane"}`, never Finance.
- **BFF config:** `RUNTIME_IDS` is a comma-separated env value. The default is `home-agent-primary`, and the list must contain `home-agent-primary`.
- **Legacy binding:** `RUNTIME_LEGACY_BINDING=on` together with more than one runtime is a startup error.
- **Home site config:**
  - New key `home_runtime_grantees_by_runtime`, a dict from runtime id to a list of Frappe User ids.
  - When the key is absent, today's `home_runtime_grantees` applies to `home-agent-primary` only, and every other runtime is denied.
  - When it is present, the dict is the only source.
  - A malformed value denies.
  - No Home schema change and no `bench migrate`.
- **Home deploys on merge to `main`.** With the new site-config key absent, Home's behaviour must stay identical to today.
- **Person reference:**
  - The reference is the hex HMAC-SHA256 of the Home **Person** id under the BFF delegation secret, with the label `b"episteck-person-ref\x00"` prefixed to the message.
  - It is computed at login from `whoami`'s `actor_person_id`.
  - An empty reference never matches anything.
  - The reference, the Person id and the user id are never logged, rendered or put in a cookie.
- **Legacy grant rows:** grant rows written before this plan have an empty `grantor_ref`. The mint keeps honouring them, so the owner's bot keeps working. The BFF shows them to nobody and revokes them for nobody. The rollout has the owner re-grant `home-agent-primary` right after the deploy, which replaces the row.
- **Logging:** log lines are static text. Only a configured, already-validated runtime id may appear in them; never a raw header value, token, session id, Person id or reference.
- **Delegations are unchanged:** 120 s lifetime, single use, no Person id in the claims.
- **UI copy is Spanish.** Keep the existing `/runtime` strings; add only the strings this plan gives.
- **Test commands** (Windows PowerShell; local Python `C:\AIProjects\episteck-delivery-workspace\.venvs\nutrition-r1\Scripts\python.exe`, abbreviated `PY`):
  - **BFF:** `cd services/home-bff; $env:PYTHONPATH="."; PY -m pytest -q -p no:cacheprovider tests`. Baseline 382 passed, 10 skipped.
  - **Home:** from the repo root, `$env:PYTHONPATH="apps/episteck_home"; PY -m pytest -q -p no:cacheprovider apps/episteck_home/tests/test_runtime_grant.py`.
  - **Deploy:** `PY -m pytest -q -p no:cacheprovider deploy/gateway/tests deploy/home-bff/tests`. Home plus gateway baseline: 71 passed, 6 skipped (the nginx tests need an nginx binary). `deploy/home-bff`: 25 passed.
- **Existing tests:** change them only where this plan says so: a new header, a person reference in a fixture, a renamed count. Never weaken an assertion.
- **Not in this plan:** nothing is deployed. Plan 3 runs the rollout.

## Review Focus

- **Ana opens `/runtime` while the owner holds a live grant.** She sees only her agent. The owner's expiry and "último uso" never appear on her page (Task 6).
- **Home is down while Ana revokes or uses "cerrar sesión en todas partes".** Only her grant row is removed; the owner's row is untouched (Task 6).
- **Ana's agent sends its own `X-Runtime-ID: home-agent-primary` to 9937.** The mint still receives `home-agent-ana` (Task 7).
- **A browser session from before the deploy tries to grant.** That session has no person reference. It is sent to log in again, and no grant row with an empty reference is ever written (Task 6).
- **Ana's agent loops and hits the mint limit.** Her mint answers 429 while the owner's mint still answers 204 (Task 4).

---

### Task 1: Home decides per runtime who may grant it

**Files:**
- Modify: `apps/episteck_home/episteck_home/identity/session.py`
- Test: `apps/episteck_home/tests/test_runtime_grant.py`

**Interfaces:**
- Produces:
  - `PRIMARY_RUNTIME_ID = "home-agent-primary"`.
  - `_grantees_for(runtime_id: str) -> list[str]`.
  - Whitelisted `get_grantable_runtimes() -> dict`, which returns `{"runtime_ids": [...]}` in `home_runtime_ids` order for the caller only. It takes no parameters and accepts `methods=["GET"]`. The BFF calls it at `/api/method/episteck_home.identity.session.get_grantable_runtimes`.
- `open_runtime_grant` keeps its signature. Its grantee check becomes `user not in _grantees_for(runtime_id)`.

- [ ] **Step 1: Write the failing tests.**
  - **Fake users.** Extend the fake `frappe` with `ANA = "ana@example.invalid"`: enabled, linked to `["PSN-0003"]`.
  - **Mapping fixture.** `MAP = {"home-agent-primary": [OWNER], "home-agent-ana": [ANA]}`, with `home_runtime_ids` set to `["home-agent-primary", "home-agent-ana"]`.

```python
def test_without_mapping_grantees_apply_to_primary_only(build): ...
    # conf: home_runtime_ids both, home_runtime_grantees [OWNER], no mapping
    # OWNER opens home-agent-primary: ok; OWNER opens home-agent-ana: PermissionError
def test_mapping_lets_each_person_grant_only_their_runtime(build): ...
    # ANA opens home-agent-ana: ok; ANA opens home-agent-primary: PermissionError
    # OWNER opens home-agent-primary: ok; OWNER opens home-agent-ana: PermissionError
def test_mapping_present_ignores_the_old_grantee_list(build): ...
    # mapping {"home-agent-ana": [ANA]}, home_runtime_grantees [OWNER] -> OWNER denied for primary
@pytest.mark.parametrize("bad", [[OWNER], "owner", 3, {"home-agent-primary": OWNER}])
def test_malformed_mapping_denies(build, bad): ...
def test_runtime_in_mapping_but_not_in_runtime_ids_is_denied(build): ...
def test_grantable_runtimes_lists_only_the_callers(build): ...
    # OWNER -> {"runtime_ids": ["home-agent-primary"]}; ANA -> {"runtime_ids": ["home-agent-ana"]}
def test_grantable_runtimes_without_mapping_matches_today(build): ...
    # no mapping, home_runtime_grantees [OWNER] -> OWNER ["home-agent-primary"]; ANA []
def test_grantable_runtimes_takes_no_parameters_and_denies_guest_and_unlinked(build): ...
    # inspect.signature has no parameters; Guest -> PermissionError; user with 0 people -> PermissionError
```

- [ ] **Step 2: Run the tests and confirm they fail.** Use the Home test command. The new tests should FAIL (`_grantees_for` and `get_grantable_runtimes` don't exist yet). Existing tests still pass.
- [ ] **Step 3: Implement `_grantees_for` and `get_grantable_runtimes`.**
  - `_grantees_for`:
    - Read `frappe.conf.get("home_runtime_grantees_by_runtime")`.
    - **Absent:** return `_conf_list("home_runtime_grantees", ())` for the primary runtime and `[]` for any other.
    - **Not a dict:** return `[]`.
    - **Dict, but the value for this runtime is not a list or tuple:** return `[]`.
  - `get_grantable_runtimes`:
    - Call `_require_human()` and `_require_single_linked_person(user)`.
    - Return the runtime ids in `_conf_list("home_runtime_ids", DEFAULT_RUNTIME_IDS)` whose `_grantees_for` contains the user.
  - Update the docstrings of `open_runtime_grant` and of the module section to describe the mapping.
- [ ] **Step 4: Run the tests and confirm they pass.** Use the Home test command. Expected: all pass.
- [ ] **Step 5: Commit.** Message: `feat: home decides per runtime who may grant it`, with the Claude-Session trailer.

---

### Task 2: BFF runtime registry and configuration

**Files:**
- Modify: `services/home-bff/home_bff/runtime.py`, `services/home-bff/home_bff/config.py`, `deploy/home-bff/home-bff.container`, `deploy/home-bff/home-bff-mint.container`
- Test: `services/home-bff/tests/test_runtime_registry.py` (create), `deploy/home-bff/tests/test_quadlets.py`

**Interfaces:**
- **`runtime.py` produces:**
  - `PRIMARY_RUNTIME_ID = "home-agent-primary"`.
  - `RUNTIME_ID = PRIMARY_RUNTIME_ID`. It is kept so existing imports keep meaning "the owner's agent".
  - `PRIMARY_GRANT_AUDIENCES = frozenset({"home-control-plane", "svc-nutrition", "svc-finance"})`.
  - `grant_audiences_for(runtime_id: str) -> frozenset[str]`: `PRIMARY_GRANT_AUDIENCES` for the primary runtime, otherwise `frozenset({"home-control-plane"})`.
  - `RUNTIME_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")`.
- **`config.py` produces:**
  - A new field, `Settings.runtime_ids: tuple[str, ...] = (PRIMARY_RUNTIME_ID,)`.
  - `parse_runtime_ids(raw: str) -> tuple[str, ...]`. It splits on `,`, strips, and drops empty parts. It raises `ConfigError` when an id doesn't match the pattern, when there are duplicates, or when `home-agent-primary` is missing. An empty or unset value yields the default.
  - `from_env` reads `RUNTIME_IDS`.
  - `Settings.__post_init__` raises `ConfigError("RUNTIME_LEGACY_BINDING must be off when more than one runtime is configured")` when `runtime_legacy_binding` is on and `len(runtime_ids) > 1`.

- [ ] **Step 1: Write the failing tests** in `test_runtime_registry.py`, using `make_settings` from `tests.test_app`:

```python
def test_primary_keeps_all_three_audiences():
    assert grant_audiences_for("home-agent-primary") == {"home-control-plane", "svc-nutrition", "svc-finance"}
def test_other_runtimes_get_the_control_plane_only():
    assert grant_audiences_for("home-agent-ana") == {"home-control-plane"}
def test_runtime_ids_default_and_parse():
    assert parse_runtime_ids("") == ("home-agent-primary",)
    assert parse_runtime_ids(" home-agent-primary , home-agent-ana ") == ("home-agent-primary", "home-agent-ana")
@pytest.mark.parametrize("raw", ["home-agent-ana", "home-agent-primary,home-agent-primary", "home-agent-primary,Ana!", "home-agent-primary,-x"])
def test_bad_runtime_ids_fail_startup(raw):
    with pytest.raises(ConfigError): parse_runtime_ids(raw)
def test_legacy_binding_with_two_runtimes_fails_startup():
    with pytest.raises(ConfigError):
        make_settings(runtime_ids=("home-agent-primary", "home-agent-ana"), runtime_legacy_binding=True)
def test_two_runtimes_with_legacy_off_is_valid():
    assert make_settings(runtime_ids=("home-agent-primary", "home-agent-ana"), runtime_legacy_binding=False).runtime_ids[1] == "home-agent-ana"
```

  In `test_quadlets.py`, add `test_both_units_carry_the_same_runtime_ids`. It asserts that `"Environment=RUNTIME_IDS=home-agent-primary,home-agent-ana"` appears in both `PUBLIC` and `MINT`.
- [ ] **Step 2: Run the tests and confirm they fail.** Use the BFF command on `tests/test_runtime_registry.py`, then the deploy command. Expected: FAIL (an ImportError and the missing Quadlet line).
- [ ] **Step 3: Implement the registry, the config parsing, and the two Quadlet lines.** Add one `Environment=RUNTIME_IDS=home-agent-primary,home-agent-ana` line to each unit, next to its `RUNTIME_LEGACY_BINDING` line. Listing `home-agent-ana` before Home or the gateway know it is harmless: Home refuses the grant, and the mint answers 401 without a grant.
- [ ] **Step 4: Run the tests and confirm they pass.** Run the full BFF suite and the deploy tests. Expected: all pass, BFF 382 + new.
- [ ] **Step 5: Commit.** Message: `feat: configure the bff runtime list and per-runtime audiences`.

---

### Task 3: Store the person reference on sessions and grants

**Files:**
- Modify: `services/home-bff/home_bff/store.py`
- Test: `services/home-bff/tests/test_store_person_ref.py` (create)

**Interfaces:**
- **Data classes:**
  - `Session` gains `person_ref: str = ""` as its last field.
  - `RuntimeGrant` gains `grantor_ref: str = ""` as its last field.
- **Columns and migration.** New columns `bff_session.person_ref` and `runtime_grant.grantor_ref`, both `TEXT NOT NULL DEFAULT ''`. Put them in `_SCHEMA`, and add an idempotent `ALTER TABLE` for each, using the same duplicate-column tolerance as `_migrate_login_binding_hash`.
- **Changed methods:**
  - `create_session(..., person_ref: str = "")`.
  - `create_session_and_claim_runtime(..., person_ref: str = "")`.
  - `get_session` and `_session_from_row` return `person_ref`.
  - `put_runtime_grant(..., ttl_seconds: int, grantor_ref: str = "")`.
  - `resolve_runtime_grant` returns `grantor_ref`.
- **New and extended methods:**
  - `list_runtime_grants_for(person_ref: str) -> list[RuntimeGrant]`: live rows (`expires_at > now`) whose `grantor_ref == person_ref`, ordered by `runtime_id`. An empty `person_ref` returns `[]`.
  - `delete_runtime_grant(runtime_id: str, *, home_session_id: str | None = None) -> bool`. With `home_session_id`, it deletes only while the row still points at that Home session.

- [ ] **Step 1: Write the failing tests:**

```python
def test_old_store_file_gains_both_columns_with_empty_defaults(tmp_path): ...
    # create the pre-plan schema by hand (copy _SCHEMA without the two columns), insert one
    # session and one grant, open SessionStore on it: both rows readable, person_ref == "" and grantor_ref == ""
def test_session_and_grant_round_trip_their_refs(tmp_path): ...
def test_list_grants_for_returns_only_live_rows_of_that_person(tmp_path): ...
    # rows: (primary, ref A, live), (ana, ref B, live), (x, ref B, expired), (y, "", live)
    # list_runtime_grants_for("B") -> [ana]; list_runtime_grants_for("") -> []
def test_conditional_delete_keeps_a_newer_grant(tmp_path): ...
    # put ana -> HDS-1; put ana -> HDS-2; delete_runtime_grant("home-agent-ana", home_session_id="HDS-1") is False; row still HDS-2
def test_unconditional_delete_still_works(tmp_path): ...
def test_two_processes_migrating_the_same_file_both_succeed(tmp_path): ...
    # open two SessionStore objects on one pre-plan file in sequence: no error
```

- [ ] **Step 2: Run the tests and confirm they fail.** Use the BFF command on `tests/test_store_person_ref.py`. Expected: FAIL.
- [ ] **Step 3: Implement the columns, the migrations and the methods.**
- [ ] **Step 4: Run the tests and confirm they pass.** Run the full BFF suite. Expected: all pass, with existing store tests unchanged.
- [ ] **Step 5: Commit.** Message: `feat: store the granting person's reference with each grant`.

---

### Task 4: Mint for the runtime the gateway names

**Files:**
- Modify: `services/home-bff/home_bff/internal_app.py`
- Test: `services/home-bff/tests/test_mint_per_runtime.py` (create). Also update `services/home-bff/tests/test_internal_mint.py`, `services/home-bff/tests/test_runtime_grant_mint.py` and `services/home-bff/tests/test_runtime_routes.py` (the `_mint` helper).

**Interfaces:**
- Consumes: `Settings.runtime_ids` and `PRIMARY_RUNTIME_ID` (Task 2).
- Produces: `RUNTIME_HEADER = "X-Runtime-ID"`. `create_internal_app` keeps its signature.
- **One limiter per configured runtime:** `{rid: _MinuteLimiter(MINT_LIMIT_PER_MINUTE, clock) for rid in settings.runtime_ids}`.
- **`POST /internal/mint`:**
  1. A header value that isn't in `settings.runtime_ids` (missing, empty or unknown) returns 401 `"no active runtime grant"` and logs the static line `"mint refused: unknown runtime"`. The limiter isn't checked and the store isn't touched.
  2. Check that runtime's limiter.
  3. Call `resolve_runtime_grant(rid)`. The audience check and the touch work as today.
  4. The legacy binding fallback applies only when the flag is on **and** `rid == PRIMARY_RUNTIME_ID`.
- **`POST /internal/mint_finance`:** any header other than exactly `home-agent-primary` returns 401 before anything else. It uses the primary's limiter.

- [ ] **Step 1: Write the failing tests** in `test_mint_per_runtime.py`. Use the settings `runtime_ids=("home-agent-primary", "home-agent-ana"), runtime_legacy_binding=False`. Grants: primary → `HDS-OWNER` with primary audiences; ana → `HDS-ANA` with `{"home-control-plane"}`.

```python
def test_missing_or_unknown_runtime_header_is_401_and_never_the_primary(mint): ...
    # no header, "", "home-agent-other", "HOME-AGENT-PRIMARY" -> 401 each, even with the primary grant live
def test_ana_header_mints_for_anas_grant_only(mint): ...
    # claims sid == "HDS-ANA"
def test_ana_without_grant_is_401_while_primary_grant_is_live(mint): ...
def test_primary_header_mints_for_the_owner_as_before(mint): ...
def test_finance_mint_refuses_any_runtime_but_primary(mint): ...
    # ana grant stored WITH svc-finance in its audiences (forced via the store): header ana -> 401; no header -> 401
def test_finance_mint_for_primary_unchanged(mint): ...
def test_each_runtime_has_its_own_rate_limit(mint_with_clock): ...
    # 600 ana mints -> 204; 601st ana -> 429; primary -> 204 in the same minute
def test_unknown_runtime_log_line_is_static(mint, caplog): ...
    # header "evil-value" -> log text contains "mint refused: unknown runtime" and not "evil-value"
def test_legacy_row_without_ref_still_mints_for_primary(mint): ...
    # put_runtime_grant(primary, "HDS-LEGACY", audiences) with no grantor_ref -> 204, sid HDS-LEGACY
```

  In the three existing files, make every mint request send `X-Runtime-ID: home-agent-primary`. Use `TestClient(app, headers={"X-Runtime-ID": RUNTIME_ID})` in the fixtures, or a header on `_mint`. Change nothing else in those files.
- [ ] **Step 2: Run the tests and confirm they fail.** Use the BFF command on `tests/test_mint_per_runtime.py`. Expected: FAIL.
- [ ] **Step 3: Implement the per-runtime mint.** Read the header with `Header(default=None, alias=RUNTIME_HEADER)`.
- [ ] **Step 4: Run the tests and confirm they pass.** Run the full BFF suite. Expected: all pass.
- [ ] **Step 5: Commit.** Message: `feat: mint delegations for the runtime the gateway names`.

---

### Task 5: Person reference at login, and asking Home what a person may grant

**Files:**
- Modify: `services/home-bff/home_bff/sessions.py`, `services/home-bff/home_bff/frappe_client.py`, `services/home-bff/home_bff/app.py` (the `/callback` route only)
- Test: `services/home-bff/tests/test_person_ref_login.py` (create), `services/home-bff/tests/test_frappe_client_grant.py`

**Interfaces:**
- **`sessions.py`:**
  - `PERSON_REF_LABEL = b"episteck-person-ref\x00"`.
  - `person_ref(person_id: str, secret: str) -> str`: the hex HMAC-SHA256 of `PERSON_REF_LABEL + person_id.encode()`. An empty `person_id` raises `ValueError`.
  - `refs_match(a: str, b: str) -> bool`: `False` when either is empty, else `hmac.compare_digest(a, b)`.
- **`frappe_client.py`:**
  - `GRANTABLE_RUNTIMES_PATH = "/api/method/episteck_home.identity.session.get_grantable_runtimes"`.
  - `list_grantable_runtimes(access_token: str) -> list[str] | None`. It sends a GET with no parameters.
    - Returns the list when the message is `{"runtime_ids": [str, ...]}`.
    - Returns `None` on `ControlPlaneUnreachable`, on any other `SessionOpenError` (including 404/417 before Home's deploy), and on a malformed body.
    - Re-raises `AccessRefused`.
- **`/callback`,** after the code exchange and **before** `open_home_session`:
  - Call `who = client.whoami(tokens.access_token)`.
  - `ControlPlaneUnreachable` → `_failure(503, "login could not be completed")`.
  - Any other `SessionOpenError`, or an `actor_person_id` that isn't a non-empty string → `_failure(403, "this account is not linked to a Home person")`.
  - Otherwise pass `person_ref=sessions.person_ref(who["actor_person_id"], settings.delegation_secret)` into whichever session-creation call the flag selects.

- [ ] **Step 1: Write the failing tests:**

```python
def test_person_ref_is_stable_labelled_and_not_the_id():
    ref = person_ref("PSN-00001", "s")
    assert ref == person_ref("PSN-00001", "s") and ref != person_ref("PSN-00002", "s")
    assert "PSN-00001" not in ref and len(ref) == 64
def test_refs_match_never_matches_empty():
    assert not refs_match("", "") and not refs_match("a", "")
def test_login_stores_the_person_ref(ctx): ...
    # after /callback, store.get_session(cookie).person_ref == person_ref("PSN-00001", DELEGATION_SECRET)
def test_login_with_whoami_unreachable_is_503_and_creates_no_session(ctx): ...
    # client.whoami_error = ControlPlaneUnreachable(); no bff_session row; no session cookie; open_home_session not called
def test_login_without_person_id_is_403(ctx): ...
    # whoami_payload = {"actor_person_id": None}
def test_ref_and_person_id_never_leave_the_server(ctx, caplog): ...
    # neither the ref nor "PSN-00001" appears in any response body, Set-Cookie header or log record of the login flow
```

  In `test_frappe_client_grant.py`, use that file's transport-stub pattern to cover `list_grantable_runtimes`:
  - a 200 list returns the list;
  - a 200 with `{"runtime_ids": "x"}` returns `None`;
  - a 500 or a transport error returns `None`;
  - a 404 returns `None`;
  - a 401 raises `AccessRefused`;
  - the request is a GET with no query and no body.
- [ ] **Step 2: Run the tests and confirm they fail.** Use the BFF command on the two files. Expected: FAIL.
- [ ] **Step 3: Implement the reference, the client method and the callback change.**
- [ ] **Step 4: Run the tests and confirm they pass.** Run the full BFF suite. Expected: all pass. The existing login tests pass because `FakeClient.whoami` returns `PSN-00001`.
- [ ] **Step 5: Commit.** Message: `feat: remember which person logged in, as an opaque reference`.

---

### Task 6: `/runtime` per person: page, grant, revoke, log out everywhere

**Files:**
- Modify: `services/home-bff/home_bff/runtime_page.py`, `services/home-bff/home_bff/app.py`
- Test: `services/home-bff/tests/test_runtime_per_person.py` (create), `services/home-bff/tests/test_runtime_routes.py`

**Interfaces:**
- Consumes:
  - `grant_audiences_for` and `PRIMARY_RUNTIME_ID` (Task 2);
  - `grantor_ref`, `list_runtime_grants_for` and the conditional delete (Task 3);
  - `refs_match` and `list_grantable_runtimes` (Task 5).
- **`runtime_page.py`:**
  - `@dataclass(frozen=True) class AgentView: runtime_id: str; grant: RuntimeGrant | None`.
  - `render(*, csrf_token: str, agents: Sequence[AgentView], now: int, message: str | None = None, home_unreachable: bool = False) -> str`.
  - **Agent sections.** One `<section>` per agent, headed `<h2>Olin <small>{runtime_id}</small></h2>`, then today's state text for its grant. The grant/renew form and, when a grant exists, the revoke form each carry `<input type="hidden" name="agent" value="{runtime_id}">`. Every value is escaped.
  - **No agents.** The page shows `<p>Esta cuenta no tiene ningún asistente que autorizar.</p>` and no grant forms.
  - **Home unreachable.** The page adds `<p role="status">Home no responde. Solo se muestran los permisos que ya diste.</p>`.
  - **Always.** The "cerrar sesión en todas partes" form stays at the bottom.
- **`app.py`:**
  - **Agent from the form:** `_form_agent(form) -> str | None`. A missing `agent` gives `PRIMARY_RUNTIME_ID`, so old pages keep working. A value in `settings.runtime_ids` is returned; anything else gives `None`.
  - **`_guard`:** returns `(session, form, error)`.
  - **Agents to show:** `_visible_agents(session, store, client) -> tuple[list[AgentView], bool]`.
    - **Home answers:** one agent per id in `settings.runtime_ids` that Home listed. Each shows its grant only when `refs_match(grant.grantor_ref, session.person_ref)`, and `None` otherwise. The flag is `False`.
    - **Home answers `None`:** one agent per grant in `store.list_runtime_grants_for(session.person_ref)` whose id is configured. The flag is `True`.
    - **`AccessRefused`:** propagates. `GET /runtime` turns it into `303 /login?next=/runtime`. Error pages rendered after a POST treat it as unreachable.
  - **`POST /runtime/grant`:**
    1. An agent `None` returns 400 `{"detail": "unknown agent"}` without calling Home.
    2. An empty `session.person_ref` returns `303 /login?next=/runtime` without calling Home.
    3. The recent-login check stays as today.
    4. Call `client.open_runtime_grant(token, agent, days)`.
    5. Call `store.put_runtime_grant(agent, hds, grant_audiences_for(agent), ttl_seconds=..., grantor_ref=session.person_ref)`.
    6. Error pages and the store-failure close work as today.
  - **`_revoke_grant(session, store, client, runtime_id) -> str`:**
    - **No grant:** today's legacy-binding clear for that runtime id applies.
    - **The grant isn't the session's** (`not refs_match`, which includes legacy rows): return `"none"` without calling Home.
    - **Home answers `False`:** return `"kept"`.
    - **Home answers `True` or `None`:** call `delete_runtime_grant(runtime_id, home_session_id=grant.home_session_id)`, clear the binding, and return `"revoked"`. `None` still logs today's static warning.
  - **`POST /runtime/revoke`:** an agent `None` returns 400. Otherwise it behaves as today, for that agent.
  - **`POST /logout/all`:** runs `_revoke_grant` for every id in `settings.runtime_ids`. The outcome is `"kept"` if any is kept, else `"revoked"` if any is revoked, else `"none"`. `AccessRefused` and store errors are handled as today.

- [ ] **Step 1: Write the failing tests** in `test_runtime_per_person.py`.
  - **Setup.** Settings `runtime_ids=("home-agent-primary", "home-agent-ana"), runtime_legacy_binding=False`.
  - **Fake client.** A `GrantClient` subclass whose `whoami_payload` and `grantable` can be switched between OWNER (`PSN-00001` → `["home-agent-primary"]`) and ANA (`PSN-00002` → `["home-agent-ana"]`). `grantable = None` simulates Home unreachable.
  - **Helper.** `REF_OWNER`/`REF_ANA = person_ref(..., DELEGATION_SECRET)`.

```python
def test_ana_sees_only_her_agent_and_nothing_of_the_owners_grant(ctx): ...
    # owner grant live (grantor REF_OWNER, expiry date D); Ana logs in, GET /runtime:
    # "home-agent-ana" in text; "home-agent-primary" not in text; D not in text; "puede actuar" not in text
def test_ana_grants_her_agent_with_the_control_plane_only(ctx): ...
    # POST /runtime/grant agent=home-agent-ana -> open_calls[-1][1] == "home-agent-ana";
    # stored grant audiences == {"home-control-plane"}, grantor_ref == REF_ANA
def test_ana_cannot_touch_the_owners_grant(ctx): ...
    # POST /runtime/revoke agent=home-agent-primary -> 303, close_calls == [], owner row unchanged
def test_home_down_ana_revoke_removes_only_her_row(ctx): ...
    # both rows live; close_result None; Ana revokes hers -> her row gone, owner row intact
def test_home_down_logout_all_by_ana_keeps_the_owners_grant(ctx): ...
    # close_result None -> JSON runtime_grant "revoked"; owner row intact; Home called once (her grant only)
def test_home_down_page_shows_only_her_stored_grants(ctx): ...
    # grantable None -> her section shown with "Home no responde"; owner's runtime id absent
def test_unknown_agent_is_400_without_calling_home(ctx): ...
    # grant and revoke with agent=home-agent-other -> 400 {"detail": "unknown agent"}; open_calls == close_calls == []
def test_session_without_person_ref_must_log_in_again_to_grant(ctx): ...
    # create a session in the store with person_ref "" and set its cookie by hand -> grant -> 303 /login?next=/runtime; open_calls == []
def test_home_refusal_for_the_wrong_person_stores_nothing(ctx): ...
    # Ana posts agent=home-agent-primary; open_error = SessionOpenError() -> 403 page; no primary row written
def test_legacy_row_is_shown_and_revoked_by_nobody(ctx): ...
    # primary row with grantor_ref "" -> owner page shows "no tiene permiso"; owner revoke -> close_calls == [], row kept
def test_access_refused_on_the_page_asks_for_a_fresh_login(ctx): ...
    # list_grantable_runtimes raises AccessRefused -> GET /runtime 303 /login?next=/runtime
def test_page_without_any_grantable_agent_says_so(ctx): ...
    # grantable [] -> "Esta cuenta no tiene ningún asistente que autorizar." and no "/runtime/grant" form
```

  In `test_runtime_routes.py`, change only the helpers:
  - `put_grant` passes `grantor_ref=person_ref("PSN-00001", DELEGATION_SECRET)`;
  - `GrantClient` returns `["home-agent-primary"]` from `list_grantable_runtimes`.
  
  The owner's existing behaviour tests must pass unchanged. That is acceptance item 7, "the owner's agent behaves as before".
- [ ] **Step 2: Run the tests and confirm they fail.** Use the BFF command on `tests/test_runtime_per_person.py`. Expected: FAIL.
- [ ] **Step 3: Implement the page, the guard and the three routes.**
- [ ] **Step 4: Run the tests and confirm they pass.** Run the full BFF suite. Expected: all pass.
- [ ] **Step 5: Commit.** Message: `feat: each person sees and controls only their own agents`.

---

### Task 7: Gateway port 9937 for Ana's agent, and the firewall

**Files:**
- Modify: `deploy/gateway/nginx-mcp-gateway.conf`, `deploy/gateway/episteck-gateway.nft`, `deploy/gateway/render-nft.sh`
- Test: `deploy/gateway/tests/test_gateway_config.py`, `deploy/gateway/tests/test_nft_policy.py`, `deploy/gateway/tests/test_gateway_integration.py`

**Interfaces:**
- **nginx 9934 server:** in both `/__mint` and `/__mint_finance`, `proxy_set_header X-Runtime-ID "";` becomes `proxy_set_header X-Runtime-ID "home-agent-primary";`.
- **nginx 9937 server:** a second `server` block with `listen 127.0.0.1:9937;`. It contains:
  - its own `location = /__mint`, identical to 9934's except for `proxy_set_header X-Runtime-ID "home-agent-ana";`;
  - `/gateway/home/` and `/gateway/nutrition/`, identical to 9934's.
  
  It has no `/__mint_finance` and no `/gateway/finance/`.
- **nft:**
  - Add `define ANA_UID = __HOME_AGENT_ANA_UID__`.
  - After the 9934 pair, add:
    ```
    ip daddr 127.0.0.1 tcp dport 9937 meta skuid $ANA_UID accept
    ip daddr 127.0.0.1 tcp dport 9937 drop
    ```
  - `render-nft.sh` also resolves `id -u home-agent-ana`, checks that it is numeric, substitutes it, and prints it on the existing stderr line. It fails if the user doesn't exist, so plan 3 creates the user before rendering.

- [ ] **Step 1: Write and adjust the failing tests:**
  - **`test_gateway_config.py`:**
    - Update the counts: `auth_request /__mint;` → 4, `auth_request_set $mint_delegation` → 5, the delegation set and hide lines → 5 each, `proxy_next_upstream off;` → 5. Also update the mutation proof.
    - In `test_mint_subrequest_cannot_receive_client_credentials_or_body`, assert per server instead of `X-Runtime-ID ""`.
    - Add these tests:
      - `test_each_server_stamps_its_own_runtime_on_the_mint`: the 9934 server text contains `X-Runtime-ID "home-agent-primary"` in both of its mint blocks; the 9937 text contains `X-Runtime-ID "home-agent-ana"`. Split `CONFIG` on `server {`.
      - `test_ana_server_has_no_finance_route_or_mint`: the 9937 server text has no `finance`.
      - `test_every_mint_block_drops_client_headers`: every `location = /__mint` and `/__mint_finance` block has `proxy_pass_request_headers off;` and `proxy_pass_request_body off;`.
      - `test_listeners_are_loopback_only`: exactly `listen 127.0.0.1:9934;` and `listen 127.0.0.1:9937;`, and no `0.0.0.0`.
  - **`test_nft_policy.py`:**
    - `test_ana_port_is_reachable_only_by_ana_uid`: the accept line comes before the drop line.
    - `test_owner_and_ana_never_cross`: no line accepts `$ANA_UID` on 9934, and none accepts `$HERMES_UID` on 9937.
    - `test_render_step_resolves_the_numeric_ana_uid`: `id -u home-agent-ana` is in `RENDER`, and `__HOME_AGENT_ANA_UID__` is substituted.
  - **`test_gateway_integration.py`** (runs only where nginx exists):
    - Rewrite `127.0.0.1:9937` to a second free port in the fixture.
    - Add `test_ana_port_mints_as_ana_even_when_the_client_forges_the_runtime`: send a request to the 9937 port with the header `X-Runtime-ID: home-agent-primary`. The recorded mint request's `x-runtime-id` must equal `home-agent-ana`.
    - Add `test_ana_port_has_no_finance_route`: `/gateway/finance/` on 9937 returns 404 and records no mint request.
- [ ] **Step 2: Run the tests and confirm they fail.** Use the deploy command. Expected: FAIL on the new assertions; integration tests are skipped without nginx.
- [ ] **Step 3: Edit the nginx config, the nft template and the renderer.**
- [ ] **Step 4: Run the tests and confirm they pass.** Use the deploy command. Expected: all pass (nginx tests skipped locally). If `nginx` is on PATH (WSL or Linux), also run the integration file, and report whether it ran or was skipped.
- [ ] **Step 5: Commit.** Message: `feat: give ana's agent its own gateway port and firewall rule`.

---

### Task 8: ADR-0017, architecture and runbooks

**Files:**
- Create: `docs/architecture/adr/0017-per-person-agent-runtimes.md`
- Modify: `docs/architecture/ARCHITECTURE.md`, `deploy/home-bff/README.md`, `deploy/gateway/README.md`, `docs/architecture/STATUS.md` (one row)

- [ ] **Step 1: Write ADR-0017 "Per-person agent runtimes".** Use the ADR format in `.claude/rules/docs.md`: status "Accepted (owner approval of the release 1 design, 2026-11-18)", "amends ADR-0010". It records:
  - **Identity:** the runtime comes from the port, the uid and nginx (spec 6.3). There is no fallback to the primary.
  - **Home:** the per-runtime grantee mapping and `get_grantable_runtimes`.
  - **Audiences:** per runtime, and Finance only for `home-agent-primary`.
  - **The person reference:** it is an HMAC of the Home **Person** id, not the user id, because Person ↔ User is one-to-one and the Person is Home's identity. Rotating the delegation secret changes every reference, so after a rotation each person re-grants.
  - **Ownership rules:** revoke, the unreachable fallback and `/logout/all` act only on the person's own grants.
  - **Legacy rows** and the re-grant step.
  - **The legacy-binding guard** and the per-runtime mint limit.
  - **Alternatives:** one shared bot (spec non-goal); a user column instead of an HMAC (stores identity in the BFF).
- [ ] **Step 2: Update `ARCHITECTURE.md`.**
  - Add a short paragraph after the H5 runtime-grant paragraph (about line 124). Mention 9937 in the diagram text next to `:9934`.
  - Update every statement that says there is one agent identity (`git grep -n "home-agent-primary" docs/architecture`).
- [ ] **Step 3: Add the rollout runbook to `deploy/home-bff/README.md`.** Plan 3 executes it. The steps:
  1. Merging deploys Home's code, which has no effect until the site config is set.
  2. Create the Linux user `home-agent-ana` (plan 3).
  3. Set the site config: `home_runtime_ids` = `["home-agent-primary", "home-agent-ana"]`, and `home_runtime_grantees_by_runtime` with the owner's and Ana's Frappe user ids (`bench --site <site> set-config -p ...`).
  4. Build the BFF image and update both Quadlets (`RUNTIME_IDS`).
  5. **Immediately**, the owner logs in and re-grants `home-agent-primary` at `/runtime`.
  6. Deploy the gateway config, then render and load the nft table.
  7. Verify that a mint without `X-Runtime-ID` returns 401 and that the owner's bot answers.
  
  Also add one paragraph to `deploy/gateway/README.md` about port 9937 and the uid rule.
- [ ] **Step 4: Update the STATUS row.** In `STATUS.md`, edit only the row for the BFF runtime grant: append `; per-person runtimes (home-agent-ana) merged, not deployed`.
- [ ] **Step 5: Check and commit.** Run the full BFF, Home and deploy suites one last time. Commit with the message `docs: adr-0017 per-person agent runtimes and rollout runbook`.

---

## What plan 3 needs from this plan

- **Ana's Hermes agent:** it calls `http://127.0.0.1:9937/gateway/nutrition/` and `/gateway/home/` only.
- **Onboarding:** Ana grants at `/runtime`. Her page lists only `home-agent-ana`. The spec's `/runtime?agent=home-agent-ana` URL also works, because the query is ignored.
- **Rollout:** the order is Task 8's runbook. The owner's re-grant of `home-agent-primary` (step 5) is mandatory.
