# Data Ownership

**Principle: no universal database.** Each domain owns its truth; other components
reference it, they do not duplicate it.

| Domain / data | Owner (source of truth) | Notes |
| --- | --- | --- |
| Person, Circle, CircleMembership, CareRelationship, ConsentGrant, CareJourney | **Home Control Plane** (`episteck_home` on home.episteck.com) | Identity + relationships + consent + coordination |
| Nutrition Profile, nutrient targets + provenance, planned/actual intake, deterministic calculations | **svc-nutrition** (Nuremberg) | Authoritative Nutrition store (SQLite → repo abstraction) |
| Recipes, meal plans, **grocery/meal-plan shopping lists / requirements** | **Mealie** (Nuremberg) | Provider only, behind Episteck adapter; canonical food/grocery planning input, not the procurement engine |
| Smart Shopping: ShoppingNeed, WatchRule, AlertRule, marketplace/retail offers, listings/snapshots, price observations, product/offer/value evaluations, BasketPlan, purchase policies, purchase/order history | **svc-shopping** `[PLANNED]` | Physical-product procurement / comparison / deals / price-quality intelligence / fulfillment. Includes grocery and household-consumable procurement, but does not own meal plans or nutrition truth |
| Smart Possessions / Inventory: OwnedItem, collections/locations, usage, condition, maintenance, disposition, inventory gaps, wardrobe/outfit and baby-item lifecycle | **svc-inventory** `[PLANNED]` | What the family actually owns. Separate from Shopping so gifts/legacy possessions and post-purchase lifecycle remain authoritative here; pantry/consumable stock may be added later |
| Clinical truth (diagnoses, conditions) | **FHIR service** `[PLANNED]` | Not built |
| Measurements + device provenance (weight, BP, etc.) | **Device Gateway** `[PLANNED]` | Not built |
| Mind domain truth | **Mind service** `[PLANNED]` | Not built |
| Durable personal/family contextual knowledge | **Knowledge service** `[CONTRACT-ONLY]` | Governance layer; references canonical domain data, never duplicates structured facts |
| Calendar events | **Calendar service/provider** `[PLANNED]` | |

## Shopping is not Inventory

`svc-shopping` answers **what should we acquire, which product/offer is best for us, and
how should the purchase be fulfilled?**

`svc-inventory` answers **what do we own and what should happen to it over time?**

A purchase can produce an Inventory item through an explicit event/contract, and an
Inventory gap can propose a ShoppingNeed, but the services do not share tables or shadow
copy each other's source-of-truth data.

Wardrobe, baby gear, household possessions and storage are specialized Inventory
workflows. Kleinanzeigen/eBay/Amazon/Idealo/supermarket/mailbox integrations are Shopping
adapters, not domain owners.

## Grocery ownership split

Grocery intentionally crosses domain boundaries without duplicating truth:

- Mealie owns the meal-plan-linked grocery requirement/list.
- Nutrition owns nutrition facts/targets/profiles and nutrition calculations.
- Shopping consumes requirements and owns product/offer comparison, normalized unit
  price, BasketPlan, provider selection, purchase intent, provider cart/order interaction
  and purchase/price history.
- Inventory may later contribute pantry/consumable stock signals, but a perfect pantry
  inventory is not a prerequisite for Shopping.

Thus `svc-shopping` may answer "where/how should we buy this week's groceries?" without
becoming the canonical grocery list or nutrition database.

## Knowledge is not a domain-fact duplicate
Knowledge stores contextual/reusable **meaning** and **references** canonical domain
data. Weight → Device Gateway. Diagnosis → FHIR. Nutrition intake → svc-nutrition.
Calendar event → Calendar. Person/Circle → Home Control Plane. ShoppingNeed/Purchase →
svc-shopping. OwnedItem/wardrobe/baby inventory → svc-inventory. Never store
credentials/secrets as Knowledge.

## Company vs Home
`erp.episteck.com` (company ERP) and `home.episteck.com` (Home Control Plane) are
**separate Frappe sites** with separate data. `EKvargas/episteck` = company code;
`EKvargas/episteck_home` = the Home product (canonical).
