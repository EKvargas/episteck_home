# ADR-0002: Domain services remain independent; no universal database

## Status
Accepted (2026-09-15)

## Context
Home spans nutrition, recipes, clinical, devices, mind, knowledge. A single monolith
DB would couple domains and blur ownership/provenance.

## Decision
Each domain owns its own truth and store (svc-nutrition, Mealie, future FHIR/Device
Gateway/Mind/Knowledge). Components reference canonical data; they do not duplicate it.

## Consequences
+ Clear ownership + provenance; independent scaling/lifecycle; blast-radius isolation.
− Cross-domain queries need composition (future ContextBundle) rather than a join.

## Alternatives
- Universal DB: rejected (coupling, ownership ambiguity, provenance loss).
