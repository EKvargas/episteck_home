# ADR-0004: svc-nutrition is the Nutrition source of truth

## Status
Accepted (2026-09-15)

## Context
Nutrition needs deterministic calculation, provenance, planned-vs-actual intake, and
provider-agnostic food data — none of which belong in Mealie or an LLM.

## Decision
`svc-nutrition` (Nuremberg, rootless) owns Nutrition Profile, nutrient targets +
provenance, planned/actual intake, and deterministic Decimal calculations. Mealie and
food providers are sources it consumes; the LLM never fabricates nutrient numbers.

## Consequences
+ Deterministic, auditable nutrition; provider swappable behind an ABC.
− Nutrition state is separate from the Control Plane; authorization is delegated to
  the Home `can_access` policy (see ADR-0008 / migration).

## Alternatives
- Mealie as nutrition truth: rejected (Mealie is recipes/plans/lists, not clinical/
  nutrition intelligence, consent, or identity).
