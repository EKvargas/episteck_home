# Smart Shopping — Commerce, Product Comparison and Grocery Automation

**Status:** APPROVED FOR ARCHITECTURE · implementation deferred until G1.6 completion  
**Date:** 2026-09-16  
**Parent ADR:** `../adr/0010-smart-shopping-and-possessions.md`

## 1. Purpose

Smart Shopping is the family-facing **procurement intelligence layer** for physical
products. It is broader than deal hunting for durable goods: it should help the family
answer the same core questions for baby gear, clothing, electronics, household goods,
consumables and groceries:

- What do we actually need?
- Which products satisfy that need?
- Which product is better for us?
- Which offer/provider is better right now?
- Is the apparent discount real?
- What is the best value after quality, quantity, delivery and safety are considered?
- Should we buy now, wait, substitute, or skip because we already own enough?
- Can Episteck prepare or execute the purchase with an explicit approval policy?

Smart Shopping remains separate from Smart Possessions/Inventory. Shopping decides what
to acquire and from whom; Inventory knows what is already owned and what happens after
acquisition.

## 2. Shopping as an umbrella, not a marketplace-specific service

`svc-shopping` supports several acquisition styles behind provider capabilities:

- classified / used marketplace offers (Kleinanzeigen, Facebook Marketplace, eBay used)
- retail product catalogs and offers (Amazon, Idealo-linked retailers, online stores)
- grocery / supermarket catalogs, baskets and delivery/pickup
- household consumables / recurring essentials
- provider feeds, official APIs, email notifications and future commerce connectors

The domain model must not contain Kleinanzeigen-, Gmail-, Amazon- or supermarket-specific
fields. Provider-specific details remain in adapters.

## 3. Core abstraction: Product, Offer, Comparison, Basket, Purchase

The long-term generic flow is:

`ShoppingNeed -> ProductCandidate -> Offer -> ProductEvaluation / OfferEvaluation ->
BasketPlan -> PurchaseIntent -> Purchase`

Existing marketplace entities remain useful:

- `MarketplaceListing` / `ListingSnapshot` are a provider-specific form of observed Offer
  optimized for classifieds and changing used listings.
- `PriceObservation` provides historical price evidence.
- `DealEvaluation` answers "is this offer unusually good?".

Add/plan the following generic concepts:

### ProductEvaluation

Evidence-based evaluation of a product independent of a particular seller/offer.
Possible dimensions are category-specific and may include:

- feature/specification fit
- durability / reliability evidence
- safety / recall evidence
- ingredient/nutrition evidence for food
- user/family preference fit
- expected useful life
- repairability / maintainability
- trusted review or testing evidence
- confidence and provenance

No single universal quality formula is required. Evaluation profiles are category-aware.
A stroller, rain jacket and yogurt should not be scored with the same quality dimensions.

### OfferEvaluation

Evaluates a specific commercial offer, including:

- current price
- unit price where applicable
- delivery / service fees
- minimum-order effects
- coupon/discount evidence
- availability
- condition (new/used/refurbished)
- seller/provider confidence
- distance / pickup cost
- expected resale value where relevant
- historical price context

### ValueEvaluation

Combines ProductEvaluation + OfferEvaluation + family constraints into an explainable
"value for us" result. It is not an opaque AI score.

Example:

`Product quality/fit: HIGH`
`Offer price: €280`
`Observed typical used asking price: €430`
`New reference: €900`
`Safety checks: 3 required / 2 confirmed / 1 unknown`
`Value confidence: MEDIUM`

AI may explain this result but deterministic/category policy owns the arithmetic and hard
constraints.

## 4. Provider capability model

Keep the existing `MarketplaceProvider` adapter for classifieds, but add a more general
commerce capability boundary so retail/grocery does not get forced into a listing-only
shape.

Conceptually:

`CommerceProvider`

with declared capabilities such as:

- `SEARCH_PRODUCTS`
- `SEARCH_OFFERS`
- `DETAIL`
- `PRICE_FEED`
- `AVAILABILITY`
- `UNIT_PRICE`
- `DELIVERY_OPTIONS`
- `CART_READ`
- `CART_WRITE`
- `CHECKOUT`
- `ORDER_STATUS`
- `SUBSTITUTIONS`

A provider implements only what it actually supports. The Deal/Value engines consume
normalized domain objects, never provider payloads.

`MarketplaceProvider` may be implemented as a specialization/adapter over this boundary
or remain a focused interface feeding normalized Offers; the implementation decision can
be made during contracts/schema design.

## 5. Grocery ownership boundary

Grocery introduces an important ownership split:

- **Mealie** remains owner/provider for meal-plan-linked grocery/shopping lists.
- **svc-nutrition** remains owner of nutrition profiles, targets and nutrition truth.
- **svc-shopping** owns procurement intelligence and fulfillment: product/offer
  comparison, unit-price normalization, basket planning, retailer/provider selection,
  checkout intent, purchases/orders and price history.
- **svc-inventory** may later provide pantry/household-stock signals, but Shopping must
  work before a perfect pantry inventory exists.

Shopping must not duplicate a Mealie grocery list as a second canonical list. It consumes
an explicit list/request contract and returns fulfillment/procurement results.

Example:

`Mealie meal plan -> grocery requirements -> svc-shopping -> retailer offers -> optimized
basket -> user approval -> provider cart/order -> PurchaseCompleted`

## 6. Grocery comparison engine

Grocery comparison cannot optimize only sticker price. It must understand normalized
quantity and family constraints.

Important inputs:

- unit price (`€/kg`, `€/L`, `€/piece`) and package quantity
- requested quantity
- brand/model/product equivalence
- acceptable substitutions
- nutrition/ingredient requirements supplied by Nutrition or user policy
- organic/allergen/quality preferences where configured
- retailer availability
- delivery fee / pickup cost / minimum order
- coupons/promotions with provenance
- waste risk / pack size vs likely consumption
- provider reliability/confidence

Example:

`Milk 1L x 4`

Provider A: €1.29/L, €5.16 total, €5 delivery  
Provider B: €1.39/L, €5.56 total, free delivery because basket threshold is met

The cheapest line item is not necessarily the cheapest basket.

## 7. Basket optimizer

Grocery and household consumables need a multi-item optimization layer:

`BasketPlan`

Suggested fields/concepts:

- requested needs/items
- selected provider(s)
- selected product substitutions
- quantities
- line totals
- delivery/pickup fees
- coupon effects
- minimum-order constraints
- unavailable items
- confidence / missing information
- total cost
- delta vs alternative basket plans

Initial optimization can be simple and deterministic. Do not start with a complex global
optimizer if one-provider basket comparison provides most value.

Future modes may compare:

- cheapest single retailer
- cheapest multi-retailer split
- best quality/value basket
- fastest delivery
- preferred retailers only

## 8. Purchase automation levels

Automatic purchasing must be progressive and explicit. Define an automation level/policy
instead of silently escalating from recommendation to checkout.

Suggested levels:

- **LEVEL 0 — RECOMMEND:** compare and recommend only.
- **LEVEL 1 — PREPARE_CART:** build/propose the provider cart, user checks out.
- **LEVEL 2 — CONFIRM_TO_BUY:** Episteck prepares everything; one explicit user approval
  authorizes the purchase within the shown basket/price.
- **LEVEL 3 — POLICY_AUTOBUY:** future opt-in for tightly bounded recurring/low-risk
  items under explicit budget, merchant, substitution, quantity and frequency limits.

MVP should stop at LEVEL 0/1 unless a provider has a clean official checkout integration
and the authorization/audit model is deliberately implemented.

No LLM decision alone may authorize payment.

## 9. PurchaseApprovalPolicy

A future `PurchaseApprovalPolicy` is distinct from baby/product `PurchasePolicy`.

`PurchasePolicy` answers whether/how an item may safely/appropriately be purchased
(e.g. USED_WITH_CHECKS).

`PurchaseApprovalPolicy` answers whether Episteck may execute a commercial action.
Possible constraints:

- maximum amount per purchase / day / month
- approved providers
- approved categories
- exact-item only vs substitutions allowed
- max substitution price delta
- quantity limits
- recurring-item allowlist
- require explicit confirmation above threshold
- delivery-address/payment-profile reference (never expose raw payment secrets to agent)

Default is explicit confirmation / no autonomous checkout.

## 10. Household consumables and recurring essentials

The grocery capability generalizes naturally to consumables such as:

- diapers
- wipes
- detergent
- toilet paper
- cleaning products
- pet food
- toiletries

Inventory/usage signals can later predict depletion and produce a proposed ShoppingNeed.
The system should first recommend/replenish based on evidence, not invent consumption.

Example:

`diapers size 3: estimated 6 days remaining -> create/propose need -> compare current
retailer unit prices -> notify or prepare cart`

## 11. Product comparison / quality-price intelligence

Smart Shopping should expose a generic family capability such as:

- "Compare these two products"
- "Which one is better quality?"
- "Which is better value for us?"
- "Is the more expensive one worth it?"
- "What is the price history?"
- "Are we paying more for brand with no meaningful benefit?"

Quality claims require provenance. Sources may include manufacturer specifications,
independent tests/reviews, safety/recall sources, Nutrition data, verified provider data
and user-confirmed experience. Community/review sentiment may be summarized separately
from objective evidence.

AI can synthesize and explain evidence but must not invent ratings, prices, test results,
safety claims or nutritional facts.

## 12. Example end-to-end grocery flow

User:

"Buy what we need for this week's meals, but show me the basket before buying. Prefer
healthy options and don't substitute Ana's preferred yogurt brand."

Flow:

1. Home Agent resolves trusted actor.
2. Mealie provides current grocery requirements.
3. Nutrition/user preferences supply allowed constraints as appropriate.
4. Shopping normalizes needs and asks compatible CommerceProvider adapters for offers.
5. Product/Offer evaluations normalize quantity, quality evidence and total cost.
6. Basket optimizer proposes one or more baskets.
7. Home Agent explains tradeoffs.
8. User explicitly approves.
9. If the provider supports cart write, Shopping prepares the cart; future checkout
   execution requires the configured approval level.
10. Completed order emits `PurchaseCompleted`; Inventory/pantry integration may consume
    relevant events later.

## 13. Friction budget applies to commerce too

The user should not manually compare dozens of websites or recreate lists.

Target experience:

- meal plan automatically yields procurement requirements
- recurring household essentials can be proposed automatically
- provider comparisons happen in background
- only materially better alternatives/deals interrupt the user
- substitutions are learned from explicit approvals/rejections
- checkout remains one confirmation when required

Automation reduces repetitive work but never hides important price, quantity,
substitution or safety changes.

## 14. Delivery phases

### V1 extension

- generic ProductEvaluation / OfferEvaluation contracts
- unit-price normalization
- manual/provider offer comparison
- grocery requirement import contract from Mealie
- BasketPlan (recommendation only)
- price/quality/value explanations

### V2

- retailer/commerce adapters with official APIs where available
- live availability/delivery fees
- cart preparation
- household-consumable recurring needs
- preference-aware substitutions
- pantry/inventory signals where useful

### V3

- approved checkout integrations
- bounded recurring auto-buy policies
- multi-retailer basket optimization
- depletion prediction
- Finance/budget integration
- broader cross-provider product intelligence

## 15. Architectural invariant

**All physical-product procurement intelligence belongs under Smart Shopping, but domain
truth stays with its source domain.**

Smart Shopping may compare, optimize and execute acquisition. It does not become the
canonical nutrition database, meal planner, household inventory database, calendar or
finance ledger.
