# LLM Routing and Cost Management Gate

Status: CANDIDATE / FUTURE ARCHITECTURE GATE — NOT SELECTED

Date opened: 2026-09-20

## Purpose

Olin will need a deliberate inference-routing layer so that model cost, quota usage,
privacy, and provider selection do not leak into domain services or the UI.

A promising candidate is [OmniRoute](https://github.com/diegosouzapw/OmniRoute), an
MIT-licensed LLM gateway with OpenAI/Anthropic/Gemini-compatible endpoints, provider
routing, fallbacks, usage metering, API-key policy, and quota-sharing capabilities.

OmniRoute is **not selected or deployed by this document**. This gate preserves the
topic for later architecture work and records the current division-of-responsibility
hypothesis.

## Architecture hypothesis

Olin should own:

- trusted Person / Household identity and security partition
- privacy and sensitivity classification
- task classification
- model/provider eligibility policy
- budget policy
- per-Person / per-Household product entitlements
- the decision about whether a request is allowed to leave the Olin trust boundary

An inference gateway such as OmniRoute may own:

- upstream provider connections
- provider/model routing
- quota awareness
- free-tier / subscription / API-key connection availability
- fallback ordering
- per-key usage metering
- cost accounting
- rate and budget enforcement
- optional prompt/token compression

The gateway must never become Olin's identity, consent, tenancy, or domain-authorization
system.

## Candidate request path

```text
Browser / Olin UI
      ↓
Olin trusted session / BFF
      ↓
trusted Person + security partition
      ↓
Olin LLM Policy
  - privacy/sensitivity
  - task class
  - allowed provider class
  - model quality floor
  - budget/fallback policy
      ↓
server-selected gateway credential/policy
      ↓
OmniRoute candidate
      ↓
user-owned / household-owned / Episteck-owned upstream provider
```

The browser, LLM, prompt, or MCP/tool payload must never choose authoritative
`api_key`, `connection_id`, quota pool, provider credential, Person, or partition.

## Cost strategy to evaluate

The desired commercial shape is **free/BYOK-first with bounded paid fallback**, not a
promise of universally free inference.

Potential routing order:

1. user-owned legitimate free quota
2. user-owned legitimate provider/API subscription quota
3. approved recurring free-tier provider
4. low-cost approved model
5. Episteck-paid premium fallback within a hard budget

This can reduce Episteck's marginal LLM cost substantially when users connect legitimate
provider credentials, while preserving a reliable paid fallback where product policy
permits it.

Sharing one Episteck upstream account among many Olin users does **not** create new
provider quota; it only allows fair allocation of that shared quota.

## OmniRoute capabilities worth evaluating

Repository review on 2026-09-20 found useful primitives including:

- API-key scoped model and connection policy
- `allowedConnections`
- `allowedQuotas`
- per-key usage/cost tracking
- daily/weekly usage limits
- request/rate controls
- provider quota sharing across API keys
- routing/fallback combos
- OpenAI-compatible client endpoints
- subscription/API/free-provider connection types

These are candidate implementation capabilities, not accepted Olin architecture.

## Privacy and sensitivity boundary

Provider selection is a privacy/security decision before it is a routing decision.

Examples:

```text
ordinary household request
→ broad approved provider set may be acceptable

HEALTH / medical document
→ restricted provider class

FINANCE
→ restricted provider class

highly sensitive family context
→ possibly local or explicitly approved provider only
```

A gateway may choose among providers **only inside the provider/model set already
authorized by Olin policy**.

It must not downgrade privacy in order to find a cheaper or available model.

## User-owned credentials / BYOK

A future user may connect their own legitimate provider account or API key.

Olin should map trusted product identity to an internal inference policy; OmniRoute API
keys/connections remain implementation details.

Conceptually:

```text
Olin Person / Household
        ↓
trusted inference policy
        ↓
gateway API key / allowed connections / quota pools
```

User A must never consume User B's private upstream connection unless an explicit future
shared-household policy allows it.

Provider credentials must remain server-side secrets and must not be exposed to the
model, browser, Knowledge, logs, or MCP arguments.

## Commercial provider-policy requirement

Do not base Olin's commercial model on unofficial consumer-session reuse.

Before a connection type is allowed in commercial Olin, classify it.

Preferred commercial candidates:

- official provider API / BYOK
- officially supported provider OAuth intended for API/agent use
- legitimate published free-tier API
- local/self-hosted model

Require explicit legal/terms review before relying commercially on:

- consumer subscription session proxying
- browser cookies
- unofficial web-session adapters
- provider-specific mechanisms whose terms do not authorize this use

A mechanism being technically supported by OmniRoute does not automatically make it an
approved Olin provider.

## Availability boundary

Olin should not require OmniRoute specifically.

The architecture should depend on an internal inference-gateway contract so OmniRoute can
be replaced later.

Critical deterministic capabilities must not require an LLM at all.

For example:

- device/safety alarms
- authorization
- domain calculations
- simple structured queries

must continue to work if the inference gateway is unavailable.

## Questions for the future gate

Before selecting or deploying OmniRoute, resolve at least:

1. Should usage/budget be accounted primarily per Person, Household, subscription plan,
   or a combination?
2. How are trusted Olin identities mapped to gateway credentials without exposing raw
   gateway keys to clients or models?
3. How are user-owned provider credentials encrypted, rotated, revoked, exported, and
   deleted?
4. Which provider/connection classes are commercially allowed?
5. What sensitivity classes/domains may leave Olin through which provider classes?
6. How are HEALTH, FINANCE, MIND, DOCUMENTS, baby/family context, and generic household
   prompts treated differently?
7. What is the exact free-first / paid-fallback policy?
8. Who pays when user quota is exhausted?
9. What hard spending limits prevent runaway Episteck cost?
10. How are provider outages and quota exhaustion represented to the user?
11. Can household members share an upstream connection, and if so under what explicit
    policy?
12. How are gateway usage logs minimized so sensitive prompt content is not retained
    unnecessarily?
13. What is the failover behavior if the gateway itself is unavailable?
14. Is OmniRoute's security/authz model sufficient as an infrastructure component behind
    Olin's trusted boundary?
15. What operational resources would OmniRoute require on the Nuremberg service node?

## Relationship to existing architecture

This topic is cross-cutting and must not be folded into the Knowledge implementation.

Knowledge determines governed context.
Health/Finance/etc. own their canonical domain truth.
The Olin LLM Policy decides what context may be sent to which provider/model.
The inference gateway performs the allowed routing.

```text
Domain + Knowledge context
        ↓
Olin authorization / sensitivity / task policy
        ↓
bounded ContextBundle / model request
        ↓
Olin LLM Policy
        ↓
Inference Gateway candidate (OmniRoute)
        ↓
approved upstream model
```

B1 Knowledge security-partition and authorization decisions remain authoritative and are
not replaced by gateway API-key permissions.

## Current decision

- OmniRoute: **CANDIDATE — NOT SELECTED**
- Inference Gateway abstraction: **architectural topic to evaluate**
- BYOK/free-first strategy: **promising hypothesis**
- Episteck-paid fallback: **future bounded policy**
- Production deployment: **NOT APPROVED**
- Provider credential onboarding: **NOT APPROVED**
- Commercial consumer-subscription proxying: **NOT APPROVED**
