# Status

**Updated:** 2026-09-15

## Live now
| Component | State |
| --- | --- |
| Nuremberg node + Tailscale mesh | ✅ operational |
| infra-agent / home-agent (Hermes) | ✅ operational, independent |
| Mealie v3.26.0 | ✅ operational (loopback + tailnet) |
| svc-nutrition (API + MCP) | ✅ operational; USDA prod key live; OFF live |
| Off-box restic backup | ✅ operational + restore validated |
| home.episteck.com Frappe site | ✅ live (frappe+erpnext) |
| episteck_home app on home.episteck.com | ✅ actor-aware Control Plane API live |
| Home MCP | ✅ live, rootless svc-home-mcp, loopback :9932 |

## G1.5 final state — PASS
| Item | State |
| --- | --- |
| Architecture docs + ADRs + archify diagram | ✅ canonical; final report complete |
| Person/Circle/CircleMembership/CareRelationship | ✅ live; synthetic records only |
| ConsentGrant + can_access policy engine | ✅ live; 11 pure policy tests |
| Actor-aware Home Core API | ✅ live; actor enforcement before Person retrieval |
| Thin Home Agent MCP | ✅ live; exactly seven business-safe tools |
| Nutrition auth migration (client, fail-closed) | ✅ live; Home is sole authority |
| Knowledge contracts + ContextBundle | ✅ pure contracts; no runtime installed |
| Synthetic conversational + latency validation | ✅ pass; see `G1_5_VALIDATION.md` |

## Deliberately NOT done
Real family/health data (G2, blocked on approval). Knowledge tech install
(Mem0/Graphiti/RAGFlow/pgvector/Docling). FHIR, Device Gateway, Mind, Calendar,
Finance, public UI, voice. `svc-home-core` (explicitly rejected — Frappe is the plane).

## G2 blocker — trusted actor binding

Explicit synthetic `actor_person_id` is permitted only for G1.5 validation. It is not
authentication. No real family data may be exposed to Home Agent, and G2 must not
begin, until an authenticated user/session is authoritatively bound to exactly its
allowed Person and actor substitution tests pass.

## Known notes
- USDA key was logged once to the root-only sudo journal (low risk, user accepted).
- Nutrition's old SQLite consent rows are retained only for audit/migration; current
  source no longer uses them as authorization and exposes no consent endpoint/tool.
- The initial Home Agent trace used lowercase `nutrition`; Home MCP now canonicalizes
  display casing before Frappe validation, and the agent has a persistent deny-stop
  rule. Allow and revoked-deny traces pass.
- Live p95: Home `check_access` 119.88 ms; cross-person Nutrition profile 121.60 ms
  (30 samples each). Full evidence: `G1_5_VALIDATION.md`.
