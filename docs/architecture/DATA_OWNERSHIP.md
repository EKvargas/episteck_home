# Data Ownership

**Principle: no universal database.** Each domain owns its truth; other components
reference it, they do not duplicate it.

| Domain / data | Owner (source of truth) | Notes |
| --- | --- | --- |
| Person, Circle, CircleMembership, CareRelationship, ConsentGrant, CareJourney, FeatureActivation | **Home Control Plane** (`episteck_home` on home.episteck.com) | Identity + relationships + consent + coordination. Feature Activation is a per-Person/Circle on/off switch, not an authorization (ADR-0012) |
| Nutrition Profile, nutrient targets + provenance, planned/actual intake, deterministic calculations | **svc-nutrition** (Nuremberg) | Authoritative Nutrition store (SQLite → repo abstraction) |
| Account balances (as observed by the bank/provider), movements, ECB reference rates used for valuation; later classification and receivables | **svc-finance** `[I1 — code in review, not deployed]` (Nuremberg) | Authoritative Finance store (SQLite). The bank is the source of each balance; Finance keeps the canonical copy. Consent and feature activation stay in Home. Real financial data lives only on Nuremberg. See ADR-0011. PSD2 consent state (state hash, a one-time code kept until the operator's command takes it, session uid map) is Finance's too (ADR-0013) |
| Recipes, meal plans, shopping lists | **Mealie** (Nuremberg) | Provider only, behind Episteck adapter |
| Clinical truth (diagnoses, conditions) | **FHIR service** `[PLANNED]` | Not built |
| Measurements + device provenance (weight, BP, etc.) | **Device Gateway** `[PLANNED]` | Not built |
| Mind domain truth | **Mind service** `[PLANNED]` | Not built |
| Durable personal/family contextual knowledge | **Knowledge service** `[CONTRACT-ONLY]` | Governance layer; references canonical domain data, never duplicates structured facts |
| Calendar events | **Calendar service/provider** `[PLANNED]` | |

## Knowledge is not a domain-fact duplicate
Knowledge stores contextual/reusable **meaning** and **references** canonical domain
data. Weight → Device Gateway. Diagnosis → FHIR. Nutrition intake → svc-nutrition.
Calendar event → Calendar. Person/Circle → Home Control Plane. Never store
credentials/secrets as Knowledge.

## Company vs Home
`erp.episteck.com` (company ERP) and `home.episteck.com` (Home Control Plane) are
**separate Frappe sites** with separate data. `EKvargas/episteck` = company code;
`EKvargas/episteck_home` = the Home product (canonical).
