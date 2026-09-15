# ADR-0001: home.episteck + episteck_home Frappe is the Home Control Plane

## Status
Accepted (2026-09-15)

## Context
Episteck Home needs a canonical owner for identity and relationships: Person, Circle,
CircleMembership, CareRelationship, ConsentGrant, CareJourney. We already run Frappe
and have a live `home.episteck.com` site (separate from company `erp.episteck.com`).

## Decision
Use the `episteck_home` Frappe app installed on `home.episteck.com` as the **Home
Control Plane**. Do **not** build a separate `svc-home-core` service.

## Consequences
+ Reuses Frappe's DocType/permission/REST machinery; one place for identity+consent.
+ Company ERP and Home stay cleanly separated (different sites, different repos).
− Introduces a Nuremberg→Ashburn (cross-node) dependency for authorization; mitigated
  by Tailscale + fail-closed clients + measuring latency before optimizing.

## Alternatives
- `svc-home-core` microservice: rejected — duplicates identity/permission plumbing
  Frappe already provides, more moving parts.
