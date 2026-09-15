# Roadmap

## Delivered (stages A–G1)
- Nuremberg node baseline; Tailscale mesh; infra-agent + home-agent (independent Hermes).
- Mealie MVP (recipe/meal-plan/shopping provider).
- svc-nutrition MVP: deterministic domain, FastAPI + MCP, planned/actual, provenance.
- Stage F: USDA + Open Food Facts provider chain; DGE/EFSA pregnancy targets; consent
  gate; unknown≠zero; menu planning; home-agent pilot (synthetic).
- Stage G1: off-box restic backup + restore validated; USDA production key live.

## This stage (G1.5)
Home Control Plane model + Knowledge contracts + architecture docs. **No real data.**
- Person/Circle/CircleMembership/CareRelationship/ConsentGrant + central `can_access`.
- Stable Home Core API + Home Agent MCP.
- Nutrition authorization migration (client + fail-closed; live cutover gated).
- Knowledge contracts + ContextBundle contract (no tech installed).

## Gates ahead
### Knowledge Technology Gate `[PENDING]`
Decide + install the Knowledge stack (candidates: Mem0 + Docling + Postgres/pgvector;
Graphiti deferred; RAGFlow rejected). Prereqs: capacity check on Nuremberg, a clear
first Knowledge use case, and the governance layer (Scope/Episode/Claim) implemented
in the Home Control Plane.

### G2 — Real family onboarding `[BLOCKED on approval]`
First real Person + explicit consent + real Pregnancy Nutrition Profile + real
providers + real meal plan + planned→actual + Home Agent with the real user. Requires:
off-box backup (done), real USDA key (done), this G1.5 model live + validated, and
explicit user approval.

### Later
Device Gateway/Withings, FHIR, Mind, Calendar, Documents, Finance, reverse proxy +
public UI, voice, grocery automation.

## Architecture Change Rule (contributors & agents)
Before architectural changes:
1. Read `ARCHITECTURE.md`. 2. Read relevant ADRs. 3. Do not silently contradict
accepted decisions. 4. If architecture changes, update `ARCHITECTURE.md`. 5.
Create/update an ADR. 6. Update `STATUS.md`. 7. Commit documentation **with** the
implementation change. Git documentation is the architecture source of truth.
