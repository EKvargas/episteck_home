# Roadmap

## Delivered (stages A–G1)
- Nuremberg node baseline; Tailscale mesh; infra-agent + home-agent (independent Hermes).
- Mealie MVP (recipe/meal-plan/shopping provider).
- svc-nutrition MVP: deterministic domain, FastAPI + MCP, planned/actual, provenance.
- Stage F: USDA + Open Food Facts provider chain; DGE/EFSA pregnancy targets; consent
  gate; unknown≠zero; menu planning; home-agent pilot (synthetic).
- Stage G1: off-box restic backup + restore validated; USDA production key live.

## Stage G1.5 — COMPLETE (PASS)
Home Control Plane model + Knowledge contracts + architecture docs. **No real data.**
- ✅ Person/Circle/CircleMembership/CareRelationship/ConsentGrant + central `can_access`.
- ✅ Actor-aware Home Core API + live thin Home Agent MCP.
- ✅ Nutrition Home authorization client + live pre-retrieval fail-closed cutover.
- ✅ Knowledge + ContextBundle contracts (`packages/home-contracts`; no tech installed).
- ✅ Synthetic Home Agent conversation, denial matrix, and latency evidence.

See `G1_5_VALIDATION.md`. Stop here; do not begin G2.

## Stage G1.6 — trusted actor binding (implemented; completion is the current G2 blocker)
Actor identity is derived from an authenticated session, never supplied. **No real data.**
- ✅ `actor_person_id` removed from the Home API, all MCP tools, and Nutrition routes.
- ✅ Server-side resolution: validated auth → Frappe User → `Person.linked_user` → actor.
- ✅ Delegated context (opaque session id, single audience, short TTL, replay-resistant).
- ✅ Dual principal: `machine_caller` + `human_actor`, both retained in audit context.
- ✅ Nutrition resolves the actor independently; never trusts an asserted actor.
- ✅ Home BFF: confidential OAuth client on the **EU node**, always S256 PKCE.
- ✅ Consent semantics unchanged. 199 automated tests pass.

See `adr/0009-trusted-actor-binding.md` and `G1_6_VALIDATION.md`.

## Gates ahead

### ~~Stage G1.7 — EU Home Control Plane migration~~ `[WITHDRAWN 2026-09-16]`
**Not a blocker. Do not create this stage.** `home.episteck.com` is the operator's own
personal/family deployment, and Ashburn/US hosting for the Home Control Plane is
accepted. Real family onboarding may proceed on the existing Ashburn instance once G1.6
is complete. **Do not migrate `home.episteck.com` during this phase.**

EU data residency is a **future commercialization** concern. Before onboarding external
EU customers, a regional deployment/data-residency strategy will be designed separately —
likely dedicated EU Home instances for those customers rather than migrating the personal
US instance. No stage is scheduled for it.

### Knowledge Technology Gate `[PENDING]`
Decide + install the Knowledge stack (candidates: Mem0 + Docling + Postgres/pgvector;
Graphiti deferred; RAGFlow rejected). Prereqs: capacity check on Nuremberg, a clear
first Knowledge use case, and the governance layer (Scope/Episode/Claim) implemented
in the Home Control Plane. The pure G1.5 contracts are complete but are not a
Knowledge runtime or persistence implementation.

### G2 — Real family onboarding `[BLOCKED]`
First real Person + explicit consent + real Pregnancy Nutrition Profile + real
providers + real meal plan + planned→actual + Home Agent with the real user.

Remaining blockers:
1. **G1.6 completion** — merge to `main`, `bench migrate`, OAuth client creation, and
   real-login binding (A10). This is the current blocker.
2. Explicit user approval for real data.
3. Real-Person onboarding + real ConsentGrants.
4. Duplicate OIDC `sub` remediation before any native/public OIDC client (a reference
   audit found zero current consumers: no OAuth clients, no bearer tokens, no social
   login keys).

EU residency is **not** a blocker — see the withdrawn G1.7 note above.

Trusted actor *design and implementation* are done (G1.6); only its merge/deploy
steps remain, which is blocker 1.

### Later
Device Gateway/Withings, FHIR, Mind, Calendar, Documents, Finance, reverse proxy +
public UI, voice, grocery automation.

## Architecture Change Rule (contributors & agents)
Before architectural changes:
1. Read `ARCHITECTURE.md`. 2. Read relevant ADRs. 3. Do not silently contradict
accepted decisions. 4. If architecture changes, update `ARCHITECTURE.md`. 5.
Create/update an ADR. 6. Update `STATUS.md`. 7. Commit documentation **with** the
implementation change. Git documentation is the architecture source of truth.
