# Episteck Home

Canonical repository for the **Episteck Home** product/platform.

## Layout
- `packages/nutrition-domain/` — canonical pure-Python Nutrition domain (deterministic calculator, provenance, intake, targets). No Frappe/HTTP/LLM deps. Single source of truth.
- `services/nutrition/` — standalone svc-nutrition (FastAPI + MCP + SQLite). Deployed rootless on Nuremberg.
- `apps/episteck_home/` — dormant Frappe app (ERPNext-side integration/operational layer). Its calculator re-exports `nutrition_domain`.
- `docs/episteck-home/` — design docs.

Migrated from EKvargas/episteck @ 2193382 (2026-09-14).
