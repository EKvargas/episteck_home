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
- ✅ Person/Circle/CircleMembership/CareRelationship/ConsentGrant + central `can_access`.
- ✅ Actor-aware Home Core API + thin Home Agent MCP source.
- ✅ Nutrition Home authorization client + pre-retrieval fail-closed cutover source.
- ✅ Knowledge + ContextBundle contracts (`packages/home-contracts`; no tech installed).
- ⏳ Live MCP deployment, synthetic conversation matrix, and latency evidence.

## Gates ahead
### Knowledge Technology Gate `[PENDING]`
Decide + install the Knowledge stack (candidates: Mem0 + Docling + Postgres/pgvector;
Graphiti deferred; RAGFlow rejected). Prereqs: capacity check on Nuremberg, a clear
first Knowledge use case, and the governance layer (Scope/Episode/Claim) implemented
in the Home Control Plane. The pure G1.5 contracts are complete but are not a
Knowledge runtime or persistence implementation.

### G2 — Real family onboarding `[BLOCKED on approval]`
First real Person + explicit consent + real Pregnancy Nutrition Profile + real
providers + real meal plan + planned→actual + Home Agent with the real user. Requires:
off-box backup (done), real USDA key (done), this G1.5 model live + validated, and
explicit user approval.

**Additional hard prerequisite:** trusted actor binding. The authenticated real user
or session must be authoritatively bound to exactly its allowed Person identity and
must resist actor-id substitution. Supplying an arbitrary `actor_person_id` is never
authentication. Until this is implemented and verified, G2 remains blocked and Home
Agent receives no real family data.

### Later
Device Gateway/Withings, FHIR, Mind, Calendar, Documents, Finance, reverse proxy +
public UI, voice, grocery automation.

## Architecture Change Rule (contributors & agents)
Before architectural changes:
1. Read `ARCHITECTURE.md`. 2. Read relevant ADRs. 3. Do not silently contradict
accepted decisions. 4. If architecture changes, update `ARCHITECTURE.md`. 5.
Create/update an ADR. 6. Update `STATUS.md`. 7. Commit documentation **with** the
implementation change. Git documentation is the architecture source of truth.
