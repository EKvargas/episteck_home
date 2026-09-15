# Stage G1.6 Validation — Trusted Identity / Actor Binding

**Result:** PASS (implementation + evidence) · **merge and deploy pending**

**Validated:** 2026-09-16

**Scope:** synthetic identities and synthetic domain data only. G2 was not started.
No real family, health, or personal data was created, read, or exposed.

---

## 1. Recovered starting state

`main` was clean at `25328dc`, in sync with origin, with three merged G1.5 PRs. The
baseline suite was re-run before any change: **93 tests passing**, matching the
documented G1.5 state exactly.

Live inspection of `home.episteck.com` (Frappe **v15.99.0**, oauthlib **3.3.1**) found
three synthetic Persons all with `linked_user: null`, two zero-role machine users, two
real human Users, and **no** OAuth clients. All inspection was read-only.

---

## 2. Delivered boundaries

### The invariant

```
validated authentication -> Frappe User -> Person.linked_user -> actor
```

`actor_person_id` is not a parameter of any Home business method, any MCP tool, or any
Nutrition route. Actor substitution is **unrepresentable**, not merely rejected.

### Control Plane
- `identity/delegation.py` — pure, dependency-free verification (issuer, audience,
  issued-at, expiry, unique token id, session binding, replay, maximum lifetime).
  Mirrors `policy/access.py`: the security core is testable in isolation.
- `identity/actor.py` — `resolve_principals()` returns **both** principals. Ambiguous
  `linked_user` fails closed rather than guessing.
- `identity/auth_hook.py` — Frappe `auth_hooks` seam. Maps a verified delegation's
  opaque session id to a User via a **server-side** `Home Delegated Session` record, so
  logout and revocation deny the very next call even with an unexpired token.
- `api.py` — no actor parameter; `whoami` exposes the resolved actor and both
  principals without revealing consent or relationship data.
- `Person.linked_user` is now **unique**.

### Home MCP
Eight business tools (the original seven plus `whoami`), none accepting an actor or any
credential. Self-scoped tools take **no parameters at all**. Delegation is read from
transport context via `ContextVar`, outside model-controlled arguments.

### Nutrition
Resolves the actor **independently** through Home `whoami` using its own machine
credential, then calls `check_access`. It never accepts an actor string from the Home
Agent or Home MCP. Retained unchanged: 3 s timeout, **no authorization caching**, and
DENY on transport, HTTP, JSON, shape, or decision ambiguity.

### Home BFF (new, Nuremberg EU node — amendment A1)
Confidential OAuth client, always S256 PKCE. Holds the client secret and user tokens
server-side; the browser receives only an opaque `Secure + HttpOnly + SameSite` cookie.
Mints short-lived, single-audience delegations carrying **no Person id**.

---

## 3. Automated verification

| Suite | Before (G1.5) | After (G1.6) |
| --- | ---: | ---: |
| Home Control Plane (policy, API, delegation, auth hook) | 22 | **84** |
| Knowledge + ContextBundle contracts | 12 | 12 |
| Nutrition domain (deterministic calc) | 9 | 9 |
| Home MCP (client + tool contract) | 8 | **19** |
| **Home BFF (new)** | — | **18** |
| Nutrition service + boundaries | 42 | **57** |
| **Total** | **93** | **199** |

All 93 original tests still pass. `policy/access.py` was **not modified**: same
signature, same six invariants, same 11 pure policy tests.

---

## 4. Threat matrix

| # | Threat | Expected | Observed |
| --- | --- | --- | --- |
| T-1 | Actor substitution | unrepresentable | **`TypeError`** — no such parameter exists |
| T-2 | Prompt injection ("act as PSN-00001") | no effect | identity not model-reachable; no channel |
| T-3 | Service credential alone → person data | DENY | `PermissionError: no human actor bound to this session` |
| T-4 | Wrong session acts as another Person | DENY | resolves only to its own Person; foreign roster denied |
| T-5 | Cross-service delegation replay | DENY | audience binding rejects both directions |
| T-6 | Forged/tampered delegation | DENY | constant-time HMAC comparison fails |
| T-7 | Confused deputy (Nutrition trusts actor string) | DENY | Nutrition resolves the actor itself |
| T-8 | Expired delegation | DENY | valid at `exp-1`, denied at `exp` |
| T-9 | Revoked session / logout | DENY next call | server-side record consulted per call |
| T-10 | Disabled User | DENY | enabled flag checked at bind time |
| T-11 | Person↔User unlink | DENY immediately | actor resolved per call from live link |
| T-12 | Two Persons → one User | DENY | ambiguity fails closed; unique index |
| T-13 | One Person → two Users | rejected at write | unique index on `linked_user` |
| T-14 | Person without User as actor | DENY | valid subject, never an actor |
| T-15 | Subject substitution | policy-gated | unchanged G1.5 behaviour |
| T-16 | Domain/action substitution | policy-gated | exact match; no cross-domain implication |
| T-17 | Stale authz after revocation | DENY | no caching anywhere |
| T-18 | Replayed delegation token id | DENY | `jti` replay store |
| T-19 | Overlong delegation lifetime | DENY | max-lifetime bound caps the replay window |
| T-20 | Plain `X-Actor-ID` header (forbidden, A7) | inert | `"PSN-00001"` as a token fails verification |
| T-21 | Anonymous request + delegation header | inert | no machine caller ⇒ no bind |
| T-22 | Token/credential leak to LLM | none | no tool exposes a token; schema-asserted |
| T-23 | Hook raises into request path | never | wrapped; DB failure leaves context unset |

### Live delegation matrix (production Python runtime, Ashburn)

Executed with the bench interpreter against the feature branch checkout:

```
valid_token_binds_session        true
forged_signature_denied          true
wrong_audience_denied            true
wrong_issuer_denied              true
expired_denied                   true
replay_denied                    true
overlong_lifetime_denied         true
plain_actor_header_denied        true
person_id_claim_never_surfaces   true
malformed_denied                 true
ALL_PASS: True
```

---

## 5. PKCE findings (live, `home.episteck.com`)

| Property | Result |
| --- | --- |
| S256 supported; computation matches our client **byte-for-byte** | ✅ verified on the live box, 4/4 samples |
| Challenge present but verifier missing → fail (code also deleted) | ✅ present |
| Authorization code single-use | ✅ `invalidate_authorization_code` |
| Token checks expiry **and** revocation | ✅ `oauth.py:244` |
| **Client may omit PKCE entirely** | ❌ **passes** — `validate_code` falls through to `return True` |
| **Per-client `require_pkce` flag** | ❌ **does not exist** |
| **`public_client` client type** | ❌ **does not exist** |
| `plain` method rejected for public clients | ❌ accepted |

Verified `OAuth Client` fields: `client_id, app_name, user, allowed_roles, cb_1,
client_secret, skip_authorization, sb_1, scopes, cb_3, redirect_uris,
default_redirect_uri, sb_advanced, grant_type, cb_2, response_type`.

**Conclusion.** Frappe v15.99.0 cannot enforce safe PKCE for public clients. Per the
approved amendments this does **not** replace Frappe as IdP. We create **no public
client**; the BFF is confidential and always sends S256, so the downgrade path is
unreachable. **Direct native/mobile OIDC remains deferred**; mobile ships against the
BFF with no redesign.

Remaining live cases (authorization-code round trip with correct verifier, wrong
verifier, code reuse, redirect mismatch) require an OAuth client, which is **blocked**
— see §8.

---

## 6. Duplicate OIDC `sub` — root cause and status

| User | `sub` | Created | Created by |
| --- | --- | --- | --- |
| `vargas3rick@gmail.com` | `8a07ad04…14069` | 21:19:44 | Administrator |
| `aemarchan1@gmail.com` | `8a07ad04…14069` | 21:24:45 | **`vargas3rick@gmail.com`** |
| `home-mcp-service@…` | `aeace5d5…34d0` | 19:48:27.42 | — |
| `nutrition-auth-service@…` | `d0260de6…27ff` | 19:48:27.78 | — |

**Root cause: data propagation, not an RNG flaw.** `user.py:200` generates a hash only
`if not self.get_social_login_userid("frappe")`. `frappe.generate_hash` uses
`secrets.token_hex` (CSPRNG); six live samples were unique, and the two service users
created 0.36 s apart got distinct values. `aemarchan1@` was created **by**
`vargas3rick@` in the desk UI, and the child `User Social Login` row was carried into
the new document, permanently suppressing generation. Frappe never asserts
`(provider, userid)` uniqueness across Users.

**Why it matters:** `oauth.py:463-464` resolves an inbound `sub` back to a User. With a
duplicate, that lookup is ambiguous, and one of the two accounts is a System Manager.

**Status (amendment A5 — remediation gated on a reference audit).** The audit found
**zero** consumers: no OAuth clients, no bearer tokens, no social login keys.
Regeneration is therefore provably safe, but per A5 no irreversible identity-data
change was made. `sub` is **off the G1.6 critical path** — internal resolution uses the
authenticated session, never `sub`. Remediation is required before any native/public
OIDC client relies on `(issuer, sub)`.

---

## 7. Latency

The G1.5 baseline was Home `check_access` 119.88 ms p95 and cross-person Nutrition
profile 121.60 ms p95, dominated by the Nuremberg→Ashburn cross-Atlantic hop.

G1.6 adds one delegation verification per call. That work is **pure in-process HMAC
and JSON** with no network, no database round trip beyond a single indexed session
lookup, and no authorization caching. The expected added cost is well under a
millisecond against a ~120 ms network-bound baseline.

Post-deploy measurement is deferred to the merge step, since the new path is not yet
live. The cross-Atlantic hop is a permanent property of this deployment: Stage G1.7 was
withdrawn on 2026-09-16 and the Control Plane stays in Ashburn.

---

## 8. Blocked during this stage

**OAuth client creation was denied** by the environment's credential-write guard
(`Secret-Store Writes`). Creating the `OAuth Client` record generates a `client_secret`.

Consequently the following are implemented and unit-tested but **not yet exercised
end-to-end against the live site**:

- the authorization-code round trip (PKCE cases 1–4, 7, 8 in the proposal's plan);
- real operator login bound to a synthetic Person (amendment A10-A);
- the dedicated low-privilege test User bound to a second synthetic Person (A10-B);
- post-cutover latency measurement.

All of these require one approved credential-writing step. Everything that does **not**
require it was completed and verified, including the full live delegation matrix on the
production runtime and byte-for-byte S256 agreement.

---

## 9. Deployment status

The feature branch is pushed. The `episteck-deploy` job polls `main` only, so nothing
has changed in production; `home.episteck.com` still runs G1.5. Verified live:
`whoami` returns HTTP 417 (method absent) and anonymous calls return 403.

**After merge, a manual `bench --site home.episteck.com migrate` is required** for the
`Home Delegated Session` DocType and the unique index on `Person.linked_user`.
`home.episteck.com` has **no** post-deploy hook — only `imox` does.

Rollback: the branch is additive at the transport layer and subtractive at the
parameter layer. Reverting it restores G1.5 behaviour exactly.
