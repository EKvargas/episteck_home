# Home Hub F2 — Session / Viewer Bootstrap: Architecture & Security Plan

**Status:** `ARCHITECTURE APPROVED (Product Architect, 2026-09-23) — NOT IMPLEMENTED`
**Baseline:** `main` @ `852a59157b8f12bb3b00468193436c8f49ae5946` (PR #36, F1)
**Date:** 2026-09-23
**Parent:** `HOME_HUB_INTEGRATION_FOUNDATION.md` (F0 decisions are final and are not reopened here)

This plan designs the smallest secure change set for: authenticated session detection,
post-login handoff to `/app`, a trusted Viewer bootstrap, discoverable Person/Circle/Care
contexts, and Next.js server-side consumption. No domain data, no Nutrition, no
`activeContext` migration (F3), no real-person onboarding.

Everything marked **[VERIFIED]** was read in code at the baseline SHA. **[PROPOSED]** is
design only. **[VERIFY LIVE]** must be proven against the running system before merge.

### Product Architect decisions (2026-09-23)

**Approved:**
1. Option B: add the single session-bound Control Plane method `get_home_bootstrap(session_id)` (§2, §3).
2. Fix `open_session` so that zero or ambiguous Person linkage is refused **before** a Home Delegated Session is created (B2).
3. Add the `__Host-episteck_home_login` browser-binding cookie to close login CSRF (B3, §9).
4. `/bootstrap` stays non-public and read-only (§4, §6, §11).
5. The explicit nginx route allowlist stays (§11).
6. The three-PR split F2a-CP → F2a-BFF → F2b-Hub stays (§13).
7. The coordinated BFF + Hub + nginx deployment window stays (§13).

**Infra decision:** the Hub container reaches the host BFF through rootless pasta with an explicit container→host TCP forward for port 9933 only, preferably `Network=pasta:-T,9933`. `Network=host` is **not** allowed, and broad `--map-gw` is **not** the default. The proof obligations and the STOP rule are in §11.

---

## 1. Current BFF behavior [VERIFIED]

`services/home-bff/home_bff/app.py`, public TCP app on `127.0.0.1:9933` behind nginx
(`bff.home.episteck.com`).

| Route | Method | Behavior |
| --- | --- | --- |
| `/login` | GET | Purges expired rows; creates PKCE pair, `state`, `nonce`; persists them server-side (`oauth_transaction`, TTL 600 s); `302` to Frappe authorize. The browser carries only `state`. **No browser-binding cookie.** |
| `/callback` | GET | `error` → 400. `consume_transaction(state)` is atomic fetch-and-delete (replay → 400). Missing `code` → 400. Code exchange with the stored verifier (failure → 400, class-only log). `open_home_session(access_token)` (refusal → 403). `create_session` stores access + refresh token. `claim_runtime` (failure → session deleted, 503). **Success → `200 JSON {"status":"authenticated","runtime_binding":<BindResult>}`** + `Set-Cookie`. |
| `/session` | GET | Cookie → local store lookup only. 401 or `{"authenticated":true,"expires_at":…}`. No upstream call. |
| `/whoami` | GET | Cookie → local session → `GET episteck_home.api.whoami` with the **human OAuth bearer only** (no delegation header). Any upstream failure → 403. Returns the upstream payload (`actor_person_id`, `principals`). |
| `/logout` | POST | Best-effort `close_session(home_session_id)` + `revoke_token`; deletes the local session (FK cascade drops runtime binding); always clears the cookie; `200 JSON`. |
| `/delegation` | POST | Cookie-authenticated mint (`aud` query param restricted to known audiences). nginx: `location = /delegation { return 404; }`. |
| `/health` | GET | Liveness only. |

Cookie: `episteck_home_session`, host-only, `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=43200`.
Separate UDS-only mint app (`internal_app.py`) serves `/internal/mint` for the runtime binding.

### Findings that shape F2

| # | Finding | Consequence |
| --- | --- | --- |
| **B1** | BFF→Control Plane calls use the **OAuth bearer alone**. The auth hook's `Home Delegated Session` checks (`status=Active`, `expires_at`, `User.enabled`) run **only when an `X-Episteck-Delegation` header is present** (`auth_hook._establish`). On the bearer-only path, `resolve_principals()` maps `frappe.session.user → Person` with **no session-record check and no `enabled` check**. G1.6 T-9/T-10 hold on the delegation path, not on this one. | A bootstrap made of N bearer-only calls to the existing APIs would **not** see an admin-revoked Home Delegated Session. Whether a disabled User's live bearer token still authenticates depends on Frappe's `validate_oauth` → **[VERIFY LIVE]**. |
| **B2** | `identity/session.open_session` checks only `User.enabled`. It does **not** require exactly one linked Person. The callback's comment ("zero links, two links … surface here as a refusal") does not match the code. | An unlinked User gets a BFF cookie today. With `303 → /app`, the chain becomes `/app → bootstrap refuses → /login → callback succeeds → /app …` — a **redirect loop**. |
| **B3** | `state` is not bound to the browser that started `/login`. An attacker can start `/login` themselves, authenticate as themselves, stop before `/callback`, and send the victim `…/callback?code=A&state=A`. The victim then holds a session **as the attacker**. | **Login CSRF.** Mostly harmless while `/callback` renders JSON. Once it lands the victim in a working `/app`, where they may enter family or health data into the attacker's account, it matters. |
| **B4** | The access token's `expires_in` is discarded and `refresh_token` is stored but never used. The local session is 12 h, but a Frappe OAuth access token defaults to 3600 s → **[VERIFY LIVE]**. | Any bearer-based call, including today's `/whoami`, starts failing roughly an hour after login while the cookie still looks valid. |
| **B5** | The public `FastAPI()` app keeps its default `/docs`, `/redoc`, `/openapi.json`, and nginx `location /` forwards everything. | The public route inventory, `/delegation` included, is discoverable. |
| **B6** | The callback JSON body is consumed **only** by `services/home-bff/tests/test_app.py` (lines ~189–215) and by operator evidence runs. No service parses it. | The 303 change is safe; those tests are updated deliberately. |

---

## 2. Decision: how bootstrap reaches the Control Plane

The brief prefers composing existing APIs with the stored OAuth token. The three options:

| Option | Mechanism | Revocation (B1) | Round trips (Nuremberg→Ashburn, ~130 ms each) | Partial failure | New surface |
| --- | --- | --- | --- | --- | --- |
| **A — compose existing APIs** | `get_care_dashboard` + `get_person(self)` + `get_person(subject)×K`, bearer-only | **Not honored** unless a delegation header is added. With one, `machine_caller` becomes the human's own OAuth user, which muddles the dual-principal audit. | 2+K, serial or fan-out | Possible, and snapshots can be inconsistent | none |
| **B — one session-bound CP read** ✅ | `episteck_home.api.get_home_bootstrap(session_id)`, human OAuth bearer. The CP checks that `session_id` is an **Active, unexpired Home Delegated Session owned by `frappe.session.user`, with the User enabled**, using the same `_user_for_session` logic as the auth hook. It then composes the internal helpers `_circles_for` and `_care_for`. | **Honored on every call** | 1 | None (one transaction) | 1 whitelisted method, no actor parameter |
| C — BFF machine credential + delegation | Full G1.6 dual-principal path | Honored | 2+K | Possible | New Frappe API user and secret on the BFF |

**Decision: Option B (APPROVED).** It still uses the human OAuth token, as the brief requires.
It is still a business API: it reuses the existing `_circles_for` / `_care_for` helpers
and makes no generic DocType reads. It closes B1, removes N+1 cross-region latency, and
cannot partially fail. Options A and C are not pursued.

The same CP PR fixes **B2**: `open_session` must require exactly one linked Person
(`actor._person_for_user`) and refuse otherwise with `PermissionError`. That makes the
callback comment true and removes the loop at its source.

---

## 3. Exact Control Plane calls

| Stage | Call | Auth | Purpose |
| --- | --- | --- | --- |
| Login (existing) | `episteck_home.identity.session.open_session` | human bearer | **[PROPOSED change]** also refuse zero or ambiguous Person link |
| Bootstrap | `episteck_home.api.get_home_bootstrap(session_id)` **[PROPOSED]** | human bearer | the only call |

`get_home_bootstrap` contract [PROPOSED]:

- **No actor parameter.** `session_id` is an **opaque selector** for a Home Delegated Session. It is neither an identity nor proof of anything. Authority comes only from the authenticated OAuth user (`frappe.session.user`), combined with the server-side checks that the selected session is owned by that user, `Active`, unexpired, and belongs to an enabled User. A missing, foreign, revoked, or expired session, or a disabled User, all raise the same `PermissionError` (no oracle).
- Actor = `resolve_actor()`. Zero or ambiguous link → `PermissionError`.
- Returns `viewer {person_id, display_name}` (`Person.full_name`), `circles` = `_circles_for(actor)` → `{circle_id, display_name}` (drop `circle_type` in F2), and `care` = `_care_for(actor)` (active rows only, `valid_from`/`valid_to` already applied) joined with the subject's `full_name` → `{person_id, display_name, relationship_type}`.
- **Never** calls `check_access`, `_has_effective_access`, or `get_access_to_person`. Returns no grants, no `external_ref`, no `User.name`/email, no `principals`, no `valid_from`/`valid_to`, no circle member lists.
- Bounded: at most 50 circles and 50 care rows. Over the bound → `ValidationError` (fail closed; realistic households never reach it).

Existing APIs **not** used, with reasons:
- `whoami`: `get_home_bootstrap` already resolves the actor.
- `get_person`: care subjects are discoverable by construction; one join replaces K calls.
- `list_circle_members`: circle co-members are **not** PERSON contexts in F2 (§5).
- `get_access_to_person`: this is the domain-authorization precompute that F2 explicitly excludes (§5).
- `get_care_dashboard`: same data, but it returns `actor_person_id` bare and has no session check.

---

## 4. `/bootstrap` response contract [PROPOSED]

BFF `GET /bootstrap`: cookie-authenticated, **read-only**, **not publicly routed** (§10).
Consumed only by the Next.js server over loopback. `Cache-Control: no-store`.

```json
{
  "version": 1,
  "viewer": { "personId": "PSN-00001", "displayName": "Erick" },
  "personContexts": [
    { "type": "PERSON", "personId": "PSN-00001", "displayName": "Erick" },
    { "type": "PERSON", "personId": "PSN-00007", "displayName": "Ana" }
  ],
  "circleContexts": [
    { "type": "CIRCLE", "circleId": "CIR-00001", "displayName": "Family" }
  ],
  "careRelationships": [
    { "subjectPersonId": "PSN-00007", "relationshipType": "CAREGIVER" }
  ]
}
```

BFF validation (strict allowlist; the BFF re-serializes and never passes the upstream body through):

- `personId` `^PSN-\d{5,}$`, `circleId` `^CIR-\d{5,}$` (the DocType autoname formats).
- `displayName`: non-empty string, ≤ 140 chars, control characters rejected.
- `relationshipType` ∈ `CAREGIVER | COORDINATOR | GUARDIAN | FAMILY_SUPPORT` (the Care Relationship options).
- `personContexts[0]` is the viewer (self). Each care subject appears once. A care subject equal to the viewer is rejected. Duplicates are rejected.
- Every `careRelationships[].subjectPersonId` exists in `personContexts`.
- Unknown upstream fields are dropped. A missing or mistyped required field, an unknown enum, or an exceeded bound **rejects the whole payload** (502, §6). A partially valid bootstrap is never returned.

Excluded by construction: OAuth tokens, `home_session_id`, cookie values, delegations,
the delegation secret, client secret, `User.name`, `principals`, grants, consent
records, `external_ref`, validity dates, circle membership lists.

Person and Circle ids are the only raw identifiers, and they are required: they are the
`ResourceScope` values F3/F4 adapters pass to domain services.

### Mapping to F1 types

| Wire | F1 type | Adjustment |
| --- | --- | --- |
| `viewer` | `Viewer` | **Rename `name` → `displayName`** for consistency with `ResourceScope` |
| `personContexts[]` | `Extract<ResourceScope,{type:'PERSON'}>` | `BootstrapContext` should reference `ResourceScope` variants instead of redeclaring inline shapes |
| `circleContexts[]` | `Extract<ResourceScope,{type:'CIRCLE'}>` | same |
| `careRelationships[]` | `CareRelationship` | narrow `relationshipType: string` to the four-value union |
| `version` | — | wire-only; checked by the adapter, not exposed to React |

These are small, type-only F1 edits and belong in F2b. `DataEnvelope`, `SafeUIErrorCode`
and `Environment` need **no change**.

---

## 5. Discoverability ≠ authorization (proof obligations)

Bootstrap answers "which scopes may this viewer **nominate**?" It never answers "which
domains may the viewer access for that scope?"

1. **No grant data exists in the response.** The CP method never evaluates policy (test: spy asserts `_check_access` is not called; response key allowlist).
2. **PERSON contexts = self + active care subjects only.** Circle co-members are not promoted to PERSON contexts, so a shared Circle yields no nominable Person. Persons who granted access without a care or circle relation are not listed in F2 (known gap, F3+).
3. **CIRCLE contexts come from the viewer's own memberships** and carry no member list. A CIRCLE scope has its own type discriminant and id namespace (`CIR-`), so it can never be read as a `personId`.
4. **Care relationship ≠ authorization** (SECURITY_AND_CONSENT invariant 2). `relationshipType` is presentation metadata. The UI must not branch authorization on it.
5. **Every domain operation still authorizes itself.** It mints a fresh delegation and the domain service calls `check_access`. A nominated scope with a denied domain renders `ACCESS_DENIED` for that domain only (foundation §5).

---

## 6. Error / status mapping [PROPOSED]

`frappe_client` must split today's catch-all `SessionOpenError` for this call into
`UpstreamRefused` (HTTP 401/403), `UpstreamUnavailable` (connect error, timeout, 404, 417
"method absent", 429, 5xx), and `UpstreamMalformed` (200 + non-JSON or schema failure).

BFF error body: `{"error":"<CODE>"}` only, with the CODE drawn from `SafeUIErrorCode`. No upstream text.

| Condition | Detected by | BFF status | Body code | Next.js action |
| --- | --- | --- | --- | --- |
| No cookie | cookie absent | 401 | `SESSION_REQUIRED` | redirect `/login` |
| Unknown / expired local session | `get_session` → None | 401 | `SESSION_INVALID` | redirect `/login` |
| Home Delegated Session revoked/expired | CP `PermissionError` (403) | 401 | `SESSION_INVALID` | redirect `/login` |
| OAuth access token expired/revoked (B4) | CP rejects bearer (403) | 401 | `SESSION_INVALID` | redirect `/login` |
| Unlinked / ambiguous User | CP `PermissionError` | 401 | `SESSION_INVALID` | redirect `/login` → callback now **403 terminal** (B2 fix), so no loop |
| Disabled User | CP `PermissionError` | 401 | `SESSION_INVALID` | redirect `/login` → Frappe refuses login (terminal) |
| CP unavailable / method absent | `UpstreamUnavailable` | 503 | `SERVICE_UNAVAILABLE` | `ServiceUnavailableBoundary`, **no redirect** |
| Malformed CP response / validation failure | `UpstreamMalformed` | 502 | `INVALID_RESPONSE` | error boundary, **no redirect** |
| Partial composition failure | impossible under Option B (single call); under Option A, any sub-failure → the row above for its class | — | — | — |
| BFF store unavailable | `StoreUnavailableError` | 503 | `SERVICE_UNAVAILABLE` | boundary |

**Anti-oracle:** every definitive refusal collapses to one `401 SESSION_INVALID`. The
browser cannot tell a revoked session from an unlinked or disabled account from an
expired token. The only distinct terminal signal is the callback's existing 403, and
that describes the caller's own account. Only definitive refusals trigger a login
redirect. Transport and shape failures never do, which is what prevents a
`/login` storm while the CP is down.

**Read-only:** `/bootstrap` never mutates the BFF store, not even on refusal. Deleting
the local session on refusal would also cascade-delete the **agent runtime binding**, and
B4 would make that happen every hour. The CP remains the authority. A dead local session
simply keeps returning 401 until a new login replaces the cookie.

---

## 7. Revocation / freshness

- No bootstrap cache in the BFF or Next.js. Every request makes exactly one CP call against live rows.
- Logout deletes the local session → the next bootstrap returns 401 without an upstream call.
- An admin revocation of the Home Delegated Session is caught by the CP session check on the next bootstrap (closes B1 for this route).
- A Person↔User unlink, a disabled User, a care relationship ending, or a circle membership removal is reflected on the next bootstrap.
- Grant revocation does not affect bootstrap because bootstrap carries no grants. The next domain call denies.
- B4 (≈1 h bearer lifetime) makes this path re-authenticate hourly. That is transparent when the Frappe session is still live and the OAuth client skips re-consent → **[VERIFY LIVE]**. Refresh-token support is **deferred** (F2.x): it needs rotation and cross-process concurrency design and is not required for correctness.
- Out of scope but recorded: the existing `/whoami` has the same B1 gap. Its code comment ("revoked → deny") is only true for OAuth-token revocation.

---

## 8. Next.js server contract (F2b) [PROPOSED]

- One module, `src/integration/home/bootstrap.server.ts`, with `import 'server-only'`.
- Reads **only** `episteck_home_session` via `cookies()`. It calls `GET http://127.0.0.1:9933/bootstrap` with `Cookie: episteck_home_session=<value>` and nothing else: it never forwards the browser's full Cookie header, `Authorization`, or `X-Forwarded-*`. The BFF URL is fixed server configuration, never derived from request `Host`.
- `fetch(…, { cache: 'no-store' })`; `export const dynamic = 'force-dynamic'` on `/app` layouts; React `cache()` request-local memo is allowed (foundation §11).
- F2b does **not** call `/session`. A successful bootstrap *is* session detection (one loopback call per render).
- `HOME_HUB_DATA_MODE=MOCK` → the mock bootstrap, and the BFF is never called. Production startup enforcement of `LIVE` is activated here (the note in `Environment.server.ts`).
- Returns `DataEnvelope<BootstrapContext>`. 401 → `redirect` to `/login`. Because of `basePath: '/app'`, the implementation must prove the target is the origin-root `/login`, not `/app/login` → **test**.

**May be serialized to Client Components:** `viewer.{personId, displayName}`,
`personContexts`, `circleContexts`, `careRelationships`, envelope metadata
(`delivery/authorization/freshness/environment/errorCode`).

**Never leaves the server:** the cookie value, raw BFF response bodies and headers, HTTP
statuses and upstream text, delegations, the BFF URL, and any logs containing identifiers.
Next.js logs record error classes only.

---

## 9. CSRF / method safety

| Route | Method | Assessment |
| --- | --- | --- |
| `/login` | GET | Creates only an unauthenticated transaction. **Add** (B3): a login-binding cookie `__Host-episteck_home_login` (random, `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600`). The transaction stores `sha256(value)`. |
| `/callback` | GET | Inherent to OAuth. Protected by single-use `state` + PKCE + **(new)** a constant-time match of the binding cookie against the transaction. A mismatch or missing binding → 400; the transaction is consumed anyway and no session is issued. The binding cookie is cleared on every callback outcome. `Lax` is sent on the top-level GET back from Frappe; `__Host-` prevents sibling-subdomain cookie tossing. |
| `/logout` | POST | `Lax` withholds the cookie on cross-site POST. Low impact regardless. |
| `/bootstrap` | GET | Read-only, no side effects; not publicly routed. Other methods → 405. |
| `/session`, `/whoami` | GET | Read-only; unchanged. |

Same-origin `/app` consequence: **any XSS in Next.js can now call `/session`, `/whoami`,
`/logout` with credentials** (`/delegation` and `/bootstrap` stay unreachable publicly).
Mitigation in F2b: a strict CSP on `/app`, no `dangerouslySetInnerHTML`, and Next.js
Server Action origin checks left at their defaults (nginx must pass `Host` /
`X-Forwarded-Host`; no wildcard `allowedOrigins`). `SameSite=Lax` stays: `Strict` would
drop the cookie on the Frappe→`/callback` navigation. Cookie `Domain` stays host-only.

Concurrent logins from two tabs overwrite the single binding cookie, so the first tab's
callback fails with 400 and the user retries. This is accepted.

---

## 10. Callback 303 design [PROPOSED]

Success response (all prior checks unchanged: replay, PKCE, exchange, `open_session`, runtime claim):

```
HTTP/1.1 303 See Other
Location: /app                       ← constant relative path; never from query, Host, X-Forwarded-*, or state
Set-Cookie: episteck_home_session=<opaque>; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=43200
Set-Cookie: __Host-episteck_home_login=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax
Cache-Control: no-store
Referrer-Policy: no-referrer
(empty body)
```

- The cookie is set on the redirect response itself, so the browser stores it before following `Location`.
- `return_to`, `next`, `redirect`, `redirect_uri` and any other query parameters are ignored. There is no code path that reads them.
- `BindResult` is no longer sent to the browser. It is logged as its static enum value. `ALREADY_BOUND` still yields 303: the Home Hub session is valid, and agent binding is orthogonal.
- Failures keep today's statuses (400 / 403 / 503) with static bodies, **never** a redirect, and never a session cookie.
- Tokens, `code`, and `state` never appear in `Location`, the body, or logs (nginx `episteck_noqs` already strips query strings).
- Confidentiality of `/callback?code=…&state=…` does **not** rely on browser-history behavior. It relies on the fixed redirect target, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, single-use `state` and `code` (plus PKCE), and query-stripped server logging.
- Tests at `test_app.py` ~189–215 that assert the JSON body are **deliberately rewritten** to assert 303 + headers. All replay, PKCE, and failure-path tests keep their assertions.

---

## 11. nginx routing (conceptual — do not deploy)

Change `location /` from catch-all proxy to an **explicit allowlist**. This also closes B5:

```nginx
location = /delegation { return 404; }            # unchanged invariant
location = /login      { proxy_pass http://127.0.0.1:9933; }
location = /callback   { proxy_pass http://127.0.0.1:9933; }   # episteck_noqs logging
location = /logout     { proxy_pass http://127.0.0.1:9933; }
location = /session    { proxy_pass http://127.0.0.1:9933; }
location = /whoami     { proxy_pass http://127.0.0.1:9933; }
location = /app        { proxy_pass http://127.0.0.1:<HUB_PORT>; }
location ^~ /app/      { proxy_pass http://127.0.0.1:<HUB_PORT>; }  # not `^~ /app` (would match /application)
location = /           { return 303 /app; }       # optional
location /             { return 404; }            # /bootstrap, /docs, /openapi.json, everything else
```

- `/bootstrap` is deliberately **not** public. Only the Next.js server calls it, over loopback.
- The Next.js listener binds `127.0.0.1:<HUB_PORT>` only (suggest `9940`; `9931–9934` are taken). Rootless Quadlet under a dedicated `svc-home-hub` with `PublishPort=127.0.0.1:…`.
- An `add_header` inside a `location` replaces server-level headers, so `/app` locations must repeat `nosniff`, `X-Frame-Options`, `Referrer-Policy` and add the CSP. HTML stays `no-store`; `/app/_next/static/` may be `immutable`.
- **Infra decision (APPROVED):** the rootless Next.js container reaches the host's `127.0.0.1:9933` through pasta with an explicit container→host TCP forward for that single port, preferably `Network=pasta:-T,9933` (inside the container, `127.0.0.1:9933` forwards to host loopback `9933`). `Network=host` is **not** allowed, and broad `--map-gw` is **not** the default. F2b must prove on the **real deployment host** **[VERIFY LIVE]**:
  1. Next.js reaches the host BFF on `127.0.0.1:9933` with this configuration.
  2. Unrelated host-loopback ports (e.g. `9931`, `9932`, `9934`, Nutrition) stay unreachable from the container.
  3. The Hub listener is exposed only as intended: to nginx on host loopback, and nowhere public.

  **STOP rule:** if the installed Podman/pasta version cannot satisfy all three, stop and return evidence **before** choosing another topology. Optionally extend the nft pattern (`deploy/gateway/episteck-gateway.nft`) so `9933` accepts only nginx + `svc-home-hub`, and `HUB_PORT` accepts only nginx.
- `next.config.ts` needs `basePath: '/app'` (today it has none, and routes live at `/`).

---

## 12. Adversarial & functional test matrix

**F2a-CP (`apps/episteck_home/tests`)**

| ID | Test | Expect |
| --- | --- | --- |
| CP-1 | Own Active session → bootstrap | viewer + circles + care, exact key allowlist |
| CP-2 | Another user's session id | `PermissionError`, identical to missing |
| CP-3 / CP-4 | Revoked / expired session | `PermissionError` |
| CP-5 | Disabled User | `PermissionError` |
| CP-6 | Zero or two linked Persons | `PermissionError` |
| CP-7 | Signature has no actor parameter | `TypeError` on `actor_person_id=` (like T-1) |
| CP-8 | Policy never evaluated | spy: `_check_access` not called; no `access`/grant keys |
| CP-9 | Circle co-member not in care | not present as a PERSON |
| CP-10 | Care row outside `valid_from/valid_to` | excluded |
| CP-11 | No `external_ref`, `User.name`, `principals`, dates | absent |
| CP-12 | > 50 circles or care rows | `ValidationError` |
| CP-13 | `open_session` for unlinked / ambiguous / disabled User | `PermissionError`, no row written |

**F2a-BFF (`services/home-bff/tests`)**

| ID | Test | Expect |
| --- | --- | --- |
| BFF-1 | Successful login | 303, `Location == "/app"`, session cookie flags exact, no `Domain`, binding cookie cleared, empty body |
| BFF-2 | `?return_to=https://evil`, `next=`, `redirect_uri=`; spoofed `Host` / `X-Forwarded-Host` | `Location` still `/app` |
| BFF-3 | Replayed `state` | 400, no cookie |
| BFF-4 | Missing or mismatched login-binding cookie (login CSRF) | 400, transaction consumed, no session |
| BFF-5 | `error=`, exchange failure, `open_session` refusal, binding failure | 400 / 400 / 403 / 503, no redirect, no cookie |
| BFF-6 | `ALREADY_BOUND` | 303; enum not in response |
| BFF-7 | Bootstrap without cookie / unknown / expired | 401 `SESSION_REQUIRED` / `SESSION_INVALID` / `SESSION_INVALID` |
| BFF-8 | Bootstrap uses the session's own token + `home_session_id` | stub asserts both; `?person_id=`, `X-Actor-ID`, and a body are ignored |
| BFF-9 | Route declares no parameters | cannot name another actor |
| BFF-10 | CP 401/403 | 401 `SESSION_INVALID`; store rows unchanged (session **and** runtime binding) |
| BFF-11 | CP connect error, timeout, 404, 417, 5xx | 503 `SERVICE_UNAVAILABLE` |
| BFF-12 | CP non-JSON, missing field, wrong type, unknown `relationshipType`, circle id in `personId`, care subject not in contexts, duplicate, over bound | 502 `INVALID_RESPONSE`, never partial |
| BFF-13 | CP adds `access`/grant or `external_ref` fields | dropped; not in output |
| BFF-14 | Response bytes vs secrets | no access/refresh token, client secret, delegation secret, `home_session_id`, cookie value |
| BFF-15 | `caplog` across every failure path | no tokens, session ids, Person ids, upstream messages |
| BFF-16 | Logout → bootstrap | 401 |
| BFF-17 | `POST/PUT/DELETE /bootstrap` | 405 |
| BFF-18 | Headers | `Cache-Control: no-store` on bootstrap and callback |
| BFF-19 | Public app | `/docs`, `/redoc`, `/openapi.json` → 404 |
| BFF-20 | SQLite migration adds the binding column idempotently while public + mint processes start concurrently | no error, one column |

**Deploy (`deploy/home-bff/tests/test_nginx_routes.py`, new, static config test)**
`/delegation` 404; `/bootstrap`, `/docs`, `/openapi.json` fall to 404; `/app` and `/app/` go to the hub port; `/application` does not; no `Domain=` rewriting; the hub listener is loopback-only in its Quadlet.

**F2b (`apps/home-hub`)**
`server-only` import guard (a client import fails the build); the serialized-props allowlist snapshot contains no cookie value; 401 → exactly one redirect to origin-root `/login`; 503/502 → boundary with no redirect; MOCK never calls `fetch`; production + MOCK → startup failure; `fetch` is `no-store`; only the one cookie is forwarded; the BFF URL ignores request `Host`; logs contain no identifiers. Synthetic e2e: login → `/app` shows the viewer; logout → `/app` redirects to login.

---

## 13. Split, merge and rollout order

Three PRs, because they have different runtimes and different deploy paths:

1. **F2a-CP** — `open_session` link requirement (B2) + `get_home_bootstrap`. Additive and backward-compatible. Deployed to Ashburn via the `episteck-deploy` job; no schema change, so no migrate. Gate: live CP-2/3/5/6 on synthetic users.
2. **F2a-BFF** — login-binding cookie + migration (B3), `/bootstrap` (read-only, split upstream errors, strict validator), callback 303, public docs disabled (B5), nginx allowlist file + static test. Consumes only the §3 contract. The BFF is released manually per `deploy/home-bff/README.md`, so merging does not deploy.
3. **F2b-Hub** — F1 type adjustments (§4), `basePath: '/app'`, `bootstrap.server.ts`, provider wiring (the `activeContext` behavior stays F3), production `LIVE` enforcement, CSP, the `svc-home-hub` Quadlet (not activated).

**Merge order:** 1 → 2 → 3. **Deploy order:** CP (1) → **one coordinated window** for the BFF image (2) + Next.js service (3) + nginx allowlist. The 303 must not go live before `/app` answers. It fails safe if it does (the user lands on a 404 with a valid cookie), but it is broken UX. Before the CP is live, the BFF's `/bootstrap` returns 503 (417 "method absent") rather than anything unsafe.

**Contract between F2a and F2b:** §4 (wire schema, `version: 1`) + §6 (status → code table). F2b's adapter tests pin both, using fixtures generated from F2a's validator output.

---

## 14. Risks

| Risk | Severity | Mitigation / status |
| --- | --- | --- |
| B1 revocation gap on the bearer-only path | High | Closed for `/bootstrap` by approved Option B |
| B3 login CSRF becomes consequential with `/app` | High | Binding cookie in F2a-BFF — **approved** |
| B2 redirect loop for unlinked users | Medium | `open_session` fix in F2a-CP |
| B4 hourly re-authentication | Medium (UX) | Accepted for F2; refresh deferred; **[VERIFY LIVE]** token TTL and skip-consent |
| Disabled User on the bearer path | Medium | Covered by the CP session check in Option B; **[VERIFY LIVE]** Frappe `validate_oauth` behavior |
| XSS in `/app` reaches same-origin BFF routes | Medium | CSP, `/bootstrap` + `/delegation` non-public |
| Container → host loopback reachability | Medium (delivery) | `Network=pasta:-T,9933` approved; **[VERIFY LIVE]** the three invariants, or STOP (§11) |
| Login still coupled to agent `claim_runtime` (503 blocks Hub login) | Low | Existing behavior; revisit when the Hub is primary |
| Existing `/whoami` has the B1 gap | Low | Recorded; follow-up |
| Care subjects reachable only via a grant are not listed | Low (product) | F3+ |

---

## 15. Explicitly out of scope

Nutrition or any domain data; `activeContext` migration; refresh tokens; `return_to`;
public `/bootstrap`; widening the cookie `Domain`; any change to `/delegation` or the
internal mint; production deployment; the Knowledge Technology Gate (PR #33).
