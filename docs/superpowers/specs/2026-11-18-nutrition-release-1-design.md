# Nutrition release 1: Ana's food diary by voice, with a pregnancy mode

**Status:** draft for owner approval · **Date:** 2026-11-18 · **Owner:** Erick
**Background:** [2026-11-15 draft scope (Codex)](2026-11-15-ana-pregnancy-nutrition-design.md),
[sugar review](../../architecture/reviews/2026-11-15-nutrition-sugar-review.json),
[readiness review](../../architecture/reviews/2026-11-15-ana-nutrition-readiness.json),
[threshold sources](../../architecture/reviews/2026-11-15-pregnancy-food-threshold-references.md).
This document narrows that draft to a first release and replaces it where they differ.

## 1. Intent

Ana is pregnant (second trimester started mid-November 2026) and wants to see how much
sugar she actually consumes. Writing things down must be effortless: she will mostly
send voice notes in Telegram. She is very visual, so the same diary must also be
visible in the Home app.

For the owner this is the first real-person use of Episteck Home (Stage G2, approved
2026-11-15). The infrastructure is live; this release turns it into something a family
member uses every day.

The capability is **healthy-nutrition tracking for anyone**, with **pregnancy as a
mode**. When the pregnancy ends, Ana switches mode and keeps using the same diary.

**Timing.** Routine glucose screening usually happens in weeks 24–28 (about mid-January
to February 2027). Target: Ana uses release 1 daily **before then, early January 2027**.

## 2. Decisions already made

| Decision | Who / when |
| --- | --- |
| G2 approved for Ana's pregnancy nutrition | Owner, 2026-11-15 |
| Ana logs **everything** she eats and drinks, not only sugary items | Owner, 2026-11-18 |
| Ana gets **her own Telegram bot**; voice is the main input | Owner, 2026-11-18 |
| Ana's agent chats through a subscription login, the same way OpenClaw and the owner's bots do: a ChatGPT (Codex) login, or Kimi K2.6 through the existing Kimi plan. **No pay-per-use OpenAI API.** Which one is confirmed before step 4 of section 8 | Owner, 2026-11-18 |
| Voice notes are transcribed **on the server** (faster-whisper), as OpenClaw and both Hermes agents already do | Owner's setups; Claude's call, 2026-11-18 |
| If early January is tight, the bot comes first and the remaining app views follow (section 8) | Owner, 2026-11-18 |
| Spanish interface; German/EU references plus WHO | Owner, 2026-11-18 |
| No gestational diabetes and no limit from her doctor | Owner, 2026-11-18 |
| Release 1 is private to Ana; sharing with her circle comes later | Owner, 2026-11-18 |
| General nutrition with a pregnancy **mode**, reusable after the birth | Owner, 2026-11-18 |
| Build approach A (section 5) | Owner, 2026-11-18 |
| Add the German food database BLS 4.0 as a source | Proposed by Claude, accepted 2026-11-18 |

## 3. Goals, non-goals, anti-goals

**Goals (release 1)**

1. Ana logs any food or drink by voice or text in her own bot. The common case needs
   exactly one confirmation ("sí").
2. Nutrition calculates sugar from sourced values that are **frozen when she confirms**.
3. After each confirmation, and whenever she asks, the bot reports today's free sugars
   against her limit and says where the limit comes from.
4. An evening check-in lets her close the day ("¿Eso fue todo hoy?").
5. The Home app shows **Today** and **Week** for sugar, the state of each day, where each
   number comes from, and lets her correct a portion.
6. Her profile has a mode (general or pregnancy); rules declare which modes they apply to.
7. The owner's agent and Finance keep working exactly as today.

**Non-goals (later releases)**

- Photo logging. Caffeine, alcohol and food-safety notices. Showing micronutrients
  (they are stored, not shown). A sharing screen for her circle. Breastfeeding mode.
- The full recommendation-source framework from the 2026-11-15 draft. Release 1
  implements the minimum in section 6.9.
- The Care Journey organizer (appointments, tasks). It is not a dependency.
- One shared bot that serves several people. Clinical advice of any kind. Blood glucose.

**Anti-goals (failure even if everything "works")**

- Ana's messages act as the owner, or she can reach Finance.
- A day shows 0 g, or looks complete, when it is not.
- The AI invents a nutrient value. Composition always comes from a named source through
  Nutrition. Portion weights may be estimated, but only visibly ("~") and confirmed by
  Ana (6.6).
- Confirming twice creates two entries.
- Logging feels like a chore and she stops.
- The limit reads like a medical instruction.

## 4. Constraints

- **Accepted architecture.** Nutrition owns intake and calculation (ADR-0004). Home is
  the only authority on identity and access, and denies when unsure (ADR-0008). The
  agent never chooses or sees who it acts as (ADR-0009). Agents act through a revocable
  runtime grant (ADR-0010). Mealie stays a recipe provider (ADR-0005). Being in the same
  circle never grants access (`policy/access.py`).
- **Home actions** are `VIEW`, `CREATE`, `UPDATE`, `MANAGE`. Ana acting on her own data
  passes as self-access; release 1 creates no ConsentGrant.
- **Delivery flow.** App code reaches production only through a PR to `main`. Nutrition
  and the BFF are images built on Nuremberg from a commit SHA and run by Quadlet; the
  operator runs the production steps. The Home Frappe app deploys from `main`; Home has
  no post-deploy migrate hook, so release 1 avoids Home schema changes (site config only).
- **Data.** Nutrition stores profiles and intake in SQLite; the daily restic job already
  backs it up off-site.
- **Hermes** transcribes Telegram voice notes itself. Both Hermes agents on Nuremberg
  already use local faster-whisper (`stt.local.model: base`), and OpenClaw on Ashburn
  uses a local faster-whisper script (`base`, int8, Spanish). Hermes memory must not
  become the diary (`AGENTS.md`).
- **Model providers in use:** ChatGPT/Codex logins (OpenClaw `gpt-5.6-terra`, owner's
  `home-agent` `gpt-5.6-sol`) and the Kimi plan (`infra-agent`, `kimi-k2.6`). For real
  financial data the owner chose OpenAI only (decision P2).
- **Current Nutrition code** computes everything per 100 g, has no sugar fields
  (`nutrient_map.py`), and recalculates past intake from the providers on every read
  (`service.py:_to_confirmed`). Its pregnancy references are outdated in places (iron
  30 mg, current DGE 27; iodine 230 µg, current DGE 220).

## 5. Approaches considered

| Approach | What it means | Trade-off | Outcome |
| --- | --- | --- | --- |
| **A. The agent proposes, Nutrition calculates** | The agent transcribes and proposes foods and portions; Nutrition stores a draft, confirms it, freezes values and returns totals | Most new pieces, but bot and app always show the same diary; no duplicates; no AI-made numbers | **Chosen** |
| B. Draft lives only in the chat | The agent keeps the proposal in the conversation and calls the existing "record intake" after "sí" | Faster start; the app can't see drafts, and duplicate protection is needed anyway | Rejected |
| C. Nutrition does the understanding | Nutrition receives text or audio and calls OpenAI itself | One parser, but AI calls and audio files land in the exact-calculation service | Rejected |

Open-source trackers were also checked on 2026-11-18 (FoodLog, NutriTrace, food-diary,
Fud AI, wger). None works with Telegram or with Home's identity and permissions, so
adopting one would create a second account and a second diary. Release 1 borrows UX
ideas only (portion presets, the sugar-limit display).

## 6. Design

### 6.1 Overview

```text
Ana (Telegram, voice/text)                    Ana (phone browser)
        │                                              │
  ana bot ─► Hermes "home-agent-ana" (own Linux user)   Home Hub /app/nutrition
        │   STT → text; nutrition skill                │  server-side loaders
        ▼                                              ▼
  gateway 127.0.0.1:9937  (nutrition + home only)     BFF cookie → delegation mint
        │  mint with X-Runtime-ID: home-agent-ana      │
        ▼                                              ▼
  BFF internal mint ─► Home (grant, self-access) ◄─ Nutrition checks every call
                                                       │
                              Nutrition: drafts, frozen facts, day status, rules
                              providers: BLS 4.0 (local), Open Food Facts, USDA
```

### 6.2 Ana's own agent

- **Linux user** `home-agent-ana` with its own uid, no sudo, no Podman socket, its own
  `~/.hermes`. User-scope `hermes-gateway.service` with lingering, like `home-agent`.
- **Telegram:** a new bot token; the allowlist holds only Ana's Telegram account.
- **Tools:** only the `nutrition` MCP (and `home` if the skill needs `whoami`), both via
  the new gateway port. No Finance MCP and no Finance skill.
- **Skill:** `olin-nutrition` in a root-owned external skills directory, the same
  pattern as the Finance skill, so the agent cannot rewrite its own rules. Behavior is
  in 6.8.
- **Chat model:** a subscription login, never a pay-per-use API key. Recommended: a
  ChatGPT (Codex) device login with **Ana's own account**, if she has a paid plan. Her
  conversations then stay in her account and use her own limits, so they can't slow
  the owner's Finance bot. Alternatives: Kimi K2.6 through the existing Kimi plan (her
  food conversations then go to Moonshot AI; for Finance the owner kept real data on
  OpenAI only), or the owner's ChatGPT login (shared limits with his bot). No fallback
  provider, as for `home-agent`. The owner confirms the choice before step 4 of section 8.
- **Voice:** Hermes local STT (faster-whisper), `language: es`. Start with `base`, as
  the existing agents do; if Spanish voice notes come out poorly, compare `small` on a
  few sample recordings (RAM and CPU on Nuremberg are limited, so measure). Audio never
  leaves the server. Voice files in `~/.hermes/audio_cache` are deleted after
  transcription (6.11).

### 6.3 Several agents, each tied to one person

Today one agent identity exists in code (`RUNTIME_ID = "home-agent-primary"` in
`services/home-bff/home_bff/runtime.py`), so every call from the bot runs as the
owner. Release 1 makes the agent identity come from **which gateway port** the call
arrived on, which the firewall ties to a Linux user.

- **Gateway** (`deploy/gateway/nginx-mcp-gateway.conf`): a second server on
  `127.0.0.1:9937` with only `/gateway/home/` and `/gateway/nutrition/`. Its mint
  location sets `proxy_set_header X-Runtime-ID "home-agent-ana"`; request headers from
  the caller are already dropped (`proxy_pass_request_headers off`). The existing 9934
  server sets `X-Runtime-ID "home-agent-primary"` explicitly. No Finance route on 9937.
- **Firewall** (`episteck-gateway.nft`): the new uid may reach only 9937; uid 1003 stays
  on 9934 only. Every other uid is dropped for both, as today.
- **BFF:** replace the constant with a configured list (`RUNTIME_IDS`, default
  `["home-agent-primary"]`). `/internal/mint` reads `X-Runtime-ID`; a missing or unknown
  value returns 401 and never falls back to the primary agent. `/internal/mint_finance`
  stays bound to `home-agent-primary`. The public `/runtime` page and grant/revoke take
  the agent id as a parameter checked against the list.
- **Home** (`identity/session.py`): add `home-agent-ana` to `home_runtime_ids` and add
  a site config `home_runtime_grantees_by_runtime`, for example
  `{"home-agent-primary": [owner], "home-agent-ana": [ana]}`. `open_runtime_grant`
  refuses a caller who is not listed for **that** agent, so Ana cannot replace the
  owner's grant and the owner cannot grant Ana's agent. When the mapping is absent,
  today's `home_runtime_grantees` applies to `home-agent-primary` only.
- **Audiences:** Ana's grant names the control-plane audience only, never Finance.
- **Each person controls only their own agent's grant.** Today the BFF stores no user
  and, by ADR-0010's design, deletes the grant row on revoke when Home is unreachable.
  With two grant holders that would let Ana delete the owner's grant during a Home
  outage. Release 1 rules:
  - At grant time the BFF stores, with the grant row, an opaque reference to the
    granting person (an HMAC of the Home user id, never a name). At login the session
    stores the same reference.
  - Revoke, the "unreachable → delete" fallback, and `/logout/all` act only on grants
    whose reference matches the session's. `/logout/all` revokes that person's grants
    only.
  - The `/runtime` page shows only the agents the logged-in person may grant (asked
    from Home; with Home unreachable, from the stored references). It never shows
    another person's expiry or last use.
  - Record these rules in ADR-0017 as an amendment to ADR-0010.
- **ADR:** this amends ADR-0010. Write ADR-0017 "Per-person agent runtimes" and update
  `ARCHITECTURE.md` with the implementation.

### 6.4 Onboarding Ana

1. Fix the phone login glitch first: the Confirm Access screen can fire twice and fail
   with "invalid or already-used authorization state". Set `skip_authorization=1` on the
   BFF's first-party OAuth client.
2. Create Ana's Frappe User and Person (`linked_user`).
3. Ana logs in on her phone at the BFF and grants her agent at `/runtime?agent=home-agent-ana`.
4. Her Nutrition profile is created in pregnancy mode with an estimated due date (6.10).

### 6.5 Sugar data and the BLS source

- **Canonical nutrients:** add `sugars_total_g` (USDA nutrient 269; OFF `sugars_100g`;
  the BLS field for total sugars). Add `sugars_added_g` only where a source states it
  (USDA 539, OFF `added-sugars_100g`). Missing stays unknown, never zero.
- **BLS 4.0:** download the Excel file from blsdb.de once, convert it with an import
  script into a read-only SQLite file in the Nutrition data volume, and serve it through
  a `bls:` provider (`provider_version` "BLS 4.0"). License CC BY 4.0: show "Datos:
  Max Rubner-Institut, BLS 4.0" wherever a BLS value is shown. Lookups never leave the
  server.
- **Search order:** BLS (generic foods and dishes), then Open Food Facts (branded and
  barcoded products), then USDA. Results stay source-labelled and are never merged.
- **Pregnancy references:** correct the outdated values (iron, iodine) and check the
  whole table against current DGE values, even though release 1 does not display them.

### 6.6 Portions and millilitres

Nutrition works per 100 g, so every entry stores:

- what she said: `amount` and `unit` (g, ml, piece, slice, glass, cup, can, spoon…);
- the grams used for the calculation, and the **conversion** with its method and version
  (from the label, from a density, or from a preset).

Where the grams may come from, in order of preference (the method is stored):

1. `USER_STATED`: Ana gives an exact amount ("330 ml", "125 g").
2. `LABEL` or `SOURCE_SERVING`: the product label, or a serving size the source provides
   (OFF `serving_size`, USDA `foodPortions`, BLS where available). The providers must be
   extended to fetch these.
3. `PRESET`: a versioned household-measure table (Episteck guidance), for example small
   glass 150 ml, glass 200 ml, large glass 300 ml, cup 250 ml, can 330 ml, tablespoon
   15 ml, teaspoon 5 ml.
4. `AGENT_ESTIMATE`: the agent's estimate of a weight a table can't supply (a slice of
   bread, an apple, a plate of a home-cooked dish). Allowed because Ana asked for
   approximate portions to be accepted. It is always shown with "~" in the proposal,
   confirmed by her, and stored with this method, so the app can show it as an estimate.

Volumes convert to grams with the food's density when the source has one, otherwise
1.0 g/ml, and the conversion records which. Release 1 shows one best estimate marked
"~", editable; ranges come later. **Composition is never estimated**: only portions.

**A food no source knows** (for example a homemade arepa) is saved by its name with no
composition. It counts as `UNKNOWN` ("sin dato") and never as 0 g. The agent may
propose the nearest match explicitly ("¿la registro como 'Maisfladen'?"); Ana decides.
It never substitutes silently.

### 6.7 Drafts, confirmation and corrections

- **Draft.** `propose_intake` stores the proposed foods and portions, resolves each food
  from its provider, and returns a draft id with a preview. Drafts never count in totals
  and expire after 24 hours.
- **Confirm.** `confirm_intake(draft_id)` turns a draft into an entry and **freezes**,
  per food: nutrients per 100 g, source, provider version, retrieval time, grams and
  conversion. Confirming the same draft again returns the same entry. Totals are always
  computed from the frozen values; a provider change never alters past days.
- **Correct and delete.** `correct_intake(entry_id, …)` writes a new revision and keeps
  the old one; totals use the latest revision. `void_intake(entry_id)` marks an entry as
  removed without erasing its history. Both require Home `UPDATE`.
- **Mode stamp.** Each entry records the profile mode active when it was confirmed.
- **Existing data.** Only synthetic intake exists today. The builder may drop it or
  migrate it; no real data is affected.

### 6.8 How the bot behaves

- Spanish. On a voice note (already transcribed by Hermes) or text: identify the items,
  search foods, pick portions from the presets, call `propose_intake`, and show the list
  with "~" amounts and "¿Lo guardo? (sí / corrige)". On "sí": `confirm_intake`, then
  reply with today's free sugars against the limit, and name any item that could not be
  counted.
- Corrections by voice ("era un vaso grande") change the draft before confirmation, or
  call `correct_intake` afterwards.
- **Evening check-in** at a time Ana chooses (a Hermes scheduled task in her agent):
  "¿Eso fue todo hoy?". "Sí" closes the day (6.9).
- Every number the bot states comes from a Nutrition tool result. No medical advice:
  for clinical questions it suggests asking her midwife or doctor.
- Food entries are not written to Hermes memory; the diary lives in Nutrition.
- If she sends a photo: "Todavía no leo fotos; dime qué es."
- **Scope:** nutrition only in release 1. Other questions get a short, friendly
  redirect. This keeps the skill simple and the cost bounded.

### 6.9 Free sugars, day status and the limit

- **Free sugars.** The limit concerns *free* sugars (EFSA definition: added sugars plus
  sugars in honey, syrups and juices). Sources mostly give *total* sugars. Each frozen
  food is classified by a versioned mapping from its provider category (BLS food group,
  OFF category) into:
  - `FREE`: free sugars = total sugars (soft drinks, juices, smoothies, sweets,
    chocolate, cakes, pastries, desserts, jam, honey, syrups, sugar, sweetened drinks);
  - `NOT_FREE`: free sugars = 0 (whole fruit, vegetables, plain milk and yogurt,
    unsweetened staples);
  - `UNKNOWN`: not counted (mixed or unclassified dishes), unless the source states
    added sugars, which are then used.
  The classification is labelled Episteck guidance and shown in each entry's detail.
- **Day status:** `NO_ENTRIES`, `OPEN` (maybe incomplete), or `COMPLETE` (Ana confirmed
  the evening check-in through `close_day`). Independently, the sugar figure is `KNOWN`
  or `PARTIAL` (some entries `UNKNOWN`: show the known sum and how many were not
  counted). A day with no entries never shows 0 g.
- **The limit as a rule record:** id, version, valid-from date, metric
  (`free_sugars_g`), operator (max), period (day), value, basis (<10 % of energy),
  energy basis (declared standard 2,000 kcal, so 50 g), origin
  (`INSTITUTIONAL_REFERENCE`), sources (WHO 2015 sugars guideline; DGE/DAG/DDG 2018
  statement; familienplanung.de "Zucker in der Schwangerschaft"), adaptation text ("10 %
  of a standard 2,000 kcal day"), and the modes it applies to (general and pregnancy).
  Rule versions are immutable; a day is evaluated with the version valid on that day.
- **Personal goal.** Ana may set her own limit, for example 25 g (the WHO 5 % option).
  It is stored as `PERSONAL_GOAL` with who set it and when. It becomes the effective
  target, and the institutional reference stays visible beside it.

### 6.10 Mode

The profile's existing `context` field holds the mode: `GENERAL` or `PREGNANCY`.
Pregnancy stores an optional estimated due date, and the trimester is derived from it.
Switching mode needs an explicit confirmation from Ana in the bot or the app. Rules list
the modes they apply to; release 1's only rule (the free-sugar limit) applies to both.

### 6.11 Nutrition API and tools

New operations, available as MCP tools (for the agent) and REST (for the Hub), all
authorized by Home on every call with the existing delegation pattern:

| Operation | Home action |
| --- | --- |
| `search_foods` (now including BLS) | none (public data), as today |
| `propose_intake`, `confirm_intake` | `CREATE` |
| `correct_intake`, `void_intake`, `close_day`, `set_personal_goal`, `set_mode` | `UPDATE` |
| `get_day_summary(date)`, `get_week_summary(end_date)`, `get_entry(entry_id)` | `VIEW` |

Tools keep the current `subject_person_id` parameter convention; in release 1 the
subject is always the acting person.

**Privacy.** Hermes keeps downloaded voice files in `~/.hermes/audio_cache`; configure
or schedule their deletion after transcription. Service logs record ids and statuses,
never food text.

### 6.12 Home app views

The Hub reads through server-side loaders, like the existing profile loader (one minted
delegation per call, the shared data envelope, no mock content in LIVE).

```text
┌ Hoy · Embarazo, 2.º trimestre ───────────────┐
│ Azúcares libres  32 g de 50 g   ███████░░░░   │
│ Día abierto · 1 alimento sin contar          │
├──────────────────────────────────────────────┤
│ 08:10 Desayuno                               │
│   Pan, 2 rebanadas (~60 g)          0 g      │
│   Jugo de naranja, vaso (~200 ml)  17 g  ›   │
│ 13:30 Almuerzo                               │
│   Lentejas con chorizo (~350 g)  sin dato ›  │
│ 16:00 Merienda                               │
│   Yogur de frutas (125 g)          15 g  ›   │
├──────────────────────────────────────────────┤
│ Límite: <10 % de la energía (OMS, DGE) ›     │
│ Semana:  ▂ ▅ ▃ · ▆ ▄ ▇   (· = sin registros) │
└──────────────────────────────────────────────┘
```

- **Today:** free sugars against the effective limit, the day and sugar status, entries
  by time with portion and sugar per item.
- **Entry detail (›):** food source and version, grams and conversion, free-sugar class,
  and "corregir porción".
- **Limit detail:** value, origin label, linked sources, the 2,000 kcal assumption, the
  personal goal if set.
- **Week:** seven bars; days without entries and partial days are visibly different
  from low values. Meaning never depends on color alone.
- Visual direction: the "daily overview" layout of the Codex prototype for Today and its
  "meal timeline" for the list. The owner can change this after seeing screenshots.

## 7. Testing and acceptance

**Automated**

- Sugar mapping per provider, including unknown ≠ 0; free-sugar classification; ml→g
  conversion with method recorded.
- Frozen facts: changing a provider value does not change a past day.
- Confirming twice yields one entry; corrections keep revisions; void excludes from totals.
- Day status and `PARTIAL` sugar status; empty day never reports 0 g.
- Rule versions: a new version does not change the evaluation of past days.
- Authorization: Ana's agent cannot mint on 9934 or for Finance; a missing or unknown
  `X-Runtime-ID` returns 401; Ana cannot grant `home-agent-primary`; the owner cannot
  grant `home-agent-ana`; the owner's agent and Finance behave as before.

**End-to-end, synthetic person first:** voice note → draft → "sí" → entry visible in the
app; a correction in the app appears in the bot's next answer; the evening check-in
closes the day.

**With Ana:** one week of real daily use on her phone without technical help. Collect
what was annoying before extending scope.

## 8. Delivery order

1. Login glitch fix; Ana's User and Person (operator).
2. Nutrition: sugar fields, BLS provider, frozen facts, drafts and revisions, presets,
   free-sugar classification, day status, rule record and summaries, REST and MCP.
3. Several agents: Home mapping, BFF, gateway, firewall, ADR-0017. Can run in parallel with 2.
4. Ana's agent: Linux user, Hermes, bot, voice, skill, evening check-in.
5. Hub views.
6. Production rollout by the operator, onboarding, one week with Ana.

**If early January is tight (owner's choice: the bot first).** Split the rollout in two:

- **Step A, target early January:** items 1–4, plus a simple "Hoy" page in the app
  (today's total, day status, list of entries). BLS stays in step A, because German
  home cooking is what Ana logs most.
- **Step B, about two weeks later:** the Week view, entry detail with corrections in
  the app (corrections by voice already work in step A), the limit detail and the
  personal goal.

## 9. Left to the builder

- BLS column names and the exact category → free-sugar mapping table.
- The preset list beyond the examples above.
- MCP tool and REST signatures, and the draft storage schema.
- How the evening check-in is scheduled inside Hermes.
- Hub component structure.
- Which test fixtures stand in for real foods.
