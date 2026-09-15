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
| episteck_home app on home.episteck.com | ⏳ **install in progress (G1.5)** |

## G1.5 progress
| Item | State |
| --- | --- |
| Architecture docs + ADRs + archify diagram | in progress |
| Person/Circle/CircleMembership/CareRelationship | to build |
| ConsentGrant + can_access policy engine | to build |
| Home Core API + Home Agent MCP | to build |
| Nutrition auth migration (client, fail-closed) | to build; live cutover gated |
| Knowledge contracts + ContextBundle | to document (contracts only) |
| Synthetic validation | to run |

## Deliberately NOT done
Real family/health data (G2, blocked on approval). Knowledge tech install
(Mem0/Graphiti/RAGFlow/pgvector/Docling). FHIR, Device Gateway, Mind, Calendar,
Finance, public UI, voice. `svc-home-core` (explicitly rejected — Frappe is the plane).

## Known notes
- USDA key was logged once to the root-only sudo journal (low risk, user accepted).
- Nutrition currently has its own consent; being migrated to Home `can_access`.
