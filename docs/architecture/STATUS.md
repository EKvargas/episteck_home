# Status

**Updated:** 2026-09-16

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
| Home BFF (confidential OAuth client, EU node) | 🟡 implemented + tested; not yet deployed |

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

## G1.6 — trusted actor binding (implemented, awaiting merge + deploy)

| Item | State |
| --- | --- |
| Actor removed from every caller-facing surface | ✅ Home API, 8 MCP tools, Nutrition routes/tools |
| Server-side resolution (session → User → Person) | ✅ `identity/actor.py`, fail-closed |
| Delegated context (pure, verified) | ✅ `identity/delegation.py` — issuer/audience/exp/jti/replay |
| Frappe `auth_hooks` seam + `Home Delegated Session` | ✅ revocation & logout deny next call |
| Dual principal (machine_caller + human_actor) | ✅ retained in audit context |
| Nutrition independent actor resolution | ✅ never accepts an asserted actor |
| Home BFF (confidential client, always S256 PKCE) | ✅ EU node; browser holds no tokens |
| `Person.linked_user` unique + ambiguity fails closed | ✅ schema + tests |
| Consent semantics | ✅ **unchanged** (`policy/access.py` untouched) |
| Automated tests | ✅ **199 passing** (was 93) |
| Live delegation matrix on prod runtime | ✅ 10/10 pass |
| PKCE S256 agreement with Frappe's computation | ✅ byte-for-byte on live box |

**Not yet done:** merge to `main`, `bench migrate` on home.episteck.com, OAuth client
creation (blocked — needs credential-write approval), real-login binding (A10).

## G2 blockers

1. **G1.6 completion** — merge, `bench migrate`, OAuth client creation, real-login
   binding (A10). **This is the current blocker.**
2. Explicit user approval for real family data.
3. Real-Person onboarding + real ConsentGrants.
4. Duplicate `sub` remediation (prepared; reference audit found **zero** consumers).

**Not a blocker:** EU data residency. Stage G1.7 (EU Home Control Plane migration) is
**withdrawn** as of 2026-09-16 — `home.episteck.com` is a personal/family deployment and
Ashburn/US hosting is accepted. Real onboarding may proceed on the existing Ashburn
instance. EU residency is a future commercialization concern only.

## Known notes
- USDA key was logged once to the root-only sudo journal (low risk, user accepted).
- Nutrition's old SQLite consent rows are retained only for audit/migration; current
  source no longer uses them as authorization and exposes no consent endpoint/tool.
- The initial Home Agent trace used lowercase `nutrition`; Home MCP now canonicalizes
  display casing before Frappe validation, and the agent has a persistent deny-stop
  rule. Allow and revoked-deny traces pass.
- Live p95: Home `check_access` 119.88 ms; cross-person Nutrition profile 121.60 ms
  (30 samples each). Full evidence: `G1_5_VALIDATION.md`.
