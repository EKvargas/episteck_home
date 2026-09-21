# Roadmap

## Delivered (stages A–G1)
- Nuremberg node baseline; Tailscale mesh; infra-agent + home-agent (independent Hermes).
- Mealie MVP (recipe/meal-plan/shopping provider).
- svc-nutrition MVP: deterministic domain, FastAPI + MCP, planned/actual, provenance.
- Stage F: USDA + Open Food Facts provider chain; DGE/EFSA pregnancy targets; consent
  gate; unknown≠zero; menu planning; home-agent pilot (synthetic).
- Stage G1: off-box restic backup + restore validated; USDA production key live.

**Stage G1 — COMPLETE (PASS).**

## Stage G1.5 — COMPLETE (PASS)
Home Control Plane model + Knowledge contracts + architecture docs. **No real data.**
- ✅ Person/Circle/CircleMembership/CareRelationship/ConsentGrant + central `can_access`.
- ✅ Actor-aware Home Core API + live thin Home Agent MCP.
- ✅ Nutrition Home authorization client + live pre-retrieval fail-closed cutover.
- ✅ Knowledge + ContextBundle contracts (`packages/home-contracts`; no tech installed).
- ✅ Synthetic Home Agent conversation, denial matrix, and latency evidence.

See `G1_5_VALIDATION.md`. Stop here; do not begin G2.

## Stage G1.6 — COMPLETE (PASS)
Actor identity is derived from an authenticated session, never supplied. **No real data.**
- ✅ `actor_person_id` removed from the Home API, all MCP tools, and Nutrition routes.
- ✅ Server-side resolution: validated auth → Frappe User → `Person.linked_user` → actor.
- ✅ Delegated context (opaque session id, single audience, short TTL, replay-resistant).
- ✅ Dual principal: `machine_caller` + `human_actor`, both retained in audit context.
- ✅ Nutrition resolves the actor independently; never trusts an asserted actor.
- ✅ Home BFF: confidential OAuth client on the **EU node**, always S256 PKCE.
- ✅ Consent semantics unchanged; final authorization-cardinality suite passes 56/56.
- ✅ Production cutover complete from SHA `ddebab6439c9d68487d180dec6995fc546d3cf68`.
- ✅ Final operator (`PSN-00001`) and zero-role (`PSN-00002`) Hermes paths proven live.
- ✅ Nutrition allowed, denied, and compound VIEW+CREATE paths proven live; temporary
  synthetic closeout rows removed.

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

### Knowledge Technology Gate `[PENDING / OPEN]`
Decide + install the Knowledge stack (candidates: Mem0 + Docling + Postgres/pgvector;
Graphiti deferred; RAGFlow rejected). Prereqs: capacity check on Nuremberg, a clear
first Knowledge use case, and **B6 (Trusted Retrieval / ContextBundle) closed**.
The pure G1.5 contracts are complete but are not a Knowledge runtime or persistence
implementation.

**Accepted B5 ownership boundary** (`proposals/KNOWLEDGE_B5_OWNERSHIP_BOUNDARIES.md`):
Home is the trusted identity, security-partition resolution and authorization
authority; a **distinct logical Knowledge owner** owns canonical contextual
assertions and Knowledge control state; domain services own structured
operational/domain truth. Physical placement, runtime and storage remain
**undecided** — the gate may choose them, but may not collapse canonical Knowledge
ownership into ordinary Home Control Plane persistence/DocTypes. B5 acceptance
approves **no** runtime implementation.

### LLM Routing & Cost Management Gate `[FUTURE / PARALLEL]`
Preserve a dedicated architecture gate for inference-provider routing, quota/cost
management, BYOK/user-owned provider credentials, privacy-aware model eligibility, and
bounded Episteck-paid fallback. **OmniRoute is a candidate, not selected or deployed.**

Olin must retain ownership of trusted identity, security partition, domain sensitivity,
provider eligibility, and budget policy; an inference gateway may handle provider
connections, quota awareness, routing/fallback, and usage metering only within those
constraints. See
`proposals/LLM_ROUTING_AND_COST_GATE.md`.

This work may proceed as architecture research in parallel, but it is **not a Knowledge
Technology Gate blocker** and does not authorize production deployment or provider
credential onboarding.

### G2 — Health / real family onboarding `[BLOCKED]`
First real Person + explicit consent + real Pregnancy Nutrition Profile + real
providers + real meal plan + planned→actual + Home Agent with the real user.

Remaining blockers:
1. Complete the **Knowledge Technology Gate** above.
2. Explicit user approval for real family/health data.
3. Approved G2 / Health architecture, Real-Person onboarding, and real ConsentGrants.

Duplicate OIDC `sub` remediation is deferred under approved amendment A5. The G1.6
actor path does not use `sub`; remediation remains mandatory before any native/public
OIDC client relies on `(issuer, sub)` and is not a G1.6 completion blocker.

EU residency is **not** a blocker — see the withdrawn G1.7 note above.

Trusted actor design, implementation, production cutover, and closeout are complete.
The next gate is Knowledge Technology, followed by G2 / Health architecture.

### Later
Device Gateway/Withings, FHIR, Mind, Calendar, Documents, Finance, reverse proxy +
public UI, voice, grocery automation.

## Architecture Change Rule (contributors & agents)
Before architectural changes:
1. Read `ARCHITECTURE.md`. 2. Read relevant ADRs. 3. Do not silently contradict
accepted decisions. 4. If architecture changes, update `ARCHITECTURE.md`. 5.
Create/update an ADR. 6. Update `STATUS.md`. 7. Commit documentation **with** the
implementation change. Git documentation is the architecture source of truth.
