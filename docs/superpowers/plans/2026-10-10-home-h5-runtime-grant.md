# Home H5 Agent Runtime Grant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner explicitly grant `home-agent-primary` permission to act on their behalf for up to 90 days, revocable at any moment and independent of any browser session.

**Architecture:** A grant is a `Home Delegated Session` with `client = "agent-runtime:<runtime_id>"` and a long expiry (no schema change). The BFF stores only a pointer row (`runtime_grant`, no OAuth tokens) and `/internal/mint` resolves that row before the legacy browser binding. The 120 s / single-use / no-Person-id delegation and Home-side actor resolution are untouched.

**Tech Stack:** Frappe app (Python 3.11+, pytest with fake `frappe` module); FastAPI + httpx + SQLite (BFF); nginx allowlist config tests; rootless Podman Quadlet.

**Spec:** `docs/architecture/proposals/HOME_AGENT_RUNTIME_GRANT.md` (branch `architecture/olin-finance-v1`, PR #74, still open — **not on `main`**). Owner approved it on 2026-10-10 with answers: recent-login window 10 min; "log out everywhere" also revokes the grant, with a notice; expiry reminder via Telegram (I1) — here Home only exposes `get_runtime_grant_status`.

## Global Constraints

- `actor_person_id` is never an input; delegation stays 120 s, single use, no Person id; Home resolves the actor.
- Revocation denies the very next call. Disabled or unlinked user → denied (existing `_user_for_session` / `_person_for_user`).
- Logs never contain tokens, session ids, Person ids, or user names. Static strings only.
- A machine can never create a grant (`open_runtime_grant` takes no user parameter, requires a human with exactly one linked Person).
- No tokens in `runtime_grant`; no schema change in Home (no `bench migrate`).
- Site config keys: `home_runtime_ids` (default `["home-agent-primary"]`), `home_runtime_grant_max_days` (default 90). Flag: `RUNTIME_LEGACY_BINDING` (BFF env, default `on`).
- Nothing is deployed by the agent. Home deploys through `main` → `episteck-deploy` (no migrate; operator sets site config). BFF image/Quadlet: operator runs a prepared `! ssh` command.
- Two backward-compatible PRs: **PR1 Home + docs**, **PR2 BFF + nginx + deploy prep**. Commits `<type>: summary`, PRs use the repo template and end with the session attribution line.
- Out of scope: `svc-finance`, H1–H4, Feature Activation, Telegram, Codex, Hermes cron, financial data, H6.

## Findings from reading the code (decisions that need approval)

1. **No "log out everywhere" exists.** `POST /logout` closes only the current browser session, and `bff_session` has no user column, so "everywhere" cannot be enumerated. Plain `/logout` must NOT revoke the grant (that would recreate the daily-login problem). Proposal: add `POST /logout/all` = current session logout + grant revocation, with a notice on `/runtime`. "Everywhere" is therefore *this session + the grant*.
2. **Any linked family member could overwrite or revoke the single grant.** `runtime_grant` is keyed by `runtime_id` and Home's rotation is per user. Proposal (additive to H5): new Home site-config key `home_runtime_grantees` (list of User names allowed to grant; absent/empty = deny all). Revoke: BFF calls Home `close_runtime_grant` **first** and deletes the local row when Home says `closed: true` **or** Home is unreachable; if Home says `closed: false` (not yours / already gone) the row is kept and the page says so. This deviates from "delete local first" only in the non-outage case.
3. **CSRF** (BFF has none today). Stateless token `HMAC-SHA256(key=HMAC(delegation_secret,"episteck-bff-csrf-key-v1"), msg=session_id)` rendered as a hidden field, plus an Origin / `Sec-Fetch-Site` check (Origin must equal the origin of `BFF_REDIRECT_URI`; if absent, `Sec-Fetch-Site` must be `same-origin`; neither → 403). Applied to `POST /runtime/grant`, `/runtime/revoke`, `/logout/all`. Form bodies are parsed with `urllib.parse.parse_qs` (no new dependency).
4. **Session id for `get_runtime_grant_status`:** `auth_hook` sets `frappe.local.episteck_delegated_session_id` only after the session binds, resets it to `None` at start and in the exception path, never logs it. The method returns no identifier. Exposed as `episteck_home.api.get_runtime_grant_status` (thin wrapper over `identity.session`) so an MCP tool can be added later without a Home change; callable only by `home-mcp-service@episteck.invalid` with a control-plane delegation. **No Home MCP tool is added in this task** (that is I1).
5. **Allowlists:** `actor.py POLICY_AUDIENCES` and `auth_hook._accepted_audiences` need **no change** (the mint stays control-plane only; `svc-finance` is stored in `allowed_audiences` but BFF `KNOWN_AUDIENCES` does not mint it until H4).
6. **"Recent login" ≠ password re-entry.** If Frappe's own session is live, `/authorize` may skip the password. The check is "BFF session ≤ 10 min old" (`bff_session.created_at`); still blocks a stolen BFF cookie. Verified in the live step; not claimed beyond that.
7. **`/login?next=/runtime`:** only the literal `/runtime` is accepted, carried in a short-lived `__Host-` cookie (no schema change); the callback redirects there and clears it. Any other `next` is ignored (no open redirect).
8. **BFF `expires_at` = BFF clock now + ttl_days×86400**, not Home's site-local string. Home remains the authority at call time.
9. **Revoke with Home down:** the doc's "registra para reintentar" is implemented as a static warning log + rotation on the next grant + natural expiry (no pending table; YAGNI). The leftover Home session cannot be used without the BFF signing secret.
10. `PR #74` is open: ADR-0010 is written self-contained and links the proposal by PR number; I do not copy the proposal into this branch (avoids an add/add conflict).

## Review Focus

1. `ttl_days` as HTTP string `"90"`, `0`, `-1`, `91`, `True`, `"abc"`, `1.5` → only integer 1..max accepted; others `ValidationError` before any write (Task 1).
2. Grant rotation must revoke the old row and create the new one atomically; a failure mid-way must not leave two Active grants (Task 1).
3. `get_runtime_grant_status` with a *browser* session (client `bff-web`) must not report a grant (Task 3).
4. Expired grant at BFF but still Active at Home: mint must not sign (Task 8).
5. `/runtime/*` POST without Origin/Sec-Fetch-Site, with a valid token but cross-site Origin, and with same-origin but wrong token → all 403 (Task 7).

---

## PR1 — Home (branch `feature/home-h5-runtime-grant`)

### Task 1: `open_runtime_grant` / `close_runtime_grant`

**Files:**
- Modify: `apps/episteck_home/episteck_home/identity/session.py`
- Create: `apps/episteck_home/tests/test_runtime_grant.py` (reuse `_make_fake_frappe` pattern from `tests/test_session_lifecycle.py`; extend `get_all` to serve `Home Delegated Session` and `conf`)

**Interfaces:**
- Produces: `RUNTIME_CLIENT_PREFIX = "agent-runtime:"`, `DEFAULT_RUNTIME_IDS = ("home-agent-primary",)`, `DEFAULT_MAX_DAYS = 90`
- Produces: `open_runtime_grant(runtime_id: str, ttl_days) -> {"session_id": str, "expires_at": str}`; `close_runtime_grant(session_id: str) -> {"closed": bool}`

- [ ] **Step 1: Write failing tests** (names are the contract):
  `test_open_takes_no_user_parameter` (inspect signature), `test_requires_authenticated_enabled_human`, `test_machine_user_without_person_denied`, `test_unlinked_or_ambiguous_person_denied`, `test_runtime_id_must_be_in_site_config` (default and custom list), `test_caller_must_be_in_grantees` (key absent/empty → denied; listed → ok), `test_ttl_days_rejects` (parametrized: `0, -1, 91, True, "abc", 1.5, None`), `test_ttl_days_accepts_string_90`, `test_custom_max_days_respected`, `test_creates_row_with_client_prefix_and_expiry` (expiry ≈ now+N days, `ignore_permissions=True`, committed), `test_rotation_revokes_previous_active_grant_of_same_user_and_runtime`, `test_rotation_leaves_other_users_and_browser_sessions_untouched`, `test_close_owner_closes`, `test_close_not_owner_and_missing_same_response`, `test_close_refuses_non_grant_session` (a `bff-web` session id → `{"closed": False}`), `test_close_allowed_after_user_unlinked`.
```python
def test_rotation_revokes_previous_active_grant_of_same_user_and_runtime(fake):
    first = session.open_runtime_grant("home-agent-primary", 90)
    second = session.open_runtime_grant("home-agent-primary", 90)
    assert fake.rows[first["session_id"]]["status"] == "Revoked"
    assert fake.rows[second["session_id"]]["status"] == "Active"
```
- [ ] **Step 2:** `cd apps/episteck_home && uv run --no-project --python 3.13 --with pytest python -m pytest tests/test_runtime_grant.py -q` → FAIL (`open_runtime_grant` missing).
- [ ] **Step 3: Implement.** Validate everything (human, single Person, runtime id, grantee, `ttl_days` via `_parse_ttl_days` that rejects `bool`, non-integral floats, non-digit strings) **before** the first write; revoke previous Active rows (`frappe.get_all` filters `user`, `client`, `status`) with `set_value` then insert the new doc, one `frappe.db.commit()` at the end; on exception `frappe.db.rollback()`. `close_runtime_grant` = `close_session` logic plus `client.startswith(prefix)` in the owner check; same `{"closed": False}` otherwise.
- [ ] **Step 4:** run the file → PASS; run the full Home suite (`--ignore=tests/test_calculator.py`) → 232 + new, 0 failures.
- [ ] **Step 5:** `git add apps/episteck_home && git commit -m "feat: add runtime grant open and close to Home sessions"`

### Task 2: `auth_hook` exposes the bound session id (local only)

**Files:** Modify `apps/episteck_home/episteck_home/identity/auth_hook.py`; Modify `apps/episteck_home/tests/test_auth_hook.py`

**Interfaces:** Produces `frappe.local.episteck_delegated_session_id: str | None`.

- [ ] **Step 1: Failing tests:** `test_session_id_set_only_after_bind`, `test_session_id_none_on_every_failure_stage` (no token, guest, not configured, invalid, replay, session missing, exception), `test_session_id_never_in_logs_or_stage_codes` (capture `log_error` calls and `episteck_delegation_stage`).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** reset to `None` next to the other two locals in `_establish` and in the exception handler; assign `context.session_id` right before `_stage(STAGE_BOUND)`.
- [ ] **Step 4:** `pytest tests/test_auth_hook.py tests/test_delegation_integration.py tests/test_replay_enforcement.py -q` → PASS.
- [ ] **Step 5:** commit `feat: expose delegated session id to request context`

### Task 3: `get_runtime_grant_status`

**Files:** Modify `identity/session.py` (impl), `apps/episteck_home/episteck_home/api.py` (wrapper + `RUNTIME_STATUS_CALLERS = frozenset({"home-mcp-service@episteck.invalid"})`); Modify `tests/test_runtime_grant.py`, `tests/test_home_api_security.py` (add the new method to any whitelist-surface assertions)

**Interfaces:** Produces `get_runtime_grant_status() -> {"granted": bool, "expires_at"?: str, "days_left"?: int}` (never an identifier).

- [ ] **Step 1: Failing tests:** `test_status_requires_delegation` (plain machine call → PermissionError), `test_status_only_for_home_mcp_machine`, `test_status_rejects_nutrition_audience`, `test_status_reports_days_left_for_grant_session` (89.2 days left → 90 via ceil; 0 floor), `test_status_browser_session_is_not_a_grant` (`{"granted": False}`), `test_status_returns_no_session_id_or_user` (assert keys ⊆ {granted, expires_at, days_left}), `test_status_after_disabled_user_denied` (hook already unbinds → PermissionError).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** impl uses `resolve_principals()` (control-plane audience only), reads session id from `frappe.local.episteck_delegated_session_id`, loads the row's `client` and `expires_at`, computes `days_left` with site-local `now_datetime()` on both sides (same clock as `_user_for_session`).
- [ ] **Step 4:** full Home suite → PASS.
- [ ] **Step 5:** commit `feat: add runtime grant status for the agent`

### Task 4: Architecture Change Rule docs

**Files:** Create `docs/architecture/adr/0010-agent-runtime-grant.md`; Modify `docs/architecture/ARCHITECTURE.md`, `docs/architecture/SECURITY_AND_CONSENT.md`, `docs/architecture/STATUS.md`, `deploy/home-bff/README.md` (site-config keys + `RUNTIME_LEGACY_BINDING` runbook section)

- [ ] **Step 1:** ADR-0010 (Context, Decision, Consequences, Alternatives per `.claude/rules/docs.md`): status *Accepted (owner approval 2026-10-10; Board review per PR)*, records the 90-day trade-off (P4), grantee allowlist, no-schema-change choice, rotation, the three owner answers, and the nine findings above that changed the proposal.
- [ ] **Step 2:** ARCHITECTURE.md identity section: add the grant path. SECURITY_AND_CONSENT.md: replace "12 h session only" wording with session vs. grant lifetimes, threat table delta. STATUS.md: "H5 PR1 in review", no "live" claims.
- [ ] **Step 3:** verify `git diff --stat docs/` touches only these; commit `docs: add ADR-0010 and document the agent runtime grant`
- [ ] **Step 4:** push `feature/home-h5-runtime-grant`, open **PR1** (template; testing = Home suite counts). Stop for review before PR2 merges are required (PR2 may be developed on a branch stacked after PR1).

### Task 5 (operator, after PR1 merges): Home site config

Prepared by me, executed by the owner: set `home_runtime_ids`, `home_runtime_grant_max_days`, `home_runtime_grantees` (`["<owner user>"]`) via `bench --site home.episteck.com set-config`. Verification after: read-only `bench execute` that the methods are importable; no grant is created by me.

---

## PR2 — BFF + nginx (branch `feature/home-h5-bff-grant`, from PR1 or `main` once merged)

### Task 6: Store — `runtime_grant` table and session `created_at`

**Files:** Modify `services/home-bff/home_bff/store.py`, `services/home-bff/home_bff/runtime.py`; Modify `services/home-bff/tests/test_store.py`; Create `services/home-bff/tests/test_runtime_grant_store.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) RuntimeGrant(runtime_id, home_session_id, allowed_audiences: frozenset[str], granted_at: int, expires_at: int, last_mint_at: int | None)`
- Produces on `SessionStore`: `put_runtime_grant(runtime_id, home_session_id, allowed_audiences, ttl_seconds) -> RuntimeGrant` (upsert), `resolve_runtime_grant(runtime_id) -> RuntimeGrant | None` (deletes and returns `None` when expired), `delete_runtime_grant(runtime_id) -> bool`, `touch_runtime_grant(runtime_id) -> None` (writes `last_mint_at` only when the minute changed)
- Produces: `Session.created_at: int = 0` (read from `bff_session.created_at`)

- [ ] **Step 1: Failing tests:** `test_table_has_no_token_columns` (PRAGMA table_info ⊆ the six columns), `test_put_then_resolve`, `test_put_replaces_existing`, `test_expired_grant_resolves_none_and_is_deleted`, `test_touch_updates_at_most_once_per_minute`, `test_existing_store_file_gains_table_without_data_loss` (open a file created with the old schema), `test_two_processes_creating_same_file_do_not_conflict` (same pattern as existing WAL test), `test_session_created_at_populated`.
- [ ] **Step 2:** `cd services/home-bff && uv run --no-project --python 3.13 --with pytest --with fastapi --with httpx --with uvicorn python -m pytest tests/test_runtime_grant_store.py -q` → FAIL.
- [ ] **Step 3:** add `CREATE TABLE IF NOT EXISTS runtime_grant (...)` to `_SCHEMA` (additive, idempotent; `_SCHEMA_PRE_LOGIN_BINDING` left alone); `allowed_audiences` stored as sorted comma text; reads via the existing `_connection`, writes via `_mutation`.
- [ ] **Step 4:** full BFF suite → 270 + new, 0 failures.
- [ ] **Step 5:** commit `feat: add runtime grant table to the BFF store`

### Task 7: Settings, CSRF guard, login-recency helper

**Files:** Modify `config.py` (add `runtime_legacy_binding: bool` from `RUNTIME_LEGACY_BINDING`, default on, accepts `on/off/true/false/1/0`, anything else → `ConfigError`; add `runtime_grant_days: int` from `BFF_RUNTIME_GRANT_DAYS`, default 90, 1..90); Create `home_bff/csrf.py`; Create `tests/test_csrf.py`, extend `tests/test_app.py` settings fixture

**Interfaces:**
- Produces: `csrf.token_for(session_id: str, secret: str) -> str`; `csrf.verify(*, session_id, secret, presented: str | None, origin: str | None, sec_fetch_site: str | None, expected_origin: str) -> bool` (constant-time compare; fail closed)
- Produces: `sessions.RECENT_LOGIN_SECONDS = 600`

- [ ] **Step 1: Failing tests:** `test_valid_token_and_same_origin_passes`, `test_missing_origin_requires_same_origin_fetch_site`, `test_cross_site_origin_with_valid_token_fails`, `test_same_origin_with_wrong_token_fails`, `test_token_bound_to_session_id`, `test_no_origin_no_fetch_site_fails`, `test_settings_flag_parsing` (parametrized incl. invalid value), `test_grant_days_bounds`.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** run → PASS. **Step 5:** commit `feat: add CSRF guard and runtime settings to the BFF`

### Task 8: Mint resolves the grant first; rate limit

**Files:** Modify `home_bff/internal_app.py`; Modify `tests/test_internal_mint.py`, `tests/test_runtime_binding.py`

- [ ] **Step 1: Failing tests:** `test_mint_prefers_grant_over_browser_binding`, `test_mint_uses_grant_when_no_browser_session_exists`, `test_mint_falls_back_to_legacy_binding_when_flag_on`, `test_mint_denies_when_flag_off_and_no_grant` (401 even if a browser binding exists), `test_mint_denies_expired_grant_even_if_home_session_active`, `test_mint_denies_when_control_plane_not_in_allowed_audiences`, `test_mint_after_revoke_is_401`, `test_rate_limit_601st_in_a_minute_is_429_with_static_log` (log contains no token/session id), `test_window_resets_next_minute`, `test_mint_updates_last_mint_at_not_more_than_once_per_minute`, `test_delegation_token_carries_grant_session_id_only` (decode body: claims keys unchanged, no Person id).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** in-process fixed-window counter (600/min, injectable clock) checked before touching SQLite; then `resolve_runtime_grant` → else `resolve_runtime` only if `settings.runtime_legacy_binding` → else 401; audience check; `touch_runtime_grant`; mint as today.
- [ ] **Step 4:** full BFF suite → PASS. **Step 5:** commit `feat: mint delegations from the runtime grant first`

### Task 9: `/callback` stops claiming when the flag is off; `/login?next=/runtime`

**Files:** Modify `home_bff/app.py`, `home_bff/sessions.py` (add `NEXT_COOKIE_NAME = "__Host-episteck_home_next"`); Modify `tests/test_login_binding.py`

- [ ] **Step 1: Failing tests:** `test_callback_claims_runtime_when_flag_on` (unchanged behaviour), `test_callback_does_not_claim_when_flag_off`, `test_login_next_runtime_sets_next_cookie`, `test_login_ignores_other_next_values` (`//evil.example`, `/app`, `https://x`, empty), `test_callback_redirects_to_runtime_and_clears_next_cookie`, `test_callback_default_redirect_is_app`.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement (flag off → `store.create_session`). **Step 4:** PASS. **Step 5:** commit `feat: stop auto-claiming the runtime when legacy binding is off`

### Task 10: `/runtime` page, `/runtime/grant`, `/runtime/revoke`, `/logout/all`

**Files:** Modify `home_bff/app.py`, `home_bff/frappe_client.py`; Create `home_bff/runtime_page.py` (pure HTML rendering with `html.escape`); Create `tests/test_runtime_routes.py`; Modify `tests/test_frappe_client_bootstrap.py` or add `tests/test_frappe_client_grant.py`

**Interfaces:**
- Produces on `HomeOAuthClient`: `open_runtime_grant(access_token, runtime_id, ttl_days) -> str` (returns the Home session id; raises `SessionOpenError` on refusal) and `close_runtime_grant(access_token, home_session_id) -> bool | None` (`None` = Home unreachable, `False` = refused/not owner)
- Produces constants `OPEN_RUNTIME_GRANT_PATH`, `CLOSE_RUNTIME_GRANT_PATH` under `/api/method/episteck_home.identity.session.`

- [ ] **Step 1: Failing tests:**
  - `GET /runtime`: no cookie → 303 `/login?next=/runtime`; with cookie → 200 HTML, `Cache-Control: no-store`, status text (granted until date / not granted / last use), CSRF hidden field present, **page contains no access token, home session id or delegation**; grant row for another user visible only as status.
  - `POST /runtime/grant`: no/invalid CSRF → 403 and Home not called; session older than 600 s → 303 `/login?next=/runtime`, Home not called; fresh session + valid CSRF → Home called with the user's token, row stored with `allowed_audiences == {home-control-plane, svc-nutrition, svc-finance}` and `ttl=settings.runtime_grant_days`; Home refusal (non-grantee) → 403 page and existing row **untouched**; Home unreachable → 503 and row untouched.
  - `POST /runtime/revoke`: invalid CSRF → 403; Home `closed: true` → row deleted; Home unreachable → row deleted + static warning log; Home `closed: false` → row kept, page says so; no row → idempotent 200.
  - `POST /logout/all`: CSRF required; closes browser Home session, revokes token, deletes the session, revokes the grant (same Home-first rule), clears cookie, body `{"status": "logged out", "runtime_grant": "revoked"|"kept"|"none"}`.
  - `POST /logout` unchanged: grant **survives** (`test_plain_logout_keeps_grant`).
  - Log hygiene: `caplog` over all of the above contains no token, session id, CSRF value, or delegation.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement; grant/revoke/logout-all read the form body with `parse_qs`; `RUNTIME_ID` stays the only runtime id (no user-supplied runtime id).
- [ ] **Step 4:** full BFF suite → PASS. **Step 5:** commit `feat: add runtime grant page and routes to the BFF`

### Task 11: nginx allowlist + Quadlet env

**Files:** Modify `deploy/home-bff/nginx-home-bff.conf`, `deploy/home-bff/tests/test_nginx_routes.py`, `deploy/home-bff/home-bff.container`, `deploy/home-bff/home-bff-mint.container`, `deploy/home-bff/tests/test_quadlets.py`

- [ ] **Step 1: Failing tests:** `test_runtime_routes_are_explicit_exact_locations` (`= /runtime`, `= /runtime/grant`, `= /runtime/revoke`, `= /logout/all`), `test_no_prefix_location_for_runtime` (no `location /runtime` / `^~ /runtime`), `test_internal_mint_is_not_proxied`, `test_catch_all_still_404`, quadlets: both containers set `Environment=RUNTIME_LEGACY_BINDING=on`.
- [ ] **Step 2:** run → FAIL. **Step 3:** add exact locations copying the existing `/whoami` proxy block. **Step 4:** `pytest deploy/home-bff/tests -q` → PASS. **Step 5:** commit `feat: allow runtime grant routes in the BFF nginx`

### Task 12: Docs, PR2, and operator package

- [ ] Update `deploy/home-bff/README.md` (grant URL, flag, rollback), `STATUS.md` (PR2 in review).
- [ ] Open **PR2**.
- [ ] After merge: prepare for the owner (not executed by me): (a) build rootless image on Nuremberg (`episteck-node1`) tagged with the merge SHA, (b) the exact `! ssh -F C:/Users/D064974/.ssh/config episteck-node1 ...` to install the new image tag in both Quadlets and `systemctl --user daemon-reload && restart` (mint unit first), (c) the nginx reload command, (d) rollback = previous image tag + previous nginx file (grants in Home are then ignored with no effect, browser binding works again).
- [ ] After the owner runs it: **I** verify read-only (health, `/runtime` unauthenticated 303, `/delegation` 404, `/internal/*` 404) and then guide the live test of the proposal §5 (grant → close browser → Hermes call at 13 h and 25 h → revoke → 401 → Home denies the old delegation → logs clean). Only then `RUNTIME_LEGACY_BINDING=off` as a separate, owner-run step.

## Self-review against the proposal

- §3.1 open/close/status → Tasks 1–3. §3.2 table, `/runtime`, grant, revoke, mint precedence, flag, callback, rate limit, `last_mint_at`, `allowed_audiences` → Tasks 6–10. nginx → Task 11. §5 tests: every listed Home/BFF test has a named test above; live test → Task 12. §6 deploy/rollback → Tasks 5, 12. Architecture Change Rule → Task 4.
- Type names consistent: `RuntimeGrant`, `put/resolve/delete/touch_runtime_grant`, `open/close_runtime_grant`, `token_for/verify`.
