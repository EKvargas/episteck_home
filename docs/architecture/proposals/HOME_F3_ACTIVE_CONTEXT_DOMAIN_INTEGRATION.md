# Home F3: active Person context and first real Nutrition read

**Status:** Architecture approved and merged in PR #48. F3a implementation merged in PR #50; **F3a live verification PASSED on 2026-10-05** (Hub image built from `b1a3d5f7cc58b58968a3250b752a1dab37d0fa8b`, after the 2026-09-27 attempt was rolled back for nginx log-format drift and the log format was corrected on 2026-09-28). F3b/F3c/F3d remain open.

**Date:** 2026-09-27

**Baseline:** refreshed against `origin/main` at `0db28ab21462c2ff74add1ecb07c215b8c64488a` (original PR baseline: `0346aede2ff4a6895ddbb4dba976bd285a1991e9`)

**Scope:** Home Hub context selection, one read-only Nutrition vertical, and its server and policy boundary. No production data mutation, deployment, or Knowledge runtime.

## 1. Purpose and process boundary

Erick signs in as `vargas3rick@gmail.com`. The authenticated session resolves to Person `PSN-00013` (Erick Vargas). He chooses whose Nutrition profile to inspect. Home turns that choice into a **requested subject**. Nutrition performs a fresh `NUTRITION/VIEW` decision before reading its own store, then Home shows the result or a distinct safe failure state. The actor, subject, operation, and decision remain separate throughout.

The first live stage works with Erick alone. The current live bootstrap contains only Erick, no Circle, and no care relationship. Later cross-person use needs a real navigable Person and explicit consent; a family Circle is not a prerequisite for the Person Nutrition read. No synthetic Ana or Circle is introduced into LIVE. **Board decision:** if Erick has no Nutrition profile, an authorized `ABSENT` result is sufficient to prove the first live end-to-end integration and authorization path. It is not proof that populated profile data rendered, and F3 must not create a profile to make the demonstration contain data.

### Process register

| Process | Actor and requested subject/context | Authority and system of record | Checkpoint | Expected UI and failure behavior |
| --- | --- | --- | --- | --- |
| **F3-P1: viewer opens Home** | Actor is the session-derived Erick; subject defaults to Erick Person. | BFF session store and Frappe User → `Person.linked_user`; Frappe owns Person and navigation topology. | Existing session-bound `get_home_bootstrap(session_id)` checks session ownership, status, expiry, enabled User, and unique Person link. | Show Erick as viewer and default context. Invalid session goes to login; unavailable/malformed bootstrap shows unavailable, never mock identities. |
| **F3-P2: select self Person** | Actor Erick; requested subject `PSN-00013`. | Browser selects; server validates against fresh session bootstrap. Nutrition owns profile. | Context validation for navigation; subsequent Nutrition `NUTRITION/VIEW` check remains mandatory. | URL and selector show Erick. Failure keeps sensitive content hidden. |
| **F3-P3: select another Person** | Actor Erick; subject is a different Person, for example Ana after real onboarding. | Frappe bootstrap owns discoverability; Home policy owns consent; Nutrition owns profile. | Server accepts only a current navigable Person candidate; Nutrition independently checks a valid `Consent Grant` for this actor, subject, domain, and action. | Selector changes and prior data clears before request. A visible care relationship alone may lead to a `DENIED` panel. An unknown Person cannot be discovered by guessing an ID. |
| **F3-P4: select Circle** | Actor Erick; requested Circle has no single Nutrition subject. | Frappe Circle and Circle Membership own navigation topology; no Circle Nutrition operation exists. | F3 Person-only active-context parser rejects a Circle ID for this vertical. | A future family entry may remain a shell/navigation affordance, but `/nutrition` explains that Circle Nutrition is unavailable and offers Person choices. No member is silently chosen and no Nutrition call is made. |
| **F3-P5: request real Nutrition** | Actor resolved from the delegated session; subject from validated Person context; operation `NUTRITION/VIEW`. | BFF mints delegation; Home policy decides; Nutrition profile store supplies data. | Nutrition calls Home once, with its own machine credential and the single-use delegation; Home establishes subject existence before any allow; Nutrition reads only after allow. | Show a real, minimally mapped profile summary or explicit no-profile state. |
| **F3-P6: authorization denied** | Same actor and selected subject; explicit policy says no. | Home `Consent Grant` and `can_access` are authoritative. | Nutrition refuses before `repo.get_profile`. | Keep the selected Person visible with an access-restricted state; never substitute self or show earlier subject data. |
| **F3-P7: domain unavailable** | Actor and selected Person unchanged. | Nutrition service health or Home policy availability. | No successful fresh authorization and domain response. | Show unavailable; no mock fallback. Retry starts a new operation with a fresh delegation. |
| **F3-P8: no domain data** | Actor and selected Person authorized; profile absent. | Nutrition repository. | Authorization succeeded, then repository returned no profile. | Show “No Nutrition profile yet,” not zero targets, denial, or error. |
| **F3-P9: authorization changes while open** | Actor and subject remain selected; grant or session state changes. | Home policy/session records. | Every new sensitive operation rechecks; focus, refresh, and context changes trigger a new operation. | Clear data during a new request; next denied result replaces it. In-flight responses for an old selection are discarded. Already rendered pixels cannot be retroactively unseen. |

## 2. Repository state and constraints recovered

| Boundary | Current `main` evidence | F3 implication |
| --- | --- | --- |
| F2 login/bootstrap | `services/home-bff/home_bff/app.py`, `bootstrap.py`, `frappe_client.py`; `apps/episteck_home/episteck_home/api.py:get_home_bootstrap`; `apps/home-hub/src/integration/home/*`. BFF `/bootstrap` is cookie-bound, `no-store`, strict allowlist, not public through nginx. Viewer comes from the caller's own active Home Delegated Session. | Reuse the existing bootstrap as navigation input. It supplies self plus active care subjects as `personContexts`, membership Circles as `circleContexts`, and no grants or permission booleans. |
| Hub | `apps/home-hub/src/components/providers/AppProvider.tsx` starts with the first bootstrap context and stores selection only in React state. `src/app/layout.tsx` fetches bootstrap on the server. `src/app/page.tsx` and `src/app/nutrition/page.tsx` still choose demo data by presentation mode. | Replace selection state with a typed Person request and server validation. Do not treat the current `PERSONAL` / `CARE_FOR_ANOTHER_PERSON` / `FAMILY` mode or mock keys as identity. |
| Domain state | `src/integration/state/DataEnvelope.ts` has delivery `LOADING/READY/ERROR`, authorization `GRANTED/DENIED/INDETERMINATE`, freshness, environment, and safe error codes. | Keep this envelope; a profile payload discriminant expresses present versus absent. `READY` alone does not mean records exist. |
| Actor and policy | `identity/actor.py`, `identity/auth_hook.py`, `identity/delegation.py`, `policy/access.py`, `policy/wrappers.py`; ADR-0006/0008/0009. `api.check_access(subject_person_id, domain, action)` has no actor parameter. Self access is allowed; cross-person access requires a matching active Consent Grant. | Preserve the server-derived actor. Membership and care relation may reveal navigation context but never satisfy `NUTRITION/VIEW`. |
| Nutrition | `services/nutrition/app/main.py`, `service.py`, `home_control/client.py`, `store/sqlite_repo.py`. `GET /profile/{person_id}` checks Home before `get_profile`, then returns 404 when absent. `/daily` and `/gap-v2` also exist. Nutrition-local consent is audit only. | Use profile read as the first real vertical; preserve Nutrition as source of truth. |
| Delegation | `home_bff/sessions.py` supports `svc-nutrition` audience, 120-second single-use tokens with opaque Home session ID. Internal BFF `POST /delegation` is cookie-bound and blocked at public nginx. | Hub server may mint one Nutrition delegation per operation. Never expose or cache it in the browser. |
| Deployment | `deploy/home-hub/svc-home-hub.container` has `Network=pasta:-T,9933`. `deploy/home-hub/README.md` records that ports 9930/9931/9932/9934 were inaccessible from the Hub during F2 rollout. Nutrition FastAPI is on 9930. | F3b needs a reviewed, narrow server-to-Nutrition transport change and live proof; direct calls cannot work on today's deployed network. Keep the F2 isolation intent. |

The F2 rollout record confirms human OAuth verification and the live Erick-only bootstrap. This proposal does not independently query production. `docs/product/HOME_HUB_F2_SESSION_BOOTSTRAP_PLAN.md` still says “NOT IMPLEMENTED” in its historical header although the F2 code and rollout record show completion. `docs/product/HOME_HUB_INTEGRATION_FOUNDATION.md` places context in F3, Nutrition adapter in F4, and UI migration in F5; this F3 proposal deliberately combines one narrow read through the UI at the user's request. The older foundation also sketches direct Hub → Nutrition access, while the later F2 deployment proof intentionally blocks that port. This proposal requires explicit F3 network review rather than assuming the older sketch is operational. The architecture Roadmap still treats G2 real family/health onboarding as blocked by the Knowledge gate and specific approvals; F3 does not create family topology or Nutrition records under that gate.

## 3. Active-context decision

`activeContext` is **the browser's requested navigation resource**, never an identity claim or authorization decision. F3's canonical live contract is:

```ts
type F3ActiveContext = { kind: 'PERSON'; personId: string };
```

There is no `actorPersonId`, `canViewNutrition`, grant snapshot, relationship, or display name in it. The server obtains display names from a fresh bootstrap. The requester may change `personId`; that change confers no authority. `PERSON` is an intentional one-member discriminated union: a later Circle operation can add `{ kind: 'CIRCLE'; circleId: string }` without treating Circle as a Person or inventing a Nutrition subject now.

| Alternative | Benefit | Cost and decision |
| --- | --- | --- |
| **A: PERSON only** | Matches the first real Nutrition operation and existing Person consent policy; smallest valid subject model. | Circle pages need a later, separate operation contract. **Selected.** |
| B: PERSON + CIRCLE | Mirrors F2 `ResourceScope` and current presentation switcher. | Nutrition has no Circle subject or authorization semantics. A Circle active context would force a fabricated Person mapping or a second domain contract. Deferred. |
| C: free subject ID or server-global selected context | Easy to wire to today's mocks. | Erases resource kind or makes two tabs race on one server state. Rejected. |

### Selection lifecycle and location

1. After login, the fixed `/app` redirect has no context parameter. Default is `bootstrap.viewer.personId` (self), not the first arbitrary array member by accident.
2. The client selector writes a **requested** Person ID to the current `/app` URL query (`?person=PSN-00013`); the URL is the refresh and tab-local source of selection. The selector may use client state only for immediate interaction and loading. There is no BFF session-global active-context row.
3. A Next.js server boundary parses the query with a strict Person ID format and obtains a fresh, session-bound bootstrap. It accepts only self or one of the current `personContexts`. Bootstrap validates navigation eligibility, not `NUTRITION/VIEW` permission. The domain check is still performed by Nutrition.
4. A malformed, deleted, or no-longer-navigable requested Person is **stale context**: clear old data, replace the URL with self, show a short context-changed notice, then make a new self request. Do not return another Person's data under the fallback URL. A valid navigable Person whose Nutrition grant was revoked remains selected and shows `DENIED`; denial never falls back to self.
5. Refresh preserves the query and revalidates it. A fresh login starts at self. A historical URL opened under a new session is revalidated against that session's bootstrap, then falls back to that viewer's self if stale. Logout invalidates the session; a URL alone has no access.
6. Two tabs hold independent URLs and requests. A context switch cancels or disregards the prior in-flight result using the requested context key and request generation. Data for subject A cannot paint under subject B.

Person IDs in the URL are navigation selectors, not secrets or authority, but they are personal metadata. F3 must keep `Referrer-Policy: no-referrer`, strip query strings from access logs and telemetry, avoid third-party links carrying the query, set all sensitive responses `Cache-Control: no-store`, and avoid embedding domain data in share previews. This Board-accepted choice gives refresh and tab isolation without persisting a selection across login.

**Board-accepted discoverability limit:** F2 bootstrap exposes self and active-care subjects, not grant-only subjects or Circle co-members as Person contexts. Thus a grant-only Person without a care relationship is not selectable in the F3 UI. The first cross-person live topology should include a real care relationship for navigation **and** a distinct Consent Grant for data access. Care Relationship is navigation/discoverability only; it **never** authorizes `NUTRITION/VIEW`. Grant-only discovery is deferred and cannot later replace the domain check.

## 4. Actor, subject, and operation contract

| Field | Source | May browser supply it? | Example |
| --- | --- | --- | --- |
| Actor Person | Home authenticated session → Frappe User → unique `Person.linked_user`, resolved by Home on the delegated request | **No** | Erick `PSN-00013` |
| Requested subject Person | Validated active Person context | Yes, as an untrusted selector | Erick now; Ana after onboarding |
| Domain/action | Fixed by the Nutrition profile read code path | **No** | `NUTRITION` / `VIEW` |
| Decision | Fresh Home `can_access` evaluation through Nutrition | **No** | literal allow or deny |

Proposed browser-to-Hub request shape is a route/query Person selector only. Proposed Hub adapter signature is conceptually `readNutritionProfile(requestedContext, requestSession): Promise<DataEnvelope<ProfileSummary>>`; it has **no actor argument**, no client-chosen domain/action, and no client-supplied delegation. The Nutrition endpoint's existing `person_id` path parameter is the subject. The actor is never serialized into the call. The BFF's mint uses the session cookie and fixed `svc-nutrition` audience; Home's policy call receives the subject and fixed domain/action and derives the actor itself.

### Home policy-boundary subject-existence invariant

**Before any positive authorization decision, Home must establish from its current Person system of record that the subject Person exists.** Missing, deleted, malformed, or unresolvable subjects fail closed. This invariant applies to `check_access(...)`, `check_access_many(...)`, and every future equivalent authorization entry point, for self and cross-person requests alike. An `ALLOW` from the pure policy evaluator cannot be exposed as an authoritative decision unless this existence condition has been satisfied in the same server-side authorization operation. No downstream domain repository read may follow a missing-subject decision.

The eventual implementation should put the check in a **shared Home policy-boundary helper**, used by single and batch APIs, instead of duplicating it in each Frappe method. `check_access_many` must fail the whole request and return no positive per-requirement decision when the subject is missing; at most, an existence result may be reused within that one request. It must not be cached across requests. A missing subject and an unauthorized subject have the same user-visible denial shape and generic reason: neither the status nor message may disclose which condition occurred. Internal audit may retain a safe reason category without returning an existence oracle.

The load-bearing race is: bootstrap validates a Person → that Person is deleted → Nutrition asks Home for authorization. Bootstrap's earlier navigation result cannot authorize the read. The fresh Home policy-boundary existence check must prevent `ALLOW`, even if an orphaned Consent Grant remains. The current `policy/wrappers.py:check_access` feeds the pure evaluator without checking subject existence; `api.check_access_many` calls that wrapper per requirement. This is a cross-API policy-boundary correction, not a Nutrition-only exception.

## 5. First real vertical and server adapter

**Selected:** authorized Nutrition profile summary from existing `GET /profile/{person_id}`. It is a read-only, person-specific operation with exactly one existing Home policy check before the repository read. A 404 after authorization has a clean “no profile” meaning. The Home mapper should expose only a small safe summary: profile context, target source, and the count of configured targets (plus a display name from bootstrap). It must validate shape and bounds; it must not copy raw profile preferences, dislikes, pregnancy notes, or arbitrary fields into the Hub. When the profile is absent, the mapper produces explicit no-profile presence, not zero targets. `updatedAt` remains absent because the existing repository does not return its stored update timestamp.

`GET /daily/{person_id}/{date}` is deferred: its empty intake and gap maps can look like zero consumption when no records exist. `GET /gap-v2` is valuable later for the pregnancy screen, but depends on a real profile and richer missingness semantics. The current mock calorie, macro, hydration, burned-calorie, supplement, and family-meal fields cannot be inferred honestly from the profile route.

The precise first UI replacement is `apps/home-hub/src/app/nutrition/page.tsx`: replace its mock calorie/macro summary cluster with one real **Nutrition profile** panel in LIVE mode. It shows present/absent/denied/unavailable states. Keep the current Today and pregnancy mock surfaces visibly marked as demo until their own verticals are designed; do not present their figures as part of the live profile. A client selector initiates navigation; a server route/component owns the profile fetch and returns only the mapped envelope. The existing root layout and bootstrap remain the session gate. No browser call to Nutrition or the internal delegation endpoint is introduced.

### Request sequence

```text
Browser: GET /app/nutrition?person=S with opaque HttpOnly cookie
  → Hub server: read cookie; request BFF /bootstrap with no-store
  → BFF: validate local session; Control Plane get_home_bootstrap(own session)
  → Hub server: validate S as a current Person navigation context
  → Hub server: POST loopback BFF /delegation?audience=svc-nutrition,
                forwarding only this request's session cookie
  → BFF: validate session and mint one short-lived, single-use Nutrition delegation
  → Hub server: GET Nutrition /profile/S with delegation header
  → Nutrition: call Home check_access(S, NUTRITION, VIEW) once,
               using Nutrition machine credential + delegation
  → Home shared policy boundary: independently resolve human actor;
          establish current subject Person existence before any ALLOW;
          evaluate current Consent Grants (self access or exact grant)
  → Nutrition: read profile only after literal ALLOW; return profile or 404
  → Hub server: validate and minimize the domain response; map safe envelope
  → Browser: render only the envelope for the current S
```

This matches the implemented Nutrition authorization order and single-use behavior in `service.py` and `home_control/client.py`. The shared subject-existence invariant above is the required Home policy-boundary adjustment. Other missing work is the Hub adapter, transport reachability, strict response mapping, and a typed distinction between explicit denial and indeterminate policy failure. The BFF remains the session/delegation issuer, the Hub server is a presentation adapter, Home is the identity/policy authority, and Nutrition remains the profile owner. Do not add Nutrition business tables or target calculations to Home.

**Board-accepted network principle for F3b:** retain Hub → BFF port 9933 and add only a narrow Hub server → Nutrition FastAPI port 9930 path. The deployment must empirically prove the exact Podman/pasta configuration: Hub → 9933 reachable; Hub → 9930 reachable; Hub → 9931/9932/9934 unreachable; public → 9930 unreachable. If that isolation cannot be proven, stop the rollout and return evidence for a new transport decision. `Network=host` and broad network exposure are not approved fallbacks.

**F3b implementation note (D1, 2026-10-06):** as deployed by G1.6, Home verified every
delegation against `home-control-plane` only, so a `svc-nutrition` delegation could not
bind. F3b.1 makes Home accept `svc-nutrition` only from Nutrition's machine credential
and only at the policy entry points. See
`docs/superpowers/specs/2026-10-05-home-f3b-nutrition-adapter-design.md` D1–D3.

## 6. Response and UI state contract

Preserve the existing `DataEnvelope<T>` axes and `SafeUIErrorCode`. For this vertical, `T` is a narrow discriminated profile summary:

```ts
type ProfileSummary =
  | { presence: 'PRESENT'; context: string; targetSource: string; targetCount: number }
  | { presence: 'ABSENT' };
```

| Product state | Envelope projection | UI behavior |
| --- | --- | --- |
| `LOADING` | `delivery=LOADING`, `authorization=INDETERMINATE`, no data | Clear prior subject data; show loading for current subject. |
| `READY_WITH_DATA` | `READY`, `GRANTED`, `LIVE`, `data.presence=PRESENT` | Show real profile summary and Nutrition provenance. |
| `READY_NO_DATA` | `READY`, `GRANTED`, `LIVE`, `data.presence=ABSENT` | Show no-profile state; no zeros or demo values. This proves the real read and authorization chain, not populated profile rendering. |
| `DENIED` | `ERROR`, `DENIED`, `ACCESS_DENIED`, no data | Access restricted; preserve selected context. |
| `UNAVAILABLE` | `ERROR`, `INDETERMINATE`, `SERVICE_UNAVAILABLE` or `OFFLINE`, no data | Service unavailable and retry. |
| `ERROR` | `ERROR`, `INDETERMINATE`, `INVALID_RESPONSE`, no data | Safe error; no raw upstream body. |
| `STALE_CONTEXT` | Server selection result outside the domain envelope; no domain call for stale S | Clear old data, replace URL with self, show notice, then fetch self. |

`RESOURCE_NOT_AVAILABLE` / `NOT_CONFIGURED` currently exist as safe codes, but the first profile 404 should map to an **authorized absent profile**, not a delivery error. This is an F3 refinement of the older F0 mapping. A malformed domain 404 from another route must never be treated as absence. A 401 from BFF means login/session invalid; 403 from Nutrition is `DENIED` **only when Nutrition has a definite policy denial**. Current Nutrition code maps both a literal Home deny and an indeterminate/unreachable Home response to `PermissionError` → HTTP 403. F3b must preserve fail closed data access while returning distinct, sanitized outcomes for an invalid delegated session, an explicit policy denial, and indeterminate policy availability. Its Home client must reject malformed allow responses, including a missing or invalid reason, rather than treating an isolated `allow: true` as sufficient. Until that adjustment, the UI must not pretend it can distinguish those causes. Any 200 payload that fails strict schema validation becomes `INVALID_RESPONSE` with no partial data. LIVE mode never calls a mock fallback.

## 7. Freshness and cache rules

| State | F3 rule |
| --- | --- |
| Identity/session | BFF may retain its existing opaque 12-hour session and tokens in its private store. Each operation validates the session for minting; Home validates the delegated session on the Nutrition policy call. No actor cache in Hub. |
| Navigation/bootstrap | Fetch with `no-store` at server render/selection; a bootstrap list is presentation eligibility, not permission. Do not persist it as authority. An already open UI refreshes on focus and context change. |
| Authorization decision | No cross-request cache at Hub, BFF, Nutrition, CDN, or browser. Exactly one fresh Home decision per Nutrition profile operation; request-local decision use is limited to that one operation and its repository read. Revocation is effective on the next sensitive operation. |
| Domain data | `cache: 'no-store'`, dynamic server rendering, `Cache-Control: private, no-store` on responses, no Next.js Data Cache/Full Route Cache or CDN cache for person data. No stale-while-revalidate. A client may hold only the current rendered result until a new operation; clear it on context change, focus recheck, logout/session failure, or denial. |
| Delegation | One audience, one protected operation, one Home authorization request; never persisted, logged, returned to browser, reused, or retried. A user retry mints a new token. |

## 8. Family topology and sequencing

**Stage 1:** Erick self context and a read-only Nutrition profile operation. No new Person, Circle, membership, care relation, or grant is necessary. The current live Nutrition profile for `PSN-00013` has **not** been inspected by this architecture work. The Board accepts an authorized `ABSENT` result as sufficient for F3's first live end-to-end integration proof if no profile exists. Evidence must say **authorized no-profile response**, never **populated profile rendered**. Do not create a Nutrition profile to fill the demo. Real data onboarding remains a separate decision under the canonical Roadmap's G2 gate.

**Stage 2, only when authorized for real onboarding:** create Ana as a distinct Person, add a care relationship if Ana should appear in the F2/F3 Person selector, and create an explicit `NUTRITION/VIEW` Consent Grant from the proper grantor. A family Circle and memberships are needed only for an actual family workflow; neither changes Person Nutrition authorization. Prove cross-person allow, deny, and revocation first with synthetic test fixtures, then with approved real records. Do not assign Ana a synthetic login or treat co-membership as consent.

## 9. Threat model disposition

| Threat or fault | Required deterministic behavior |
| --- | --- |
| Browser edits `personId` | Server checks format and current bootstrap navigation candidates. Guessing an undiscoverable ID yields stale/invalid context with no Nutrition call. Even a navigable ID gets a fresh Nutrition policy check. |
| Browser edits Circle ID | F3 Person parser rejects it; no Nutrition call or member substitution. |
| Browser forges `actor_person_id` | No actor field in active context, Hub adapter, BFF mint, Nutrition route, or Home `check_access`. Reject unexpected identity fields where a structured request body exists; query noise cannot change actor. |
| Stale bootstrap | Re-fetch on server operation; bootstrap never authorizes domain data. Failed refresh cannot reuse prior eligible list to call Nutrition. |
| Revoked Consent Grant | Next Nutrition operation gets literal deny before repository read; clear prior panel on recheck. |
| Removed Circle membership | Circle navigation disappears on fresh bootstrap. It never controls Person Nutrition permission; any separate affected Person eligibility is recomputed. |
| Context from previous session | New login defaults to self. A historical URL is revalidated against the new session, then falls back to that viewer's self with a notice if stale. |
| Deleted Person | Fresh bootstrap/navigation validation rejects it. If deletion races after bootstrap, the shared Home policy-boundary check confirms subject existence at authorization time; missing means no positive decision and no repository read. The user sees the same generic denial as other unauthorized subjects. |
| Disabled User | Frappe session/bootstrap and delegated actor resolution refuse; login/session error, no data. |
| Expired BFF session | `/bootstrap`/mint refuses; redirect to login, clear client domain data. |
| Nutrition cannot reach Home | No repository read. F3b maps indeterminate policy availability to sanitized unavailable, never granted/empty. |
| Home returns malformed authorization | Nutrition accepts only literal well-formed `allow: true`; otherwise no repository read and unavailable/error classification. |
| Nutrition returns malformed response | Hub strict mapper rejects entire payload as `INVALID_RESPONSE`, no partial render. |
| Two tabs use different contexts | URL is tab-local; no BFF session-global context; responses are bound to their request's subject. |
| Context changes during in-flight read | Clear prior data; abort or discard old response by subject/generation; old subject cannot paint under new selection. |
| Cached response after revocation | No shared or cross-request sensitive cache, `no-store` throughout. On next operation re-authorize; no stale result served. |

## 10. F3 implementation phases for later review

Each phase is a separate, reviewable PR. The table remains the approved scope contract for each phase.

| Phase | Scope and code areas | Acceptance and security checks | Live verification and non-goals |
| --- | --- | --- | --- |
| **F3a — Person context** | `apps/home-hub/src/components/providers/AppProvider.tsx`, typed context/URL parser under `src/integration/home`, server selection boundary, `/nutrition` navigation. Self default, refresh, tab isolation, stale handling. | Invalid Person/Circle/actor injection rejected; care-only candidate navigable but no domain permission asserted; stale URL clears old data. | Human login still lands on Erick self; two tabs and refresh behave independently. No Nutrition call, Circle domain semantics, or topology mutation. |
| **F3b — Nutrition server adapter** | `src/integration/nutrition/*` server-only adapter; existing BFF `/delegation`; `services/nutrition/app/home_control/client.py`, `service.py`, `main.py` for typed deny versus indeterminate; shared subject-existence guard under `apps/episteck_home/episteck_home/policy/`, consumed by `api.check_access`, `api.check_access_many`, and future policy entry points; reviewed `deploy/home-hub` narrow port 9930 forwarding. | One mint and one Home policy call per profile operation; no actor input; all positive decisions require a currently existing subject; deleted subject and deny/unknown never read the repository; strict policy/profile response validation; no token/browser exposure. | Host proves 9933 and 9930 reachable from Hub, 9931/9932/9934 not, and public 9930 inaccessible. `Network=host` and broad exposure are excluded. No new domain or policy cache. |
| **F3c — one live page** | `apps/home-hub/src/app/nutrition/page.tsx` and its small profile presentation boundary. Replace mock Nutrition summary cluster in LIVE with profile present/absent/error panel. | All six product states are distinct; current subject visible; no fabricated calories, targets, or mock fallback; stale in-flight result discarded. | Authenticated Erick sees a real service-derived profile or truthful no-profile panel. Today, pregnancy, Mealie, and other mock surfaces stay clearly demo. |
| **F3d — negative and live validation** | Focused tests in Hub, BFF boundary, Home policy, Nutrition; deployment/runbook evidence in `deploy/home-hub/README.md` and Home status docs after approval. | Cross-person allow/deny/revoke with fixtures; single/batch/future-equivalent policy entry points deny missing subjects without an oracle; bootstrap-then-delete race; actor substitution, stale context, disabled/expired session, malformed responses, Home outage, tab races, and no-cache assertions. | Read-only production verification for Erick; approved real cross-person checks only after separate topology/data authorization. No production fixture creation as a testing shortcut. |

**F3a implementation status (2026-09-27):** PR #50 merged the Person-only active-context type, strict query resolver, session-bound `POST /app/api/context` validation, URL selection, stale-to-self canonicalization, focus revalidation, query-preserving links, and keyed presentation reset. The route reuses the existing no-store bootstrap request; the browser supplies no actor. MOCK Family remains a separate presentation choice and cannot become an active Person. A Hub image built from `7739dab807873270163f62b8b9d3511c9f46b585` was deployed briefly and rolled back because the live nginx access-log format included query-bearing `Referer` headers. See `deploy/home-hub/README.md` for sanitized evidence. **2026-10-05:** after the nginx log-hygiene correction, a Hub image built from `b1a3d5f7cc58b58968a3250b752a1dab37d0fa8b` (byte-identical Hub source and image ID to `7739dab`) was rolled out and the authenticated live matrix passed: Erick self default, stale/malformed/Circle/duplicate requests canonicalized to self, asserted actor rejected, refresh, two-tab isolation, focus revalidation, history, `no-store`, and logs free of IDs/credentials/query strings. F3a is closed; F3b/F3c/F3d remain open.

## 11. Acceptance matrix and live proof

| Case | Setup and action | Required observation |
| --- | --- | --- |
| Self context | Erick OAuth login → self default → profile request | Home resolves actor `PSN-00013`; subject `PSN-00013`; subject exists at authorization time; `NUTRITION/VIEW` self allow; Nutrition responds with a real profile summary **if present** or authorized `ABSENT` if not. No mock values. Authorized `ABSENT` passes the initial live path proof, without a populated-data claim. |
| Cross-person allow | Synthetic actor Erick, another Person navigable through care, active `NUTRITION/VIEW` grant | Fresh Home allow; Nutrition reads only that subject; Hub renders the subject's profile. Live version awaits approved real topology. |
| Cross-person deny | Same navigable Person, no matching active grant | HTTP/domain deny before profile repository read; no subject data, no self fallback. |
| Revocation | Initial grant allows; revoke; request again | Next operation denies with zero new domain disclosure; no cached allow/result. |
| Actor substitution | Send actor field/query/header and forged delegation | Actor never changes; unsupported input rejected/ignored safely, forged delegation denied. |
| Stale context | Remove navigation eligibility or open prior-session URL | Fresh validation clears old data and routes to current viewer self with notice; no call for stale subject. |
| Subject deleted after bootstrap | Bootstrap validates another Person; delete that Person before Nutrition's Home authorization, with an orphaned grant if needed | Shared policy boundary returns no positive decision from `check_access` or `check_access_many`; all future equivalent entry points obey the same invariant; zero Nutrition repository reads; generic denial does not reveal whether the Person exists. |
| Domain failure | Stop/unreach Nutrition or Home policy | Unavailable state, no fake data; a retry uses fresh delegation. |
| Absent profile | Authorized subject has no Nutrition profile | `READY_NO_DATA`, not `0`, `DENIED`, or transport `ERROR`. |
| Concurrent tabs/in-flight switch | Different Person URL per tab; switch during delayed response | Independent selections; late response discarded; no cross-subject paint. |

**Architecture-task verification:** inspect only repository code and existing rollout records; do not query or change production. During a later implementation rollout, capture the exact deployed SHAs, F3 narrow network proof, authenticated BFF/bootstrap evidence, a single Nutrition request trace showing one Home policy decision, response classification, no sensitive cache headers, and logs free of IDs/credentials. If Erick's profile is absent, record an **authorized ABSENT end-to-end proof** and stop there; do not seed a profile for display. Live cross-person consent and populated self profile are gated by real-data authorization; synthetic tests prove those branches before any real topology exists.

## 12. Board disposition and remaining gates

The Board accepts Person-only F3 active context; URL-carried requested Person with fresh server validation; session-derived actor and context-derived subject; Nutrition Profile as the first vertical; an authorized `ABSENT` result as the first live end-to-end proof if the profile is absent; self plus active-care Person discovery; a narrow Hub-server → Nutrition port 9930 path in principle; and distinct `DENIED` versus indeterminate/unavailable outcomes, with both failing closed for data access.

The Board requires the shared Home policy-boundary subject-existence invariant in §4 before **any** positive authorization decision, including single, batch, and future equivalent entry points. The deletion race and no-oracle behavior are acceptance requirements, not optional hardening.

**Open Board architecture questions: none.** F3b still has an empirical Podman/pasta isolation gate before deployment. Populated-profile rendering and real cross-person topology remain outside the first live proof; no production records are created to satisfy them. These are implementation and real-data authorization gates, not unresolved choices about the F3 trust model.
