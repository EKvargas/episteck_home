# Nutrition profile · Plan 2: Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Ultron and Ana's bot one repo-managed nutrition skill. It covers onboarding, profile updates, day and period reviews, recommendations and the evening check-in. Install it for both agents, give Ultron the evening check-in, and replace Ultron's self-written nutrition notes with pointers. One runbook installs the backend and the agents together.

**Architecture:** One `SKILL.md` under `deploy/hermes/skills/olin-nutrition/`, installed root-owned and read-only into each agent's external skills directory: `/etc/episteck/hermes/skills` for Ultron and `/etc/episteck/hermes-ana/skills` for Ana. Per-agent differences stay outside the skill:
- **Language and scope:** Ana's `SOUL.md`.
- **Access checks:** Ultron's own standing skill, which calls `check_access` before each domain call.
- **Check-in time and language:** each installer's cron prompt.

Ultron gets a new installer, `install-olin-nutrition.sh`, on the pattern of `install-olin-finance.sh`. A small, tested Python helper rewrites the nutrition parts of Ultron's agent-owned notes into pointers.

**Tech Stack:** Hermes Agent v0.21.2, bash (Git Bash for local tests), Python 3.11 stdlib, pytest, PyYAML (already used by the tests).

**Spec:** `docs/superpowers/specs/2026-11-23-nutrition-profile-onboarding-design.md`, sections 6.8, 6.9 and 7 (the live acceptance steps). Plan 1, the Nutrition backend, is merged at `53dd190` and not deployed. Plan 3 covers the Hub's views.

## Global Constraints

- Tests run from the repo root: `C:\AIProjects\episteck-delivery-workspace\.venvs\nutrition-r1\Scripts\python.exe -m pytest -q -p no:cacheprovider deploy/hermes/tests`. Abbreviated below as `HT`. The backend suites (`packages/nutrition-domain/tests services/nutrition/tests`) must keep passing; nothing here changes them.
- Implementers never touch the node. The scripts run only when the owner says go, through the runbook in Task 5.
- Installed skill files are `root:root 644` in root-owned directories, so an agent cannot rewrite its own rules. Shell scripts are LF-only, start with `set -euo pipefail` and `cd /`, run agent commands through an `as_agent` helper with stdin from `/dev/null`, and never read or print `.env`, `auth.json`, tokens or memory contents.
- Before changing anything, a script backs up every file it changes and prints the backup directory. Rollback restores those files byte for byte.
- Numbers rule (release 1, spec 3): every figure comes from a Nutrition tool result in the same turn. The agent never adds up, averages or estimates nutrient totals. Unknown is `sin dato`, never 0.
- Fixed Spanish wording, used verbatim when replying in Spanish (existing release 1 phrases stay):
  - `¿Lo guardo? (sí / corrige)`
  - `Guardado.`
  - `¿Eso fue todo hoy?`
  - `Día cerrado.`
  - `¿Qué quieres que confirme?`
  - `sin dato`
  - `Referencia general`
  - `Eso es mejor consultarlo con tu matrona o tu médico.`
  - `Todavía no leo fotos; dime qué es.`
  - `No tengo permiso para usar tu diario. Renuévalo en bff.home.episteck.com/runtime.`
  - `¿Confirmas que estás embarazada y que la fecha probable de parto es el <fecha>? (sí / no)`
- New fixed wording:
  - `Para compararlo con tus objetivos necesito tu perfil. ¿Lo creamos ahora? Son unas ocho preguntas.`
  - `¿Cierro el <día> de <mes>? (sí / no)`
  - `Por ahora el perfil es solo para mayores de 19 años.`
  - `En el embarazo no fijamos objetivos de peso ni de déficit.`
  - `Todavía no registro el ejercicio; lo tendré cuando conectemos tu reloj.`
  - Ana's scope line, which lives in her SOUL: `Solo te ayudo con tu nutrición.`
- The Nutrition MCP has exactly 20 tools (plan 1). Tool names in skills use Hermes' form `mcp__<server>__<tool>`.
- Ultron's Hermes reads cron expressions in UTC: `config.yaml` has no `timezone` and the node is UTC; Finance's job requires it. Ana's reads them in `Europe/Berlin`.

## Review Focus

- **A bare "sí" while an intake draft and a profile draft are both pending:** the agent acts on its last question only. Task 1 test `test_yes_acts_on_the_last_question_for_either_draft`.
- **The owner writes to Ultron in English:** fixed Spanish phrases are translated faithfully, not mixed in. Ana, whose SOUL fixes Spanish, gets them verbatim. Task 1 test `test_language_rule_is_explicit`.
- **Hermes has rewritten Ultron's own skill since this plan was written** (the nutrition heading renamed or gone): the helper changes nothing and the installer stops with a message rather than corrupting the file. Task 3 test `test_missing_heading_changes_nothing`.
- **Daylight saving:** `cron 21:45` run in winter schedules 20:45 UTC and prints a reminder to re-run after the switch to summer time. Task 4 test `test_cron_converts_berlin_time_to_utc_and_reminds_about_dst`.
- **Ana asks for weight-loss advice while pregnant:** the agent gives the fixed refusal, never a deficit. Task 1 test `test_pregnancy_guardrails`.

---

### Task 1: The shared nutrition skill

**Files:**
- Move: `deploy/hermes/home-agent-ana/skills/olin-nutrition/SKILL.md` → `deploy/hermes/skills/olin-nutrition/SKILL.md` (`git mv`, then rewrite)
- Modify: `deploy/hermes/install-home-agent-ana.sh`. Add `SHARED_SKILL=$SRC/skills/olin-nutrition/SKILL.md` and route every former `$ANA_SRC/skills/olin-nutrition/SKILL.md` use through it: in `need_src`, `configure`, `cron` and `verify`. The install target `$SKILL_DIR/SKILL.md` is unchanged.
- Modify: `deploy/hermes/tests/test_olin_nutrition_skill.py` (new path; tests below; fixes the stale `== 21` tool count that fails on `main`) and `deploy/hermes/tests/test_install_home_agent_ana.py` (the `SKILL` constant)

**Interfaces:**
- Produces:
  - The skill at `deploy/hermes/skills/olin-nutrition/SKILL.md` with frontmatter `name: olin-nutrition` and `version: 2.0.0`. Ana's installer reads it through `SHARED_SKILL`.
  - Section headings that later tasks grep for, exactly as written: `## Evening check-in (cron)`, `## Yes and no`, `## Profile and onboarding`.
  - `metadata.hermes.requires_tools` lists exactly `mcp__home__whoami` and these Nutrition tools: `search_foods`, `get_food_detail`, `evaluate_meal`, `propose_intake`, `confirm_intake`, `correct_intake`, `void_intake`, `get_diary_entry`, `get_day_summary`, `get_period_summary`, `close_day`, `set_nutrition_mode`, `get_nutrition_profile`, `propose_profile`, `confirm_profile`, `search_recipes`, `get_meal_plan`, `plan_menu` (each as `mcp__nutrition__<name>`).

Sections, in this order. Rules are from spec 6.8 and 6.9; wording within the Global Constraints is the builder's.

1. **Who you act for:** `mcp__home__whoami` once per conversation and its `actor_person_id` as `subject_person_id`; never show the id. If your standing rules require an explicit access check before domain calls, keep doing it.
2. **Language:** reply in the language your persona sets. If it sets none, reply in the language the person writes in. Quoted phrases are the Spanish wording: use them verbatim in Spanish, and translate them faithfully in another language.
3. **Numbers:** the release 1 rules (`null` is `sin dato`, never 0; `NO_ENTRIES` is `todavía no hay registros hoy`, never `0 g`). Add: never add up, average or estimate nutrients yourself; use `get_day_summary`, `get_period_summary`, `evaluate_meal` or `plan_menu`. A target is a reference, not an order: no scores, no "debes".
4. **Logging food**, **Confirming**, **Corrections and deleting**, **Foods no source knows:** the release 1 sections, kept, with the `Unit tokens:` line.
5. **Profile and onboarding:**
   - **When to offer:** when the person asks, or when a review needs targets and `get_nutrition_profile` returns `{"error": "no profile"}` or `"onboarded": false`. Offer with the fixed offer line, at most once per conversation.
   - **Questions,** one or two per message, skipping anything already known: birth date; sex (for the calculation; never asked in pregnancy mode); height; current weight and when it was measured; a normal day, mapped to `activity_pal` 1.4, 1.6, 1.8 or 2.0 and shown in words; training sessions per week and what; goal in GENERAL mode only (mantener, perder grasa, ganar músculo, rendimiento → `MAINTAIN`, `LOSE_FAT`, `BUILD_MUSCLE`, `PERFORMANCE`); food preferences, dislikes and intolerances. In pregnancy mode: the due date through the Mode flow if missing, and the weight before the pregnancy. No goal.
   - **Proposing:** call `propose_profile` with only the fields the person gave in this conversation. Show the fields, the chosen activity level and goal in words, each target from `targets_after` with its one-line explanation, and anything listed as missing. Then ask `¿Lo guardo? (sí / corrige)`.
   - **Confirming:** after a yes, call `confirm_profile`, then reply `Guardado.` and one line on what the targets are for.
   - **Updates** ("ahora peso 82"): the same flow with only that field. Show the targets before and after.
   - **`INVALID_FIELD` reasons:**
     - `UNDER_19` → the under-19 line.
     - `NOT_ALLOWED_IN_MODE` → in pregnancy, the pregnancy weight line.
     - `MEASUREMENT_TOO_OLD` and `FUTURE_DATE` → ask for the current value and date.
     - `OUT_OF_RANGE` and `INVALID_FORMAT` → ask the person to check that field.
     - `NO_CHANGES` → say there is nothing to save.
6. **Reviews and recommendations:**
   - Today → `get_day_summary`. Several days → `get_period_summary` with `start` and `end` (at most 31 days).
   - Show each day's energy, protein, fiber and free sugars against that day's targets, and the averages the tool returns, with days used and left out. Unknowns read `sin dato`.
   - When a review needs an open past day, ask once with the close-day line, then `close_day` with that date.
   - Recommendations are practical foods tied to the gaps the tools show. Without a profile, make no personal claims of too little or too much.
   - A match or training session the person mentions is context for advice only. Never change targets or store it. If asked about burned energy, use the exercise line.
7. **Foods, meals, recipes and menus:**
   - `search_foods`, then `get_food_detail`, before any figure. `evaluate_meal` takes `food_id` with `grams`.
   - In `plan_menu`, a `null` gap and the nutrients in `unknown_in_menu` read `sin dato`.
   - `search_recipes` and `get_meal_plan` for ideas.
8. **Mode:** the release 1 section (explicit confirmation line, never inferred, back to GENERAL after the birth).
9. **Pregnancy:**
   - No weight-loss goal, energy deficit or dieting advice; use the pregnancy weight line.
   - Clinical questions get the clinical line.
   - References are said as `Referencia general`.
10. **Yes and no:**
    - Act on your last question only.
    - After `¿Lo guardo?`, confirm the draft that question was about: `confirm_intake` for food, `confirm_profile` for the profile.
    - After `¿Eso fue todo hoy?` or the close-day line, `close_day` with the date it named, never today by default, then `Día cerrado.`
    - Otherwise ask `¿Qué quieres que confirme?`. Never both.
11. **Evening check-in (cron):**
    - Call `whoami` and `get_day_summary` once each.
    - A COMPLETE day, or an error other than an access refusal, gets exactly `[SILENT]`. An access refusal gets the permission line.
    - Otherwise send one short message naming the day as day and month in words, no weekday. Include the free sugars against the reference and the uncounted items. When `profile_version` is not null, also include energy and protein from `nutrients` against their targets. End with the finish question.
12. **Photos:** if you can read the image, use it only as evidence for a draft (transcribe, never assume amounts). If you cannot, use the photos line.
13. **Errors:** `DRAFT_EXPIRED` → propose again. `PROVIDER_UNAVAILABLE` → the release 1 line. `INVALID_ITEM` → fix the item once. `INVALID_FIELD` → section 5. An access refusal → the permission line.
14. **Privacy:** never write food, amounts, body data or health facts to memory or to skill notes. Never talk about anyone else's data.

- [ ] **Step 1: Write the failing tests** in `test_olin_nutrition_skill.py`. `SKILL` points at the new path. Keep the existing tests whose subject stays: unit tokens, German search fallback, late `consumed_at`, the mode confirmation, numbers, and the check-in contract. Re-point them, and replace the tests below.

```python
REQUIRED = ["mcp__home__whoami"] + [f"mcp__nutrition__{t}" for t in (
    "search_foods", "get_food_detail", "evaluate_meal", "propose_intake", "confirm_intake",
    "correct_intake", "void_intake", "get_diary_entry", "get_day_summary", "get_period_summary",
    "close_day", "set_nutrition_mode", "get_nutrition_profile", "propose_profile",
    "confirm_profile", "search_recipes", "get_meal_plan", "plan_menu")]

def test_frontmatter_and_required_tools_exist():          # name, version 2.0.0, REQUIRED exactly,
    ...                                                   # each in the servers' tool lists; nutrition has 20 tools

def test_the_skill_lives_in_one_shared_place():
    assert not (ROOT / "deploy/hermes/home-agent-ana/skills").exists()

def test_ana_installer_reads_the_shared_skill():
    t = (ROOT / "deploy/hermes/install-home-agent-ana.sh").read_text(encoding="utf-8")
    assert "SHARED_SKILL=$SRC/skills/olin-nutrition/SKILL.md" in t and "$ANA_SRC/skills" not in t

def test_fixed_spanish_replies_are_present(): ...          # every phrase in Global Constraints except the scope line
def test_scope_line_is_not_in_the_shared_skill():
    assert "Solo te ayudo" not in _body()

def test_language_rule_is_explicit():
    s = _flat(_section(_body(), "## Language"))
    assert "persona" in s and "language the person writes in" in s and "verbatim" in s and "translate" in s

def test_never_sums_nutrients_itself():
    s = _flat(_section(_body(), "## Numbers"))
    for tool in ("get_day_summary", "get_period_summary", "evaluate_meal", "plan_menu"):
        assert tool in s
    assert "never add up" in s.lower()

def test_onboarding_flow():
    s = _flat(_section(_body(), "## Profile and onboarding"))
    for needle in ("propose_profile", "confirm_profile", "onboarded", "targets_after", "1.4", "1.6",
                   "1.8", "2.0", "MAINTAIN", "LOSE_FAT", "BUILD_MUSCLE", "PERFORMANCE",
                   "at most once", "UNDER_19", "NOT_ALLOWED_IN_MODE", "MEASUREMENT_TOO_OLD"):
        assert needle in s, needle

def test_reviews_use_the_period_tool_and_ask_before_closing_past_days():
    s = _flat(_section(_body(), "## Reviews and recommendations"))
    assert "get_period_summary" in s and "31" in s and "¿Cierro el" in s and "close_day" in s

def test_yes_acts_on_the_last_question_for_either_draft():
    s = _flat(_section(_body(), "## Yes and no"))
    assert "last question" in s and "confirm_intake" in s and "confirm_profile" in s and "Never both" in s

def test_pregnancy_guardrails():
    s = _flat(_section(_body(), "## Pregnancy"))
    assert "En el embarazo no fijamos objetivos de peso ni de déficit." in s
    assert "Eso es mejor consultarlo con tu matrona o tu médico." in s

def test_check_in_adds_energy_and_protein_with_a_profile():
    s = _flat(_section(_body(), "## Evening check-in (cron)"))
    assert "profile_version" in s and "energy" in s and "protein" in s and "[SILENT]" in s

def test_privacy_rule():
    s = _flat(_section(_body(), "## Privacy")).lower()
    assert "memory" in s and "body data" in s
```

- [ ] **Step 2: Run** `HT deploy/hermes/tests/test_olin_nutrition_skill.py`. Expected: FAIL (path missing).
- [ ] **Step 3: `git mv` the skill and rewrite it** per the sections above. Keep it under about 220 lines. Route Ana's installer through `SHARED_SKILL`.
- [ ] **Step 4: Run** `HT`. Expected: all PASS, including `bash -n` on Ana's installer.
- [ ] **Step 5: Commit** `git add -A deploy/hermes && git commit -m "feat: share one nutrition skill between both agents"`

### Task 2: Ana's persona and check-in for the wider scope

**Files:**
- Modify: `deploy/hermes/install-home-agent-ana.sh` (step 4 of `CRON_PROMPT` only), `deploy/hermes/home-agent-ana/SOUL.md`
- Modify: `deploy/hermes/tests/test_install_home_agent_ana.py` (the cron-prompt constant), `deploy/hermes/tests/test_olin_nutrition_skill.py` (the SOUL test)

**Interfaces:**
- Consumes: Task 1's skill and its `## Evening check-in (cron)` heading.
- Produces:
  - Step 4 of `CRON_PROMPT` adds: "When profile_version is not null, also give energy and protein from nutrients against their targets." The ending stays `¿Eso fue todo hoy?`.
  - SOUL (Spanish, one paragraph):
    - Olin is Ana's nutrition assistant.
    - It loads `olin-nutrition` with `skill_view` before replying.
    - It always replies in Spanish.
    - It gives no medical advice.
    - For anything that is not nutrition it replies `Solo te ayudo con tu nutrición.`

- [ ] **Step 1: Update the tests.** The cron-prompt constant follows the new wording. The SOUL test asserts `olin-nutrition`, `skill_view`, `Olin`, `Ana`, `nutrición`, `médic`, `Solo te ayudo con tu nutrición.` and `español`, and that there are no English function words.
- [ ] **Step 2: Run** `HT`. Expected: FAIL on the new assertions.
- [ ] **Step 3: Change** the cron prompt and SOUL.
- [ ] **Step 4: Run** `HT`. Expected: all PASS, including `bash -n` on the script.
- [ ] **Step 5: Commit** `git add deploy/hermes && git commit -m "feat: widen Ana's agent to nutrition and add targets to her check-in"`

### Task 3: Rewrite Ultron's own nutrition notes as pointers

Ultron's standing skill `~/.hermes/skills/episteck-home-agent/SKILL.md` and its `references/nutrition-diary.md` are agent-owned files, partly written by Ultron itself. They teach rules this design replaces, such as "calculate per-day totals with a computation tool", and they name the retired `get_daily_nutrition_gap`. As read on 2026-11-23:
- The standing skill has a section `## Nutrition intake capture`, followed by `## Consumer-product health claims`.
- One bullet under `## Tool invocation mechanics` names `mcp__nutrition__get_daily_nutrition_gap`.

**Files:**
- Create: `deploy/hermes/ultron_nutrition_notes.py`, `deploy/hermes/home-agent/nutrition-pointer-section.md`, `deploy/hermes/home-agent/nutrition-diary-pointer.md`
- Test: `deploy/hermes/tests/test_ultron_nutrition_notes.py`

**Interfaces:**
- Produces, in `ultron_nutrition_notes.py` (stdlib only, run as `python3 -I ultron_nutrition_notes.py <skill.md> <pointer-section.md>`):
  - `NUTRITION_HEADINGS = ("## Nutrition intake capture", "## Nutrition")`
  - `RETIRED_TOOL = "get_daily_nutrition_gap"`
  - `rewrite(text: str, pointer_section: str) -> tuple[str, list[str]]`. It returns the new text and a list of what changed (`"section replaced"`, `"retired tool line removed"`).
    - It replaces the first heading in `NUTRITION_HEADINGS` and its body, up to the next line starting `## ` or the end of the file, with `pointer_section`.
    - It removes every line containing `RETIRED_TOOL`.
    - If no heading is found, it raises `NotesChanged("nutrition heading not found")`.
    - Text already equal to the result produces `(text, [])`.
  - `class NotesChanged(Exception)`
  - `main(argv) -> int`: rewrites the file in place, keeping its owner and mode, and prints only the change list. Exit 0 = rewritten or already current. Exit 3 = `NotesChanged`: the file is left untouched and a message tells the operator to look at the section by hand.
- `nutrition-pointer-section.md` starts with `## Nutrition` and says, in English: for everything about nutrition (diary, profile and onboarding, day and period reviews, recommendations, recipes and menus), load the `olin-nutrition` skill with `skill_view` and follow it; it replaces the notes that used to be here.
- `nutrition-diary-pointer.md`: `# Nutrition diary workflows`, then one sentence: moved; load `olin-nutrition` with `skill_view`; do not add nutrition procedures here.

- [ ] **Step 1: Write the failing tests** on a fixture copied from the 2026-11-23 shape:

```python
SAMPLE = ("# Episteck Home Agent\n\n## Tool invocation mechanics\n\n- one per tool_call\n"
          "- `mcp__nutrition__get_daily_nutrition_gap` requires `date`.\n\n## Finance workflows\n\nf\n\n"
          "## Nutrition intake capture\n\n1. old rule\n\nSee [references/nutrition-diary.md](x).\n\n"
          "## Consumer-product health claims\n\nc\n")
POINTER = (HERMES / "home-agent" / "nutrition-pointer-section.md").read_text(encoding="utf-8")

def test_rewrite_replaces_the_section_and_drops_the_retired_tool():
    new, changes = rewrite(SAMPLE, POINTER)
    assert "old rule" not in new and POINTER.strip() in new and "get_daily_nutrition_gap" not in new
    assert "## Finance workflows" in new and "## Consumer-product health claims\n\nc\n" in new
    assert changes == ["section replaced", "retired tool line removed"]

def test_rewrite_is_idempotent():
    once, _ = rewrite(SAMPLE, POINTER)
    assert rewrite(once, POINTER) == (once, [])

def test_missing_heading_changes_nothing():
    with pytest.raises(NotesChanged): rewrite(SAMPLE.replace("## Nutrition intake capture", "## Food"), POINTER)

def test_main_keeps_mode_and_reports_without_content(tmp_path, capsys): ...  # file rewritten, mode kept, stdout = change list only
def test_main_exit_3_leaves_file_untouched(tmp_path): ...
def test_pointers_name_the_skill():
    for f in ("nutrition-pointer-section.md", "nutrition-diary-pointer.md"):
        t = (HERMES / "home-agent" / f).read_text(encoding="utf-8")
        assert "olin-nutrition" in t and "skill_view" in t
```

- [ ] **Step 2: Run** `HT deploy/hermes/tests/test_ultron_nutrition_notes.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the module and the two pointer files.
- [ ] **Step 4: Run** `HT`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add deploy/hermes && git commit -m "feat: add a helper that points Ultron's nutrition notes at the shared skill"`

### Task 4: Ultron's installer and evening check-in

**Files:**
- Create: `deploy/hermes/install-olin-nutrition.sh`
- Test: `deploy/hermes/tests/test_install_olin_nutrition.py`

**Interfaces:**
- Consumes: Task 1's skill path and its `## Evening check-in (cron)` heading; Task 3's helper and pointer files. It follows `install-olin-finance.sh` for structure, `as_agent`, backups, `cron_count`, `cron_show`, `cron_remove` and `restart_gateway`.
- Produces: `install-olin-nutrition.sh <step>`, piped over SSH as root like the Finance installer. Constants:
  - `AGENT=home-agent`
  - `SRC=/var/lib/episteck/hermes-nutrition/deploy/hermes`
  - `SKILLS_ROOT=/etc/episteck/hermes/skills`
  - `SKILL_DIR=$SKILLS_ROOT/olin-nutrition`
  - `NOTES=/home/home-agent/.hermes/skills/episteck-home-agent`
  - `CRON_NAME=olin-nutrition-checkin`
  - `BACKUPS=/var/backups/episteck`

Steps:
- `preflight` (read-only): source present; Hermes version; `mcp_servers.nutrition` and `skills.external_dirs`, printed as key paths and values the way `finance_keys` prints them; `timezone` unset or UTC; node offset `+0000`; whether the skill directory and the cron job exist; and a dry run of the helper on a temporary copy of `$NOTES/SKILL.md`, printing its change list or the `NotesChanged` message.
- `install`:
  1. Back up `config.yaml`, `$NOTES/SKILL.md` and `$NOTES/references/nutrition-diary.md` into `$BACKUPS/hermes-nutrition-<UTC stamp>`, check the hashes, and print the directory.
  2. Install the skill as `root:root 644`.
  3. Run the helper on `$NOTES/SKILL.md`. On exit 3, stop before any further change and print the rollback line.
  4. Replace `references/nutrition-diary.md` with the pointer, owned by `home-agent`, `644`.
  5. Change no `config.yaml` key, check that it is unchanged against the backup, then `restart_gateway`.
- `cron <HH:MM>`, Berlin time:
  1. Validate `HH:MM` with the same regex as Ana's installer.
  2. Require the installed skill to equal this commit's and to have the check-in heading. Require the node to be UTC and `timezone` to be unset or UTC.
  3. Convert the time to UTC with the current offset of `TZ=Europe/Berlin` (`date +%z`), wrapping across midnight.
  4. `cron_remove`, then `hermes cron create --name olin-nutrition-checkin --deliver telegram --failure-deliver local --skill olin-nutrition "<M> <H> * * *" "$CRON_PROMPT"`.
  5. Print the UTC schedule and this reminder: `Berlin changes to summer time on the last Sunday of March and back on the last Sunday of October: re-run 'cron HH:MM' after each change to keep the check-in at HH:MM Berlin time.`
- `CRON_PROMPT` mirrors Ana's 1–3. Its step 4 says to write ONE short message in English, name the day as day and month (no weekday), give the free sugars against the reference and the uncounted items, give energy and protein from `nutrients` against their targets when `profile_version` is not null, and end with exactly `Was that everything today?` The prompt does not contain the job name.
- `verify` (read-only):
  - The skill is root's, `644`, this commit's, readable but not writable by `home-agent`.
  - `$NOTES/SKILL.md` contains `## Nutrition` from the pointer and no `get_daily_nutrition_gap`.
  - `references/nutrition-diary.md` equals the pointer. Report drift, never fix it.
  - `hermes mcp test nutrition` lists 20 tools, including `propose_profile` and `get_period_summary`.
  - `cron_show` and the gateway state.
- `rollback-cron`: remove the job only.
- `rollback <backup-dir>`: in this order:
  1. Remove the job.
  2. Restore `$NOTES/SKILL.md` and `references/nutrition-diary.md` byte for byte, with owner and mode.
  3. Restore `config.yaml` if it differs.
  4. Remove the skill directory.
  5. `restart_gateway`.

- [ ] **Step 1: Write the failing tests**, static checks in the style of `test_install_home_agent_ana.py` (bash `-n` via Git Bash, text assertions, and the small parsers run on sample input):

```python
def test_script_is_strict_bash_lf_and_starts_at_root(): ...       # bash -n; no \r; set -euo pipefail; cd /
def test_skill_is_installed_root_owned_from_the_shared_source(): ...  # install -m 644 -o root -g root "$SRC/skills/olin-nutrition/SKILL.md"
def test_backup_happens_before_any_change():
    t = SCRIPT.read_text(encoding="utf-8"); inst = _step(t, "install")
    assert inst.index("cp -p") < inst.index("install -m 644") < inst.index("ultron_nutrition_notes.py")
def test_helper_exit_3_stops_the_install(): ...                   # the install step checks the helper's exit status 3 and exits non-zero
def test_cron_converts_berlin_time_to_utc_and_reminds_about_dst(tmp_path):
    # run the script's conversion function (extract it or call `bash -c 'source <fn>; to_utc 21:45 +0100'`)
    assert _to_utc("21:45", "+0100") == "45 20"
    assert _to_utc("00:30", "+0100") == "30 23"
    assert _to_utc("21:45", "+0200") == "45 19"
    assert "last Sunday of March" in SCRIPT.read_text(encoding="utf-8")
def test_cron_rejects_bad_times(): ...                             # 24:00, 9:5, 21:60 exit 2 before any change
def test_cron_prompt_is_english_and_ends_with_the_question(): ...  # "in English", ends 'Was that everything today?', no job name
def test_cron_requires_utc_and_this_commits_skill(): ...
def test_rollback_restores_notes_and_removes_the_job_first(): ...
def test_never_reads_secrets(): ...                                # no .env, auth.json, memories content reads
```

The conversion lives in a small bash function `to_utc <HH:MM> <+HHMM>` that prints `"<M> <H>"`, so the tests can call it.

- [ ] **Step 2: Run** `HT deploy/hermes/tests/test_install_olin_nutrition.py`. Expected: FAIL (script missing).
- [ ] **Step 3: Write** the installer.
- [ ] **Step 4: Run** `HT`. Expected: all PASS.
- [ ] **Step 5: Commit** `git add deploy/hermes && git commit -m "feat: add Ultron's nutrition skill installer and evening check-in"`

### Task 5: Runbook: install the backend and both agents together

**Files:**
- Create: `docs/runbooks/nutrition-profile-rollout.md`

Follow the format of `docs/runbooks/nutrition-r1-rollout.md`: the step tags `[CLAUDE VERIFY]`, `[PREP]` and `[OPERATOR]`, the same helper block (`SSH`, `ROLL`, `ANA`, `ARCHIVE`), and a new `NUT() { $SSH "sudo -n bash -s -- $*" < deploy/hermes/install-olin-nutrition.sh; }`. `SHA` is this plan's merge commit; it contains plan 1. Stages, each with verification and rollback:

- **C0 Baseline** `[CLAUDE VERIFY]`:
  - `ROLL nutrition baseline`, `NUT preflight`, `ANA preflight`, and the owner's `NRestarts`.
  - Read-only counts in `nutrition.sqlite`: `profile`, `intake` and `diary_entry` rows per person.
- **C1 Nutrition backend:**
  - `ARCHIVE svc-nutrition services/nutrition packages/nutrition-domain deploy/nutrition`, then `ROLL nutrition build|preview|apply $SHA` and `ROLL nutrition verify`.
  - Checks: `curl` on `:9930/profile/PSN-00013` without a delegation gives `401`. `profile_version` holds only MIGRATED rows, for the legacy synthetic persons. The `intake` row count is unchanged.
  - Rollback: `ROLL nutrition rollback <dir>`. Note: rolling back loses mode changes made on the new image; do not run Ana's B6 inside a rollback window.
- **C2 Ultron:**
  - `git archive $SHA deploy/hermes` into `/var/lib/episteck/hermes-nutrition` (root, as release 1 did for `hermes-ana`).
  - `NUT install`, then `NUT cron 21:45`, then `NUT verify`.
  - Rollback: `NUT rollback <dir>`.
- **C3 Erick (acceptance, spec 7 steps 2–4, 6, 7):**
  1. Onboarding with Ultron.
  2. Ask for "my last two days and today's match", and check the figures against `get_period_summary`. The Hub's Días page arrives with plan 3.
  3. Change your weight on a later day and check that yesterday is unchanged.
  4. Ultron cannot see Ana's profile without her grant.
  5. Check the 21:45 check-in.
- **C4 Ana:**
  - `ANA configure` installs the shared skill; run `ANA verify`.
  - Rollout stage B6 from the release 1 runbook, with her phone, including `ANA cron <HH:MM>`.
  - She sends her due date, then onboards: due date, weight before the pregnancy, the rest.
  - Check: the energy target shows the second-trimester supplement.
- **C5 Watch:** one week of check-ins; memory scan; restart counts.

- [ ] **Step 1: Write** the runbook. Every command it names must exist in the scripts at `SHA`. Check this with a test in `deploy/hermes/tests/test_runbook_commands.py`. The test reads the runbook, finds every `NUT <step>`, `ANA <step>` and `ROLL nutrition <step>` line, and asserts each step name appears as a `case` label in the matching script.
- [ ] **Step 2: Run** `HT`. Expected: PASS.
- [ ] **Step 3: Commit** `git add docs/runbooks deploy/hermes/tests && git commit -m "docs: add the nutrition profile rollout runbook"`
