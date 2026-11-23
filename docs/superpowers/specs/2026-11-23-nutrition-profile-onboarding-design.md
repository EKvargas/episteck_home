# Nutrition profile and onboarding: personal targets for Erick and Ana

**Status:** draft for owner review · **Date:** 2026-11-23 · **Owner:** Erick
**Background:** [Nutrition release 1 design](2026-11-18-nutrition-release-1-design.md) (the diary),
[ADR-0004](../../architecture/adr/0004-svc-nutrition-source-of-truth.md) (Nutrition owns intake and profile),
[ADR-0008](../../architecture/adr/0008-consent-fail-closed.md) (fail-closed consent),
[ADR-0017](../../architecture/adr/0017-per-person-agent-runtimes.md) (one agent per person),
[release 1 rollout runbook](../../runbooks/nutrition-r1-rollout.md).
**Mockups:** https://claude.ai/code/artifact/201a1534-dde6-4121-a878-f30c3f9b4b4a (private to the owner; example numbers).

This is project 1 of three in the agreed Nutrition + Health path:

1. **Profile and onboarding** (this document)
2. Health log: matches, training, symptoms and weight, with Garmin and Apple Watch data
3. Proactive patterns

## 1. Intent

Home Nutrition + Health exists to find patterns in what the family eats, how they move and how
they feel, so the owner does not have to find them himself. It must work in two ways: on request
("give me a recommendation from my last two days and today's match") and proactively.

On 2026-11-22 the on-request case failed. The owner asked Ultron for a recommendation from two
days of eating plus a 90-minute football match. Ultron answered that no personal nutrition
profile exists and that it has no tool to create one. The data model explains why: a profile
today stores only mode, preferences, dislikes, intolerances and a free-form target map. There is
no age, sex, height, weight, activity or goal, no target calculation, and no agent tool that
writes a profile (only `set_nutrition_mode`, which creates an empty one).

This project gives each person a real profile, calculates personal daily targets from named
sources, onboards both people through their own agent, and lets both the agent and the app
compare days against those targets. Patterns (project 3) will build on the same targets.

Two people use it first, each with their own profile:

- **Erick** (owner), about 40, focused on health and improving at sport. Plays football.
  Wears a Garmin.
- **Ana**, pregnant (second trimester started mid-November 2026). Starts with an Apple Watch
  in December. Her diary (release 1) is installed but not yet switched to her
  (rollout stage B6 not run).

## 2. Decisions already made

| Decision | Who / when |
| --- | --- |
| Order: profile and onboarding → health log → proactive patterns | Owner, 2026-11-23 |
| Separate profiles for Erick (about 40, health and sport) and Ana (pregnant) | Owner, 2026-11-23 |
| Ana gets the same nutrition options Erick has | Owner, 2026-11-23 |
| Whatever the agent can read or calculate is also visible in the app | Owner, 2026-11-23 |
| Changes happen in the chat; the app shows the result (mockup choice A) | Owner, 2026-11-23 |
| Body data lives in Nutrition (approach 1, section 5) | Owner, 2026-11-23 |
| Exercise and match data arrive with the health log (project 2), not here | Owner agreed the path, 2026-11-23 |
| Ultron asks every evening whether the day is finished, like Ana's bot | Owner, 2026-11-23 |
| wger rejected for now; Open Wearables deferred | Owner, 2026-11-23 |

Proposed by Claude in the 2026-11-23 conversation and shown to the owner, to be confirmed by
approving this document: the profile fields in 6.2, the goal chosen during onboarding, no
medical conditions in this project, and the free-sugar limit staying at the release 1 rule.

## 3. Goals, non-goals, anti-goals

**Goals**

- A profile per person with body data, activity, training, goal, food preferences and mode.
- Daily targets calculated by Nutrition from named sources, versioned by date.
- Onboarding through each person's own agent in about eight questions, ending with a summary
  and "¿lo guardo?". Updates by chat ("ahora peso 82").
- A several-days comparison against personal targets, calculated by Nutrition, used by the
  agent and shown in the app.
- The app shows the full profile with targets (Perfil), today against targets (Hoy), and
  several days side by side (Días).
- Ana: pregnancy targets that follow her trimester, and the same nutrition abilities as Erick.

**Non-goals (this project)**

- Logging matches, training, symptoms or weight history as health events (project 2).
- Garmin, Apple Watch or any device data (project 2).
- Proactive pattern finding (project 3).
- Editing in the app. The app stays read-only.
- Medical conditions, diagnoses, lab values or medication.
- Pregnancy weight-gain tracking.
- A personal free-sugar limit. The release 1 rule (50 g, 10 % of a standard 2,000 kcal day)
  stays for both people.
- Micronutrient meters in Hoy and Días. Micronutrient targets appear in Perfil only.
- Children and teenagers (under 19).
- The Home landing page redesign (UI track) and a shared multi-person agent.

**Anti-goals (a failure even if it works)**

- The agent saves a profile value the person did not confirm.
- A target appears that Nutrition did not calculate, or the agent does its own target maths.
- Changing a profile changes a past day's targets.
- The app and the agent show different numbers for the same day.
- Weight-loss goals or energy deficits in pregnancy mode.
- Scores, grades or "debes" language. Targets are references, not orders.
- Body data in logs, agent memory or the Home Control Plane.

## 4. Constraints

- **Data residency.** Body data is health data. It stays in Nutrition on the Nuremberg node
  (EU). The Home Control Plane (Ashburn, US) stores none of it.
- **Authorization.** Every person-specific read or write is decided by Home with exactly one
  request per operation (delegations are single-use). Fail closed. Circle membership never
  grants access. One person sees another's profile only through a consent grant.
- **Numbers.** Every figure comes from a Nutrition tool result. The AI never invents nutrient
  values or targets (release 1 rule). Unknown is never 0.
- **Capacity.** Nuremberg has about 1.7 GB of memory free. No new service or container.
- **Agents.** One agent per person (ADR-0017). Ultron is the owner's `home-agent`; Ana's is
  `home-agent-ana` on its own gateway port. Ana's agent uses the owner's ChatGPT login with
  Kimi K2.6 as fallback (release 1 decision).
- **Language.** App labels in Spanish. Ana's agent replies in Spanish. Ultron replies in the
  language the owner writes in.
- **Deployment.** Nutrition and the Hub roll out with the existing Nuremberg roll procedure
  from the release 1 runbook. Agent skills are installed by repo scripts, not edited by hand.

## 5. Approaches considered

**Where body data lives** (owner picked 1):

1. **Everything in Nutrition.** New fields and the target history go into the profile Nutrition
   already owns. In project 2 the weight history either moves to the health log or stays in
   Nutrition and the health log reads it there. Fastest, no new service. The cost is one small,
   planned decision in project 2.
2. **A small Health service first** for body data and weight, read by Nutrition. Each value
   lands in its final home, but it starts project 2 before project 1 works: new service, new
   permissions, new tools, more memory.
3. **Split with Home.** Birth date and sex in the Home person record, the rest in Nutrition.
   Rejected: it puts health data on the US node and spreads one profile over two places.

**How the person changes data** (owner picked A):

- **A. In the chat.** The app offers "Cambiar en el chat" with a ready message; the agent
  proposes, the person confirms. The diary already works this way.
- **B. Also in the app.** An edit form with the same confirm step. Rejected for now: it would be
  the first time the app writes data, which needs its own security review.

## 6. Design

### 6.1 Overview

```
Person ──chat──> own agent (Ultron / Ana's bot)
                   │ propose_profile → summary with targets → "¿lo guardo?" → confirm_profile
                   │ get_nutrition_profile, get_day_summary, get_period_summary
                   ▼
              Nutrition (Nuremberg)
                   profile versions ── target method v1 (pure, in nutrition-domain)
                   diary entries (release 1, frozen food facts)
                   day + period summaries with nutrient totals against the day's targets
                   ▲
Home app (Hub) ────┘ read-only: Perfil, Hoy, Días
Home Control Plane: authorizes every call; stores no body data
```

### 6.2 What the profile holds

| Group | Fields | Notes |
| --- | --- | --- |
| Basics | birth date, sex, height (cm), weight (kg) with the date it was measured | Sex is used only to choose the formula and reference table. Age is derived from birth date on each day. |
| Activity | everyday activity level (one of four, 6.3), training sessions per week (0 to 14) with a short free-text description ("fútbol: 2 entrenos + 1 partido") | The description is shown, never calculated with. |
| Goal | MAINTAIN, LOSE_FAT, BUILD_MUSCLE, PERFORMANCE | GENERAL mode only. Pregnancy mode has no goal field. |
| Food | preferences, dislikes, intolerances | Already exist; unchanged meaning. |
| Mode | GENERAL or PREGNANCY, due date | Already exist (`set_nutrition_mode`). |
| Pregnancy | weight before the pregnancy (kg) | Asked only in pregnancy mode. |

Validation (Claude's call): age 19 to 100 on the day of confirmation, height 120 to 230 cm,
weight 30 to 250 kg, measurement date not in the future and not more than 90 days old. A
profile for someone under 19 is refused with a clear message (non-goal).

A profile may be incomplete. Each target that needs a missing field is left out and shown as
"falta: <campo>", never guessed. Fiber and the free-sugar rule need nothing; protein needs
weight; energy and fat need all basics plus activity.

### 6.3 Target calculation, method v1

Pure, deterministic functions in `packages/nutrition-domain`, like the free-sugar limit rule
(`rules.py`). The method carries a version. A published method is never edited: a change is
method v2, and profile versions keep the method they were calculated with. Every target
carries its value, unit, source organisation, source reference and a one-line Spanish
explanation for the app ("Gasto en reposo × actividad 1,6").

**Energy (kcal).**

- Resting energy: Mifflin-St Jeor (Mifflin et al., Am J Clin Nutr 1990;51:241).
  Men: 10 × kg + 6.25 × cm − 5 × age + 5. Women: 10 × kg + 6.25 × cm − 5 × age − 161.
  (Claude's call; a standard, validated formula that needs only these four values.)
- Activity: the DGE physical activity levels (PAL) for everyday life:
  1.4 mostly sitting with little leisure activity; 1.6 sitting with some walking or standing;
  1.8 mostly standing or walking; 2.0 heavy physical work.
- Training add-on: DGE adds 0.3 PAL for sport 4 to 5 times a week, 30 to 60 minutes. Method v1
  uses 0 for no sessions, +0.1 for 1 to 2, +0.2 for 3 to 4, +0.3 for 5 or more
  (Claude's call, scaled from the DGE figure). Total PAL is capped at 2.4.
- Goal (GENERAL only): MAINTAIN and PERFORMANCE 0 %, BUILD_MUSCLE +10 %, LOSE_FAT −15 % but never
  below resting energy (Claude's call; common practice, the builder cites a source).
- Pregnancy: energy before pregnancy (same formula, with the weight before the pregnancy, no
  goal) plus the DGE trimester supplement: +0 first, +250 kcal second, +500 kcal third
  trimester. The trimester comes from the due date on each day (existing `trimester()`), so the
  supplement steps up on the right dates without a new profile version.

Rounded to the nearest 50 kcal for display; the unrounded value is kept for comparisons.

**Protein (g).**

- GENERAL: 0.8 g per kg (DGE, adults under 65), 1.0 g per kg at 65 and over (DGE).
- GENERAL with 2 or more training sessions a week, or goal BUILD_MUSCLE, PERFORMANCE or
  LOSE_FAT: 1.6 g per kg (ISSN position stand on protein and exercise, 2017: 1.4 to 2.0 g per kg).
- PREGNANCY: the DGE pregnancy reference for the day's trimester, per kg of the weight before
  the pregnancy (Claude's call on which weight). The current fixed 58 g in
  `pregnancy_targets.py` is replaced. The builder confirms the exact DGE values from the source;
  the existing file notes they could not be confirmed on 2026-11-19.

Weight for GENERAL is the current profile weight.

**Fat (g).** 30 % of the energy target ÷ 9 (DGE guideline value 30 to 35 % of energy). Shown as
approximate.

**Fiber (g).** At least 30 g (DGE, adults). Same in pregnancy.

**Free sugars (g).** The release 1 rule `free-sugars-daily-max` v1 (50 g), unchanged and still
chosen by `effective_limit()`. It appears in the target list with its own source.

**Micronutrients.**

- GENERAL: DGE reference values by sex and DGE adult age band (19–24, 25–50, 51–64, 65+) for the
  nutrients the canonical set already knows: calcium, iron, folate, vitamin B12, vitamin D,
  iodine, zinc, selenium.
- PREGNANCY: the existing `PREGNANCY_REFERENCE` table for everything except energy and protein.

Carbohydrates get no target in v1; their daily total is still reported.

**Worked example (for tests).** A man, 40, 180 cm, 82 kg, PAL 1.6, 3 sessions a week, goal
PERFORMANCE: resting energy 10 × 82 + 6.25 × 180 − 5 × 40 + 5 = 1,750 kcal; PAL 1.6 + 0.2 = 1.8;
energy 3,150 kcal; protein 1.6 × 82 = 131 g; fat 3,150 × 0.30 ÷ 9 = 105 g; fiber ≥ 30 g; free
sugars ≤ 50 g. (The mockup page used different example numbers; this one is the test case.)

### 6.4 Versions and history

- Every confirmed change creates a new profile version. Versions are never edited or deleted
  by the agent.
- A version is valid from the local (Europe/Berlin) date it was confirmed. The targets in force
  on day D come from the latest version valid on or before D, its method version, and (for
  pregnancy) the trimester on D.
- Some versions carry no body data: a mode switch before onboarding (Ana sends her due date in
  rollout stage B6, which calls `set_nutrition_mode`) and migrated rows (6.12). They hold mode,
  due date and food fields, so they produce no energy or protein targets.
- **The first onboarded version also covers every earlier day.** "Onboarded" means the first
  version confirmed through `confirm_profile`. For days before it, targets come from that version
  (with each day's trimester in pregnancy mode) instead of from the earlier versions without body
  data. Those days had no calculable targets, so nothing that was shown moves. The question that
  failed on 2026-11-22 ("my last two days") gets an answer right after onboarding, and Ana's days
  logged between B6 and her onboarding get targets too (Claude's call).
- When several versions are confirmed on the same local day, the last one is in force for that
  day. On the onboarding day this includes the backward reach, so a typo fixed the same day is
  fixed everywhere.
- A correction on a later day ("I typed 182, it's 180") is a new version from that day.
  Back-dating corrections is a non-goal for this project.
- A migrated row is valid from the migration date and never reaches backwards.
- Each version stores the inputs, the method version and the calculated base targets, so an
  audit can show exactly what was shown on a given day.
- `get_nutrition_profile` returns the current version, its targets with sources and valid-from
  date, and a short history (version, valid-from, what changed, source = chat).

### 6.5 Drafts and confirmation

Profile changes reuse the release 1 draft pattern (6.7 there):

1. The agent calls `propose_profile` with the person's answers. Only the fields the person gave
   in this conversation are sent; everything else carries over from the current version.
2. Nutrition validates, calculates the targets, stores a draft (24 h time to live) and returns
   the full profile as it would be saved, the targets with sources, the fields still missing,
   and what changes against the current version.
3. The agent shows that summary and asks "¿Lo guardo? (sí / corrige)".
4. Only after the person's yes, the agent calls `confirm_profile`. A repeated yes is idempotent.

The agent may turn free text into a field value ("trabajo en oficina y camino a diario" →
activity 1.6), but it must show the value it chose in the summary, so the person confirms the
interpretation, not just their own words.

`set_nutrition_mode` keeps its own confirmation question (release 1) and also creates a new
profile version, because the mode changes the targets. In pregnancy mode it no longer creates
a profile without targets: the targets that can be calculated appear, the rest show as missing.

### 6.6 Nutrient totals for days and periods

Release 1 day summaries count only free sugars. This project adds nutrient totals from the
same frozen food facts in confirmed, non-voided diary entries:

- For energy, protein, fat, carbohydrate, fiber and each micronutrient with a target: the known
  total and the number of items that could not be counted for that nutrient (no food match, or
  the matched food has no value for it). Same rule as `items_uncounted` for sugars.
- Against the day's targets: target, percentage, and status KNOWN or PARTIAL (some items
  uncounted). A day with no entries stays NO_ENTRIES; no 0.

`get_day_summary` gains this nutrient block (additive; existing fields unchanged).

New `get_period_summary(subject_person_id, start, end)`:

- At most 31 days (Claude's call). Defaults to the last 7 days ending today.
- One row per day: status (NO_ENTRIES / OPEN / COMPLETE), nutrient block as above, and the
  targets in force that day.
- Averages per nutrient over COMPLETE days where that nutrient has no uncounted items, with the
  number of days used and the number left out and why.
- Days before the first profile version have no targets only if the person has no profile at
  all; then the summary says so instead of comparing.

This replaces the instruction Ultron wrote into its own notes on the server
(`references/nutrition-diary.md`: "calculate per-day totals and the multi-day average with a
computation tool"). After this project, the agent never sums nutrients itself.

### 6.7 Nutrition API and tools

| Capability | MCP tool | REST (for the Hub) | Home action |
| --- | --- | --- | --- |
| Read profile, targets, history | `get_nutrition_profile` (extended) | `GET /profile/{person_id}` (extended) | VIEW |
| Propose a profile change | `propose_profile` (new) | none | UPDATE + VIEW |
| Confirm a profile draft | `confirm_profile` (new) | none | UPDATE + VIEW |
| Switch mode | `set_nutrition_mode` (now versioned) | `PUT /profile/{id}/mode` | UPDATE + VIEW |
| Day with nutrients | `get_day_summary` (extended) | `GET /diary/{id}/days/{date}` (extended) | VIEW |
| Several days | `get_period_summary` (new) | `GET /diary/{id}/period?start&end` (new) | VIEW |

Each operation authorizes with one Home request, as today.

Existing write paths that bypass the calculation:

- `POST /profile/{id}/pregnancy` writes the fixed reference targets. Retire it; pregnancy targets
  now come from the calculation.
- `PUT /profile/{id}` writes a free-form target map. Restrict it to the food fields
  (preferences, dislikes, intolerances) through a new version, or retire it if nothing uses it.
  No path may store targets that did not come from the method.
- `plan_menu` and `get_pregnancy_profile` read `profile.targets`. Point them at the targets in
  force on the day in question.

**Retire the pre-diary intake tools.** `record_planned_meal`, `record_actual_intake`,
`ate_as_planned` and `get_daily_nutrition_gap`, and the REST routes `/daily/{id}/{date}`,
`/intake/{id}/planned`, `/intake/{id}/actual`, `/intake/{id}/ate-as-planned` and
`/gap-v2/{id}/{date}`, add up the old `intake` table. No app view reads that table, and it looks
nutrients up live instead of using frozen facts. Kept as they are, the agent could report
"nothing eaten" while Hoy shows real meals, which breaks two anti-goals. Live data checked on
2026-11-23: one real row (Erick, 2026-11-21, probably logged twice, since his diary has that
day's meals) and synthetic rows from September. Remove these tools from MCP and REST and from
both agents' skills, and update the exact tool-set tests. The table and its rows stay in place,
unread. Planning ahead stays with `search_recipes`, `get_meal_plan` and `plan_menu` (Mealie);
`evaluate_meal` and `propose_meal_change` stay because they do not touch stored intake
(Claude's call).

### 6.8 Onboarding through the agents

The same flow for Ultron and Ana's agent, in the person's language:

1. Trigger: the person asks ("¿cómo creo mi perfil?"), or the agent needs targets and there is
   no profile. The agent offers onboarding once; it does not nag.
2. About eight questions, one or two per message, skipping any already answered:
   birth date; sex (for the calculation); height; current weight and when it was measured;
   a normal day (activity level); training (sessions per week and what); goal (GENERAL only:
   mantener, perder grasa, ganar músculo, rendimiento); food preferences, dislikes and
   intolerances. In pregnancy mode: due date (if not set) and weight before the pregnancy,
   no goal question.
3. `propose_profile` → summary: the fields, the chosen activity level and goal, the targets
   with one-line sources, anything missing → "¿Lo guardo? (sí / corrige)".
4. `confirm_profile` → "Guardado." plus one line on what the targets will be used for.
5. Updates later: "ahora peso 82", "entreno 4 veces" → the same propose/confirm with only that
   field, showing old and new targets.

Recommendations after onboarding: the agent reads `get_period_summary` (and the day summary for
today) and talks about the gaps against targets in practical food terms. Match days: in this
project the agent can use what the person says in chat ("jugué 90 minutos") as context for its
advice, but it does not change the targets or store the match. Calculated exercise energy
arrives with project 2.

**Evening check-in for both agents.** Averages and multi-day advice count only finished
(COMPLETE) days, and a day is finished only when the person confirms it. Ana's agent already
asks every evening (release 1, `olin-nutrition-checkin`). Ultron gets the same daily check-in
(owner decision, 2026-11-23):

- Once a day at a time set at install, default 21:45 Europe/Berlin (Claude's call; the owner can
  change it), the same way the release 1 install sets Ana's time.
- It reads `get_day_summary` for today. If the day is already COMPLETE, or a call fails with
  anything other than an access refusal, it stays silent.
- Otherwise it sends one short message naming the day: with a profile, energy and protein
  against the day's targets plus the free-sugar figure; without one, the free-sugar figure; then
  the uncounted items, ending with the finish question ("¿Eso fue todo hoy?", or in the language
  the owner uses with Ultron).
- On "yes", the agent closes that day (`close_day` with the date the check-in named) and replies
  with the final figures.
- Older days that are still open can be finished whenever the person confirms them, as today
  (Erick finished 21 and 22 November this way). When a review needs an open past day, the agent
  asks once whether to finish it.

The check-in prompt is part of the shared skill, so both agents behave the same. Ana's check-in
gains the energy and protein line once she has a profile.

**Skill files.** Ultron's nutrition behaviour today lives only on the server, partly in notes
Ultron wrote itself. Ana's lives in the repo (`deploy/hermes/home-agent-ana/skills/olin-nutrition`).
Because both should behave the same, the nutrition instructions move into one repo-managed
skill used by both agents, installed by repo scripts (as `install-olin-finance.sh` does for
Ultron's finance skill). Per-agent differences (persona, language, Ultron's explicit
`check_access` step) stay in each agent's SOUL or standing skill. Ultron's self-written
`references/nutrition-diary.md` is replaced or removed by the install, with the owner's OK,
because parts of it now contradict this design.

### 6.9 Ana: the same options, with pregnancy guardrails

Ana's agent today answers only diary requests ("Solo te ayudo con tu diario de comidas"). It
gains the same nutrition abilities as Ultron: profile and onboarding, day and period summaries,
recommendations against her targets, food search and detail, meal evaluation, recipes and menus
(Mealie). Neither agent keeps the retired pre-diary intake tools (6.7). It stays limited to nutrition: no Finance and no general chat, as ADR-0017 scopes her
runtime.

Guardrails that stay or are added:

- References, not limits: no "debes", no scores.
- No weight-loss goal, no energy deficit and no dieting advice in pregnancy mode.
- Clinical questions get the release 1 answer: "Eso es mejor consultarlo con tu matrona o tu médico."
- The mode is never inferred; it changes only after her explicit confirmation (release 1).

**Rollout for Ana (track 0, can start now).** Her diary works today without this project.
Run rollout stage B6 (`docs/runbooks/nutrition-r1-rollout.md`) with her phone and the owner:
revoke the tester grant, map her runtime, she sets her password and grants at `/runtime`,
bookmarks `/app/nutrition/hoy`, then the owner sets her Telegram id and check-in time, and she
sends her due date. Her profile onboarding follows when this project's agent changes are live.
Target from release 1 still holds: daily use before her glucose screening in January 2027.

### 6.10 Home app views

All three views read only; each shows the person in the subject selector (`?person=`), with
Home deciding access as today. Numbers come from the same Nutrition endpoints the agent uses,
so they match by construction. Spanish labels. Mockups: see the link at the top.

**Perfil** (`/nutrition`): every profile field; the targets with value, source line and
"vigentes desde"; missing fields with "falta"; mode and trimester for pregnancy; a short history
("23 nov: perfil creado por chat"). Each section has "Cambiar en el chat", which copies a ready
message for the person's agent, like the existing `NutritionActions` prompts. With no profile:
an empty state that explains onboarding and offers the copy-ready "Quiero crear mi perfil".

**Hoy** (`/nutrition/hoy`): today's energy, protein, fiber and free sugars against the day's
targets, with the existing day status, the uncounted-items note and the meal list. Without a
profile it shows today as it does now (free sugars only) plus the onboarding hint.

**Días** (`/nutrition/dias`, new): 3, 7 or 14 days. One row per day with status, energy,
protein, fiber and free sugars, percentages against that day's targets, and the averages row
from `get_period_summary`. Unknowns read "sin dato". Two dashed placeholders name what comes
later: "Actividad y partidos" (project 2) and "Patrones" (project 3).

**Contract change.** The Hub's profile mapper (`profile-contract.ts`) deliberately reads only
three fields today and never copies preferences, dislikes, intolerances or pregnancy fields.
That rule changes on purpose: the owner decided the app shows everything the agent can read.
The mapper stays strict (rejects malformed payloads, ignores unknown fields) and reads exactly
the fields the Perfil view shows.

### 6.11 Privacy and logging

- No body values, food text or targets in logs: ids, versions and statuses only (release 1 rule).
- Agents never write body data, food or health facts to memory or to self-written skill notes.
- Profile data is returned only to the subject or to someone with a consent grant for
  NUTRITION VIEW, decided by Home.

### 6.12 Existing data

- Erick (`PSN-00013`) has no profile and 5 diary entries. Ana (`PSN-00014`) has no profile and no
  entries. The tester (`PSN-00015`) may have test data.
- Existing profile rows (synthetic and test, with fixed reference targets) become version 1 with
  source MIGRATED, keeping mode, due date and food fields. Their fixed targets are not carried
  over; targets are recalculated where the inputs exist, otherwise shown as missing.
- Diary entries need no migration; nutrient totals come from the facts already frozen in them.

## 7. Testing and acceptance

**Tests**

- Domain: the worked example in 6.3 and a pregnancy example per trimester, by hand; PAL and goal
  edges; the LOSE_FAT floor; missing inputs leave targets out; method versions are immutable.
- Service: version validity by date; first version applies backwards; a later change does not
  move past days; trimester step without a new version; draft expiry and idempotent confirm;
  one Home request per operation; refusals fail closed.
- Summaries: unknown never 0; partial nutrients; averages only over complete, fully known days;
  NO_ENTRIES days; the 31-day cap.
- Hub: strict contract tests for the extended profile, day and period bodies; the three views
  in MOCK and LIVE modes.
- Skills: extend `deploy/hermes/tests/test_olin_nutrition_skill.py` to cover the shared skill
  (tools listed, confirm-before-save wording, pregnancy guardrails, no self-computed totals).

**Acceptance on the live system**

1. Erick is the first live user, as he asked ("so I can test it with my user"). The synthetic
   tester is not used: after B6 no agent runtime is mapped to the tester, and remapping Ana's or
   Erick's agent would interrupt real use. Erick's mistakes are undone with a new version.
2. Erick onboards with Ultron in about ten messages. The summary shows targets with sources.
   After "sí", Perfil shows the same profile and targets.
3. Erick asks for a recommendation from his last two days plus a match. Ultron answers against
   his targets using `get_period_summary`, and its figures match the Días page.
4. Erick changes his weight. Today's targets change; yesterday's row in Días does not.
5. Ana onboards in pregnancy mode with her due date and weight before the pregnancy. Her energy
   target shows the second-trimester supplement, and the day her third trimester starts it
   steps up by itself.
6. Without a consent grant, Erick cannot see Ana's profile in the app or through Ultron, and the
   reverse.
7. Ultron's evening check-in arrives at the set time on a day Erick has not finished, stays
   silent on a day he has, and his "sí" finishes the day; the Días averages then include it.

## 8. Delivery order

0. **Now, independent:** Ana's rollout stage B6 (6.9). Needs Ana's phone and the owner.
1. Target method v1 and nutrient day totals in `nutrition-domain`, with tests.
2. Nutrition service: profile versions, drafts, confirm, extended profile and day summary,
   period summary, retired or restricted old write paths, migration of existing rows. REST and
   MCP.
3. Agents: the shared nutrition skill, install scripts for both agents, Ultron's evening
   check-in job, replacement of Ultron's self-written nutrition notes. Erick first, then Ana.
4. Hub: Perfil, Hoy, Días and the contract change.

Steps 1 and 2 can ship before 3 and 4. If time is tight before January, Ana's onboarding by chat
(step 3) comes before the app views (step 4), as in release 1.

## 9. Left to the builder

- Table design for versions and drafts, migration mechanics, endpoint and payload naming.
- Confirming every DGE, EFSA and ISSN value and reference from the source, including the
  pregnancy protein values, and recording the date checked (as `pregnancy_targets.py` does).
- How the shared skill is packaged and installed for two Hermes agents.
- Exact Spanish copy in the app and the agent, within the tone rules above.
- Component structure in the Hub and how the period view chooses its default range.

**Claude's calls in this document** (the owner can change any of them when approving):
the energy formula; the training add-on steps; the goal percentages; the PAL cap; protein
1.6 g per kg for training; the weight used for pregnancy protein and energy; the validation
ranges; the first onboarded version applying backwards; same-day corrections reaching back with
it; later corrections from their own day only; the 31-day period cap; micronutrients only in
Perfil; one shared skill for both agents; retiring the pre-diary intake tools; Erick as the
first live user instead of the synthetic tester; Ultron's check-in time defaulting to 21:45.
