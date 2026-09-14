# EPISTECK HOME — Nutrition core: smallest viable design

**Status:** `SOURCE CORE READY — NOT INSTALLED` · **Date:** 2026-09-14

## Purpose and boundary

Nutrition is an Episteck-owned decision and calculation boundary, not a second food community or clinical nutrition service.

```text
Person context → Nutrition Profile → Nutrition Engine → planned meals
Mealie (later) ↔ recipes / schedule / shopping list
Actual Intake → confirmed foods or planned meal reference → daily totals
```

Mealie owns recipe, household-plan and shopping-list UX. Episteck owns Person context, targets with provenance, planned-versus-actual distinction and deterministic calculation. No target is medical instruction.

## Implemented source model

The uninstalled Frappe source at [`apps/episteck_home`](../../apps/episteck_home) contains only:

| Record | Minimum fields / invariant |
| --- | --- |
| `Nutrition Profile` | person reference, stated preferences/dislikes/intolerances, target source, provenance reference and validity interval. Sources are `REFERENCE_TARGET`, `USER_CONFIGURED`, `PROFESSIONAL_PROVIDED`, or `AI_SUGGESTION`; an AI suggestion is never authoritative. |
| `Nutrition Intake` | person, timestamp, meal type, source, optional planned-meal reference, actual portion factor, outcome status and provenance. Only `USER_CONFIRMED` is accepted as authoritative intake. |

`nutrition.calculator` sums caller-supplied, source-labelled food facts using `Decimal`. It has no LLM, food-dataset download, clinical target or persistence dependency.

## Planned versus actual workflow

1. A future Meal Plan creates a stable planned-meal reference (often Mealie).
2. **Ate as planned** creates one intake: `PLANNED_MEAL`, `CONFIRMED`, portion factor `1` (or explicitly chosen factor).
3. **Changed** retains the planned reference and creates an intake from `RECIPE`, `FOOD` or `MANUAL`, with `CHANGED` status.
4. Natural-language/voice capture may create an AI proposal outside this DocType. Human confirmation produces structured food amounts; then deterministic calculation runs.

Planned salmon remains visible even if the actual confirmed meal is pasta; neither overwrites the other.

## Dataset abstraction

Do not ingest BLS, USDA or Open Food Facts now. A future adapter resolves a `FoodFact`: stable food reference, provider, provider version/release, nutrient ID/value/unit, basis quantity and retrieval time. The engine receives only this normalized fact plus a confirmed amount. Persist dataset/version and fact reference with each result. Conflicting facts remain source-specific.

## Mealie, Pantry and Grocery boundaries

The future Mealie adapter may exchange recipe IDs, ingredients, meal-plan slots and shopping-list lines through documented API only. It never owns Profile, target selection, confirmed intake, Device Gateway data or consent. Mealie tokens are provider credentials, not Episteck authorization.

`PantryItem` is deferred. Its future minimal shape is food/product reference, approximate quantity/unit, low-stock state and optional expiry. `GroceryProvider` remains replaceable: `search_product`, `get_price`, `get_availability`, `prepare_basket`. REWE is desired but no undocumented API or checkout automation is in this scope; basket/checkout always needs separate user approval.
