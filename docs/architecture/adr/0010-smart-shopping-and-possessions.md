# ADR-0010 — Smart Shopping + Smart Possessions as sibling domain services

**Status:** Accepted (architecture only; no runtime implementation yet)  
**Date:** 2026-09-16

## Context

Episteck Home needs to help a family not only decide what to buy, but also understand
what it already owns, what is actually used, what is duplicated, what should be
rotated/donated/sold, and what is genuinely missing.

The first concrete Shopping use case is baby preparation: a family creates needs,
receives provider offers (initially Kleinanzeigen Saved Search notifications via email),
compares prices, evaluates deal quality, receives only high-value alerts, records
purchases, and builds price history.

The same lifecycle is broader than purchasing. For clothing and household possessions,
the family also needs a low-friction way to answer:

- what do we own, where is it, and who uses it?
- what is overstocked, underused, missing, outgrown, or due for disposal?
- what outfit should each person wear given calendar, weather, availability and style?
- what baby items are temporary and should be bought used, resold, donated, or deferred?

Putting all of this into Shopping would create a universal "things" service. Putting it
into the Home Control Plane would violate the existing no-universal-database decision.

## Decision

Create two sibling bounded contexts, implemented later as independent domain services:

1. **Smart Shopping** (`svc-shopping`) — the family's physical-product procurement
   intelligence layer: intent to acquire, product/offer comparison, provider listings,
   deal and price intelligence, grocery/retail basket planning, watch/alert rules,
   purchase policies, approval-aware purchase execution and purchase history.
2. **Smart Possessions / Inventory** (`svc-inventory`) — what is actually owned,
   locations, condition, usage, lifecycle, wardrobe/baby/home organization, disposition
   and inventory gaps.

The existing **Home Agent** remains the conversational interface. No new Hermes agent is
introduced for either domain. Each service exposes business-safe APIs/MCP tools and uses
the established trusted-actor + Home `ConsentGrant` pattern.

The Home Control Plane remains canonical for Person, Circle, CareRelationship,
ConsentGrant and CareJourney. It does not become the Shopping or Inventory database.

## Ownership boundary

### `svc-shopping` owns

- ShoppingList
- ShoppingNeed
- WatchRule
- AlertRule
- ProductIdentity / ProductVariant (lightweight canonicalization, not a global catalog)
- MarketplaceListing
- ListingSnapshot
- PriceObservation
- ProductEvaluation / OfferEvaluation / ValueEvaluation
- DealEvaluation
- BasketPlan
- PurchasePolicy
- PurchaseApprovalPolicy
- Purchase / order-procurement history
- NotificationIntent / deduplication state

### `svc-inventory` owns

- OwnedItem
- InventoryCollection
- StorageLocation
- ConditionObservation
- UsageEvent
- MaintenanceRecord
- DispositionPlan / DispositionEvent
- InventoryGap
- garment-specific metadata (GarmentProfile)
- Outfit / OutfitTemplate / outfit feedback
- baby lifecycle state (active / future / outgrown / stored / disposition candidate)

Shopping never becomes the authoritative record of what the family owns. Inventory
must support possessions acquired outside Episteck, inherited items, gifts and legacy
items. Conversely, Inventory may propose a need without silently starting a purchase.

## Person / Circle scoping

Shopping lists and possessions may be organized under either a Person or a Circle.
Circle membership remains organizational only and does **not** grant authorization.
Cross-person access continues to require explicit Home consent.

Planned consent domains:

- `SHOPPING`
- `INVENTORY`

with the existing actions `VIEW`, `CREATE`, `UPDATE`, `MANAGE`.

These domains are architecture decisions only until implemented in the policy engine.

## Shopping provider boundary

Shopping must not depend directly on Kleinanzeigen, Gmail, eBay, Amazon, Idealo,
supermarkets or any other source. The domain consumes normalized provider events behind
replaceable abstractions.

The classifieds path uses:

- `InboundMessageSource` — obtains an inbound event (Gmail, IMAP, forwarding, webhook,
  etc.).
- `MarketplaceProvider` — parses provider-specific content and emits normalized listing
  candidates.

The MVP path is intentionally:

`Kleinanzeigen Saved Search -> email notification -> inbound mail adapter ->
Kleinanzeigen provider adapter -> normalized listing -> Deal Engine`

No direct scraping dependency is required. Missing provider fields remain `UNKNOWN`;
the system does not fabricate condition, seller, distance, description or availability.

For retail/grocery, a more general `CommerceProvider` capability boundary may expose
only the capabilities a provider actually supports, such as product search, offers,
price feeds, unit price, availability, delivery options, cart read/write, checkout,
order status and substitutions. The Deal/Value engines consume normalized domain
objects, never provider payloads.

## Smart Shopping includes grocery procurement

Smart Shopping is intentionally broader than durable-goods deals. It is the common
physical-product procurement layer for baby goods, clothing, electronics, household
products, consumables and groceries.

Grocery ownership is split cleanly:

- **Mealie** remains owner/provider for meal-plan-linked grocery/shopping lists.
- **svc-nutrition** remains owner of nutrition profiles, targets and nutrition truth.
- **svc-shopping** owns grocery procurement intelligence and fulfillment: normalized
  product/offer comparison, unit-price comparison, BasketPlan, retailer selection,
  purchase intent, provider cart/order interaction and price history.
- **svc-inventory** may later provide pantry/consumable stock signals, but Shopping must
  work without requiring a perfect pantry inventory.

Shopping therefore consumes grocery requirements from Mealie rather than becoming a
second canonical grocery list.

## Product quality / price / value intelligence

Smart Shopping must answer not only "is this discounted?" but also "which product is
better for us?" and "is the extra cost worth it?".

`ProductEvaluation` is category-aware and evidence-based. Possible inputs include
feature/spec fit, durability/reliability evidence, safety/recall evidence,
nutrition/ingredient evidence for food, family preference fit, expected useful life and
trusted external testing/review evidence.

`OfferEvaluation` covers current price, unit price, availability, delivery/service fees,
condition, coupon/discount evidence, seller/provider confidence, historical price and
other acquisition costs.

`ValueEvaluation` combines product quality/fit and offer economics for the family's
actual constraints. It must remain explainable and carry confidence/provenance. The LLM
may summarize the evidence but may not invent prices, quality claims, tests, safety facts
or nutrition data.

No single universal quality score is required: a stroller, rain jacket and yogurt use
different evaluation profiles.

## Grocery basket optimization

Grocery/consumables require multi-item planning rather than independent deal scoring.
A future `BasketPlan` can account for requested quantity, unit price, substitutions,
availability, delivery/pickup cost, minimum-order thresholds, coupons and family
constraints. Initial optimization should remain deterministic and simple; comparing
single-retailer baskets can precede advanced multi-retailer optimization.

## Purchase automation must be progressive

Shopping may eventually automate purchasing, but automation level is explicit policy,
not an LLM decision.

Suggested progression:

- **LEVEL 0 — RECOMMEND:** compare/recommend only.
- **LEVEL 1 — PREPARE_CART:** prepare/propose a provider cart; user checks out.
- **LEVEL 2 — CONFIRM_TO_BUY:** one explicit user approval authorizes the shown
  basket/purchase within its exact constraints.
- **LEVEL 3 — POLICY_AUTOBUY:** future opt-in only for tightly bounded recurring or
  low-risk items under explicit amount/provider/category/substitution/frequency limits.

MVP does not silently execute payments. Raw payment credentials never enter the agent or
model context.

## Deal Engine

`DealScore` is deterministic, versioned and explainable. The LLM may explain results but
is not the source of the score. A DealEvaluation records its component contributions,
for example price vs target, price vs observed used baseline, price vs new reference,
product/variant match, condition, urgency and distance.

Deal quality is accompanied by `DealConfidence` (`LOW`, `MEDIUM`, `HIGH`) so an
apparently excellent price with weak evidence does not behave like a well-supported
market comparison.

Observed marketplace prices are asking prices unless a source explicitly proves a
completed transaction. Price intelligence must preserve that provenance.

## Purchase policy

PurchasePolicy is configurable data, not hardcoded baby logic. Initial policy classes:

- `USED_OK`
- `USED_WITH_CHECKS`
- `NEW_PREFERRED`
- `NEW_ONLY`

A policy can carry required checks, severity, rationale, provenance, jurisdiction and
review date. Unknown safety facts remain unknown; absence of evidence is never converted
into a positive safety claim.

A separate future `PurchaseApprovalPolicy` controls whether Episteck may perform a
commercial action (amount limits, approved providers/categories, substitutions,
quantities, recurring allowlists and explicit-confirmation thresholds). Safety policy
and payment/approval policy are deliberately separate concerns.

## Shopping <-> Inventory events

The two domains cooperate through explicit events/contracts rather than shared tables.
Examples:

- `PurchaseCompleted` -> Inventory proposes/creates an `OwnedItem` according to the
  workflow policy.
- `InventoryGapDetected` -> Shopping proposes a `ShoppingNeed`; it never purchases
  silently.
- `ItemOutgrown` -> creates a disposition candidate and may forecast a future need.
- `DispositionCompleted` -> updates possession state and can record recovered/resale
  value.
- `ItemUsageObserved` / `OutfitWorn` -> improve utilization and style recommendations.

## Wardrobe specialization

Wardrobe is a specialized experience inside Smart Possessions, not a separate source of
truth. `GarmentProfile` extends an OwnedItem with clothing attributes such as category,
brand, size, color, material, season, occasion, style tags, fit, weather suitability,
last-worn and wear count.

The Style Recommendation Engine combines inventory availability with context from other
domains/providers (for example Calendar and Weather) without copying those domains'
canonical data. Fashion/trend knowledge is advisory: it can influence ranking and
explanations but must not manufacture purchase needs simply because something is trendy.

A useful recommendation should prefer "use what you own" and surface a purchase only
when there is a functional/style gap or an explicit user goal.

## Baby lifecycle economics

Baby goods receive first-class lifecycle support because their useful windows are short.
Inventory can track sizes, age/usage windows, outgrown state, storage and disposition.
Shopping can consider expected resale value and estimate effective ownership cost:

`purchase cost - expected/actual resale value`

Safety policy always takes precedence over price optimization.

Pregnancy / due-date context remains owned by the appropriate health/CareJourney domain.
Shopping/Inventory may receive derived planning fields such as `watch_from`, `needed_by`
or a `care_journey_ref`; they do not copy clinical details into their own stores.

## Low-friction product principle

A hard product requirement is a **friction budget**: the system should learn from normal
use rather than make the family maintain a perfect database.

V1 must provide value without special hardware:

- photo-first capture with AI proposals + user confirmation/provenance
- bulk/group items when individual tracking adds little value
- one-tap "wore this", "another", "donate", "sold", "purchased"
- natural-language creation/update of needs
- incomplete inventory is explicitly allowed; confidence/coverage can be tracked
- grocery/consumable requirements should flow from existing lists/plans rather than be
  re-entered manually

V2 may add QR/NFC, with a default preference to tag **containers/locations before every
item** (boxes, drawers, baskets, wardrobe zones). This delivers most automation with
far less maintenance.

V3 may integrate ambient signals such as RFID wardrobe zones, laundry baskets,
washing-machine/Home Assistant events or other smart-home sensors. Hardware is an
optional accelerator, never a prerequisite for a useful product.

## Consequences

Positive:

- shopping decisions become inventory-aware instead of encouraging unnecessary buying;
- the same procurement intelligence can compare durable goods, retail products,
  groceries and recurring household essentials;
- grocery planning can flow from Mealie into price/quality/basket optimization without
  duplicating the canonical meal/grocery list;
- baby temporary goods can be optimized for buy/use/resell/donate lifecycle;
- wardrobe/outfit planning can become a daily Home experience;
- provider and hardware integrations remain replaceable adapters;
- each domain keeps a clear source of truth and existing Home authorization semantics.

Costs / risks:

- two services and explicit contracts are more work than one broad Shopping service;
- grocery/retail checkout integrations add provider, payment, authorization and audit
  complexity and must be introduced progressively;
- item normalization and duplicate detection are inherently probabilistic;
- manual inventory maintenance can destroy adoption unless the friction budget is
  enforced;
- provider email/API formats can change, so adapters need fixtures/versioning;
- quality comparisons require evidence/provenance and category-specific logic rather
  than opaque AI scoring;
- trend/style recommendations require preference learning and should not create alert
  fatigue or unnecessary consumption;
- images, seller data and household possessions may be sensitive and require conservative
  retention and authorization.

## Delivery sequence

This ADR does **not** authorize implementation before the current G1.6 security gate is
complete.

After G1.6, the next architecture step is contracts/schema design for `svc-shopping` and
`svc-inventory`, followed by an intentionally small V1. Smart tags, smart wardrobe,
advanced grocery checkout and laundry automation are deferred until the relevant
low-friction/manual flows prove useful.

See `../proposals/SMART_SHOPPING_AND_POSSESSIONS.md` for the main phased proposal and
`../proposals/SMART_SHOPPING_COMMERCE_AND_GROCERY.md` for the commerce/grocery extension.
