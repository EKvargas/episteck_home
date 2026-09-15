# ADR-0009: Trusted actor binding via Frappe-issued sessions and a confidential BFF

## Status
Accepted (2026-09-16) — Stage G1.6

## Context

Through G1.5, `actor_person_id` was a **function parameter**. It travelled from the LLM
through the Home MCP tool call into the Frappe business API, and was accepted as the
acting human whenever the caller held an allowlisted machine credential. The consent
engine evaluated it faithfully, but its first argument was never proven.

This made three attacks available: an LLM (or a prompt injection in retrieved content)
could name a different Person; anyone holding a service credential could act as anyone;
and Nutrition trusted an actor string handed to it by an upstream component.

Live inspection of `home.episteck.com` (Frappe v15.99.0, oauthlib 3.3.1) found:

1. A complete OAuth2/OIDC provider already ships (authorize, token, revoke, userinfo,
   discovery, introspection). No external IdP is needed.
2. **PKCE cannot be required.** If a client omits `code_challenge`, `oauth.py`
   `validate_code` falls through to `return True`. The `OAuth Client` DocType has no
   `public_client` and no `require_pkce` field.
3. **A machine credential and a human bearer token cannot share the `Authorization`
   header** — `auth.py` dispatches on the prefix (`bearer` → OAuth, `token`/`basic` →
   API key), so the two paths are mutually exclusive.
4. Two real Users shared an identical `User Social Login.userid` (the OIDC `sub`),
   caused by a child row copied during desk user creation. `generate_hash` uses
   `secrets.token_hex` and is not at fault.

## Decision

**Actor identity is never an input. It is always a server-side derivation of validated
authentication context:**

```
validated authentication -> Frappe User -> Person.linked_user -> actor
```

Neither `actor_person_id` nor `User.name` is ever a caller assertion.

1. **Frappe Home remains the identity authority**, used as a **confidential
   client/BFF** flow only. No Keycloak/Authentik. Direct public/native OIDC is **not
   approved** until PKCE is enforceable.
2. **The BFF runs on the Nuremberg EU node.** It holds the client secret and the user's
   tokens server-side; the browser receives only an opaque `Secure + HttpOnly +
   SameSite` cookie. Placing it in the EU now means the future EU migration (G1.7)
   requires no BFF move.
3. **Dual principal.** Every delegated sensitive request carries `machine_caller`
   (proven by the service API key) and `human_actor` (resolved from the delegated
   session). A service credential never means "this service is Person X". Both are
   retained in audit context.
4. **Delegated context**, not a trusted header. A short-lived, single-audience,
   replay-resistant token carries an **opaque session id** — never a Person id. A plain
   `X-Actor-ID` header is forbidden. Frappe's `auth_hooks` validates it server-side and
   maps the session to a User via a `Home Delegated Session` record, so revocation and
   logout deny the very next call.
5. **Nutrition resolves the actor independently** against Home, and never accepts an
   actor string from the Home Agent or Home MCP.
6. **`Person.linked_user` is unique.** Ambiguity fails closed rather than guessing.
7. **`sub` stays off the critical path.** Internal resolution uses the authenticated
   session. `(issuer, sub)` is remediated before any native OIDC client relies on it.

## Consequences

### Positive
+ Actor substitution is **unrepresentable**, not merely rejected — there is no
  parameter to set, so prompt injection has no channel.
+ A stolen service credential yields no human's data.
+ The confused-deputy gap in Nutrition is closed.
+ Revocation/logout are immediate; no authorization caching is introduced.
+ Consent semantics are untouched: `policy/access.py` keeps its signature, six
  invariants, and 11 pure tests.
+ `auth_hooks` is a clean seam; swapping to an external IdP later replaces one module.

### Negative
− A new component (the BFF) to operate and back up.
− Two credentials per delegated call instead of one.
− Direct native-mobile OIDC is blocked until upstream can enforce PKCE; mobile ships
  against the BFF in the interim.
− The Home Control Plane is still US-hosted while the BFF is EU. This is acceptable
  only while all Home data is synthetic, and is why G1.7 exists.

## Alternatives considered

**Frappe API keys per human** — rejected: the agent would hold every family member's
long-lived master credential, which is strictly worse than a service credential.

**External IdP (Keycloak/Authentik) now** — deferred, not rejected: no concrete blocker
exists for the BFF flow, and it would add a stateful service to a node at ~1.4 GB idle
of 2.8 GB while still requiring the same session→Person mapping that is the actual
deliverable.

**Custom home-issued JWTs as the primary credential** — rejected: rolling our own
crypto/rotation/revocation. The delegation token is deliberately narrow — short-lived,
single-audience, carrying no identity claim — and sits behind Frappe's own
authentication rather than replacing it.

**Forwarding the user's OAuth bearer token to services** — rejected: it hands a
full-scope user token to two services and whatever they log.
