# Status

## Knowledge (2026-11-07)

No Knowledge endpoint, witness service, runtime or production schema is active.

| Item | State |
| --- | --- |
| B1–B6 architecture decisions | ✅ resolved |
| Technology Gate | ✅ closed 2026-09-25: S1 relational owner on **SQLite 3.41.2**. Six pre-runtime obligations remain (durability mode, warm/cold e2e, timing side-channel, R13 production, real R14 domain read, restore-freshness realization) |
| Authorization Plan contract (KAP-1…KAP-10) | ✅ §17 accepted; **§19 recovery amendment ratified for v1 on 2026-11-07** ([ADR-0014](adr/0014-knowledge-authorization-recovery-incarnation.md)) |
| KAP-1 wire contracts | ✅ merged (with #71) |
| KAP-2 PERSON candidate | 🟡 merged 2026-10-24 (#71) and deployed to the Home bench as **inert** code. No import, hook, whitelisted method or schema reaches it; `tests/test_knowledge_disconnected.py` enforces this. R1/R6 fixed locally |
| KAP-2 decisions | ✅ 2026-11-07: Erick is witness operator with no backup delegate (accepted risk); latency screen accepted as a gate ([decision sheet](../../spike/knowledge-kap2-two-host/DECISION_SHEET.md)) |
| KAP-2 open | ⏳ R2 repeated epoch/principal retirement; R3 unknown Home-commit acknowledgement windows; R4 CIRCLE, production Home writers, RT#2 contexts, reauthorization interface, credential custody; one two-host run (needs exact-SHA authorization) |
| KAP-3…KAP-10 | ⏳ not started |

Details: [KAP-2 consolidation handoff](proposals/KNOWLEDGE_KAP2_CONSOLIDATION_HANDOFF.md). The GCS request-time authorization path is rejected.

**Updated:** 2026-11-07

## Live now
| Component | State |
| --- | --- |
| Nuremberg node + Tailscale mesh | ✅ operational |
| infra-agent / home-agent (Hermes) | ✅ operational, independent |
| Mealie v3.26.0 | ✅ operational (loopback + tailnet) |
| svc-nutrition (API + MCP) | ✅ operational; USDA prod key live; OFF live |
| Off-box restic backup | ✅ operational + restore validated; Finance SQLite included since 2026-11-07 (tag `finance`) |
| home.episteck.com Frappe site | ✅ live (frappe+erpnext) |
| episteck_home app on home.episteck.com | ✅ actor-aware Control Plane API live |
| Home MCP | ✅ live behind dedicated gateway; direct loopback `:9932` blocked from callers |
| Home BFF (confidential OAuth client, EU node) | ✅ live; public session app + socket-only mint process |
| Hermes delegation gateway | ✅ live on `127.0.0.1:9934`; Home, Nutrition and Finance paths |
| Home Hub (`svc-home-hub`, Nuremberg) | ✅ live; `/app/nutrition` shows the live Nutrition profile panel (F3c). Follow-ups #108/#109 live since 2026-11-07 (image `3b9a3dc`); signed-in banner check pending (owner) |
| Olin Finance (`svc-finance`: API `:9935`, MCP `:9936`) | ✅ live since 2026-10-13; image `6a31366` since 2026-11-07. Bank of America via SimpleFIN (2 accounts) since 2026-10-25. Backed up nightly; sync timer at 06:20 and 18:20 UTC (#117) |

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
public UI, voice. (Finance I1 is in progress with the owner's own real data, decision P1.) `svc-home-core` (explicitly rejected — Frappe is the plane).

## Stage completion

| Stage | State |
| --- | --- |
| G1 | ✅ **COMPLETE** |
| G1.5 | ✅ **COMPLETE** |
| G1.6 | ✅ **COMPLETE** — production closeout 2026-09-19 |

Next: **Knowledge KAP-2 close-out** (the Technology Gate closed 2026-09-25), then
KAP-3…KAP-10. **G2 / Health architecture** still needs explicit approval. No G1.7
stage is created.

## G1.6 — trusted actor binding (COMPLETE)

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
| Authorization cardinality suite | ✅ **56 passing** from deployed SHA; service/HTTP/MCP inventory + replay cases |
| Live delegation matrix on prod runtime | ✅ 10/10 pass |
| PKCE S256 agreement with Frappe's computation | ✅ byte-for-byte on live box |
| Final Hermes/gateway actor proof | ✅ operator `PSN-00001`; zero-role synthetic user `PSN-00002` |
| Nutrition compound proof | ✅ allowed planned→actual; denied synthetic subject created zero rows; test rows removed |
| Final deployed source | ✅ `ddebab6439c9d68487d180dec6995fc546d3cf68` for BFF, Home MCP, Nutrition |

Full runtime, provenance, network, rollback, and trust-boundary evidence is in
`G1_6_VALIDATION.md`.

## H5 — agent runtime grant (LIVE, legacy binding off)

| Item | State |
| --- | --- |
| Home: `open_runtime_grant`, `close_runtime_grant`, `get_runtime_grant_status` | ✅ merged (PR #75), deployed |
| BFF: grant table, `/runtime`, mint precedence, `RUNTIME_LEGACY_BINDING` | ✅ merged (PRs #76, #77), deployed |
| Live verification | ✅ 2026-10-13: grant carries Hermes with no browser session; Revoke stops it; re-grant restores it |
| `RUNTIME_LEGACY_BINDING` | `off` in both units (grant only) |

Design: `adr/0010-agent-runtime-grant.md`.

## Olin Finance I1 (in progress)

| Item | State |
| --- | --- |
| Architecture proposal (PR #74) and ADR-0011 | ✅ merged |
| `services/finance` (store, read model, API/MCP, connectors) | ✅ live on Nuremberg since 2026-10-13 (#96, #97, #99, #102). Bank of America connected 2026-10-25 via SimpleFIN (runbook 8a); first sync OK |
| Feature Activation DocType + `get_feature_state` (B3, ADR-0012) | ✅ merged (#90) and migrated on home.episteck.com. Finance I1 does not consult it |
| Home changes H1–H4 (audience, `authorize_batch`, Feature Activation, mint + gateway route) | ✅ merged and deployed (#89, #90, #92, #93); `/gateway/finance/` live |
| Home accepts `svc-finance` (B1; extends ADR-0009 pattern) | ✅ merged (#89); `home_finance_machine_user` set (2026-10-13) |
| PSD2 callback `/finance/connect/callback` + `app.connect authorize` (B5, ADR-0013) | ✅ live 2026-11-07 (image `6a31366`); nginx route with rate limit (#113) on the BFF vhost; 403/400/404 and 429-after-burst verified, no query string in nginx logs |
| Sparkasse and Trade Republic cash via Enable Banking (runbook 8b) | ⏳ next; owner registers the redirect URL, places the application key and approves in the bank app |
| Finance backup block and sync timer (runbook 9–10) | ✅ applied 2026-11-07; snapshot `8af2d8ea` holds `finance.sqlite`. Timer schedule fixed in #117 (`06:20,18:20` fired 06:18 and 06:20 only) |
| Olin Finance skill + `finance` MCP on `home-agent` (B9) | ✅ installed 2026-11-07; tool discovery through the gateway works, so the runtime grant covers `svc-finance` (B10) |
| Telegram (B7), `openai-codex` login (B8), live verification (B11) | ⏳ open (B7, B8 owner steps) |

## G2 blockers

1. ✅ **Knowledge Technology Gate** closed 2026-09-25 (SQLite 3.41.2 selected; no
   runtime approved).
2. Obtain explicit user approval for real family/health data.
3. Approve the G2 / Health architecture, Real-Person onboarding, and real
   ConsentGrants.

Duplicate OIDC `sub` remediation is not a G1.6 or G2 actor-binding blocker because the
live path does not consume `sub`. It remains mandatory before any native/public OIDC
client relies on `(issuer, sub)`; no identity-data regeneration was performed.

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
