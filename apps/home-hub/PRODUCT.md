# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Members of one household, each with their own login and their own data. The Hub is used mostly on phones, often from an iPhone Home Screen web app.
- Nutrition pages serve first a pregnant household member who checks daily on her phone that she and the baby are getting what they need. Confirmed by the owner, 2026-11-24.
- Other members use the same pages with their own targets (for example an adult with sport and performance goals). Their needs must fit the same design, not lead it.
- A member may see another member's data only through a consent grant in Home. Without one, the other person's data never appears.

## Product Purpose

Olin (Episteck Home) is a household's personal and family OS. Nutrition exists to find patterns in food, exercise and health so the household does not have to work them out by hand. The Hub shows what each person's agent has recorded and computed: the profile and daily targets, today against those targets, and several days side by side.

Success for the nutrition pages: in the first seconds she knows whether she is on track today (energy, protein, fiber, free sugars). Below that sits a calm weekly status for vitamins and minerals. Detail is there when she asks for it. Confirmed by the owner, 2026-11-24.

## Positioning

Logging happens in conversation with each person's own agent on Telegram. The app is the read-only mirror of exactly what that agent reads, with the same numbers from the same Nutrition service, so the chat and the screen never disagree. Targets and food data name their sources (DGE/D-A-CH, EFSA, USDA, BLS, Open Food Facts).

## Operating Context

- Each person has a personal agent on Telegram. They log meals by chat, and the agent asks for confirmation before saving.
- An evening check-in from the agent ("¿Eso fue todo hoy?") closes the day.
- Changes to the profile or the diary are made by chat. The app offers copy-to-chat prompts ("Copiar «…»") instead of forms.
- UI copy is Spanish. Login is the Home session; the Hub is served under `/app`.

## Capabilities and Constraints

- Read-only app. No forms that change nutrition data.
- Per day, the Nutrition service reports 15 nutrients: energy, protein, fat, carbohydrate, fiber, calcium, iron, folate, vitamin B12, vitamin D, iodine, zinc, selenium, choline and DHA. Free sugars are reported against a daily limit.
- Each nutrient carries:
  - its known total;
  - how many items could not be counted;
  - a completeness status (known, partial or none);
  - its target;
  - a percentage.
- Period views return averages for the same set.
- Every target has a kind that defines "fine":
  - `ABOUT`: near the value (energy, fat);
  - `MIN`: at least the value (protein, fiber, vitamins and minerals);
  - a limit: at most the value (free sugars).
- Pregnancy mode carries a due date and trimester-dependent targets. Profiles are versioned, with history.
- Unknown is never shown as zero. Missing data is never shown as "low".
- Not yet tracked (open decision, planned): dietary supplements, such as a prenatal vitamin. Until they are tracked, food-only totals understate nutrients a supplement covers. Designs must leave room to show "food + supplement" per nutrient.
- Service logs carry counts only; no food text or body values.

## Brand Commitments

- Product name Olin (Episteck Home). The app icon is the Episteck ε symbol on oxblood.
- The visual system is recorded in DESIGN.md (six selectable themes over one token vocabulary).

## Evidence on Hand

- Synthetic fixtures only: `test-support/fake-bff.mjs` and `test-support/fake-nutrition.mjs`.
- No real household data may be used in design work, screenshots or this repository.

## Product Principles

1. Calm and factual: green when fine, amber when short, grey when data is incomplete, no red alarms. This matters most in pregnancy. Confirmed by the owner, 2026-11-24.
2. Glance first: "am I on track today?" is answered in seconds. Everything else is one step away, not on the first screen.
3. The app mirrors the agent: the same numbers as the chat, and every change goes through the chat.
4. Unknown is not zero: incomplete data is labelled as incomplete, never judged.
5. Each person's data is theirs: nothing about another member appears without consent.
