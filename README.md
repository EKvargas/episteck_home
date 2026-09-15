# Episteck Home

Canonical repository for the **Episteck Home** product/platform.

## Layout
- `packages/nutrition-domain/` — canonical pure-Python Nutrition domain (deterministic calculator, provenance, intake, targets). No Frappe/HTTP/LLM deps. Single source of truth.
- `packages/home-contracts/` — dependency-free Knowledge governance and ContextBundle contracts. No Knowledge runtime or storage.
- `services/nutrition/` — standalone svc-nutrition (FastAPI + MCP + SQLite). Deployed rootless on Nuremberg.
- `services/home-mcp/` — thin business-safe MCP adapter to the Frappe Home Control Plane; owns no Home data.
- `apps/episteck_home/` — live Frappe Home Control Plane app for Person/Circle/Care/Consent and actor-aware business APIs. Its calculator re-exports `nutrition_domain`.
- `docs/episteck-home/` — design docs.

Migrated from EKvargas/episteck @ 2193382 (2026-09-14).
