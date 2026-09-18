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
| Home BFF (confidential OAuth client, EU node) | 🟡 implemented + tested; G1.6 live validation in progress |

## G1.5 final state — PASS
| Item | State |
| --- | --- |
| Architecture docs + ADRs + archify diagram | ✅ canonical; final report complete |
| Person/Circle/CircleMembership/CareRelationship | ✅ live; synthetic records only |
| ConsentGrant + can_access policy engine | ✅ live; 11 pure policy tests |
| Actor-aware Home Core API | ✅ live; actor enforcement before Person retrieval |
| Thin Home Agent MCP | ✅ live; business-safe tools |
| Nutrition auth migration (client, fail-closed) | ✅ live; Home is sole authority |
| Knowledge contracts + ContextBundle | ✅ pure contracts; no runtime installed |
| Synthetic conversational + latency validation | ✅ pass; see `G1_5_VALIDATION.md` |

## Deliberately NOT done
Real family/health data (G2, blocked on approval). Knowledge tech install
(Mem0/Graphiti/RAGFlow/pgvector/Docling). FHIR, Device Gateway, Mind, Calendar,
Finance, public UI, voice. `svc-home-core` (explicitly rejected — Frappe is the plane).

## G1.6 — trusted actor binding (current security/completion gate)

G1.6 implementation, deployment and live validation are in progress. The current
canonical evidence is `G1_6_VALIDATION.md`; do not infer completion from architecture
planning documents. G2 remains blocked until G1.6's live security matrix is complete.

## Planned — Smart Shopping + Smart Possessions `[ARCHITECTURE APPROVED; NOT IMPLEMENTED]`

| Capability | State |
| --- | --- |
| `svc-shopping` bounded context | ✅ architecture approved; no runtime |
| Provider-independent marketplace boundary | ✅ architecture approved |
| Kleinanzeigen Saved Search → email adapter as first MVP source | ✅ planned; no scraping dependency |
| Deterministic explainable DealScore + confidence | ✅ architecture approved |
| PurchasePolicy / price history / deduplicated alerts | ✅ architecture approved |
| `svc-inventory` bounded context | ✅ architecture approved; no runtime |
| Wardrobe + outfit/style recommendation | ✅ architecture approved |
| Baby temporary-item lifecycle / resale economics | ✅ architecture approved |
| Shopping ↔ Inventory domain events | ✅ architecture approved |
| Friction Budget / photo-first capture | ✅ product invariant approved |
| QR/NFC container/zone tagging | ⬜ V2 only |
| smart wardrobe / RFID / laundry / Home Assistant | ⬜ V3 only |

Key decision: Shopping and Inventory are **sibling domain services**. Shopping owns
needs/deals/purchases; Inventory owns actual possessions and lifecycle. The Home Agent
remains the user-facing conversational interface. See ADR-0010 and
`proposals/SMART_SHOPPING_AND_POSSESSIONS.md`.

Planned Home consent domains `SHOPPING` and `INVENTORY` are **not live values yet** and
must not be added to the policy engine until their services and pre-retrieval
authorization paths are implemented and tested.

## G2 blockers

1. **G1.6 completion** — finish the live trusted-actor/replay/security matrix and final
   Home Agent/Nutrition acceptance. **This is the current blocker.**
2. Explicit user approval for real family data.
3. Real-Person onboarding + real ConsentGrants.
4. Duplicate `sub` remediation before any future native/public OIDC client.

**Not a blocker:** EU data residency. Stage G1.7 (EU Home Control Plane migration) is
**withdrawn** as of 2026-09-16 — `home.episteck.com` is a personal/family deployment and
Ashburn/US hosting is accepted. Real onboarding may proceed on the existing Ashburn
instance after G1.6. EU residency is a future commercialization concern only.

Smart Shopping / Smart Possessions planning does **not** become a new G2 blocker and
must not distract from closing G1.6.

## Known notes
- USDA key was logged once to the root-only sudo journal (low risk, user accepted).
- Nutrition's old SQLite consent rows are retained only for audit/migration; current
  source no longer uses them as authorization and exposes no consent endpoint/tool.
- The initial Home Agent trace used lowercase `nutrition`; Home MCP canonicalizes
  display casing before Frappe validation, and the agent has a persistent deny-stop
  rule.
- Smart Shopping/Inventory must remain low-friction: incomplete inventories are allowed;
  hardware automation is optional, not a prerequisite for V1.
