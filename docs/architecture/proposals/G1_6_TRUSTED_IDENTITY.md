# Stage G1.6 — Trusted Identity / Actor Binding (PROPOSAL — not implemented)

**Status:** **APPROVED** — implementation authorized with the amendments in §0
**Date:** 2026-09-15 · **Revision:** 4 (2026-09-16 data-residency correction: A11 superseded, G1.7 withdrawn; supersedes revisions 1–3)
**Blocks:** G2 (real family onboarding)
**Repo state at authoring:** `main` @ `25328dc`, clean, in sync with origin

---

## 0. Approved amendments (binding)

The architecture review was approved with the following final decisions. Where these
conflict with anything later in this document, **these win**.

| # | Decision | Effect on this document |
| --- | --- | --- |
| A1 | **BFF lives on the Nuremberg EU node**, not Ashburn | Resolves §22 Q2. Frappe stays on Ashburn — for G1.6 and, per the 2026-09-16 correction, for real personal/family data as well. No BFF migration required. |
| A2 | Browser holds **no** Frappe tokens; opaque **Secure + HttpOnly + SameSite** cookie only; OAuth state/tokens stay server-side | Tightens §4.4 / §6 |
| A3 | Frappe remains identity authority. **Confidential-client/BFF flow only.** No Keycloak/Authentik. Native/public OIDC **not approved** | Confirms §4.2, §11 |
| A4 | Trusted actor invariant: neither `actor_person_id` **nor** `User.name` is ever a caller assertion | Confirms §4.1 |
| A5 | **Do not depend on OIDC `sub`** for the G1.6 actor path. Prepare remediation + uniqueness invariant, but **no irreversible identity-data change** without proving no downstream references | **Changes §18 Q3:** regeneration is now gated on a reference audit |
| A6 | **Dual-principal model**: every delegated sensitive request carries `machine_caller` **and** `human_actor`; audit/event context must retain both | **New requirement** — extends §7 |
| A7 | Delegated context must consider issuer, audience, issued-at, expiry, unique id, session binding, replay prevention, revocation. **A plain `X-Actor-ID` header is forbidden** | Tightens §6.2 |
| A8 | Home MCP: remove actor from model-controlled schemas; **subject may remain** a parameter | Confirms §6/§10 target contract |
| A9 | Nutrition resolves the actor independently; repository access only after literal ALLOW | Confirms §8 |
| A10 | G1.6 test identities: **(A)** operator's real account → synthetic Person, **(B)** one dedicated **low-privilege** test User → another synthetic Person | Confirms §14 incl. my recommendation |
| A11 | ~~EU residency is a new hard G2 blocker; create Stage G1.7~~ — **SUPERSEDED 2026-09-16.** `home.episteck.com` is the operator's own personal/family deployment; keeping the Home Control Plane in Ashburn/US is accepted. **No G1.7 migration requirement.** EU residency is a **future commercialization** concern | **Revised** — see §16 and §23 |
| A12 | Repo `EKvargas/episteck_home` only; branch → tests → PR → main; no secrets in Git; no real data; no G2; no Knowledge runtime | Implementation rules |

### Amendment detail: dual-principal model (A6)

```
machine_caller = svc-nutrition        human_actor = trusted Person
   proves: "this service may call      proves: nothing about which human
            this internal interface"            — resolved server-side only
```

A service credential never means "this service *is* Person X." Both principals are
resolved separately and both are retained in audit context.

### Amendment detail: `sub` remediation is now gated (A5)

Revision 2 recommended regenerating both `sub` values during G1.6. **Amended:** first
prove there are no downstream references, then remediate. Since nothing in the approved
G1.6 path consumes `sub`, remediation is *prepared and documented* in G1.6 and the
uniqueness invariant is *asserted*, but the data change itself is not forced.

---

> Revision 2 corrects revision 1 after live investigation of the Frappe v15.99.0
> deployment. Three findings changed the design materially: the root cause of the
> duplicate OIDC `sub`, the absence of any PKCE enforcement capability, and the fact
> that a machine credential and a human token **cannot share** the `Authorization`
> header. See §3, §11, and §6.

---

## 1. Problem statement

The authorization engine is correct. Its **first argument is not trustworthy**.

`can_access(actor, subject, domain, action)` is evaluated faithfully, but
`actor_person_id` arrives as a **function parameter** chosen by the LLM:

```
home-agent (LLM) --actor_person_id="PSN-00002"--> Home MCP --> Frappe _actor()
                    ^^^^^^^^^^^^^^^^^^^^^^^^^
                    model-chosen string = claimed identity
```

All seven tools in `services/home-mcp/home_mcp/server.py` declare
`actor_person_id: str` as their first argument. In
`apps/episteck_home/episteck_home/api.py`, `_actor()` ends:

```python
if user not in _service_users() or not actor_person_id:
    frappe.throw("actor binding required", frappe.PermissionError)
if not frappe.db.exists("Person", actor_person_id):
    _not_found("Person")
return actor_person_id          # <-- asserted, never proven
```

The machine credential authenticates **the service**, not the human. Anyone holding
that credential — or any prompt that persuades the model to emit a different string —
acts as any Person. The missing boundary is precisely: *who proves this authenticated
session belongs to that actor?*

### What is already correct and must be preserved

```python
linked_person = frappe.db.get_value("Person", {"linked_user": user}, "name")
if linked_person:
    if actor_person_id and actor_person_id != linked_person:
        frappe.throw("actor mismatch", frappe.PermissionError)
    return linked_person
```

A session-authenticated human is already bound to exactly one Person. **G1.6 does not
invent this. It makes it the only path and deletes the asserted-string path.**

---

## 2. Verified live state

Read-only inspection of `home.episteck.com`, Frappe **v15.99.0**, oauthlib **3.3.1**:

| Fact | Value | Impact |
| --- | --- | --- |
| Persons | PSN-00001/2/3, **all `linked_user: null`** | Human path has never executed in production |
| Machine users | `home-mcp-service@`, `nutrition-auth-service@` — **0 roles**, API keys set | Least privilege already correct |
| Human Users | `vargas3rick@gmail.com` (System Manager +42 roles), `aemarchan1@gmail.com` (Desk User) | Real logins exist, unlinked |
| OAuth Clients | **none** | Greenfield |
| Consent Grants | CG-00012 ACTIVE, CG-00011 REVOKED | Unchanged by G1.6 |
| `auth_hooks` | supported, **unused by any installed app** | Clean extension point (§6.4) |

Confirmed OIDC surface: `authorize`, `get_token`, `revoke_token`, `openid_profile`,
`openid_configuration`, `introspect_token`.

---

## 3. The duplicate `sub` — root cause found

### Evidence

| User | `sub` (User Social Login.userid) | Created | Created by |
| --- | --- | --- | --- |
| `vargas3rick@gmail.com` | `8a07ad04425bcd1c064e3fe872475bfddf14069` | 21:19:44 | Administrator |
| `aemarchan1@gmail.com` | `8a07ad04425bcd1c064e3fe872475bfddf14069` | 21:24:45 | **`vargas3rick@gmail.com`** |
| `home-mcp-service@…` | `aeace5d58923f096c8370e807f14b8b089134d0` | 19:48:27.42 | — |
| `nutrition-auth-service@…` | `d0260de6438973f94934ef8b99053c04f5227ff` | 19:48:27.78 | — |

### Why it happened (answers §5.1–§5.4)

**1. How Frappe constructs `sub`** — `user.py:200`:

```python
if (self.name not in ["Administrator", "Guest"]) and (not self.get_social_login_userid("frappe")):
    self.set_social_login_userid("frappe", frappe.generate_hash(length=39))
```

**2. It is not an RNG flaw.** `frappe.generate_hash` uses `secrets.token_hex`
(CSPRNG). Six live samples were generated on this box: all unique. The two service
users, created **0.36 s apart**, received distinct values.

**3. It is a data-propagation bug.** The guard only generates a hash
`if not self.get_social_login_userid("frappe")`. `aemarchan1@` was created **by**
`vargas3rick@` in the desk UI five minutes later, and the child `User Social Login`
row was carried into the new document — most plausibly a duplicate/copy-fields action.
Because a value was already present, the generator was permanently suppressed.

**4. Configuration, data, or upstream?** **Data**, caused by an **upstream robustness
gap**: Frappe never asserts uniqueness of `(provider, userid)` across Users, so a
copied child row silently produces two Users with one identity.

### Why this is genuinely dangerous

`oauth.py:463-464` resolves an inbound `sub` **back to a User**:

```python
frappe.get_all("User Social Login", {"userid": payload.get("sub"), "provider": "frappe"}, ...)
```

With a duplicate, that lookup is ambiguous. Any external relying party keying on
`sub` would treat Erick and Ana as **the same identity** — a live actor-substitution
hole with a System Manager on one side.

### Recommendation (answers §5.5–§5.6)

- **Does it block the web/BFF flow? No.** The BFF never uses `sub`. Identity is
  resolved server-side from `frappe.session.user` (`User.name`), which is unique by
  primary key. This is the reason revision 2 keeps `sub` off the critical path.
- **Does it block native/direct OIDC? Yes** — and that path is deferred anyway (§11).
- **Remediation (G1.6, reversible):** regenerate the `frappe` social-login `userid` for
  **both** users with `frappe.generate_hash(length=39)`; add a startup/migration
  assertion that `(provider='frappe', userid)` is unique across Users, failing loudly.
  Nothing currently consumes `sub`, so regeneration breaks no live integration. Record
  it in the validation evidence. Do **not** perform it until approval.

> Per §17, this is a **correction** to revision 1: revision 1 said "bind on `User.name`,
> never on `sub`." That conflated two things. The correct statement is: **internal
> resolution uses the authenticated `frappe.session.user`; `sub` is never accepted from
> a caller; and `(issuer, sub)` is remediated so it can become the stable external
> identity tuple when native OIDC is unblocked.**

---

## 4. Recommended architecture

### 4.1 The invariant

> **`actor_person_id` is never an input. It is always a server-side derivation of an
> authenticated session.** The caller submits neither `actor_person_id` **nor**
> `User.name`. Frappe derives the user from validated authentication context.

```
UNTRUSTED                         TRUSTED
─────────────────────             ─────────────────────────────
user text                         validated authentication
LLM output                  ==>   → authenticated Frappe User
tool arguments                    → Person.linked_user
client JSON                       → canonical Person
caller headers                    → actor_person_id
```

### 4.2 Decision: Frappe Home as identity authority — **YES**, with a BFF

Confirmed suitable for the **confidential-client/BFF** pattern. **Not** currently
suitable as a direct IdP for public native clients (§11). No Keycloak/Authentik —
the concrete blocker required by §3 of the brief does not exist for the BFF flow.

### 4.3 Trust boundaries

```
T0  LLM / prompt / retrieved content      ← never carries identity
T1  agent process (home-agent)            ← holds no human credential
T2  service credential (MCP, Nutrition)   ← proves SERVICE, never a human
T3  Home BFF / gateway                    ← holds human session, validates it
T4  Frappe Home Control Plane             ← SOLE identity authority
```

Rule: **identity descends only from T4.** Anything T0–T2 says about *who the human is*
is a claim, never a fact.

### 4.4 Component flow

```mermaid
sequenceDiagram
    participant H as Human (web/tablet/mobile/voice)
    participant BFF as Home BFF (confidential client)
    participant F as home.episteck.com (Frappe = IdP + Control Plane)
    participant A as home-agent (LLM)
    participant M as Home MCP
    participant N as svc-nutrition

    H->>BFF: log in
    BFF->>F: OAuth2 code + PKCE S256 (client_secret held server-side)
    F-->>BFF: access token (short TTL) + refresh
    Note over BFF: token stored server-side; browser gets an opaque cookie
    H->>BFF: "what can I see for Ana?"
    BFF->>A: turn + opaque session ref (NOT the token, NOT in the prompt)
    A->>M: tool call — NO actor_person_id
    M->>BFF: resolve delegated context for session ref
    BFF-->>M: short-lived scoped delegation token
    M->>F: business API, machine key + delegation token
    F->>F: auth_hook validates delegation → sets session user
    F->>F: _resolve_actor(): User → Person.linked_user  ← THE BINDING
    F->>F: can_access(actor, subject, domain, action)
    F-->>M: decision / data
    M-->>A: business result only
    A->>N: nutrition tool — NO actor_person_id
    N->>F: check_access with its OWN machine key + the delegation token
    F->>F: resolves the actor INDEPENDENTLY
    F-->>N: allow / deny
    N->>N: repository access only on allow
```

Two properties are load-bearing. The agent never holds a bearer token or a Person id.
And Nutrition re-resolves the actor **itself** — it never trusts an actor string.

### 4.5 Server-side actor resolution (the heart of G1.6)

`_actor()` is replaced by a resolver with exactly two outcomes:

```python
def _resolve_actor() -> str:
    """Actor identity is derived, never asserted. Fail closed."""
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw("authentication required", frappe.PermissionError)

    # Exactly one Person may be linked to this User (uniqueness enforced).
    linked = frappe.db.get_value("Person", {"linked_user": user}, "name")
    if linked:
        return linked

    # A machine credential is a SERVICE identity, never a human actor.
    frappe.throw("no human actor bound to this session", frappe.PermissionError)
```

Deleted: the `actor_person_id` parameter, the service-user path to *human* action, and
`frappe.db.exists("Person", actor_person_id)`. **No branch remains in which a
caller-supplied string becomes an identity.**

**Why `frappe.session.user` is authoritative** (verified in `auth.py`): a validated
Bearer token calls `frappe.set_user(...)` from the `OAuth Bearer Token` record
(`auth.py:665`); `validate_auth` raises `AuthenticationError` if an `Authorization`
header fails to resolve (`auth.py:626-628`). Token validity checks both expiry and
revocation (`oauth.py:244`). We therefore read the **resolved session** and never call
the `allow_guest=True` `introspect_token`, which stays unexposed (closes T-9).

---

## 5. Consent policy: unchanged

`policy/access.py` is **not modified**. Same signature, same six invariants, same 11
pure tests. G1.6 changes only *how the first argument is obtained*. This keeps the
blast radius small and preserves all 93 existing tests.

---

## 6. Trusted-context transport (§6, §8, §9)

### 6.1 The constraint that shapes this

Verified in `auth.py:619-621`: `validate_oauth` and `validate_auth_via_api_keys` both
run against the **same** `Authorization` header and are mutually exclusive by prefix
(`bearer` → OAuth; `token`/`basic` → API key). **A machine credential and a human
bearer token cannot both travel in `Authorization`.** Revision 1 implicitly assumed
they could. They cannot.

### 6.2 Consequence: a second, server-validated channel

| Leg | Machine identity | Human context |
| --- | --- | --- |
| MCP/Nutrition → Frappe | `Authorization: token <key>:<secret>` | `X-Episteck-Delegation: <short-lived token>` |

The delegation token is **not** a caller assertion of identity. It is an opaque,
server-issued, single-audience, short-TTL credential minted by the BFF and validated
server-side against its issuing record. It carries no Person id that the client could
alter; the actor is looked up from the validated record.

### 6.3 Why not simply forward the user's OAuth bearer token?

Forwarding is simpler but weaker: it hands a full-scope user token to two services and
to whatever they log. The delegation token is audience-scoped, far shorter-lived, and
independently revocable. **Recommendation: delegation token.** If reviewers prefer
fewer moving parts, forwarding the bearer token is acceptable *only* if the token never
enters agent context and both services treat it as a secret (§8).

### 6.4 Implementation seam

`auth_hooks` (verified supported, currently unused) validates the delegation header
**before** any business method runs, then calls `frappe.set_user(...)`. The business
API therefore reads only `frappe.session.user` and needs no knowledge of transport.
Swapping to an external IdP later replaces the hook, not the API.

### 6.5 Token secrecy (§8) — how it holds with Hermes + FastMCP

| Boundary | Control |
| --- | --- |
| LLM prompt/context | Agent receives an **opaque session ref**, never a token |
| MCP tool parameters | No tool has a token or actor parameter — schema-asserted in tests |
| MCP transport | Delegation token travels as transport metadata resolved by the BFF, outside model-chosen arguments |
| Logs | Explicit redaction; tokens never logged by MCP, Nutrition, or Frappe app code |
| Git / env output | Unchanged rule: secrets never in Git; service secrets in `600` files |

The model sees **business concepts only**: subjects, domains, actions, decisions.

---

## 7. Service identity vs human identity (§9)

| Call shape | Credential | Actor | May access |
| --- | --- | --- | --- |
| **On-behalf-of a human** | machine key **+** delegation token | derived server-side | what that human may access |
| **Pure service** | machine key only | **none** | health, schema/reference reads. **No person data, ever.** |

A machine credential alone yields `PermissionError`. Stealing the Home MCP key buys an
attacker **no human's data** (closes T-3). This is the precise separation §9 requires:
the service is authorized to *ask*, never to *be* Erick or Ana.

---

## 8. Nutrition independent actor resolution (§7)

Preserved and strengthened. Today Nutrition asks Home before repository access; that
defense remains. The change is that Nutrition stops receiving an actor **string**:

```
authenticated delegation context
   → Nutrition sends its OWN machine key + the delegation token
   → Home resolves the trusted actor independently
   → check_access(trusted actor, subject, NUTRITION, action)
   → ALLOW / DENY  → repository access
```

Nutrition never accepts "trust me, the actor is PSN-00002" from Home MCP or the agent.
Two independent resolutions of the same delegation context must agree; neither service
can vouch for a human to the other. This closes the confused-deputy risk (T-7).

Retained unchanged: 3 s timeout, **no authorization caching**, and DENY on transport,
HTTP, JSON, shape, or decision ambiguity.

---

## 9. Person without User (§13)

Preserved exactly:

- A Person **may** have `linked_user = null` — infants, elderly relatives, dependents.
  They are fully valid **subjects** of consent and care.
- Such a Person can **never be an actor**: with no session, `_resolve_actor()` cannot
  return them. Care flows through a caregiver's own session plus an explicit
  `ConsentGrant` (closes T-10).
- **No Person is forced to have a User.** Person ≠ User remains a core model property.

### Binding integrity

- **Unique index on `Person.linked_user`** — one User maps to at most one Person.
- **One Person, multiple Users:** rejected; the unique constraint makes it
  unrepresentable.
- **Multiple Persons, one User:** rejected by the same constraint.
- A migration assertion fails loudly on any pre-existing violation.
- Creating or changing `linked_user` is **administrative**: not in the business API,
  not available to machine users, not reachable by the agent.

---

## 10. Threat model (§12)

Fail closed everywhere. Every row has threat → control → test → expected failure.

| # | Threat | Control | Test | Expected failure mode |
| --- | --- | --- | --- | --- |
| T-1 | **Actor substitution** | No actor parameter exists anywhere | Schema assertion + call attempt | **Unrepresentable** — cannot be expressed |
| T-2 | **Agent prompt injection** ("act as PSN-00001") | Identity not model-reachable | Injection corpus vs. live agent | No effect; actor unchanged |
| T-3 | **Service credential misuse** | Machine key ≠ human actor | Machine key alone → person data | `PermissionError`, 403 |
| T-4 | **Wrong-session usage** | Per-call resolution, no ambient actor | User A's context vs. B's subject | DENY unless explicit grant |
| T-5 | **Token replay** (different client/audience) | Audience-scoped, single-audience delegation | Replay at the other service | DENY |
| T-6 | **Token theft** | Short TTL, server-side revocable, never in LLM context | Steal + reuse after revoke | DENY |
| T-7 | **Expired token** | `now < expiration_time` (`oauth.py:244`) | Expire then call | DENY |
| T-8 | **Revoked token / logout** | `status != "Revoked"`; no auth caching | Revoke, call immediately | DENY on the **next** call |
| T-9 | **Person↔User unlink/relink** | Actor resolved per call from live link | Unlink mid-session | DENY immediately |
| T-10 | **Disabled User** | Session resolution fails | `enabled = 0`, then call | DENY |
| T-11 | **Disabled/absent Person** | No link → no actor | Person removed/unlinked | DENY |
| T-12 | **Two Persons → one User** | Unique index on `linked_user` | Attempt second link | Rejected at write time |
| T-13 | **One Person → two Users** | Same unique index | Attempt second link | Rejected at write time |
| T-14 | **Subject substitution** | Subject still gated by `can_access` | Allowed actor, foreign subject | DENY (unchanged G1.5) |
| T-15 | **Domain/action substitution** | Exact match; no implication across domains | NUTRITION grant → MIND/UPDATE | DENY (unchanged G1.5) |
| T-16 | **Stale authz after revocation** | No caching; re-check per call | Revoke grant, immediate call | DENY on next call |
| T-17 | **Duplicate `sub`** | `sub` off the critical path; uniqueness assertion | Two users, one `sub` | Assertion fails loudly |
| T-18 | **Unauthenticated introspection** | `introspect_token` never exposed | Route reachability probe | Not reachable |
| T-19 | **Token leak into LLM/logs** | Opaque session ref + redaction | Prompt/context/log inspection | No token material present |
| T-20 | **Mixed-trust deployment** | Atomic cutover (§13) | Old actor parameter post-cutover | Rejected |

---

## 11. PKCE analysis — **blocking finding** (§11)

### What the code actually does

`oauth.py:88-92` stores a challenge **only if the client sends one**:

```python
if request.code_challenge and request.code_challenge_method:
    oac.code_challenge = request.code_challenge
    oac.code_challenge_method = request.code_challenge_method.lower()
```

`oauth.py:158-180` validates it — correctly — **only if one was stored**:

```python
if code_challenge and not request.code_verifier:
    ... delete code ...; return False          # good: challenge without verifier fails
if code_challenge_method == "s256":  ...       # correct S256 comparison
elif code_challenge_method == "plain": ...     # plain accepted
return True                                    # ← NO challenge stored → PASSES
```

### Findings

| Property | Result |
| --- | --- |
| S256 supported and correctly computed | ✅ yes |
| Challenge present but verifier missing → fail | ✅ yes (code also deleted) |
| Authorization code single-use | ✅ yes (`invalidate_authorization_code`, `oauth.py:232-236`) |
| Token checks expiry **and** revocation | ✅ yes (`oauth.py:244`) |
| **Client may omit PKCE entirely** | ❌ **passes** (line 180) |
| **Per-client "require PKCE" flag** | ❌ **does not exist** |
| **`public_client` / no-secret client type** | ❌ **does not exist** in the `OAuth Client` doctype |
| `plain` method rejected for public clients | ❌ accepted |

Verified `OAuth Client` fields: `client_id, app_name, user, allowed_roles, cb_1,
client_secret, skip_authorization, sb_1, scopes, cb_3, redirect_uris,
default_redirect_uri, sb_advanced, grant_type, cb_2, response_type`. There is **no**
`public_client` and **no** `require_pkce`.

### Conclusion and decision

Frappe v15.99.0 **cannot enforce safe PKCE for public clients**. PKCE is opt-in per
request, so a downgrade attack (omit `code_challenge`) is available to anyone who can
reach the authorize endpoint with a client id.

Per §11's explicit instruction, this does **not** replace Frappe as IdP. Instead:

- **Adopt now:** web/PWA/tablet via **Backend-for-Frontend, confidential client**.
  The `client_secret` stays server-side, the code never reaches a browser, and the BFF
  **always** sends S256 PKCE as defense in depth. The downgrade is unreachable because
  no public client exists.
- **Defer:** direct native-mobile OIDC remains **blocked** until either upstream gains
  `require_pkce` + public-client support, or we add an enforcing shim. Mobile ships
  against the BFF in the interim — identical to the web path, no redesign.

### PKCE live test plan (run against this exact deployment)

| # | Case | Expected | Gate |
| --- | --- | --- | --- |
| 1 | Code + S256 PKCE, correct verifier | **succeed** | Must pass |
| 2 | Wrong `code_verifier` | **fail** | Must pass |
| 3 | Reused authorization code | **fail** | Must pass |
| 4 | Challenge sent, verifier omitted | **fail** | Must pass |
| 5 | Public client, **no** `code_challenge` | should fail | **Expected to FAIL the gate** — documents the limitation |
| 6 | `plain` `code_challenge_method` | should fail | **Expected to FAIL the gate** — documents the limitation |
| 7 | Redirect URI mismatch | fail | Must pass |
| 8 | Expired code | fail | Must pass |

Cases 5 and 6 are expected to fail and are recorded as **known upstream limitations**
justifying the BFF. They are the evidence for deferring native OIDC, not a reason to
abandon Frappe.

---

## 12. Client compatibility (§15)

| Client | Mechanism | Status |
| --- | --- | --- |
| **Home web UI / PWA** | BFF confidential client, S256 PKCE, opaque session cookie | Design target |
| **Tablet Home Hub** | Same as web + short idle timeout (shared device) | Design target |
| **Home Agent** | Opaque session ref; never a token, never a Person id | Design target |
| **Future mobile** | Ships against the **same BFF**; direct native OIDC deferred (§11) | No redesign needed |
| **Future voice** | **Device/session authentication** (device enrolled + bound to a session) is the authenticator. **Speaker identification is a convenience signal only and is NEVER sufficient authentication for sensitive actions.** Recommend first voice scope = read-only, low-sensitivity domains | Deferred, unblocked |
| **Multiple family members** | Each has their own User → own Person; concurrent sessions isolated | Design target |
| **Service-to-service** | Machine key only, no human actor | Design target |

Not overbuilt: only the BFF and the Frappe-side binding are built in G1.6. The others
are kept viable, not implemented.

---

## 13. Cutover strategy (§14)

**Agreed:** there must never be a deployed mixed-trust state. Revision 1 said "ship
Tasks 1–3 together," which is right but insufficient as a *sequence*. Refined:

### Phases

| Phase | Action | Deployed? | Gate to proceed |
| --- | --- | --- | --- |
| **P0** | Add trusted path **alongside** the old one, behind `home_trusted_actor_binding` (default **off**). Old synthetic path untouched. | Yes, inert | All 93 tests still green |
| **P1** | Prove session → User → Person on a real login bound to a **synthetic** Person (§14) | Yes, inert | Real login resolves the correct Person |
| **P2** | Prove actor substitution impossible on the new path | Yes, inert | Full §10 matrix passes against the new path |
| **P3** | Prove Nutrition resolves the actor independently | Yes, inert | Two independent resolutions agree; string-injection attempt denied |
| **P4** | **Atomic switch:** flag on + MCP/domain contracts drop `actor_person_id` in one release | Yes, live | All of P1–P3 green |
| **P5** | Delete the caller-supplied path entirely; assert the old shape is rejected | Yes, live | Old-path rejection test passes |

P0–P3 are deployed but **inert**: the new path exists and is exercised by tests while
production still runs the old path. The trust switch happens exactly once, at P4.

**Why no mixed state:** the flag gates *both* the Frappe resolver and the MCP/Nutrition
contracts from a single release. Home MCP and Nutrition are never on opposite sides.

### Rollback gates

| Phase | Rollback | Blast radius |
| --- | --- | --- |
| P0–P3 | Flag already off; revert branch | None — production behavior unchanged |
| **P4** | Flip flag off **and** redeploy the prior image tags together | Minutes; G1.5 behavior restored exactly |
| **P5** | Revert commit (old path deleted → full revert required) | Do **not** enter P5 until P4 has soaked |

Deploy follows the standard flow: PR → `main` → `episteck-deploy` → **manual
`bench migrate`** for the `linked_user` unique index (home.episteck.com has no
post-deploy hook). Record image tags for Home MCP and Nutrition so P4 rollback is a
paired, single-step action.

---

## 14. One real login, synthetic Person (§10) — **APPROVED**

**DECISION: Approve exactly as described.**

Bind **one** real operator login (`vargas3rick@gmail.com`) to a **synthetic** Person
(PSN-00002 or a new synthetic operator Person). No other family member is onboarded.
All domain data stays synthetic.

**Why:** this is the only way to prove the real authentication path end-to-end —
browser login, OAuth code+PKCE, BFF, delegation, `frappe.session.user`, `linked_user`,
Person — **without** introducing any real personal data. Identity and data sensitivity
are orthogonal, and G1.6 must prove identity.

**Security consequence:** strictly positive. It closes the largest untested gap (all
three Persons have `linked_user: null`, so the human branch has never run live). Worst
case, a real login reaches synthetic records it already effectively controls as
System Manager.

**One caution:** `vargas3rick@` holds System Manager with 42 roles. For validation,
confirm that Home business-API behavior is driven by the Person binding and **not** by
ambient desk privileges. Recommend also binding a **low-privilege** second test User to
a synthetic Person to prove the path does not depend on elevated roles.

---

## 15. G1.6 acceptance criteria

G1.6 is complete when **all** hold:

1. `actor_person_id` appears in **no** MCP tool schema, **no** Nutrition route, and
   **no** Home business API signature — asserted mechanically by tests.
2. Actor identity derives **only** from `frappe.session.user` → `Person.linked_user`.
3. A machine credential alone cannot obtain person data (`PermissionError`).
4. Nutrition resolves the actor **independently** and refuses any delegated actor string.
5. `Person.linked_user` is unique; both violation directions are rejected at write time.
6. All 20 threat-model rows (§10) pass with their expected failure modes.
7. PKCE cases 1–4, 7, 8 pass; cases 5–6 documented as known upstream limitations.
8. Duplicate `sub` remediated; uniqueness assertion in place.
9. One real login bound to a synthetic Person resolves end-to-end; a low-privilege
   User does too.
10. Logout/revocation denies on the **next** call; no authorization caching introduced.
11. No token material in agent context, tool schemas, or logs.
12. **All 93 existing tests still pass**; consent semantics unchanged.
13. Old caller-supplied path explicitly rejected (P5).
14. `G1_6_VALIDATION.md` records evidence incl. latency delta vs. the G1.5 baseline
    (119.88 ms / 121.60 ms p95).

---

## 16. Remaining G2 blockers after G1.6

| Blocker | Cleared by G1.6? |
| --- | --- |
| Trusted actor binding | ✅ **yes** — this is the deliverable |
| ~~Stage G1.7 — EU Home Control Plane migration~~ (A11) | ✅ **withdrawn 2026-09-16** — not a blocker. Personal/family deployment stays in Ashburn/US. See §23 |
| Explicit user approval for real data | ❌ no — your decision |
| Real-Person onboarding + real ConsentGrants | ❌ no — G2 scope |
| Duplicate `sub` remediation (gated on reference audit, A5) | ⚠️ prepared in G1.6; required before native OIDC |
| Backup covering Home Control Plane identity data | ⚠️ verify — restic covers Nutrition + Mealie; Frappe Home identity data must be confirmed |

---

## 17. Deferred / not in G1.6

- Real family/health data (G2).
- Passkeys/WebAuthn, MFA enforcement, external IdP (Option B remains a clean later
  swap behind the `auth_hooks` seam).
- **Direct native-mobile OIDC** — blocked on PKCE enforcement (§11).
- Public Internet exposure; everything stays on Tailscale/loopback.
- Voice interface implementation.
- Knowledge runtime; new domain services.
- The three G1.5 cosmetic observations. Note: agent decision reuse becomes **strictly
  safer** under G1.6, because the actor can no longer differ between a remembered
  decision and the actual call.

---

## 18. Original Section 8 questions — recovered and answered

> Revision 1's §8 questions, verbatim, each answered in the required format.

### Q1. Voice scope — restrict the first voice interface to read-only, low-sensitivity domains until a speaker factor exists?

**DECISION:** Yes. Read-only, low-sensitivity domains only.
**WHY:** Voice is the weakest channel. Per §15, device/session authentication is the
authenticator; speaker identification is a convenience signal. Speaker recognition is
spoofable by recording or synthesis and must never alone authorize sensitive actions.
**SECURITY CONSEQUENCE:** Caps blast radius of a compromised or overheard voice session
to low-sensitivity reads. A household member or guest cannot voice their way into
health or finance data.
**IMPLEMENTATION CONSEQUENCE:** None for G1.6 (voice is deferred). Recorded as a
constraint so the voice stage inherits it rather than relitigating it.

### Q2. Token TTL — 15 min access / 8 h refresh, shorter idle timeout on shared tablets. Acceptable?

**DECISION:** Yes, with one change: the **delegation** token is far shorter — minutes,
single-audience, single-turn.
**WHY:** Revision 1 assumed the user's bearer token flowed to services. Under §6 it
does not; a separate delegation credential does. Its TTL should be scoped to a single
agent turn, not a session.
**SECURITY CONSEQUENCE:** Substantially reduces the replay/theft window (T-5, T-6). A
leaked delegation token is useless within minutes and only at one audience.
**IMPLEMENTATION CONSEQUENCE:** BFF mints per-turn delegation tokens. Slightly more
issuance logic; no extra round trip on the critical path since the BFF is already in it.

### Q3. Duplicate `sub` — regenerate for both, or disable the unused account?

**DECISION:** Regenerate for **both** users; keep both accounts. Add a uniqueness
assertion. Do not disable `aemarchan1@`.
**WHY:** Root cause is a copied child row, not a compromised account (§3), so disabling
fixes nothing and loses a real account. Both values must change because it is not
determinable which document is the "original." Nothing consumes `sub` today, so
regeneration is non-breaking.
**SECURITY CONSEQUENCE:** Removes a live identity-collision hole in which a System
Manager and a Desk User are indistinguishable to any `sub`-keyed relying party. The
assertion prevents silent recurrence.
**IMPLEMENTATION CONSEQUENCE:** Small, reversible data fix plus a migration assertion.
Must happen before any native/direct OIDC client. Not on the BFF critical path, so it
does not gate G1.6 delivery — but it **is** a G1.6 acceptance item (§15.8).

### Q4. Task 5 scope — bind one real human in G1.6 (synthetic data only), or defer all human binding to G2?

**DECISION:** Bind in G1.6. Restated and strengthened in §14 per the brief's §10.
**WHY:** Identity is exactly what this stage must prove, and the human path has never
executed in production. Deferring it would ship an unproven trust boundary.
**SECURITY CONSEQUENCE:** Positive — closes the largest untested gap with no real data
at risk. Added caution: also bind a low-privilege User, so the path is proven
independent of System Manager privileges.
**IMPLEMENTATION CONSEQUENCE:** Phases P1–P3 (§13) are exactly this. Requires the
administrative `linked_user` write plus the unique index.

### Q5. Residency — Home Control Plane is US-hosted while health data is EU. Flagged, not a G1.6 blocker?

**DECISION (revised 2026-09-16):** Not a G1.6 blocker and **not a G2 blocker either.**
The earlier promotion to a hard G2 blocker is withdrawn along with Stage G1.7.
**WHY:** `home.episteck.com` is the operator's own personal/family deployment, and the
operator accepts US hosting for it. G1.6 does make Ashburn the authentication authority
in addition to the consent authority, concentrating identity + consent + authentication
in one US node — that is a known, accepted property of a personal deployment, not a
defect to remediate before real data.
**SECURITY CONSEQUENCE:** Unchanged for G1.6. For G2, the concentration is accepted by
the data subject, who is also the operator.
**IMPLEMENTATION CONSEQUENCE:** None. The `auth_hooks` seam (§6.4) keeps a future
relocation or external-IdP swap contained to one module, which is what makes residency
safe to defer to a commercialization-time design (§23).

**Relevance check (per the brief):** all five remain relevant after the architecture
correction. Q2 and Q3 changed substantively; Q1, Q4, Q5 are confirmed with added
detail.

---

## 19. Challenges to the stated preferred decisions (§17)

Of the thirteen preferred decisions, **twelve are adopted unchanged**. One needs
qualification, and one revision-1 statement is corrected.

### Qualified: "Frappe Home as identity provider: YES"

**Concrete problem:** adopted for the **BFF/confidential-client** flow, but Frappe
v15.99.0 **cannot** safely serve direct public/native clients — no `public_client`
type, no `require_pkce`, and PKCE is skippable (§11).
**Alternative:** external IdP now (rejected — no blocker for BFF, and it adds a
stateful service to a node at ~1.4 GB idle of 2.8 GB), or an enforcing shim (deferred).
**Tradeoff:** BFF is slightly more server-side work and keeps sessions server-side,
which is a security gain. Native mobile must wait or ship against the BFF.
**Recommendation:** adopt Frappe **as scoped**; keep native OIDC blocked; record the
limitation. This matches the brief's own §11 instruction.

### Corrected from revision 1: "bind on `User.name`, never on `sub`"

**Concrete problem:** that phrasing conflated internal resolution with external
identity, and read as "use client-supplied `User.name`," which §4 of the brief
correctly forbids.
**Correction:** the caller supplies **neither**. Frappe derives the user from validated
authentication context (`frappe.session.user`), then maps server-side to
`Person.linked_user`. `(issuer, sub)` is remediated so it can serve as the stable
external tuple **later**, for native OIDC only.
**Tradeoff:** none — this is strictly more correct and matches the intended model.

All other preferred decisions — remove client-supplied `actor_person_id`; no
client-supplied `User.name`; internal resolution to `Person.linked_user`; Person
independent of User; one real login bound to a synthetic Person; Nutrition never trusts
an actor string; Nutrition resolves independently; no token visible to the LLM; live
PKCE validation required; no real data in G1.6; no ConsentGrant semantic change; no
additional IdP — are **adopted without change**.

---

## 20. Implementation plan (for later approval — not started)

Eight tasks, TDD-first, consistent with the repo's existing test style (in-memory
Frappe fake; no live site required for unit tests).

| # | Task | Deliverable | Phase |
| --- | --- | --- | --- |
| 1 | **Binding core** — `_resolve_actor()`; drop `actor_person_id` from `api.py`; unique index on `linked_user` + migration assertion | Frappe app | P0 |
| 2 | **Delegation transport** — `auth_hooks` validator; BFF issues per-turn tokens; machine key ≠ actor | Frappe app + BFF | P0 |
| 3 | **BFF + OAuth client** — confidential client, S256 PKCE always, opaque session cookie, server-side token store | New BFF | P0 |
| 4 | **Home MCP** — remove `actor_person_id` from all seven tools; forward delegation context; schema assertion tests | `services/home-mcp` | P0→P4 |
| 5 | **Nutrition** — drop actor from FastAPI routes + MCP tools; independent resolution; keep 3 s timeout, no cache | `services/nutrition` | P0→P4 |
| 6 | **`sub` remediation** — regenerate both values; uniqueness assertion | Data + migration | P1 |
| 7 | **Validation** — full §10 matrix, §11 PKCE plan, real-login binding, latency delta | `G1_6_VALIDATION.md` | P1–P3 |
| 8 | **Docs + ADR** — **ADR-0009: Trusted actor binding via Frappe-issued sessions** (records BFF scoping and deferred native OIDC); update `ARCHITECTURE.md` §3.1, `SECURITY_AND_CONSENT.md`, `STATUS.md`, `ROADMAP.md` | Docs | P4–P5 |

**Critical path:** Tasks 1–3 gate everything. Tasks 4–5 must flip **together** at P4.
Task 6 is independent and can land early. Task 8 lands with the implementation, per the
Architecture Change Rule.

**Effort shape:** Tasks 1–5 are ~70%; the BFF (Task 3) is the only genuinely new
component. Tasks 6–8 are data, evidence, and documentation.

---

## 21. Files changed by this review

**Exactly one** — this proposal:

```
docs/architecture/proposals/G1_6_TRUSTED_IDENTITY.md   (untracked, not committed)
```

No implementation file, no accepted ADR, and no other document was modified. Nothing
was committed or pushed. All live inspection was **read-only**.

---

## 22. Open questions for approval

1. **Delegation token vs. forwarded bearer token** (§6.3) — adopt the scoped delegation
   token? *(Recommend: yes.)*
2. **BFF placement** — Ashburn (next to Frappe, lower auth latency) or Nuremberg (next
   to the agent, EU)? *(Resolved by A1: Nuremberg. Residency is settled separately in
   §23 — Ashburn/US is accepted for the personal deployment.)*
3. **`sub` remediation timing** — during G1.6 as planned, or immediately as a standalone
   fix given a System Manager is involved? *(Recommend: standalone and soon.)*
4. **Second low-privilege test User** (§14) — approve creating one to prove the path
   does not depend on System Manager privileges? *(Recommend: yes.)*
5. **Backup coverage** (§16) — confirm whether restic covers the Frappe Home identity
   data, or whether identity/consent is currently outside off-box backup.

---

## 23. Data residency — Ashburn/US accepted for personal use `[CORRECTED 2026-09-16]`

**Status:** **Stage G1.7 (EU Home Control Plane Migration) is WITHDRAWN.** It is **not**
a G2 blocker. Amendment A11 is superseded by this section.

### Decision

The current `home.episteck.com` deployment is the operator's **own personal and family**
deployment. The operator accepts keeping the Home Control Plane — identity, consent and
authentication authority — in **Ashburn (US)**.

Therefore:

- **G1.6 (trusted identity) remains the current blocker** for G2.
- After G1.6, **real family onboarding may proceed on the existing Ashburn Home Frappe
  instance**. Real data does not require an EU Control Plane.
- **Do not migrate `home.episteck.com`** during this phase.
- **Do not create a G1.7 infrastructure migration requirement.**

### What is unchanged

Everything else stands. The BFF still runs on the Nuremberg EU node (A1) — that was
chosen on its own merits and is not contingent on a later migration. Nutrition, Mealie
and off-box backup remain EU. Cross-node calls remain Tailscale-only with no cross-region
database. All other approved G1.6 identity and security decisions are untouched.

### Future commercialization

EU data residency is a **future commercialization concern**, not an engineering blocker
for personal use. Before onboarding **external EU customers**, a regional
deployment / data-residency strategy will be designed separately — likely **dedicated EU
Home instances for those customers** rather than migrating the operator's personal US
instance. That design is out of scope here and has no scheduled stage.

The `auth_hooks` seam (§6.4) keeps any future relocation or external-IdP swap contained
to one module, so this decision is cheap to revisit.

### Relationship to G2

G2 (real family onboarding) requires **G1.6 complete** and **explicit user approval**.
No migration stage gates it.
