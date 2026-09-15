# Data Ownership

**Principle: no universal database.** Each domain owns its truth; other components
reference it, they do not duplicate it.

| Domain / data | Owner (source of truth) | Notes |
| --- | --- | --- |
| Person, Circle, CircleMembership, CareRelationship, ConsentGrant, CareJourney | **Home Control Plane** (`episteck_home` on home.episteck.com) | Identity + relationships + consent + coordination |
| Nutrition Profile, nutrient targets + provenance, planned/actual intake, deterministic calculations | **svc-nutrition** (Nuremberg) | Authoritative Nutrition store (SQLite → repo abstraction) |
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
