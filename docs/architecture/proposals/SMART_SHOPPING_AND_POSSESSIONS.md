# Smart Shopping + Smart Possessions — Architecture Proposal

**Status:** APPROVED FOR ARCHITECTURE · implementation deferred until G1.6 completion  
**Date:** 2026-09-16  
**Related ADR:** `../adr/0010-smart-shopping-and-possessions.md`

## 1. Product goal

Episteck Home should help a family manage the complete lifecycle of physical things:

`Need -> Buy -> Own -> Use -> Rotate/Maintain -> Sell/Donate/Give away/Discard`

Two complementary capabilities are required:

- **Smart Shopping** — what we need, offers, price/deal intelligence, purchase safety,
  notifications and purchase history.
- **Smart Possessions / Inventory** — what we own, where it is, who uses it, condition,
  utilization, wardrobe/outfit planning, baby lifecycle and disposition.

The central product requirement is **low friction**. The family should receive value
without maintaining a perfect catalog. V1 must work with photos, natural language,
lightweight confirmation and one-tap lifecycle actions; smart tags/hardware are optional
later accelerators.

## 2. Bounded contexts

### Smart Shopping (`svc-shopping`)

Owns intent to acquire and market intelligence.

Core entities:

- `ShoppingList`
- `ShoppingNeed`
- `WatchRule`
- `AlertRule`
- `ProductIdentity`
- `ProductVariant`
- `MarketplaceListing`
- `ListingSnapshot`
- `PriceObservation`
- `DealEvaluation`
- `PurchasePolicy`
- `Purchase`
- `NotificationIntent`

### Smart Possessions (`svc-inventory`)

Owns the family's actual physical inventory and lifecycle.

Core entities:

- `OwnedItem`
- `InventoryCollection`
- `StorageLocation`
- `UsageEvent`
- `ConditionObservation`
- `MaintenanceRecord`
- `DispositionPlan`
- `DispositionEvent`
- `InventoryGap`
- `GarmentProfile`
- `Outfit`
- `OutfitTemplate`
- `OutfitFeedback`

Wardrobe, baby gear and household/storage are specialized views/workflows over the same
inventory source of truth rather than separate databases.

## 3. Home Control Plane integration

The Home Control Plane remains canonical for Person, Circle, CareRelationship,
ConsentGrant and CareJourney.

Shopping/Inventory records can be organized for a Person or a Circle, but **Circle
membership never grants authorization**. Cross-person access must use explicit Home
consent.

Planned consent domains:

- `SHOPPING`
- `INVENTORY`

using the existing actions `VIEW`, `CREATE`, `UPDATE`, `MANAGE`.

These domains must not be added to the live policy engine until their services and
pre-retrieval authorization paths are implemented and tested.

Every person-sensitive service call must follow the G1.6 pattern:

`authenticated human session -> trusted delegation -> machine caller + human actor ->
Home can_access -> domain repository`

The LLM never supplies an actor id.

## 4. Smart Shopping model

### ShoppingList

A logical plan, e.g. `Baby Preparation 2027`, `Erick wardrobe gaps`, `Home office`.

Suggested fields:

- id / name / purpose / currency / status
- organizational scope: Person or Circle
- authorization subject Person (MVP bridge while consent remains person-centric)
- optional `care_journey_ref`

### ShoppingNeed

Represents intent, not a listing.

Suggested fields:

- name / category
- acceptable brands / models / variants / attributes
- target price / max price
- minimum condition
- acquisition mode: NEW / USED / BOTH
- location / radius
- priority
- `watch_from` / `needed_by`
- notes
- purchase policy
- lifecycle: `NOT_NEEDED_YET -> WATCHING -> GOOD_DEAL_FOUND -> PURCHASED` plus
  CANCELLED

### WatchRule vs AlertRule

Keep these separate:

- **WatchRule:** what is monitored (product, range, distance, provider constraints).
- **AlertRule:** when to interrupt the family (DealScore threshold, confidence, price,
  urgency, distance, etc.).

This prevents provider search configuration from being coupled to notification policy.

## 5. Provider abstraction

Shopping core must not know Kleinanzeigen, Gmail, eBay, Amazon, Idealo or any specific
transport.

Two boundaries are used:

### InboundMessageSource

Obtains external events. Implementations may include Gmail, IMAP, forwarding, webhook
or another mailbox/event source.

### MarketplaceProvider

Converts provider-specific events/data into normalized listings.

Conceptual capabilities:

- `PUSH_LISTINGS`
- `SEARCH_API`
- `DETAIL_API`
- `PRICE_FEED`
- `AVAILABILITY`
- `IMAGE_FEED`

The MVP provider path is:

`Kleinanzeigen Saved Search -> official email notification -> mail adapter ->
KleinanzeigenSavedSearchProvider -> NormalizedListing -> Deal Engine`

No direct scraping dependency is required. If the email lacks seller, condition,
distance, images or full description, those fields remain `UNKNOWN`.

Future providers can be added without changing the Deal Engine.

## 6. Listings and price intelligence

`MarketplaceListing` represents provider identity; `ListingSnapshot` records observed
state over time so price changes are not overwritten.

Example:

`€350 -> €320 -> €280`

`PriceObservation` is a uniform analytical projection across providers/sources:

- product / variant
- amount / currency
- NEW vs USED
- condition
- source / provider / listing reference
- observed_at
- provenance / confidence

Marketplace listing prices are **asking prices** unless a provider explicitly proves a
completed transaction. Price analytics must describe them accordingly.

This supports future questions such as:

- typical observed price in the last 90 days
- estimated savings vs new
- buy now vs wait
- preparation spending to date

## 7. Deal Engine

DealScore is deterministic, versioned and explainable; the LLM does not invent it.

Initial score components can include:

- price vs target
- price vs observed used baseline
- discount vs new reference
- product/variant match
- condition
- urgency
- distance
- absolute and percentage savings

Each `DealEvaluation` stores component contributions plus a `DealConfidence`
(`LOW`/`MEDIUM`/`HIGH`). A high score with weak evidence must not be treated like a
high-confidence deal.

Example explanation:

- +28 price vs target
- +18 vs typical observed used asking price
- +15 exact model match
- +8 condition
- +9 urgency
- +3 distance

AI may normalize and explain, but deterministic code owns score arithmetic and policy.

## 8. Purchase safety

PurchasePolicy is configurable/versioned data, reusable beyond baby products:

- `USED_OK`
- `USED_WITH_CHECKS`
- `NEW_PREFERRED`
- `NEW_ONLY`

Policies can include required checks, rationale, severity, provenance, jurisdiction and
review date. Examples for baby goods include accident history, hygiene, recalls, expiry,
missing parts and visible damage.

Unknown safety facts remain unknown; the system must never convert missing evidence into
a positive safety claim.

## 9. Notifications and deduplication

The Deal Engine creates `NotificationIntent`; delivery channels are adapters.

Future channels may include Home notification, push, email and messaging integrations.

Deduplication fingerprint concept:

`listing_id + shopping_need_id + alert_rule_id + meaningful_version`

Renotify only when something meaningful changes (e.g. material price drop, threshold
crossing, urgency transition), not for every repeated provider notification.

## 10. Smart Possessions / Inventory

### Generic OwnedItem

Tracks a real possession independently of how it was acquired.

Suggested fields include:

- identity/category
- owner/scope (Person or Circle for organization)
- storage location
- condition
- acquisition metadata/reference
- lifecycle state
- usage/maintenance summary
- provenance/confidence

Inventory must support gifts, inherited items, manual additions and pre-existing
possessions, not just Shopping purchases.

### Collections and locations

Examples:

- Erick wardrobe
- Ana wardrobe
- Baby clothes size 62
- Baby gear
- Kitchen
- Keller storage
- Tools

V2 smart-tag design should prefer tagging **containers/locations before individual
objects** (boxes, drawers, baskets, wardrobe zones), because this gives high value with
low maintenance.

## 11. Wardrobe and Style Engine

Wardrobe is an Inventory specialization.

`GarmentProfile` may include:

- category / brand / size / color / material
- season / occasion / style tags / fit
- weather suitability
- last worn / wear count
- availability state

Style recommendation combines:

`Wardrobe + Calendar context + Weather + personal preferences + occasion + fashion
knowledge -> ranked Outfit suggestions`

Calendar and Weather remain external/canonical sources; Wardrobe consumes only needed
context and does not duplicate them.

Interaction must be lightweight:

- `wore this`
- `another`
- `more casual/formal`
- `like` / `don't like`

Feedback improves preference ranking over time.

Fashion/trend knowledge should influence ranking and explanations, not generate
unnecessary purchases. Preferred behavior is "use what you own"; Shopping is invoked
when there is a real functional/style gap or explicit user goal.

Example inventory-aware behavior:

- four winter jackets, one heavily used
- zero rain jackets
- system proposes donation/sale candidates for redundant jackets
- system proposes a rain-jacket ShoppingNeed rather than another winter jacket

## 12. Baby lifecycle and economics

Baby goods deserve first-class lifecycle support because useful windows are short.

Inventory can track:

- clothing sizes / quantities
- active vs future vs outgrown
- stored / sell / donate / give-away candidates
- baby equipment useful window
- condition and safety checks

Shopping/Inventory can estimate effective ownership cost when evidence exists:

`purchase cost - expected/actual resale value`

This helps optimize temporary items without letting financial optimization override
PurchasePolicy safety.

Pregnancy/due-date data remains in its proper Home/health/CareJourney context. Shopping
receives only derived fields such as `watch_from`, `needed_by` or a CareJourney
reference; clinical details are not copied into Shopping/Inventory.

## 13. Shopping <-> Inventory contracts/events

No shared database.

Initial event vocabulary:

- `PurchaseCompleted`
- `OwnedItemCreated`
- `InventoryGapDetected`
- `ShoppingNeedProposed`
- `ItemOutgrown`
- `DispositionPlanned`
- `DispositionCompleted`
- `ItemUsageObserved`
- `OutfitWorn`

Important safety rule: an Inventory gap may **propose** a ShoppingNeed but must not
silently trigger a purchase. Likewise a Shopping purchase can propose/create an OwnedItem
according to explicit workflow policy, but Inventory remains authoritative thereafter.

## 14. Low-friction / Friction Budget

Adoption is a hard architecture/product constraint.

Target interactions:

- register a purchase: automatic or one confirmation
- create/update a need: natural language
- add a garment/item by photo: seconds, not forms
- mark outfit worn: one tap
- move a baby box from storage to active: one scan/tap
- mark sold/donated/given away: one tap

V1 should explicitly tolerate incomplete inventory and can track coverage/confidence
rather than pretending the household digital twin is perfect.

### Capture hierarchy

1. photo-first AI proposal + user confirmation/provenance
2. natural-language/manual quick-add
3. grouped/bulk items where individual identity adds little value
4. V2 QR/NFC on containers/selected valuable items
5. V3 ambient RFID / wardrobe / laundry / Home Assistant integrations

Hardware never becomes required for basic usefulness.

## 15. AI boundaries and provenance

AI can:

- interpret natural language into ShoppingNeed / WatchRule proposals
- normalize listing/product text
- propose garment/item metadata from photos
- rank/explain outfits using deterministic/contextual inputs
- summarize why a deal is attractive

AI must not:

- invent prices or safety facts
- silently confirm uncertain item identity
- make actor identity caller-controlled
- purchase automatically without an explicitly designed future approval flow

Detected/derived data carries provenance such as `AI_DETECTED`, `USER_CONFIRMED`,
`PROVIDER_OBSERVED`, etc., consistent with Episteck Home's broader provenance model.

## 16. UI direction

A coherent Home experience is preferable to separate mini-apps:

- **Today** — outfit suggestions / contextual prompts
- **Things** — Wardrobe / Baby / Home / Storage
- **Shopping** — Needs / Deals / Purchases
- **Declutter** — Sell / Donate / Give away / Discard

The Home Agent connects all of these through business-safe tools.

## 17. Delivery phases

### V1 / MVP

Smart Shopping:

1. ShoppingList / ShoppingNeed
2. WatchRule + AlertRule
3. mail ingestion abstraction
4. Kleinanzeigen Saved Search email adapter
5. listing normalization
6. deterministic DealScore + confidence + explanation
7. deduplicated good-deal notifications
8. Shopping/Deals UI
9. mark purchased
10. price-paid/history

Smart Possessions:

1. OwnedItem / Collection / Location
2. photo-first/manual capture
3. Wardrobe basics
4. Outfit suggestions + one-tap feedback
5. baby inventory + size/equipment lifecycle
6. InventoryGap + disposition workflows
7. Shopping/Inventory event contracts

### V2

- additional providers/APIs (eBay/retail/price feeds)
- 90-day baselines and richer price intelligence
- richer safety/recall integrations
- QR/NFC, prioritizing containers/zones
- Calendar + Weather outfit context
- stronger style preference learning
- resale-value/effective-cost analysis
- CareJourney-driven preparation windows
- Home Assistant/laundry event adapters where useful

### V3

- multi-market optimization / buy-now-vs-wait models
- seasonal price intelligence
- advanced fashion/trend knowledge
- ambient RFID / smart wardrobe / smart laundry
- deeper budget/Finance integration
- commercial multi-tenant/regional deployments

## 18. Risks

- **Adoption:** manual maintenance can destroy value; enforce the friction budget.
- **Provider fragility:** email/API formats change; adapters require fixtures and
  quarantine on unknown format.
- **Provider/legal constraints:** avoid architecture that requires unauthorized scraping;
  prefer official notifications/APIs/feeds.
- **Incomplete market data:** asking price is not transaction price.
- **False bargains:** low price may correlate with damage, missing parts or scams;
  combine DealScore with confidence and PurchasePolicy.
- **Privacy:** clothing, home possessions, seller information and photos are sensitive;
  retain conservatively and authorize before retrieval.
- **Normalization:** product/item recognition is probabilistic; preserve provenance and
  allow `UNKNOWN`.
- **Alert fatigue:** alert thresholds and deduplication are first-class requirements.

## 19. Implementation gate

Do not implement these services until the current G1.6 trusted-actor/replay/security gate
is complete. The immediate post-G1.6 work for this capability is contracts/schema +
service boundary design, not hardware integration and not a broad provider rollout.
