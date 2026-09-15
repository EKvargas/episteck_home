# ADR-0005: Mealie is a recipe/meal-plan/shopping provider only

## Status
Accepted (2026-09-14, reaffirmed 2026-09-15)

## Context
Mealie provides excellent recipe/meal-plan/shopping-list UX. It is not our nutrition
engine, clinical system, consent authority, identity source, or AI brain.

## Decision
Mealie is used strictly as a provider, behind an Episteck-owned adapter in
svc-nutrition. A dedicated Mealie API token (not the admin password) is used. **Mealie
tokens are provider credentials, not Episteck authorization.** home-agent never sees them.

## Consequences
+ Clean boundary; Mealie replaceable; no leakage of Mealie creds to agents.
− An extra hop (Nutrition adapter) for recipe access; acceptable.

## Alternatives
- Treat Mealie as the meal/nutrition source of truth: rejected (see ADR-0004).
