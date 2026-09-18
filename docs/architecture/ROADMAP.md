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

## Stage G1.6 — trusted actor binding (current completion/security gate)
Actor identity is derived from an authenticated session, never supplied. **No real data.**
G1.6 implementation/deployment exists and live security validation is still the current
G2 blocker; use `G1_6_VALIDATION.md` as the canonical evidence rather than stale counts
or intermediate descriptions in older commits.

## Gates ahead

### ~~Stage G1.7 — EU Home Control Plane migration~~ `[WITHDRAWN 2026-09-16]`
**Not a blocker. Do not create this stage.** `home.episteck.com` is the operator's own
personal/family deployment, and Ashburn/US hosting for the Home Control Plane is
accepted. Real family onboarding may proceed there once G1.6 is complete. **Do not
migrate `home.episteck.com` during this phase.**

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
1. **G1.6 completion** — finish the live trusted-actor/replay/security matrix and final
   Home Agent/Nutrition acceptance. This is the current blocker.
2. Explicit user approval for real data.
3. Real-Person onboarding + real ConsentGrants.
4. Duplicate OIDC `sub` remediation before any future native/public OIDC client.

EU residency is **not** a blocker — see the withdrawn G1.7 note above.

## Planned product capabilities after the current gates

### Smart Shopping + Smart Possessions `[ARCHITECTURE APPROVED; NOT IMPLEMENTED]`

ADR-0010 defines two sibling domain services rather than one broad "things" service:

- **`svc-shopping`** — ShoppingNeed, WatchRule/AlertRule, provider-normalized listings,
  PriceObservation, deterministic explainable DealEvaluation, PurchasePolicy and
  Purchase.
- **`svc-inventory`** — OwnedItem, locations/collections, usage/condition/maintenance,
  disposition, InventoryGap, Wardrobe/outfits and baby/home possession lifecycle.

The first Shopping provider is planned as **Kleinanzeigen Saved Search → official email
notification → mail adapter → MarketplaceProvider**, explicitly avoiding an architecture
that depends on direct scraping.

The product must enforce a **Friction Budget**: V1 is useful without special hardware
(photo-first capture, natural language, grouped items, one-tap feedback). QR/NFC
container/zone tagging is V2; smart wardrobe/RFID/laundry/Home Assistant is V3 only
after normal-use adoption is proven.

Initial V1 outcomes:

- baby preparation needs, deals, safety policy, price history, purchase/resale lifecycle
- inventory-aware shopping so the system does not recommend duplicates
- wardrobe rationalization (keep/use/sell/donate) and outfit suggestions
- InventoryGap → proposed ShoppingNeed; PurchaseCompleted → OwnedItem workflow
- provider/channel abstractions so future eBay/Amazon/Idealo/etc. do not change the Deal
  Engine

This capability is **not a G2 blocker** and must not interrupt closure of G1.6.
See `adr/0010-smart-shopping-and-possessions.md` and
`proposals/SMART_SHOPPING_AND_POSSESSIONS.md`.

### Later
Device Gateway/Withings, FHIR, Mind, Calendar, Documents, Finance, reverse proxy +
public UI, voice, grocery automation, additional Shopping providers, richer style/fashion
knowledge and ambient inventory automation.

## Architecture Change Rule (contributors & agents)
Before architectural changes:
1. Read `ARCHITECTURE.md`. 2. Read relevant ADRs. 3. Do not silently contradict
accepted decisions. 4. If architecture changes, update `ARCHITECTURE.md`. 5.
Create/update an ADR. 6. Update `STATUS.md`. 7. Commit documentation **with** the
implementation change. Git documentation is the architecture source of truth.
