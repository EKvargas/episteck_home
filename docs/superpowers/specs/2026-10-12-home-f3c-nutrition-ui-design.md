# Home F3c — Nutrition UI wiring: design

**Date:** 2026-10-12
**Status:** Approved 2026-10-13; revised 2026-10-13. Implemented in PR-A #104 and PR-B #<PR-B>; gate R4 not yet run. Implementation plan: docs/superpowers/plans/2026-10-13-home-f3c-nutrition-ui.md
**Parent architecture:** `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` (Board-approved, PR #48), phase F3c (§10) and acceptance matrix (§11).
**Predecessor:** `docs/superpowers/specs/2026-10-05-home-f3b-nutrition-adapter-design.md`. F3b is LIVE on Nuremberg (rollout gate R3 PASS, 2026-10-12, PR #91 merge `89e0550`, evidence PR #98 merged).
**Baseline:** `origin/main` `2096e60`.

## Purpose

Replace the mock Nutrition cluster on `/nutrition` with a real, server-rendered panel driven by `readNutritionProfile`, keeping every F3b invariant. F3c is the first live caller of the adapter.

**Success criteria**
- In LIVE, `/nutrition` shows no mock value. It shows the validated subject and exactly one of: profile on file, no profile, access restricted, session expired, unavailable, invalid response, not configured, or a loading skeleton.
- An authorized `ABSENT` profile renders an honest empty state: no zeros, no rings, no mock.
- One mint and one Nutrition call per page load; `no-store`; no delegation or cookie reaches the browser. A stale `?person=` link makes no call for the stale ID and exactly one call after the client canonicalizes the URL to self.
- MOCK mode renders today's demo unchanged.

## Revision 2026-10-13

Changes after the plan review, all within the settled decisions:

- **Stale selection makes no read.** The server renders the loading panel for a stale `?person=` and does not call Nutrition; the client's canonical self URL makes the one read. (Previously the stale render read self, and the result was never shown.)
- **The bootstrap on the panel path is bounded and shared.** `loadBootstrap` gets the same per-fetch timeout and body drain, and `getBootstrapForRequest` is wrapped in React `cache()` so the layout and the panel share one read per server render. The panel's worst case is now bounded (it was unbounded, not 8 s).
- **The whole panel path is guarded.** Any throw (bootstrap, subject, adapter) renders `UNAVAILABLE`; Next's own control-flow errors are rethrown with `unstable_rethrow`.
- **One log line per panel render** with a fixed vocabulary gives R4 an ID-free count of reads.
- **Back/Forward behavior is documented**, not claimed away: Next restores history entries from its client router cache.
- Try again uses `router.refresh()`; "header renders immediately" is corrected; copy updates; `'use server'` guard narrowed to Nutrition.

## Decisions (settled with the operator)

| ID | Decision |
| --- | --- |
| **S1** | **Scope A.** F3c stays within the current `ProfileSummary` (`presence`, `context`, `targetSource`, `targetCount`). No contract widening, no Nutrition or Home change. Showing named targets (calories, macros) is a separate future spec that touches Nutrition/Home and needs its own review. |
| **S2** | **Stream with Suspense.** The page content (title, switcher, panel) appears once the client has validated the selection through `POST /api/context` (F3a `AppProvider`); meanwhile the server runs the Nutrition read in parallel and the panel streams behind a skeleton. Every Hub fetch on the panel path (bootstrap, mint, profile) gets `AbortSignal.timeout(4000)`. The layout and panel share one bootstrap, so the shell is bounded at about 4 s and the panel at about 8 s more. A timeout renders the `SERVICE_UNAVAILABLE` panel with Try again. |
| **S3** | **Read-only live proof (R4).** Production is observed only. Error states are proven by automated tests against fake upstreams; the live record labels each state "observed live" or "tests only". No fault drill, no fixtures. |
| **S4** | **LIVE hides the whole mock cluster** on `/nutrition` (calorie ring, macros, Mealie card, Ana pregnancy card). `/nutrition/pregnancy` is out of scope and unchanged; in LIVE it loses its only in-app link (the demo card's "View Dashboard"), stays reachable by URL, and keeps its demo banner. Accepted. |

## Findings from exploration

1. `/nutrition/page.tsx` is a `'use client'` component over `getTodaySummaryMock`. `readNutritionProfile` is `server-only`, so the live path needs a server component. The client `AppProvider` result cannot be handed to the server, so the server re-derives the context itself.
2. `AppShell` renders a global banner, "DEMO / MOCK DATA — domain content is illustrative and is not data or access for the selected person", because `layout.tsx` passes `demoContent` unconditionally. On a live `/nutrition` that banner would contradict real data. It must not show on `/nutrition` in LIVE, and must remain on every other page.
3. `F3ActiveContext` is a plain object type. Any code can build `{ kind: 'PERSON', personId }`, so "only `resolveRequestedPerson` output reaches the adapter" is currently a convention, not a guarantee.
4. `loadNutritionProfile` fetches have no timeout. A hung upstream stalls the render for the platform default (about 300 s). Unread response bodies on early-return paths are not cancelled. `loadBootstrap` has the same gap, and the panel re-reads the bootstrap.
5. `playwright.config.ts` already starts `test-support/fake-bff.mjs` (port 3323) and the LIVE Hub on 3322, with `HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930` and no fake behind it. A fake Nutrition server is the missing piece for end-to-end state coverage.
6. Known Nutrition code values are `PREGNANCY` (context) and `REFERENCE_TARGET` / `USER_CONFIGURED` (target source). The set is open, so the UI must tolerate unknown codes.
7. `AppProvider` renders "Loading context…" in place of page children until `POST /api/context` validates the selection (`e2e/bootstrap.spec.ts` asserts the document HTML says "Loading context"). On `STALE_CONTEXT` it replaces the URL with self before it ever shows children. So the server-rendered panel is first visible after hydration, and a stale URL's server render is never shown.
8. Next's client router restores Back/Forward history entries from its in-memory cache without a new server render.
9. `next build` deletes `.next` before compiling (Next 16.3.5 `dist/build/index.js:623`), and `test:server-boundary` runs two builds that fail on purpose. Anything that needs a build must run before it, or after a rebuild.

## Invariants (carried from F3b; F3c must not weaken any)

- The subject comes only from a validated `F3ActiveContext`. No actor, domain, or action input exists on this path.
- Exactly one delegation mint and one Nutrition call per read. No retry inside a request; Try again is a new server render (`router.refresh()`), with a new mint.
- No cache anywhere: `no-store` on the page response, no `unstable_cache`, no `revalidate`, no module-level memo of profile data. Two bounded exceptions, both stated: (a) the bootstrap is memoized per server render with React `cache()` so the layout and panel share it; it never crosses requests and holds no profile data; (b) Next's client router restores Back/Forward history entries from memory, so Back shows the panel as it was rendered for that entry, without a new read. Any new navigation, Try again, or reload reads again.
- No mock substitution in LIVE, including on error. The view model also maps any non-LIVE `READY` envelope to `UNAVAILABLE`.
- The delegation and the session cookie never reach the browser. No Person ID appears in the HTML other than the visible, already-validated subject.
- Missing and unauthorized subjects render the same Access restricted panel.
- No production fixtures, Persons, grants, or profiles are created. ABSENT is a valid live proof.
- Logging: the Hub writes exactly one line per panel render, `nutrition.profile outcome=<LABEL>`, from a fixed vocabulary (`PRESENT`, `ABSENT`, a `SafeUIErrorCode`, `STALE_SKIPPED`, `BOOTSTRAP_SESSION`, `BOOTSTRAP_UNAVAILABLE`, `THREW` with the error class name). No IDs, names, URLs, query strings, or tokens are ever logged.

## Architecture

```text
Browser GET /nutrition?person=…
  layout.tsx (existing): getBootstrapForRequest() [React cache()] → login redirect | AppProvider | AppShell
  nutrition/page.tsx  (server component)
    MOCK  → <NutritionDemoCluster/>            (client, today's demo, moved unchanged)
    LIVE  → <NutritionHeader/>                 (client: title, switcher)
            <Suspense key={raw person selector} fallback={<ProfilePanel model=LOADING/>}>
              <LiveProfilePanel searchParams/>  (async server component; whole body in try/catch)
                resolveLiveSubject(searchParams) → reuses the layout's bootstrap
                                                 → context + name + stale | session | unavailable
                stale → LOADING model, no read   (the client canonicalizes the URL to self)
                readNutritionProfile(context)    → DataEnvelope<ProfileSummary>
                log "nutrition.profile outcome=<LABEL>"
                toProfilePanelModel(envelope, subjectName) → ProfilePanelModel
                <ProfilePanel model/>            (pure presentation)
```

### Components

| Unit | Purpose | Depends on |
| --- | --- | --- |
| `integration/state/fetch-timeout.ts` | `FETCH_TIMEOUT_MS = 4000`, `isAbortError`, `discardBody`. One budget for every Hub fetch on a page render. | — |
| `integration/home/bootstrap-loader.ts` + `bootstrap.server.ts` | Bootstrap read with the per-fetch timeout and body drain; `getBootstrapForRequest` wrapped in React `cache()` (request-scoped). | `fetch-timeout` |
| `integration/nutrition/profile-panel-model.ts` | Pure `toProfilePanelModel(envelope, subjectName)` → discriminated `ProfilePanelModel`, exhaustive `never` check; `outcomeLabel(envelope)` for the log line. No React, no server imports; unit-testable under `node --test`. | `DataEnvelope`, `ProfileSummary`, `SafeUIErrorCode` |
| `integration/nutrition/live-subject.ts` + `.server.ts` | `pickSubject` (pure) and `resolveLiveSubject(searchParams)`: request bootstrap + `resolveRequestedPerson()`; returns the branded context, the subject's display name, and the stale flag, or a session/unavailable result. The only producer of the context passed to the adapter. | `bootstrap.server`, `active-context` |
| `components/features/nutrition/ProfilePanel.tsx` (+ `.module.css`, `RetryButton.tsx`) | Renders one `ProfilePanelModel`. Server-safe, no hooks, no env access. `RetryButton` is the one client piece (`router.refresh()`). | model type only |
| `app/nutrition/LiveProfilePanel.tsx` | Async server component wiring the above. Wraps the whole path in try/catch (rethrowing Next control flow), skips the read on a stale selection, writes the one log line. The only importer of `profile.server.ts`. | all above |
| `app/nutrition/NutritionDemoCluster.tsx` | Today's page body, moved verbatim, `'use client'`. Rendered only when mode is MOCK. | mocks |
| `app/nutrition/page.tsx` | Server component: branch on `SERVER_CONFIGURATION.mode`. | the two above |
| `AppShell` + `layout.tsx` | New `liveRoutes` exact-match list. In LIVE the layout passes `['/nutrition']`; `AppShell` suppresses the demo banner when the pathname is in it. MOCK and every other route keep the banner. | — |

### Subject resolution and staleness

`resolveLiveSubject` reads `searchParams.person` as a list, calls `resolveRequestedPerson`, and uses the returned `activeContext`. A `STALE_CONTEXT` result resolves to self, matching F3a canonicalization. On a stale render the server does not call Nutrition at all: it renders the loading panel and logs `STALE_SKIPPED`. `AppProvider` replaces the URL with self before it shows children, and that render makes the one read. The server never returns another Person's data under the fallback. A valid navigable Person whose grant was revoked stays selected and renders Access restricted; denial never falls back to self.

Accepted narrow race: if the client's bootstrap (fetched a moment later) disagrees with the server's because the care topology changed in between, the client keeps the URL and the panel stays in its loading state until the next navigation or reload.

`<Suspense>` is keyed on the raw `person` selector (the validated ID is not known before the bootstrap). Together with F3a's keyed provider reset, a response for subject A cannot paint under subject B. The server render is per request; Back/Forward restores the entry's own earlier render (see Invariants).

The panel calls `getBootstrapForRequest()`, which reuses the layout's read for this request through React `cache()`: a fresh, session-bound bootstrap, never a value handed over by the browser. `/api/context` is a route handler and still reads its own.

### Panel states

| Envelope | Model | Panel |
| --- | --- | --- |
| streaming | `LOADING` | Skeleton: "Checking Nutrition profile…" (`role="status"`, `aria-busy`). The fallback carries no name: the subject is not known before the bootstrap. |
| stale `?person=` | `LOADING` (no read) | Never visible: the client canonicalizes the URL first. |
| READY / PRESENT | `PRESENT` | "Nutrition profile on file" for {name}: profile type, target source, "N configured" or "None configured", and a "Source: Nutrition service" badge. States that target values are not shown on this page yet. Codes use a small label map (`PREGNANCY` → Pregnancy, `GENERAL` → General, `REFERENCE_TARGET` → Reference targets, `USER_CONFIGURED` → Personalized targets) and fall back to a humanized code. No numbers are invented. |
| READY / ABSENT | `ABSENT` | "No nutrition profile for {name}." No zeros, rings, mock, or create CTA (onboarding is gated). |
| ERROR / `ACCESS_DENIED` (DENIED) | `DENIED` | "Access restricted." Identical for missing and unauthorized subjects; no reason text; subject stays visible; no fallback to self. |
| `SESSION_INVALID`, `SESSION_REQUIRED` | `SESSION` | "Your session has expired" with a sign-in link to `/login`. No redirect (headers are already sent when streaming). |
| `SERVICE_UNAVAILABLE` (includes timeout and any throw) | `UNAVAILABLE` | "Nutrition is temporarily unavailable" plus Try again (`router.refresh()`: a new server render and a new mint). |
| `INVALID_RESPONSE` | `INVALID` | Distinct "This profile could not be shown safely" plus Try again. |
| `NOT_CONFIGURED` | `NOT_CONFIGURED` | "Nutrition is not set up on this Hub." No retry, no env var names. |
| unmapped code (`OFFLINE`, `RESOURCE_NOT_AVAILABLE`), or a non-LIVE / non-GRANTED `READY` | `UNAVAILABLE` | Fails safe to unavailable; covered by the exhaustive test. |

The parent architecture counts "six product states"; F3c maps them as PRESENT, ABSENT, DENIED, UNAVAILABLE (with INVALID as its own distinct panel), SESSION, and LOADING, plus NOT_CONFIGURED, which is an operator condition. The full set is eight models; this is a deliberate refinement, not a contradiction of the six.

Errors render `role="alert"`; loading and empty states `role="status"`. The page `<h1>` stays "Nutrition Hub". The LIVE page adds no second `<main>` landmark (`AppShell` already renders one). Panel copy avoids the prototype-claims vocabulary ("authorized", "Consent required", "live data", …) and internal service names.

## Entry criteria from the F3b.3 final review (early tasks)

1. **Timeouts and body drain.** `AbortSignal.timeout(4000)` on both fetches in `profile-loader.ts` and on the bootstrap fetch in `bootstrap-loader.ts`; every early-return path cancels the unread body; a body read aborted by the timeout is `SERVICE_UNAVAILABLE`, not `INVALID_RESPONSE`. `getBootstrapForRequest` is wrapped in React `cache()`. Tested with fake fetchers that never resolve (injectable timeout so tests are fast), a real socket that stalls after the headers, and fake bodies that record `cancel`.
2. **No client-reachable adapter.** `readNutritionProfile` must never be reachable via a `'use server'` action or a route taking a client-supplied context. `test:server-boundary` gains a static check: no `'use server'` module and no `route.ts` may import the Nutrition integration, the only allowed importer of `profile.server.ts` is `app/nutrition/LiveProfilePanel.tsx` (a server component), and `profile.server.ts` must verify the context before reading cookies. The existing build-time probe (client import fails on `server-only`) stays.
3. **Branded context.** `F3ActiveContext` becomes a branded type. `resolveRequestedPerson` is the only issuer; issued objects are frozen and registered in a `WeakSet` stored on `globalThis` under a `Symbol.for` key, so it is shared across Next.js per-layer module instances (see plan Task 2). `readNutritionProfile` verifies registry membership at runtime. A cast object literal, a spread copy, or the JSON copy the browser receives makes `readNutritionProfile` throw a `TypeError` before any cookie read or network call (a programming error, not an envelope state; the panel layer's try/catch renders `UNAVAILABLE`). Tests cover forged literal, spread copy, and JSON round-trip. The context type is erased by `--experimental-strip-types`, so the runtime registry is the real guard.
4. **Optional cleanups** (one small task): `ProfileContractError.name`; contract regression tests (`1e999`, `Infinity`, `0x10`, `__proto__` key); case-insensitive header-isolation test; Quadlet test reading the `Network=` value instead of hard-coding it.

## Error handling

- The adapter returns an envelope for every upstream failure. The panel layer wraps the whole path (subject resolution, adapter call, mapping) in one try/catch, so any throw renders `UNAVAILABLE`, never a framework error page and never mock. The catch calls `unstable_rethrow` first so Next's redirect and dynamic-rendering signals are not swallowed. The app has no `error.tsx`, so this catch is the only guard.
- An unavailable bootstrap inside the panel renders `UNAVAILABLE`; a session failure there renders `SESSION` (the layout has already handled the common dead-session redirect).
- Logging is the one fixed-vocabulary line per panel render (see Invariants). Nothing logs envelope internals, IDs, or tokens.

## Testing

- **Unit (`node --test`):** panel-model mapping for every envelope and error code (exhaustive), the non-LIVE guard, and `outcomeLabel`; branded-context issuance and forgery cases; loader and bootstrap timeouts, body-stall timeout, drain, and the cleanup regressions; a static check that the bootstrap is `cache()`-wrapped; Quadlet network test.
- **Server boundary:** extended `test:server-boundary` as above.
- **E2E (Playwright, LIVE mode):** add `test-support/fake-nutrition.mjs` on 9930 beside `fake-bff.mjs` (the fake BFF gains `POST /delegation` and per-run counters for mints and bootstraps). Scenarios: PRESENT, ABSENT, 403 denied, 401 session, 503 with Try again, failed mint, malformed body, hung upstream (timeout path), stale `?person=` (no read for the stale render, exactly one for self), actor query noise, subject switch plus Back (pins the router-cache behavior), a document-only load (layout and panel share one bootstrap; one mint; one call), and a prefetch check (visiting another page never mints or calls Nutrition). Assertions: exactly one mint and one Nutrition call per load (fake counters); delegation, cookie-value, and private-field sentinels absent from the HTML and from every document and fetch response the browser receives; `Cache-Control: no-store` on the document; no CSP violations on the streamed page; no mock strings from `getTodaySummaryMock`; no demo banner on `/nutrition` in LIVE but present on another route; the prototype-claims check still covers LIVE `/nutrition`.
- **Gates:** `npm test`, `npm run lint`, `npm run build` (LIVE env), `npm run test:startup-config`, `npm run test:e2e`, then `npm run test:server-boundary` last (finding 9), and `python -m pytest deploy/home-hub/tests -q`.

## Rollout gate R4 (operator-run; Claude runs read-only checks)

1. Merge SHA and evidence baseline: confirm the live image is `89e0550…`, `NRestarts=0`, Quadlet SHA unchanged since R3.
2. Build as `svc-home-hub` from a `git archive` of `apps/home-hub` at the merge SHA (same method as R3); throwaway probe with the unchanged `Network=pasta:-T,9933,-T,9930`.
3. Back up the Quadlet to `/var/backups/episteck/home-f3c-<SHA>/`. The apply diff must be exactly the `Image=` line; `Network=` and `Environment=` are already correct from R3. Reload, restart.
4. Verify: 9933/9930 reachable from the Hub container, 9931/9932/9934 not; host listeners on `127.0.0.1` only; anonymous `/nutrition` redirects to login; second restart repeats the probes with `NRestarts=0`.
5. **Authenticated read-only proof (Erick self):** the page renders the profile panel for `PSN-00013`, PRESENT or ABSENT, whichever production holds. Record: document `Cache-Control: no-store`; HTML contains no delegation, cookie, or other Person ID; no mock strings; no demo banner on `/nutrition`, banner present elsewhere; stale `?person=` falls back to self. **Read count:** over the proof window, the Hub journal shows exactly one `nutrition.profile outcome=` line per page load (`ABSENT` or `PRESENT`), and the stale check shows `outcome=STALE_SKIPPED` followed by one read line. **Log hygiene:** a grep of Hub, BFF, and Nutrition logs over the window for `PSN-`, cookie, bearer, JWT-shaped, and delegation values returns nothing. Per-load mint and Nutrition-call counts are recorded as "tests only" (fake counters) unless the BFF or Nutrition already keeps an ID-free per-request record.
6. Evidence wording: an ABSENT result is recorded as "authorized no-profile response", never "populated profile rendered". The record lists which states were observed live and which were proven by tests only.

Rollback: restore the saved Quadlet byte for byte, reload, restart; the `89e0550` image stays on the host. Repeat step 4's checks.

## Out of scope

- Any Nutrition or Home contract/service change; named targets, calories, macros (future spec).
- `/nutrition/pregnancy`, Mealie, other pages' mock content, `GET /daily` and `/gap-v2` adapters.
- Fault-injection drills in production; fixture, Person, grant, or profile creation.
- Cross-person live checks (G2-gated). F3d covers negative and cross-person validation.
- Client-side polling or refetch, including a forced re-read on Back/Forward. Try again is a server re-render.

## Assumptions

- The layout already redirects dead sessions before the page renders, so an in-page `SESSION` panel is a narrow race.
- 4 s per fetch is a reasonable default for a loopback hop; the value is a single constant and can be tuned in review.
- Humanized-code fallback is acceptable for unknown `context` / `target_source` values.
- React `cache()` shares the bootstrap between the root layout and the page within one render (pinned by the document-only e2e).
- Next restores Back/Forward entries from its client router cache (pinned by the switch e2e). If Next re-reads instead, the test and the Invariants sentence change; the design does not.

## Open questions

- None blocking. Reviewer may want to tune the timeout and the PRESENT-panel copy.
