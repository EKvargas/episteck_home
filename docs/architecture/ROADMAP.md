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

## Home Hub F0–F2 — COMPLETE (PASS)

The Home Hub integration foundation, session-bound viewer/bootstrap flow, BFF routing,
and authenticated Hub rollout are complete. The 2026-09-27 live login resolved
`vargas3rick@gmail.com` to `PSN-00013` / Erick Vargas; the bootstrap contained only
his Person context, with no Circle or care relationships. See
`deploy/home-hub/README.md` for the rollout record. Historical F0/F2 design files
may retain their original pre-implementation status labels.

## Home F3 — ARCHITECTURE BOARD DISPOSITION RECORDED

`proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` records the Board-accepted
Person-only active context and one read-only, server-mediated Nutrition profile
vertical. An authorized no-profile response is sufficient for the first live
integration proof; it does not prove populated profile rendering. Home must establish
subject Person existence before any positive authorization decision through its shared
policy boundary. The older foundation's separate F3 context, F4 adapter, and F5 UI
steps become four small F3 implementation reviews. No implementation, deployment,
family topology creation, or real-data onboarding is authorized by this documentation
update. The G2 real family/health onboarding gate below remains in force.

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

### Knowledge Technology Gate `[CLOSED — SELECTION COMPLETE; RUNTIME GATES OPEN]`
The Gate selected S1, a relational canonical owner with structured retrieval,
realized on SQLite 3.41.2. The Knowledge governance layer remains Episteck-owned;
SQLite has **not** been installed as a Knowledge runtime. See the accepted
[Technology Gate](proposals/KNOWLEDGE_TECHNOLOGY_GATE.md),
[durability decision](proposals/KNOWLEDGE_SQLITE_DURABILITY.md), and
[Knowledge architecture progress](KNOWLEDGE.md#knowledge-authorization-plan-implementation-progress).

The Architecture Board accepted the Authorization Plan runtime contract in PR #56.
PR #56 is documentation-only and remains open; its acceptance does not authorize
production endpoints, credentials, certificates, deployment, or migration. KAP-1
is architecturally accepted at PR #58 head `e5b2e4ff47245d7d1af4d74873e7eaabc57e7718`
but unmerged. KAP-2 is open. After PR #63 at
`3f69b0bedb073e9200a8dd7f7669bb25b2f2717c`, the architect rejected the
current request-time GCS mechanism; PRs #61–63 remain evidence. The
[transactional-witness feasibility brief](proposals/KNOWLEDGE_KAP2_TRANSACTIONAL_WITNESS_FEASIBILITY.md)
evaluates a separate MariaDB instance and leaves restore proof for review.
KAP-3–10 remain ahead. The accepted
sequence and per-item criteria are in the runtime contract §15; live gates #2
(latency), #3 (timing/existence-oracle closure), and #5 (real R14/domain measurement)
remain open.

**Accepted B5 ownership boundary** (`proposals/KNOWLEDGE_B5_OWNERSHIP_BOUNDARIES.md`):
Home owns trusted identity, security-partition resolution and authorization; a
distinct logical Knowledge owner owns canonical contextual assertions and Knowledge
control state; domain services own structured operational/domain truth. Physical
placement and runtime responsibilities must preserve this split.

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
