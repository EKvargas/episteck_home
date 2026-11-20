# Nutrition R1 · Plan 3: Ana's agent, onboarding, the "Hoy" page and the production rollout

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ana logs everything she eats by voice in her own Telegram bot, sees today's free sugars on a "Hoy" page in the Home app, and plans 1–3 run in production without changing how the owner's agent and Finance behave.

**Architecture:**
- **Part A (one PR).** Code and deploy assets:
  - Nutrition hardening and its Quadlets (BLS mounted read-only).
  - One reusable image-rollout script for Nutrition, BFF and Hub.
  - A race-proof BFF grant claim, plus the runbook fixes carried over from plan 2.
  - The Hub "Hoy" page.
  - Ana's Hermes skill, persona and installer.
- **Part B (after the merge).** The production rollout, in the owner's order:
  1. Nutrition.
  2. Home settings.
  3. The BFF/gateway/firewall window, with the owner's immediate re-grant.
  4. Hub.
  5. Ana's agent, proven first with a synthetic person, then switched to Ana.

The owner runs every live step. Claude prepares the steps and verifies them read-only.

**Tech Stack:**
- Python 3.11, FastAPI, SQLite, fastmcp 4.0.3 (pinned).
- Next.js (node:test, Playwright).
- Hermes Agent v0.21.2, pinned at commit `a89c1e1`.
- Rootless Podman Quadlets, nginx, nftables, Frappe site config, bash.

**Spec:** `docs/superpowers/specs/2026-11-18-nutrition-release-1-design.md`: sections 6.2, 6.4, 6.8, 6.11 (privacy), 6.12 ("Hoy" only), 7 (end-to-end) and 8 (step A).
- This is plan 3 of 4.
- Plan 1, the diary backend, merged as #136. Plan 2, per-person runtimes, merged as #139.
- Plan 4 is step B: the Week view, entry detail, corrections in the app, the limit detail and the personal goal.

## Global Constraints

- **Runtimes and ports (plan 2, unchanged).**
  - Ana's agent is runtime `home-agent-ana`, Linux user `home-agent-ana`.
  - It reaches only `127.0.0.1:9937`, with `/gateway/home/` and `/gateway/nutrition/`. It never reaches 9934 or anything Finance.
  - The owner's agent stays uid 1003 on 9934.
- **Hermes for Ana.**
  - **Install:** pin `HERMES_COMMIT=a89c1e1135a97dc1262926d93933357fbacd2bd2`, the owner's commit (`hermes --version` reads `v0.21.2`). The installer is that commit's `scripts/install.sh`, checked against a pinned SHA-256, and run with `--commit <pin> --skip-setup --skip-browser --skip-computer-use --no-skills`.
  - **Skill root:** `/etc/episteck/hermes-ana/skills`, root-owned. This is separate from the owner's `/etc/episteck/hermes/skills`, so neither agent sees the other's skills.
  - **Model:** `openai-codex` with `gpt-5.6-sol`, the same as the owner's agent. Credential label `ana-codex`, from a device login the owner approves with the owner's own ChatGPT account.
  - **Fallback:** `fallback_providers: [{provider: kimi-coding, model: kimi-k2.6}]`. The Kimi key is copied root-to-root from `/home/home-agent/.hermes/.env` and is never printed. The owner's agent keeps no fallback.
  - **Voice and memory:**
    - Voice: `stt.enabled: true`, `stt.local.model: base`, `stt.language: es`.
    - `timezone: Europe/Berlin`.
    - Memory: `memory.memory_enabled: false`, `memory.user_profile_enabled: false`.
  - **Cron and display:**
    - Cron: `cron.catch_up_missed: false`, `cron.mirror_delivery: true`.
    - Display: `display.tool_progress: off`, `display.interim_assistant_messages: false`.
  - **Tools:** on the `telegram` and `cron` platforms only the built-in toolsets `skills` and `clarify` stay enabled. The only MCP servers are `home` and `nutrition`, both on 9937.
  - **Resources:** a drop-in sets `MemoryMax=900M` on Ana's `hermes-gateway.service`. Preflight refuses to install with less than 900 MB `MemAvailable` (the node has 3.8 GB in total, about 1.4 GB available on 2026-11-20).
  - **Media purge:** every 10 minutes, delete files older than 10 minutes in `~/.hermes/cache/audio`, `~/.hermes/audio_cache`, `~/.hermes/cache/image` and `~/.hermes/image_cache`, and cron outputs older than 1 day in `~/.hermes/cron/output`. Hermes' own pruning waits 24 hours.
- **Evening check-in.**
  - Hermes job `olin-nutrition-checkin`, scheduled `MM HH * * *` in Europe/Berlin (via `timezone`, so daylight saving needs nothing).
  - Flags: `--deliver telegram --failure-deliver local --skill olin-nutrition`.
  - The question is exactly `¿Eso fue todo hoy?`.
- **BLS reference data.**
  - Built from `BLS_4_0_Daten_2025_DE.xlsx` by the merged `services/nutrition/scripts/import_bls.py`. It holds 7,140 foods.
  - Installed at `/srv/episteck/services/nutrition/reference/bls-4.0.sqlite`, mode 0440, owner `svc-nutrition`.
  - Mounted read-only at `/reference` in both `nutrition` and `nutrition-mcp`, with `BLS_DB=/reference/bls-4.0.sqlite`. Never committed.
  - Attribution text: `Datos: Max Rubner-Institut, BLS 4.0`.
- **Copy (Spanish).**
  - An unknown sugar figure is `sin dato`, and a day without entries is `Sin registros hoy`. Neither ever shows `0 g`.
  - The limit is called a `Referencia general`, never an instruction.
  - Every fixed string is given in its task.
- **Secrets.**
  - Ana's bot token arrives through the secret drop, slot `telegram-ana`, written to `/home/home-agent-ana/.hermes/.env` with mode 600.
  - Scripts test for keys with `grep -c`/`grep -q`. They never print `.env`, `auth.json` or token values.
- **Delivery.**
  - Part A is one PR from branch `feature/nutrition-r1-ana-rollout`, cut from `docs/nutrition-r1-plan-3-ana-rollout` so the plan rides with it.
  - Plan 3 changes no Home (Frappe) code. Home's settings change through site config and the desk only.
  - Images are built from the merge SHA, never from a branch.
- **Step labels in Part B.**
  - `[OPERATOR]`: the owner runs a live step.
  - `[OPERATOR INPUT]`: only the owner has the value.
  - `[PREP]`: writes on the node but changes nothing live. Claude runs it only after the owner says go for that step; otherwise the owner runs it.
  - `[CLAUDE VERIFY]`: read-only.
- **Logging.** Service and script logs never contain food text, tokens, delegations, Person ids or references.
- **Test commands.** Local Python is `C:\AIProjects\episteck-delivery-workspace\.venvs\nutrition-r1\Scripts\python.exe` (`PY`). Baselines are on origin/main `3edbc60`.
  - **Nutrition (498 passed):** from the repo root, `$env:PYTHONPATH="packages/nutrition-domain/src;services/nutrition"; PY -m pytest -q -p no:cacheprovider services/nutrition/tests packages/nutrition-domain/tests`.
  - **BFF (446 passed, 10 skipped):** `cd services/home-bff; $env:PYTHONPATH="."; PY -m pytest -q -p no:cacheprovider tests`.
  - **Deploy (107 passed, 9 skipped):** `PY -m pytest -q -p no:cacheprovider deploy/gateway/tests deploy/home-bff/tests deploy/hermes/tests deploy/secret-drop/tests`.
    - New test folders are added to this command.
    - `deploy/finance/tests` has one known Windows-only failure (`test_provision_script_is_syntactically_valid`, a bash path) and stays out of this command.
  - **Hub:** `cd apps/home-hub; npm ci` once, then `npm test`, `npm run test:server-boundary`, `npm run lint`, `npx tsc --noEmit`, `npm run test:e2e`. Record the baseline counts in the progress ledger before Task 6.
- **Existing tests.** Change them only where a task says so. Never weaken an assertion.
- **Commits.** Each ends with the executing session's `Claude-Session:` trailer.

## Review Focus

- **Ambiguous "sí".**
  - **Case:** Ana answers "sí" after the evening check-in while one of her drafts is still unconfirmed.
  - **Expected:** the bot acts on its *last* question only. That is the draft after `¿Lo guardo?`, or closing the day after `¿Eso fue todo hoy?`. Otherwise it asks; it never does both (Task 8).
- **BLS is missing after the deploy.**
  - **Case:** a wrong `BLS_DB` path only logs a warning, and the chain quietly falls back to OFF and USDA.
  - **Expected:** the Quadlet test pins `BLS_DB` inside the read-only mount (Task 2). `verify` fails unless *both* containers' first `Apfel` hit is a `bls:` id (Task 3).
- **Entries near midnight.**
  - **Case:** an entry at 23:30 Berlin, or one stored in UTC.
  - **Expected:** the Hub shows Berlin clock times whatever the server zone (Task 7).
- **A second Hermes on a small node.**
  - **Case:** Ana's agent plus a voice transcription push the node into swap.
  - **Expected:** Ana's unit is capped at 900M and preflight refuses when memory is short. The owner's `home-agent` shows no new restarts (Task 9).
- **Daylight saving.**
  - **Case:** on 2027-03-28 the check-in would drift by an hour if scheduled in UTC.
  - **Expected:** the cron step refuses unless Ana's `timezone` is `Europe/Berlin` (Task 9).

---

## Part A: Code

### Task 1: Nutrition fails cleanly and guides the agent before its first deploy

**Files:**
- Modify:
  - `services/nutrition/app/providers/food_provider.py`, `bls.py`, `chain.py`, `synthetic.py`
  - `services/nutrition/app/diary/service.py` (`_fetch`)
  - `services/nutrition/app/mcp/server.py` (`_ITEM_GUIDE`)
- Test: `services/nutrition/tests/test_bls_provider.py`, `services/nutrition/tests/test_diary_service.py`, `services/nutrition/tests/test_diary_api.py`

**Interfaces:**
- **Produces:**
  - `class FoodNotFound(KeyError)` in `food_provider.py`. Every "unknown id" raise in BLS, synthetic and the chain becomes `FoodNotFound`. Existing `pytest.raises(KeyError)` tests keep passing.
  - `BlsFoodProvider._connect()` opens `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. A missing `meta` version row raises `sqlite3.DatabaseError("BLS metadata missing")`.
- **`DiaryService._fetch` mapping:**
  - `FoodNotFound`, or an HTTP 404 → `InvalidField("food_id")`.
  - Any other `LookupError`, `TypeError`, `ValueError` (including `json.JSONDecodeError`), `sqlite3.DatabaseError`, `httpx.RequestError`, or a non-404 `httpx.HTTPStatusError` → `ProviderUnavailable`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_bls_without_metadata_is_provider_unavailable(tmp_path): ...
    # build_bls_db one row; DELETE FROM meta; propose with that bls id -> ProviderUnavailable; no diary_draft row
def test_bls_file_that_is_not_sqlite_is_provider_unavailable(tmp_path): ...
    # write b"not a database" to the file -> ProviderUnavailable
def test_bls_opens_read_only(tmp_path): ...
    # p._connect().execute("CREATE TABLE x(a)") raises sqlite3.OperationalError
def test_unknown_food_id_is_still_invalid_item(): ...
    # syn-does-not-exist -> InvalidField with field "food_id"
def test_provider_parse_error_is_provider_unavailable(): ...
    # stub provider whose get_food raises KeyError("fdcId") -> ProviderUnavailable
def test_mcp_lists_exactly_the_21_tools(): ...
    # asyncio.run(server.mcp.list_tools()) succeeds and its names == the 21 names below
def test_item_guide_says_serving_needs_an_estimate_without_a_source_serving(): ...
    # "serving" and "grams_estimate" both appear in the sentence added in Step 3
```

  The 21 tool names are:
  - `get_nutrition_profile`, `evaluate_meal`, `get_daily_nutrition_gap`
  - `record_planned_meal`, `record_actual_intake`, `ate_as_planned`, `propose_meal_change`
  - `search_recipes`, `get_meal_plan`, `search_foods`, `get_food_detail`
  - `get_pregnancy_profile`, `plan_menu`
  - `propose_intake`, `confirm_intake`, `correct_intake`, `void_intake`
  - `get_diary_entry`, `get_day_summary`, `close_day`, `set_nutrition_mode`

  Replace the subset assertion in `test_mcp_exposes_the_eight_diary_tools` with this exact-set test.
- [ ] **Step 2: Run the tests and confirm they fail.** Use the Nutrition command on the three files. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Do everything in the Interfaces block.
  - In `_ITEM_GUIDE`, after the `serving` token line, add exactly: `serving uses the food's own serving size; when the food has none, the result is INVALID_ITEM and you must send grams_estimate instead.`
- [ ] **Step 4: Run the full Nutrition suite.** Expected: all pass (498 + new).
- [ ] **Step 5: Commit.** Message: `fix: nutrition maps bls and provider failures cleanly`.

---

### Task 2: Nutrition Quadlets in the repo, with BLS mounted read-only

**Files:**
- Create: `deploy/nutrition/nutrition.container`, `deploy/nutrition/nutrition-mcp.container`, `deploy/nutrition/README.md`
- Test: `deploy/nutrition/tests/test_nutrition_quadlets.py`

**Interfaces:**
- **Produces:** two Quadlet templates, read by Task 3's `apply`.
  - **Base:** each is the live file as read on 2026-11-20 (`Image=…cf801947…`, `PublishPort`, the data `Volume`, three `EnvironmentFile`s, `NUTRITION_DB`, `AddHost`, `PodmanArgs` memory caps; the MCP also has `MCP_PORT` and `Exec=python -m app.mcp.server`).
  - **Changes:** the image line becomes `Image=localhost/episteck-nutrition:REPLACE_WITH_COMMIT_SHA`. Each unit gains exactly three lines:
    ```
    Volume=/srv/episteck/services/nutrition/reference:/reference:ro
    Environment=BLS_DB=/reference/bls-4.0.sqlite
    Environment=DIARY_TZ=Europe/Berlin
    ```

- [ ] **Step 1: Write the failing tests.**

```python
def test_both_units_carry_the_image_placeholder_once(): ...
def test_bls_is_mounted_read_only_and_bls_db_points_inside_the_mount(): ...
    # the Volume target "/reference" with ":ro"; BLS_DB startswith "/reference/"; same in both units
def test_both_units_share_data_env_files_and_timezone(): ...
def test_ports_are_loopback_only_and_the_mcp_runs_the_mcp_server(): ...
def test_no_secret_value_is_inline(): ...
    # no line matches (KEY|SECRET|TOKEN|PASSWORD)= outside EnvironmentFile paths
```

- [ ] **Step 2: Run the tests and confirm they fail.** Use the deploy command on `deploy/nutrition/tests`. Expected: FAIL (files missing).
- [ ] **Step 3: Write the two templates and the README.** The README covers:
  - **Building `bls-4.0.sqlite` locally** with `PY services/nutrition/scripts/import_bls.py <xlsx> <out>`. Expected output: `wrote 7140 foods to <out>`.
  - **Staging:** record the `sha256`, then `scp -F C:/Users/D064974/.ssh/config <out> episteck-node1:/home/episteck/stage/bls-4.0.sqlite`.
  - **The operator install:** `install -d -m 0750 -o svc-nutrition -g svc-nutrition /srv/episteck/services/nutrition/reference`, then `install -m 0440 -o svc-nutrition -g svc-nutrition`, and compare the `sha256`.
  - **The CC BY 4.0 attribution.**
  - **That the file is never committed.**
- [ ] **Step 4: Run the tests and confirm they pass.** Use the deploy command including `deploy/nutrition/tests`. Expected: all pass.
- [ ] **Step 5: Commit.** Message: `feat: nutrition quadlets in the repo with the bls mount`.

---

### Task 3: One image-rollout script for Nutrition, BFF and Hub

**Files:**
- Create: `deploy/ops/image-rollout.sh`, `deploy/ops/README.md`
- Test: `deploy/ops/tests/test_image_rollout.py`

**Interfaces:**
- **Invocation:** `ssh -F C:/Users/D064974/.ssh/config episteck-node1 'sudo -n bash -s -- <component> <step> [arg]' < deploy/ops/image-rollout.sh`. With `--lib` as the first argument it only defines functions (for tests).
- **Component table:**

| component | account | units, in restart order | Quadlet templates (repo) | image | build (from `/home/<account>/build/<SHA>`) |
| --- | --- | --- | --- | --- | --- |
| `nutrition` | `svc-nutrition` | `nutrition`, `nutrition-mcp` | `deploy/nutrition/*.container` | `localhost/episteck-nutrition` | `podman build -f services/nutrition/Dockerfile -t <image>:<SHA> .` |
| `home-bff` | `svc-home-bff` | `home-bff-mint`, `home-bff` | `deploy/home-bff/home-bff-mint.container`, `home-bff.container` | `localhost/episteck-home-bff` | `podman build -f services/home-bff/Dockerfile -t <image>:<SHA> .` |
| `home-hub` | `svc-home-hub` | `svc-home-hub` | `deploy/home-hub/svc-home-hub.container` | `localhost/episteck-home-hub` | `podman build -f apps/home-hub/Dockerfile -t <image>:<SHA> apps/home-hub` |

- **Functions:**
  - `render_quadlet <template> <sha> <out>`: replaces only `REPLACE_WITH_COMMIT_SHA`. It fails when the template has no placeholder line, or more than one.
  - `as_account <account> <cmd…>`: sets `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS`.
- **Steps:**
  - **`baseline`** (RO): prints each unit's running image, ActiveState, NRestarts, and the sha256 of each live Quadlet.
  - **`build <SHA>`** (PREP): needs the extracted tree at `/home/<account>/build/<SHA>`, then prints the image ID.
  - **`apply <SHA>`** (LIVE):
    1. Refuse a SHA that is not 40 lowercase hex characters, and refuse a missing image.
    2. Back up every live Quadlet to `/var/backups/episteck/<component>-<sha7>-<UTC stamp>/` (mode 0700) and compare its sha256 before writing.
    3. Render each template from the build tree and install it.
    4. Print `diff -u` between the backup and the new file.
    5. Run `daemon-reload`, restart the units in table order, wait 5 s, and print ActiveState and NRestarts.
    6. Print the exact rollback command.
  - **`verify`** (RO):
    - `nutrition`: `/health` 200 on 9930; any HTTP answer on 9931; `GET /profile/PSN-00013` without a delegation is 401; `printenv BLS_DB` in both containers. In *both* containers, `python -c "from app.deps import _build_provider; print(_build_provider().search_food('Apfel')[0].food_id)"` must start with `bls:`, else it prints `FAIL`.
    - `home-bff`: `/health`, and the mint socket answers 401 to `svc-home-gateway` without `X-Runtime-ID`.
    - `home-hub`: the October `hub-rollout.sh verify` checks: 9933/9930 reachable from the container; 9931/9932/9934 refused; anonymous `/app/nutrition` returns 307.
  - **`rollback <backup-dir>`** (LIVE): restores every file byte for byte (sha256 printed), reloads, and restarts in table order.
- **README.** It documents the laptop-side archive. Paths per component:
  - `nutrition`: `services/nutrition packages/nutrition-domain deploy/nutrition`
  - `home-bff`: `services/home-bff deploy/home-bff`
  - `home-hub`: `apps/home-hub deploy/home-hub`

  ```
  git archive <SHA> <paths> | ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
    "cd /; sudo -n -u <account> bash -c 'mkdir -p /home/<account>/build/<SHA> && tar -x -C /home/<account>/build/<SHA>'"
  ```

- [ ] **Step 1: Write the failing tests.**

```python
def test_script_is_valid_strict_bash_that_starts_at_root(): ...       # bash -n; "set -euo pipefail"; "cd /"
def test_components_accounts_and_restart_order(): ...                 # home-bff-mint before home-bff
def test_every_repo_template_has_exactly_one_placeholder(): ...       # nutrition x2, bff x2, hub x1
def test_render_replaces_only_the_image_line(tmp_path): ...           # bash: source --lib; render; diff == 1 line
def test_render_refuses_a_template_without_or_with_two_placeholders(tmp_path): ...
def test_apply_refuses_a_short_sha_and_backs_up_before_writing(): ... # SHA regex; backup + hash compare precede install
def test_nutrition_verify_requires_bls_in_both_containers(): ...      # both container names in the bls check; FAIL path
def test_never_prints_environment_files(): ...                        # no cat/sed of EnvironmentFile paths or .env
```

- [ ] **Step 2: Run the tests and confirm they fail.** Use the deploy command on `deploy/ops/tests`. Expected: FAIL.
- [ ] **Step 3: Implement the script and the README.** Model `apply` and `verify` on `.worktrees/ops-2026-10-24/hub-rollout.sh`; that script is not in the repo, so read it there.
- [ ] **Step 4: Run the tests and confirm they pass.** Run the deploy command including the new folder.
- [ ] **Step 5: Commit.** Message: `feat: one image rollout script for nutrition, bff and hub`.

---

### Task 4: BFF: a grant never replaces another person's live grant, even in a race

**Files:**
- Modify: `services/home-bff/home_bff/store.py`, `services/home-bff/home_bff/app.py` (`POST /runtime/grant`)
- Test: `services/home-bff/tests/test_grant_claim.py` (create), `services/home-bff/tests/test_runtime_per_person.py`

**Interfaces:**
- **`SessionStore.claim_runtime_grant(runtime_id, home_session_id, allowed_audiences, *, ttl_seconds, grantor_ref) -> RuntimeGrant | None`.** It runs inside one `_mutation()` (`BEGIN IMMEDIATE`):
  - **Refuse (return `None`, write nothing)** when the current row is live (`expires_at > now`) and its non-empty `grantor_ref` fails `sessions.refs_match` with `grantor_ref`.
  - **Otherwise** write the same row `put_runtime_grant` writes, and return it.
  - **Empty argument:** an empty `grantor_ref` raises `ValueError`.
- **`put_runtime_grant`** is unchanged.
- **`/runtime/grant`:**
  - It calls `claim_runtime_grant` where it called `put_runtime_grant`.
  - On `None`: close the just-opened Home grant (best effort, like the store-failure path) and return the existing 409 page `Este asistente ya tiene el permiso de otra persona.`
  - The pre-check before Home stays.

- [ ] **Step 1: Write the failing tests.**

```python
def test_claim_writes_when_no_row(tmp_path): ...
def test_claim_replaces_own_legacy_and_expired_rows(tmp_path): ...
def test_claim_refuses_another_persons_live_row(tmp_path): ...       # None; row unchanged
def test_two_people_claiming_at_once_leave_exactly_one_owner(tmp_path): ...
    # two SessionStore on one file, threading.Barrier(2), refs A and B: exactly one non-None; row.grantor_ref == winner
def test_claim_with_an_empty_ref_raises(tmp_path): ...
def test_race_lost_after_home_opened_closes_the_home_grant(ctx): ...
    # Ana grants; the fake open_runtime_grant inserts the owner's live row before returning;
    # -> 409 with the copy above; close_calls == [the HDS Home returned]; owner row intact
```

- [ ] **Step 2: Run the tests and confirm they fail.** Use the BFF command on the two files.
- [ ] **Step 3: Implement the claim and the route change.**
- [ ] **Step 4: Run the full BFF suite.** Expected: all pass (446 + new, 10 skipped).
- [ ] **Step 5: Commit.** Message: `fix: grant claim never replaces another person's live grant`.

---

### Task 5: Gateway runbook fixes, and the first run of the 9937 nginx tests

**Files:**
- Modify: `deploy/home-bff/README.md` ("Per-person runtimes rollout"), `deploy/gateway/README.md`. Also `deploy/gateway/*` and its tests only if Step 1 finds a defect.
- Test: `deploy/home-bff/tests/test_rollout_runbook.py` (create)

- [ ] **Step 1: Run the nginx harness for the first time.** Use a throwaway Ubuntu 26.04 container (the node's OS), from the repo root. Docker comes from Rancher Desktop on the laptop.

```bash
docker run --rm -v "$PWD:/src:ro" -w /src ubuntu:26.04 bash -c \
  "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx python3 python3-pytest >/dev/null \
   && nginx -v && python3 -m pytest -q -p no:cacheprovider deploy/gateway/tests/test_gateway_integration.py deploy/gateway/tests/test_gateway_lifecycle.py"
```

  - Read `nginx -v` on the node read-only and record both versions.
  - **Expected:** every test passes, including `test_ana_port_mints_as_ana_even_when_the_client_forges_the_runtime` and `test_ana_port_has_no_finance_route`.
  - **On a failure:** use superpowers:systematic-debugging, then fix the config or the harness in this task and re-run. Never skip or xfail.
  - **The lifecycle test as root:** if it is skipped or fails only because the container runs as root, run that file again as an unprivileged user in the same container (`useradd t && su t -c …`) and record that.
- [ ] **Step 2: Write the failing runbook test.** It checks these facts in `deploy/home-bff/README.md`:
  - Every `nginx -t` runs as `sudo -u svc-home-gateway nginx -e /dev/stderr -t …`.
  - Rollback 6.1 has two cases:
    - **Before 3.3:** only `sudo rm /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new`; there is no `.old`.
    - **After 3.3:** restore `.old`, reload, then remove `.conf.new`.
  - The precondition names "the owner's Hermes user (uid 1003)" and gives `id home-agent-ana` and `id home-agent` with "no `episteck-gw`".
  - Step 3.2 runs `deploy/ops/image-rollout.sh home-bff apply <SHA>`.
  - The integration-test precondition names the container run from Step 1.

  In `deploy/gateway/README.md`, the line "On test rollback delete only `table inet episteck_gateway`" is gone. In its place: `On rollback, restore the previous boot file and restart episteck-gateway-nft.service. Never delete the table at runtime (that drops every rule until the next boot) and never flush the global ruleset.`
- [ ] **Step 3: Run the test and confirm it fails.** Use the deploy command on the new file.
- [ ] **Step 4: Edit both READMEs.** Record Step 1's result (date, nginx versions, pass counts) under "Isolated integration harness".
- [ ] **Step 5: Run the deploy suites and confirm they pass.**
- [ ] **Step 6: Commit.** Message: `docs: fix the per-person rollout runbook and record the 9937 nginx run`.

---

### Task 6: Hub: read today's diary

**Files:**
- Create in `apps/home-hub/src/integration/nutrition/`: `nutrition-delegation.ts`, `diary-contract.ts`, `diary-loader.ts`, `diary.server.ts`
- Modify:
  - `apps/home-hub/src/integration/nutrition/profile-loader.ts` (imports the shared mint and helpers; behavior unchanged)
  - `apps/home-hub/test-support/verify-adapter-callers.mjs` and its `.test.mjs`
  - `apps/home-hub/test-support/verify-server-only-client-import.mjs` (`PROBES`)
- Test: `diary-contract.test.ts`, `diary-loader.test.ts`, next to the code. `profile-loader.test.ts` stays unchanged and must pass.

**Interfaces:**
- **`nutrition-delegation.ts`** holds the code moved out of `profile-loader.ts`:
  - `NUTRITION_AUDIENCE`, `DELEGATION_HEADER`, `PERSON_ID`
  - `mintNutritionDelegation(o: { fetcher: typeof fetch; bffBaseUrl: string; cookieValue: string; timeoutMs?: number }): Promise<{ token: string } | { error: SafeUIErrorCode }>`
  - `readJson`, `readyEnvelope<T>(data: T, environment)`, `failedEnvelope<T>(code)`
- **`diary-contract.ts`** (field names are camelCase; wire names in comments):

```ts
export type DayStatus = 'NO_ENTRIES' | 'OPEN' | 'COMPLETE';
export type SugarStatus = 'NONE' | 'KNOWN' | 'PARTIAL';
export type ConversionMethod = 'USER_STATED' | 'SOURCE_SERVING' | 'PRESET' | 'AGENT_ESTIMATE';
export interface DiaryItem { label: string; amount: string; unit: string; grams: string; method: ConversionMethod; source: string | null; freeSugarsG: string | null }
export interface DiaryEntry { id: string; consumedAt: string; items: DiaryItem[] }
export interface DiaryLimit { valueG: string; sources: { title: string; url: string }[] }
export interface DiaryDay { date: string; mode: 'GENERAL' | 'PREGNANCY'; trimester: 1 | 2 | 3 | null; dayStatus: DayStatus; sugarStatus: SugarStatus; freeSugarsKnownG: string | null; itemsTotal: number; itemsUncounted: number; limit: DiaryLimit | null; entries: DiaryEntry[]; attribution: string[] }
export function parseDayWire(body: unknown): DiaryDay; // throws TypeError on any malformed required field
```

  - **Mapping:** `method` comes from `conversion.method`, and `source` from `facts.source`.
  - **Amounts:** an amount may arrive as a number or a numeric string; keep it as a string.
  - **Decimal strings** must match `/^\d+(\.\d+)?$/`.
  - **Unknown wire fields** are ignored.
- **`diary-loader.ts`:** `loadDiaryToday(o: LoadDiaryTodayOptions): Promise<DataEnvelope<DiaryDay>>`. The options are those of `LoadNutritionProfileOptions`.
  - **Before any fetch, in this order:**
    1. MOCK → READY with an empty `NO_ENTRIES` day and `environment: 'MOCK'`.
    2. No URLs → `NOT_CONFIGURED`.
    3. No cookie → `SESSION_REQUIRED`.
    4. A bad person id → `INVALID_RESPONSE`.
  - **Calls:** one mint, then exactly one `GET {nutrition}/diary/{encodeURIComponent(personId)}/days/today` with `X-Episteck-Delegation`, no cookie, `cache:'no-store'`, `redirect:'manual'` and the timeout.
  - **Status mapping:** 200 → `parseDayWire` (malformed → `INVALID_RESPONSE`); 401 → `SESSION_INVALID`; 403 → `ACCESS_DENIED`; ≥500 → `SERVICE_UNAVAILABLE`; anything else → `INVALID_RESPONSE`.
- **`diary.server.ts`:** `import 'server-only'`; `readDiaryToday(context: F3ActiveContext): Promise<DataEnvelope<DiaryDay>>`. It calls `assertIssuedContext(context)` before `cookies()`.
- **Guard rules.** These mirror the profile pair:
  - Only `src/app/nutrition/hoy/LiveTodayPanel.tsx` may import `diary.server`.
  - Only `diary.server.ts` may import `diary-loader`.
  - The adapter calls `assertIssuedContext(` before `cookies()`.
  - No `'use client'` file imports either module.
  - `diary.server` is added to `PROBES`.

- [ ] **Step 1: Write the failing tests.**

```ts
test('MOCK never fetches and returns a non-LIVE empty day')
test('missing URLs, missing cookie and a bad person id fail before any fetch')
test('one mint, then one GET /diary/PSN-00001/days/today with the delegation and without the cookie')
test('a mint 401 is SESSION_INVALID and Nutrition is never called')
test('Nutrition 401, 403, 404 and 500 map to SESSION_INVALID, ACCESS_DENIED, INVALID_RESPONSE, SERVICE_UNAVAILABLE')
test('a malformed day is INVALID_RESPONSE')
test('a null free-sugar figure stays null, never "0"')            // contract
test('an empty day parses to NO_ENTRIES with a null total')       // contract
test('the guard rejects diary.server imported outside LiveTodayPanel and diary-loader imported outside diary.server') // .test.mjs
```

- [ ] **Step 2: Run the tests and confirm they fail.** Run `npm test` and `npm run test:server-boundary`.
- [ ] **Step 3: Implement.** Move the mint into `nutrition-delegation.ts` first and run `profile-loader.test.ts` unchanged, then add the diary modules and the guard rules.
- [ ] **Step 4: Run the Hub unit, boundary, lint and type checks and confirm they pass.**
- [ ] **Step 5: Commit.** Message: `feat: hub reads today's food diary through one delegation`.

---

### Task 7: Hub: the "Hoy" page

**Files:**
- Create:
  - `apps/home-hub/src/components/features/nutrition/today-panel-model.ts` (+ `.test.ts`), `TodayPanel.tsx`, `TodayPanel.module.css`
  - `apps/home-hub/src/app/nutrition/hoy/page.tsx`, `apps/home-hub/src/app/nutrition/hoy/LiveTodayPanel.tsx`
  - `apps/home-hub/e2e/nutrition-today.spec.ts`
- Modify:
  - `apps/home-hub/src/app/layout.tsx`: `liveRoutes` becomes `['/nutrition', '/nutrition/hoy']`.
  - `apps/home-hub/src/app/nutrition/page.tsx`: in LIVE, one link `Hoy` to `/nutrition/hoy`, keeping `?person=` when set.
  - `apps/home-hub/test-support/fake-nutrition.mjs`: the diary route.

**Interfaces:**
- Consumes Task 6.
- **Produces `toTodayPanelModel(envelope: DataEnvelope<DiaryDay>): TodayPanelModel`:**

```ts
export type TodayPanelModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | { kind: 'TODAY'; heading: string; sugarLine: string; meter: { valueG: number; limitG: number } | null;
      statusLine: string; entries: { time: string; items: { text: string; sugar: string }[] }[];
      referenceLine: string | null; attribution: string[] };
```

  A READY envelope that is not LIVE is `NOT_CONFIGURED`, as the profile model does.
- **Exact copy:**
  - **Numbers:** `Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 })` on the decimal string, followed by ` g`.
  - **`heading`:** `Hoy` for GENERAL. For PREGNANCY: `Hoy · Embarazo, 1.er trimestre`, `2.º trimestre`, `3.er trimestre`, or `Hoy · Embarazo` when the trimester is null.
  - **`sugarLine`:**
    - `NO_ENTRIES` → `Azúcares libres: sin registros todavía`, with `meter: null`.
    - Entries but a null total → `Azúcares libres: sin dato`.
    - Otherwise `Azúcares libres: {known} de {limit}`, or `Azúcares libres: {known}` without a limit. Append ` (por encima de la referencia)` when known > limit.
  - **`statusLine`:** `Sin registros hoy` | `Día abierto` | `Día cerrado`. When PARTIAL, add ` · 1 alimento sin contar` or ` · {n} alimentos sin contar`.
  - **Entry `time`:** `HH:MM` from `consumedAt`, formatted in `Europe/Berlin` (`Intl.DateTimeFormat('es-ES', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit' })`).
  - **Item `text`:** `{label}, {portion}`.
    - **Portion:** `{amount} g|ml` for USER_STATED g or ml. Otherwise `{amount} {unit label} ({~ when PRESET or AGENT_ESTIMATE}{grams} g)`.
    - **Unit labels (singular/plural, plural when amount ≠ 1):**

      | Token | Label |
      | --- | --- |
      | serving | porción del envase / porciones del envase |
      | small_glass | vaso pequeño / vasos pequeños |
      | glass | vaso / vasos |
      | large_glass | vaso grande / vasos grandes |
      | cup | taza / tazas |
      | can | lata / latas |
      | tablespoon | cucharada / cucharadas |
      | teaspoon | cucharadita / cucharaditas |
      | piece | unidad / unidades |
      | slice | rebanada / rebanadas |
      | plate | plato / platos |
      | portion | porción / porciones |
  - **Item `sugar`:** `sin dato` when null, else the formatted grams.
  - **`referenceLine`:** `Referencia general: {limit} de azúcares libres al día (OMS, DGE). No es una indicación médica.`
  - **Error copy in `TodayPanel`:**

    | Kind | Copy |
    | --- | --- |
    | DENIED | `No tienes acceso a este diario.` |
    | SESSION | `Inicia sesión para ver tu día.`, with the profile panel's sign-in link |
    | UNAVAILABLE | `El diario no responde ahora. Inténtalo de nuevo.`, with the existing `RetryButton` |
    | INVALID | `No se pudo leer el diario.` |
    | NOT_CONFIGURED | `La vista Hoy solo funciona con datos reales.` |
    | LOADING | `Cargando tu día…` |
- **`TodayPanel`:**
  - The root is `<section lang="es">`.
  - The figure is `<meter min=0 max={limitG} value={min(valueG, limitG)} aria-label={sugarLine}>` next to the same text, so meaning never depends on color.
  - **Layout:** copy the markup and CSS of the prototype's daily overview (`renderVariantA`, `.dailyHero/.overview/.big`) and meal timeline (`renderVariantB`, `.timeline/.timelineRow/.time`) from `git show origin/spike/nutrition-intake-review:apps/home-hub/src/app/nutrition/prototype/AnaNutritionPrototype.tsx` (and `.module.css`). No client state.
- **`LiveTodayPanel`** follows `LiveProfilePanel`:
  - It calls `resolveLiveSubject`, then `readDiaryToday`, then `toTodayPanelModel`.
  - It writes one log line, `nutrition.today outcome=<kind>`, and calls `unstable_rethrow` in its catch.
- **`hoy/page.tsx`:**
  - It sets `dynamic = 'force-dynamic'`.
  - MOCK renders `NOT_CONFIGURED`.
  - LIVE renders the Suspense pattern of `nutrition/page.tsx` with a LOADING fallback.
- **`fake-nutrition.mjs`:** `GET /diary/{id}/days/today`. Scenarios:
  - `today-empty`: 200 `NO_ENTRIES`.
  - `today-partial`: 200, two entries: a glass of juice PRESET 17.0 and a BLS item with a null figure; `attribution` has the BLS text.
  - `today-denied`: 403.
  - `today-error`: 500.
  - Every other scenario: the `today-empty` day.

- [ ] **Step 1: Write the failing model tests.**

```ts
test('an empty day never shows 0 g anywhere')            // no model string matches /(^|\D)0 g/; meter null
test('a partial day shows the known sum and the uncounted count')  // "Azúcares libres: 17 g de 50 g"; "Día abierto · 1 alimento sin contar"
test('two uncounted items use the plural')
test('estimates carry ~ and stated amounts do not')       // "Zumo, 1 vaso (~200 g)"; "Cola, 330 ml"
test('times are Berlin clock times')                      // "2026-11-18T23:30:00+01:00" -> "23:30"; "2026-11-18T23:30:00Z" -> "00:30"
test('decimal comma, no trailing ,0')                     // "15.9" -> "15,9 g"; "17.0" -> "17 g"
test('pregnancy heading per trimester and without one')
test('over the reference says so in words')
test('BLS attribution passes through')
test('a READY envelope that is not LIVE is NOT_CONFIGURED')
```

- [ ] **Step 2: Write the failing e2e spec** (`e2e/nutrition-today.spec.ts`, using the `signIn` and `observed` helpers of `nutrition-profile.spec.ts`).

```ts
test('an empty day shows "Sin registros hoy" and never "0 g"; one mint and one diary call without a cookie')
test('a partial day lists entries with ~, "1 alimento sin contar" and the BLS attribution')
test('denied shows the Spanish denied copy; a 500 offers retry')
test('no demo banner on /app/nutrition/hoy in LIVE')
```

- [ ] **Step 3: Run the tests and confirm they fail.** Run `npm test` and `npm run test:e2e`.
- [ ] **Step 4: Implement the model, the panel, the route, the link, `liveRoutes` and the fake route.**
- [ ] **Step 5: Run every Hub check and confirm it passes.** Every existing e2e spec passes unchanged.
- [ ] **Step 6: Commit.** Message: `feat: hub "hoy" page with today's free sugars`.

---

### Task 8: Ana's skill and persona

**Files:**
- Create in `deploy/hermes/home-agent-ana/`: `skills/olin-nutrition/SKILL.md`, `SOUL.md`, `config-ana.yaml` (reference only, like `config-finance.yaml`: every key Task 9 sets, no credential)
- Test: `deploy/hermes/tests/test_olin_nutrition_skill.py`

**Interfaces:**
- **Produces:** the section heading `## Evening check-in (cron)`, which Task 9's cron prompt names.
- **The skill body** is English instructions with exact Spanish replies, like `olin-finance`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_frontmatter_and_required_tools_exist(): ...
    # name olin-nutrition; requires_tools ==
    # [mcp__home__whoami, mcp__nutrition__search_foods, mcp__nutrition__propose_intake,
    #  mcp__nutrition__confirm_intake, mcp__nutrition__correct_intake, mcp__nutrition__void_intake,
    #  mcp__nutrition__get_day_summary, mcp__nutrition__close_day, mcp__nutrition__set_nutrition_mode];
    # each maps (via _hermes_mcp_name) to an @mcp.tool in services/nutrition/app/mcp/server.py
    # or services/home-mcp/home_mcp/server.py
def test_no_finance_anywhere(): ...                         # "finance" not in skill, SOUL or config-ana (case-insensitive)
def test_fixed_spanish_replies_are_present(): ...
    # "¿Lo guardo? (sí / corrige)", "¿Eso fue todo hoy?", "Todavía no leo fotos; dime qué es.",
    # "sin dato", "Referencia general", "Eso es mejor consultarlo con tu matrona o tu médico.",
    # "Solo te ayudo con tu diario de comidas.",
    # "No tengo permiso para usar tu diario. Renuévalo en bff.home.episteck.com/runtime."
def test_unknown_or_empty_is_never_zero(): ...              # the rule naming null -> "sin dato" and NO_ENTRIES -> no "0 g"
def test_ambiguous_yes_acts_on_the_last_question_only(): ...# section names both branches and the fallback question "¿Qué quieres que confirme?"
def test_mode_changes_need_her_explicit_confirmation(): ...
def test_unit_tokens_match_the_tool_guide(): ...            # tokens listed in the skill == tokens in _ITEM_GUIDE
def test_german_search_fallback_is_taught(): ...            # mentions BLS names are German, e.g. "Apfelschorle"
def test_soul_is_spanish_and_loads_the_skill_first(): ...
```

- [ ] **Step 2: Run the tests and confirm they fail.** Use the deploy command on `deploy/hermes/tests`. Expected: FAIL.
- [ ] **Step 3: Write `SKILL.md`.** Frontmatter as tested; `description: "Diario de comidas de Ana: registrar lo que come y bebe y ver los azúcares libres del día."`. Sections, in this order:
  - **"Who you act for":**
    - Call `mcp__home__whoami` once per conversation.
    - Pass its `actor_person_id` as `subject_person_id` to every Nutrition tool.
    - Never another id, and never show it.
  - **"Logging food":**
    - Identify each item, then `search_foods`. Try her words, then the German name (BLS names are German: "Apfel", "Brezel", "Apfelschorle"), then English.
    - Pick a unit token from the tool guide (list all tokens).
    - For `piece`, `slice`, `plate` and `portion`, give a visible estimate (`grams_estimate`).
    - Call `propose_intake`.
    - **Reply:** one line per item, with `~` on estimated portions and each item's free sugars as returned or `sin dato`. Then `¿Lo guardo? (sí / corrige)`.
    - Never confirm without her yes.
  - **"Confirming":**
    - Call `confirm_intake`.
    - **Reply:** `Guardado.`, then today's free sugars from the returned `day`, then `items_uncounted` with the names of the items not counted. Show `attribution` when present.
  - **"Corrections and deleting":**
    - Before confirming: propose again.
    - After confirming: `correct_intake` with the full list.
    - Delete: `void_intake`, only after naming the entry and getting her yes.
  - **"Foods no source knows":**
    - `food_id: null` is saved as `sin dato`.
    - You may offer the nearest match: `¿La registro como «<nombre>»?`. Never substitute silently.
  - **"Numbers":**
    - Every number comes from a tool result in this turn.
    - A null figure is `sin dato`, never 0.
    - `NO_ENTRIES` is `todavía no hay registros hoy`, never `0 g`.
  - **"The reference, not a limit":**
    - Say it as `Referencia general`, e.g. `32 g de una referencia general de 50 g al día (OMS, DGE)`.
    - Never use "debes".
    - Clinical questions get `Eso es mejor consultarlo con tu matrona o tu médico.`
  - **"Mode":**
    - Call `set_nutrition_mode` only after she states it and answers yes to `¿Confirmas que estás embarazada y que la fecha probable de parto es el <fecha>? (sí / no)`.
    - After the birth, switch to `GENERAL` the same way.
    - Never infer.
  - **"Yes and no":** act on your last question only.
    - After `¿Lo guardo?`, confirm the draft.
    - After `¿Eso fue todo hoy?`, call `close_day` and reply `Día cerrado.` with the final figure.
    - Otherwise ask `¿Qué quieres que confirme?`. Never both.
  - **"## Evening check-in (cron)":**
    - Call `whoami` and `get_day_summary` once each.
    - `COMPLETE`, or an error → `[SILENT]`.
    - An access refusal → the permission line.
    - Otherwise one short message ending with exactly `¿Eso fue todo hoy?`: today's figure against the reference and the uncounted count, or for `NO_ENTRIES`, that nothing is logged yet.
  - **"Errors":**
    - `DRAFT_EXPIRED` → propose again.
    - `PROVIDER_UNAVAILABLE` → `No puedo consultar los alimentos ahora; inténtalo en un rato.`
    - `INVALID_ITEM` → fix the item once (e.g. add `grams_estimate`), else ask.
    - An access refusal → the permission line.
  - **"Photos":** reply `Todavía no leo fotos; dime qué es.`
  - **"Only the diary":** reply `Solo te ayudo con tu diario de comidas.`
  - **"Privacy":**
    - Never write food, amounts or health facts to memory.
    - Never talk about anyone else's data.
- [ ] **Step 4: Write `SOUL.md` and `config-ana.yaml`.** `SOUL.md`, in Spanish, three sentences:
  - Olin is Ana's food-diary assistant, short and warm.
  - Before answering any message, load the skill `olin-nutrition` with `skill_view` and follow it.
  - Olin gives no medical advice and has access to nothing but her diary.
- [ ] **Step 5: Run the tests and confirm they pass.** Use the deploy command.
- [ ] **Step 6: Commit.** Message: `feat: olin-nutrition skill and persona for ana's agent`.

---

### Task 9: Ana's agent installer, media purge and secret-drop slot

**Files:**
- Create:
  - `deploy/hermes/install-home-agent-ana.sh`
  - `deploy/hermes/home-agent-ana/systemd/ana-media-purge.service`, `ana-media-purge.timer`, `hermes-gateway-memory.conf`
- Modify: `deploy/secret-drop/secret-drop`, `deploy/secret-drop/README.md`
- Test: `deploy/hermes/tests/test_install_home_agent_ana.py` (create), `deploy/secret-drop/tests/test_secret_drop.py`

**Interfaces:**
- **Invocation:** like `install-olin-finance.sh`. `git archive <SHA> deploy/hermes` is extracted to `SRC=/var/lib/episteck/hermes-ana`, then `ssh … 'sudo -n bash -s -- <step> [arg]' < deploy/hermes/install-home-agent-ana.sh`.
- **Constants:**

| Constant | Value |
| --- | --- |
| `AGENT` | `home-agent-ana` |
| `HERMES_COMMIT` | `a89c1e1135a97dc1262926d93933357fbacd2bd2` |
| `INSTALLER_URL` | `https://raw.githubusercontent.com/NousResearch/hermes-agent/$HERMES_COMMIT/scripts/install.sh` |
| `INSTALLER_SHA256` | `sha256sum /home/home-agent/.hermes/hermes-agent/scripts/install.sh` on the node, read-only, in Step 1. That clone is clean at the pin. |
| `SKILLS_ROOT` | `/etc/episteck/hermes-ana/skills` |
| `GW` | `http://127.0.0.1:9937` |
| `CRON_NAME` | `olin-nutrition-checkin` |
| `MIN_AVAILABLE_MB` | `900` |

- **Steps.** Every step runs as the agent via `runuser` with `HOME`, `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` set and stdin from `/dev/null`, as in `install-olin-finance.sh`.

| Step | Kind | Does |
| --- | --- | --- |
| `preflight` | RO | MemAvailable ≥ 900 MB; ≥ 5 GB free on `/`; node TZ `+0000`. `id home-agent-ana` (absent, or present without `episteck-gw` and with a uid other than 0, 1003, `svc-home-gateway`'s and `www-data`'s). The owner's Hermes HEAD (as `home-agent`) == `HERMES_COMMIT`. The owner's `install.sh` sha256 == `INSTALLER_SHA256`. The HTTP status of `GW/gateway/home/` as the agent, when the user exists. |
| `user` | LIVE | `useradd -m -s /bin/bash home-agent-ana`; `chmod 700` the home; `loginctl enable-linger`; print `id`. Idempotent. |
| `install` | LIVE | As the agent: download the installer, compare its sha256 (stop on mismatch), run it with `--commit "$HERMES_COMMIT" --skip-setup --skip-browser --skip-computer-use --no-skills`. Then require `hermes --version` to contain `v0.21.2` and `git rev-parse HEAD` == the pin. |
| `configure` | LIVE | Back up `config.yaml` when present, mode 0700 under `/var/backups/episteck/hermes-ana-<stamp>/`. Install `SOUL.md` (agent-owned, 0644) and the skill (root:root 0644, directories 0755). Set every key of `config-ana.yaml` with Hermes' own `hermes_cli.config` load/save in the agent's venv python. For `telegram` and `cron`, disable each built-in toolset that `hermes tools list --platform <p>` shows enabled, except `skills` and `clarify`. Print the changed key paths and both tool lists. |
| `env` | LIVE | Create `.env` (0600, agent-owned) when missing. Copy the `KIMI_API_KEY` and `KIMI_BASE_URL` lines from `/home/home-agent/.hermes/.env` without printing them. Print the key names present. |
| `telegram <id>` | LIVE | `^[0-9]{5,15}$`. Back up, then set `TELEGRAM_ALLOWED_USERS=<id>` and `TELEGRAM_HOME_CHANNEL=<id>` in `.env`, plus `platforms.telegram.enabled: true` and `home_channel {platform: telegram, chat_id: <id>, user_id: <id>}`. Restart the gateway when active. Re-runnable: test phase, then Ana. |
| `login` | LIVE, owner approves | Start `hermes auth add openai-codex --type oauth --no-browser --label ana-codex` detached, with `PYTHONUNBUFFERED=1`, output to `~/.hermes/codex-login.log` (0600). Wait up to 20 s, then print only the lines holding the verification URL and the user code. |
| `login-check` | RO | `hermes auth list` lines naming `ana-codex`. Smoke tests: `hermes chat -q "Responde solo: ok" --oneshot -Q --provider openai-codex -m gpt-5.6-sol`, then the same with `--provider kimi-coding -m kimi-k2.6`; each answer contains `ok`. |
| `gateway` | LIVE | Require `TELEGRAM_BOT_TOKEN` (`grep -c`) and an `ana-codex` credential. `hermes gateway install`; install `hermes-gateway-memory.conf` (`[Service]` `MemoryMax=900M`) as a drop-in; `daemon-reload`; `enable --now`. After 10 s print ActiveState, NRestarts, the cgroup `memory.max`, the RSS, and `home-agent`'s NRestarts (it must not change). |
| `cron <HH:MM>` | LIVE | `^([01][0-9]|2[0-3]):[0-5][0-9]$`. Refuse unless the installed skill `cmp`s equal to the shipped one and has `## Evening check-in (cron)`, and unless `timezone` == `Europe/Berlin`. Remove the job by name, then `hermes cron create --name olin-nutrition-checkin --deliver telegram --failure-deliver local --skill olin-nutrition "<MM> <HH> * * *" "$CRON_PROMPT"`, then show it. |
| `purge` | LIVE | Install the timer and service into `~/.config/systemd/user`; `enable --now` the timer; show the next trigger. |
| `verify` | RO | Everything above as an end state. Telegram and cron enabled sets == `{skills, clarify}`. The MCP servers are exactly `nutrition` and `home`. `.env` key names, the allowed-users count == 1, file modes. The skill is root-owned and `cmp`-equal. MemoryMax is effective. `curl` as the agent: 9937 gives an HTTP status, 9934 times out (exit 28). `free -m`. |
| `stop` | LIVE | Disable the gateway and the timer, and remove the cron job. State is kept. |
| `rollback-config <dir>` | LIVE | Restore `config.yaml` byte for byte; restart. |
| `remove yes-delete-home-agent-ana` | LIVE | Without that exact word it does nothing. Otherwise: `stop`; tar `~/.hermes` to `/var/backups/episteck/` (0700); `loginctl disable-linger`; `userdel -r`; remove `SKILLS_ROOT`. |

- **`CRON_PROMPT`** (exact):

```
Scheduled evening check-in. Follow the skill section "Evening check-in (cron)".
1. Call mcp__home__whoami once, then mcp__nutrition__get_day_summary once with subject_person_id set to its actor_person_id and no date. Call no other tool and save nothing.
2. If day_status is COMPLETE, or a call returns an error other than an access refusal, your whole final response is exactly [SILENT].
3. If a call returns an access refusal, reply with the permission line from the skill and stop.
4. Otherwise write ONE short message in Spanish as that section says, ending with exactly: ¿Eso fue todo hoy?
```

- **Purge units:**
  - **`ana-media-purge.service`** (`Type=oneshot`) runs `/usr/bin/find %h/.hermes/cache/audio %h/.hermes/audio_cache %h/.hermes/cache/image %h/.hermes/image_cache -type f -mmin +10 -delete`, then `/usr/bin/find %h/.hermes/cron/output -type f -mtime +0 -delete`. Missing directories are ignored (`-ignore_readdir_race`, `2>/dev/null` via `sh -c`).
  - **`.timer`:** `OnBootSec=5min`, `OnUnitActiveSec=10min`.
- **Secret-drop slot:** `telegram-ana|env|/home/home-agent-ana/.hermes/.env|home-agent-ana|TELEGRAM_BOT_TOKEN|^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$|Telegram bot token for Ana's Olin (Hermes home-agent-ana)`

- [ ] **Step 1: Record `INSTALLER_SHA256` read-only from the node.**
- [ ] **Step 2: Write the failing tests.**

```python
def test_script_is_valid_strict_bash_that_starts_at_root(): ...
def test_hermes_is_pinned_and_the_installer_is_hash_checked_before_it_runs(): ...
def test_agent_uses_only_port_9937_and_no_finance(): ...       # no "9934" except in the verify timeout check; no "finance"
def test_ana_skills_root_is_not_the_owners(): ...
def test_only_skills_and_clarify_remain_on_telegram_and_cron(): ...
def test_checkin_runs_in_berlin_time_and_refuses_otherwise(): ...  # timezone check precedes `cron create`; schedule "$MM $HH * * *"
def test_checkin_failures_stay_local_and_delivery_is_mirrored(): ... # --failure-deliver local; config-ana cron.mirror_delivery true
def test_checkin_prompt_names_a_skill_section_that_exists(): ...
def test_memory_is_off_capped_and_preflighted(): ...           # memory_enabled false; MemoryMax=900M; MIN_AVAILABLE_MB 900 checked
def test_secrets_are_never_printed(): ...                      # no cat/echo of .env, auth.json or codex-login.log beyond URL/code lines
def test_media_purge_every_ten_minutes_for_media_older_than_ten(): ...
def test_remove_needs_the_exact_word(): ...
# in test_secret_drop.py:
def test_the_ana_token_slot_targets_her_env_as_her_user(): ...
```

- [ ] **Step 3: Run the tests and confirm they fail.**
- [ ] **Step 4: Implement the script, the three unit files and the slot.** Update the secret-drop README's slot list.
- [ ] **Step 5: Run the deploy suites and confirm they pass.**
- [ ] **Step 6: Commit.** Message: `feat: installer for ana's hermes agent, media purge and her token slot`.

---

### Task 10: Rollout runbook, architecture docs and status

**Files:**
- Create: `docs/runbooks/nutrition-r1-rollout.md`
- Modify: `docs/architecture/AGENTS.md` (a third instance, `home-agent-ana`), `docs/architecture/DEPLOYMENT.md` (the BLS reference mount and Ana's agent), `docs/architecture/STATUS.md` (the Nutrition, BFF runtime-grant and Hub rows: "merged, not deployed")

- [ ] **Step 1: Write the runbook.** It is Part B below in runbook format (`.claude/rules/docs.md`): "When to Use", "Prerequisites", the steps with their labels and exact commands from Tasks 2, 3, 5 and 9, a "Verification" and "Rollback" per stage, and the acceptance checklist.
- [ ] **Step 2: Edit the three architecture docs.**
  - `AGENTS.md`: Ana's instance in its own subsection. Cover the user, the port, its tools, its model with the fallback, memory off, and that it is not in `episteck-gw`.
- [ ] **Step 3: Check every suite one last time.** Nutrition, BFF, deploy and Hub (unit, boundary, lint, tsc, e2e). Record the counts in the PR body.
- [ ] **Step 4: Commit.** Message: `docs: nutrition release 1 rollout runbook and agent docs`.
- [ ] **Step 5: Open the PR.** Base `main`. Its body lists the suites and the parked items below. It is merged only when the owner names it.

---

## Part B: Production rollout (after the owner merges Part A)

`SHA` is the merge commit. Each stage ends with `[CLAUDE VERIFY]` and has its own rollback. A failed check stops the rollout at that stage.

**Owner inputs:**

| Input | Stage | How it is given |
| --- | --- | --- |
| Ana's login email | B2 | Typed by the owner in the Frappe desk |
| A tester email the owner controls | B2 | Desk |
| Bot token for a new BotFather bot for Ana | B5 | Secret drop, slot `telegram-ana` (Termius) |
| The owner's own Telegram ID (test phase) | B5 | `telegram <id>` argument |
| Ana's Telegram ID | B6 | `telegram <id>` argument |
| The ChatGPT device login | B5 | The owner opens the printed URL, enters the code and approves with the owner's ChatGPT account |
| The check-in time (HH:MM, Berlin) | B6 | `cron <HH:MM>` argument |
| The due date | B6 | Ana tells her bot; the owner checks the heading |

**B0. Preparation. Nothing goes live.**
1. `[PREP]` Build `bls-4.0.sqlite` locally from the merged importer. Expect `wrote 7140 foods`. Record the sha256 and `scp` the file to `/home/episteck/stage/`.
2. `[PREP]` Extract the three archives and the `deploy/hermes` archive (Task 3 README, Task 9). Run `image-rollout.sh <component> build <SHA>` for nutrition, home-bff and home-hub.
3. `[CLAUDE VERIFY]` Run `image-rollout.sh <component> baseline` for all three. Run `install-home-agent-ana.sh preflight`. Run `free -m`. Run the owner's `hermes cron list` (the Finance job is present).

**B1. Nutrition (plan 1 live, BLS in both containers).**
1. `[OPERATOR]` Install the reference file:
   - Create `/srv/episteck/services/nutrition/reference` (0750, `svc-nutrition`).
   - Install the file at 0440.
   - `sha256sum`: it must equal B0.1's value.
2. `[OPERATOR]` Run `image-rollout.sh nutrition apply <SHA>`. The diff per unit is exactly: the `Image=` line, `Volume=…reference:/reference:ro`, `BLS_DB`, and `DIARY_TZ`.
3. `[CLAUDE VERIFY]` Run `image-rollout.sh nutrition verify`. Checks:
   - Both containers' first `Apfel` hit is `bls:`.
   - The diary tables exist; list them with `python -c` inside `nutrition`, names only.
   - Logs carry no food text.
   - NRestarts is 0.
   - The live Hub `/app/nutrition` still answers.

**Rollback:** `image-rollout.sh nutrition rollback <backup-dir>`. The reference file may stay; the old image ignores it, and the diary tables it ignores too.

**B2. Home (site config and desk only).**
1. `[OPERATOR]` In the desk, open OAuth Client "Episteck Home BFF" and tick **Skip Authorization**. This fixes the phone login that fires twice.
2. `[OPERATOR INPUT]` Create two Users, each with **Send Welcome Email** on, no roles (a Website User), and exactly one Person with **Linked User** set:
   - Ana's User. If a Person for Ana already exists, link that one instead of creating a new one.
   - The tester's User, with Person `Prueba Nutrición (sintética)`.
3. `[OPERATOR]` Set the site config on Ashburn. The runtime is mapped to the **tester** first:
   ```bash
   bench --site home.episteck.com set-config -p home_runtime_ids '["home-agent-primary","home-agent-ana"]'
   bench --site home.episteck.com set-config -p home_runtime_grantees_by_runtime \
     '{"home-agent-primary":["<owner user, as in home_runtime_grantees>"],"home-agent-ana":["<tester email>"]}'
   ```
4. `[CLAUDE VERIFY]` Read-only SQL and config checks, counts and flags only:
   - The OAuth client has `skip_authorization=1`.
   - Both users are enabled Website Users with exactly one Person each.
   - Each runtime has 1 grantee.
   - An anonymous `get_grantable_runtimes` still returns 403.

**Rollback:**
- Untick Skip Authorization.
- `bench --site home.episteck.com execute frappe.installer.update_site_config --args '["home_runtime_grantees_by_runtime","None"]'`.
- Set `home_runtime_ids` back to `["home-agent-primary"]`.

**B3. BFF, gateway and firewall window** (the runbook from Task 5, `deploy/home-bff/README.md`).
1. `[OPERATOR]` Run `install-home-agent-ana.sh user`. `[CLAUDE VERIFY]` `id home-agent-ana` shows no `episteck-gw`, and the uid collides with nothing.
2. `[OPERATOR]` Stage the gateway `.new` and `nginx -t` it as `svc-home-gateway`. Stage the nft boot `.new` and run `nft --check`.
3. Window, in this order:
   1. `[OPERATOR]` 3.1 Load nft.
   2. `[OPERATOR]` 3.2 Run `image-rollout.sh home-bff apply <SHA>`. The diff per unit is `Image=` plus `RUNTIME_IDS`. The owner's bot returns 401 until the next step.
   3. `[OPERATOR]` 3.3 Install the live gateway config, run `nginx -t` as `svc-home-gateway`, and reload.
4. `[OPERATOR]` **Immediately:** log in again at `bff.home.episteck.com/runtime` and re-grant `home-agent-primary`.
5. `[CLAUDE VERIFY]` README step 5 and `image-rollout.sh home-bff verify`.
   - The owner sends the owner's own bot one Home question and one Finance question. Both answer.

**Rollback:** README step 6 as fixed in Task 5. Never serve 9937 in front of the old BFF.

**B4. Hub ("Hoy").**
1. `[OPERATOR]` Run `image-rollout.sh home-hub apply <SHA>`. The diff is the `Image=` line only.
2. `[CLAUDE VERIFY]` Run `image-rollout.sh home-hub verify`. An anonymous `/app/nutrition/hoy` returns 307 to the login.
3. `[OPERATOR]` On the phone, open `/app/nutrition/hoy`. Expected: `Sin registros hoy`, no `0 g`, no demo banner.

**Rollback:** `image-rollout.sh home-hub rollback <backup-dir>`.

**B5. Ana's agent, proven with the synthetic person.**
1. `[OPERATOR]` Run `install-home-agent-ana.sh install`, then `configure`, then `env`.
2. `[OPERATOR]` Install the updated `secret-drop` to `/usr/local/sbin/` (secret-drop README).
   - `[OPERATOR INPUT]` Create Ana's bot in @BotFather.
   - In Termius, drop the token in slot `telegram-ana`.
   - `[CLAUDE VERIFY]` The journal line `stored slot=telegram-ana`, and `.env` mode 600.
3. `[OPERATOR]` Run `telegram <owner's own Telegram ID>`.
4. `[OPERATOR INPUT]` Run `login`, then approve the device code with the owner's ChatGPT account.
5. `[CLAUDE VERIFY]` Run `login-check`. Both providers answer `ok`.
6. `[OPERATOR]` Run `gateway`, then `purge`. Then run `cron <a time 5 minutes ahead>`.
7. `[CLAUDE VERIFY]` Run `verify`. The owner's `home-agent` NRestarts is unchanged and `free -m` is noted.
8. `[OPERATOR]` In a private browser window, log in as the tester at `bff.home.episteck.com/runtime`. Only `home-agent-ana` is listed; grant it. Then open `/app/nutrition/hoy` as the tester.
9. End-to-end, on the owner's phone with Ana's bot (spec 7, step A):
   1. A voice note, e.g. "un vaso de zumo de naranja y dos rebanadas de pan", gives a draft with `~` and `¿Lo guardo? (sí / corrige)`.
   2. `sí` gives `Guardado.` and the free-sugar figure. The tester's Hoy page shows the entry.
   3. A voice correction, "era un vaso grande", calls `correct_intake`, and Hoy shows the new figure.
   4. "una arepa" is saved as `sin dato`. Hoy shows `1 alimento sin contar`, never `0 g`.
   5. The check-in arrives, ending `¿Eso fue todo hoy?`. `sí` gives `Día cerrado.`, and Hoy shows `Día cerrado`.
   6. A photo gets `Todavía no leo fotos; dime qué es.`
   7. "¿qué tiempo hace?" gets `Solo te ayudo con tu diario de comidas.`
   8. 15 minutes after the voice notes, the audio cache is empty (`[CLAUDE VERIFY]`, file count only).
   9. Nutrition logs show ids and statuses only.
   10. The owner's own bot still answers Home and Finance.

**Rollback:** `stop`, then optionally `remove yes-delete-home-agent-ana`. The Home mapping and grants stay harmless without the agent.

**B6. Switch to Ana.**
1. `[OPERATOR]` As the tester, revoke the grant at `/runtime`. Then disable the tester User in the desk.
2. `[OPERATOR]` Map `home-agent-ana` to Ana's user:
   ```bash
   bench --site home.episteck.com set-config -p home_runtime_grantees_by_runtime \
     '{"home-agent-primary":["<owner user>"],"home-agent-ana":["<Ana email>"]}'
   ```
3. `[OPERATOR INPUT]` Run `telegram <Ana's Telegram ID>`, then `cron <Ana's check-in time>`.
4. With Ana, on her phone:
   - She sets her password from the welcome email.
   - She logs in at `bff.home.episteck.com`.
   - She grants at `/runtime`; only `home-agent-ana` is shown.
   - She bookmarks `/app/nutrition/hoy`.
5. Ana writes to her bot: `Estoy embarazada; la fecha probable de parto es el <fecha>`. She confirms. The Hoy heading reads `Hoy · Embarazo, 2.º trimestre`.
6. `[CLAUDE VERIFY]` Checks:
   - `verify` passes.
   - The BFF holds two live grants with distinct grantor references (counts only).
   - The 9937 gateway log shows 200s.
   - The owner's bot is unaffected.
7. Claude updates the "Olin Household Guide" artifact and writes the rollout evidence to the deploy READMEs and `STATUS.md` in a docs PR.

**B7. One week with Ana (spec 7).** Each day Claude checks read-only:
- The check-in was delivered.
- Ana's agent and `home-agent` show no restarts.
- Nutrition logs no errors.
- Memory headroom.

If her Spanish voice notes come out poorly, compare the `small` Whisper model with `base` on three of her recordings, and measure RAM before switching `stt.local.model` (spec 6.2).

Collect what annoyed Ana before extending the scope (plan 4).

---

## Parked for plan 4 (not in this plan)

- **Nutrition data and display:**
  - USDA branded and FNDDS category fields for the free-sugar class.
  - The day shows the profile's current mode, not the stamped mode. This matters once past days are shown (Week view).
  - The protein, energy and DHA pregnancy references are unverified; nothing shows them yet.
  - `get_food_detail` has no error mapping.
- **Hub:**
  - Meal names and ml labels for drinks.
  - A "Hoy" entry in the main navigation (exact-match active state).
- **BFF (plan 2's "can wait" minors):**
  - Distinct log line for a Finance refusal of a known runtime.
  - Store-down 503 page may become 500.
  - Home asked twice when it is unreachable during a grant.
- **Home and gateway:**
  - The tester User can be deleted once the week with Ana has passed.
  - The gateway README's generic "Switch" block on a true first install.
