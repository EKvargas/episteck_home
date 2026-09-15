# ADR-0008: Centralized, fail-closed consent (can_access)

## Status
Accepted (2026-09-15)

## Context
Authorization must be uniform across domains and safe by default. Domain-local ad-hoc
checks drift and leak.

## Decision
One centralized policy engine in the Home Control Plane:
`can_access(actor_person_id, subject_person_id, domain, action)`, **fail closed**.
Invariants: membership ≠ auth; care relationship ≠ auth; revoked/expired → DENY;
unknown/unavailable → DENY; one domain never implies another; action-scoped
(VIEW/CREATE/UPDATE/MANAGE). Self-access (actor==subject) permitted for own data.

## Consequences
+ One auditable authorization decision point; safe defaults.
+ Domain services (e.g. Nutrition) delegate to it and fail closed if it is unreachable.
− Cross-node latency for remote services; measure before optimizing; cache carefully
  only with correct revocation semantics (future).

## Alternatives
- Per-domain consent (current Nutrition-local consent): being deprecated in favor of
  this central engine once the Control Plane is authoritative.
