# Status

## Knowledge delivery update (draft, 2026-10-10)

KAP-1 is architecturally accepted; KAP-2 is open after the bounded disposable
PERSON foundation. The proposed recovery amendment has no Board ratification.
The GCS request-time authorization path is rejected. The disconnected selected
implementation and all open PR/worktree dispositions are in the
[KAP-2 consolidation handoff](proposals/KNOWLEDGE_KAP2_CONSOLIDATION_HANDOFF.md).
No Knowledge endpoint, witness service or production schema is activated.

**2026-10-24:** PR #71 merged the disconnected candidate into `main`, so it is
deployed to the Home bench as inert code (no import, hook, whitelisted method or
schema reaches it; `tests/test_knowledge_disconnected.py` enforces this). KAP-2
stays open: R2–R5, Board ratification and a newly authorized two-host attempt.

**Updated:** 2026-10-25

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
| Home MCP | ✅ live behind dedicated gateway; direct loopback `:9932` blocked from callers |
| Home BFF (confidential OAuth client, EU node) | ✅ live; public session app + socket-only mint process |
| Hermes delegation gateway | ✅ live on `127.0.0.1:9934`; Home, Nutrition and Finance paths |
| Home Hub (`svc-home-hub`, Nuremberg) | ✅ live; `/app/nutrition` shows the live Nutrition profile panel (F3c, image `d91341d`). Follow-ups #108/#109 merged; image `3b9a3dc` built and probed, rollout pending (owner) |
| Olin Finance (`svc-finance`: API `:9935`, MCP `:9936`) | ✅ live since 2026-10-13 (image `9256f8c`). First real data 2026-10-25: Bank of America via SimpleFIN, 2 accounts, first sync OK. Backup block and sync timer not applied yet |

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

Next: **Knowledge Technology Gate**, then **G2 / Health architecture** with explicit
approval. No G1.7 stage is created.

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

## H5 — agent runtime grant (IN REVIEW, not deployed)

| Item | State |
| --- | --- |
| Home: `open_runtime_grant`, `close_runtime_grant`, `get_runtime_grant_status` | PR1 in review |
| BFF: grant table, `/runtime`, mint precedence, `RUNTIME_LEGACY_BINDING` | PR2 in review |
| Live verification | not run |

Design: `adr/0010-agent-runtime-grant.md`.

## Olin Finance I1 (in progress)

| Item | State |
| --- | --- |
| Architecture proposal (PR #74) and ADR-0011 | ✅ merged |
| `services/finance` (store, read model, API/MCP, connectors) | ✅ live on Nuremberg since 2026-10-13 (#96, #97, #99, #102). Bank of America connected 2026-10-25 via SimpleFIN (runbook 8a); first sync OK |
| Feature Activation DocType + `get_feature_state` (B3, ADR-0012) | ✅ merged (#90) and migrated on home.episteck.com. Finance I1 does not consult it |
| Home changes H1–H4 (audience, `authorize_batch`, Feature Activation, mint + gateway route) | ✅ merged and deployed (#89, #90, #92, #93); `/gateway/finance/` live |
| Home accepts `svc-finance` (B1; extends ADR-0009 pattern) | ✅ merged (#89); `home_finance_machine_user` set (2026-10-13) |
| PSD2 callback `/finance/connect/callback` + `app.connect authorize` (B5, ADR-0013) | 🔀 merged (#111, #112); image `03970d5` built on the node, **not installed**; nginx route not applied. Owner ships it with runbook 8c |
| Sparkasse and Trade Republic cash via Enable Banking (runbook 8b) | ⏳ after B5 ships; owner places the application key and approves in the bank app |
| Finance backup block and sync timer (runbook 9–10) | ⏳ prepared, owner applies |
| Telegram (B7), `openai-codex` login (B8), Olin Finance skill (B9), live verification (B11) | ⏳ open |

## G2 blockers

1. Complete the **Knowledge Technology Gate** before G2 implementation.
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
