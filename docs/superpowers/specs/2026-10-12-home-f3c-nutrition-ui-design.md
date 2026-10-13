# Home F3c — Nutrition UI wiring: design

**Date:** 2026-10-12
**Status:** Draft for operator review. Design approved in conversation 2026-10-12 (scope A, Suspense streaming, read-only live proof, mock cluster hidden in LIVE). Nothing here is implemented.
**Parent architecture:** `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` (Board-approved, PR #48), phase F3c (§10) and acceptance matrix (§11).
**Predecessor:** `docs/superpowers/specs/2026-10-05-home-f3b-nutrition-adapter-design.md`. F3b is LIVE on Nuremberg (rollout gate R3 PASS, 2026-10-12, PR #91 merge `89e0550`, evidence PR #98 merged).
**Baseline:** `origin/main` `45b8cbe`.

## Purpose

Replace the mock Nutrition cluster on `/nutrition` with a real, server-rendered panel driven by `readNutritionProfile`, keeping every F3b invariant. F3c is the first live caller of the adapter.

**Success criteria**
- In LIVE, `/nutrition` shows no mock value. It shows the validated subject and exactly one of: profile on file, no profile, access restricted, session expired, unavailable, invalid response, not configured, or a loading skeleton.
- An authorized `ABSENT` profile renders an honest empty state: no zeros, no rings, no mock.
- One mint and one Nutrition call per page load; `no-store`; no delegation or cookie reaches the browser.
- MOCK mode renders today's demo unchanged.

## Decisions (settled with the operator)

| ID | Decision |
| --- | --- |
| **S1** | **Scope A.** F3c stays within the current `ProfileSummary` (`presence`, `context`, `targetSource`, `targetCount`). No contract widening, no Nutrition or Home change. Showing named targets (calories, macros) is a separate future spec that touches Nutrition/Home and needs its own review. |
| **S2** | **Stream with Suspense.** Header renders immediately; the profile panel streams behind a skeleton. Each Hub fetch gets `AbortSignal.timeout(4000)`, so worst case is about 8 s. A timeout renders the `SERVICE_UNAVAILABLE` panel with a Try again link. |
| **S3** | **Read-only live proof (R4).** Production is observed only. Error states are proven by automated tests against fake upstreams; the live record labels each state "observed live" or "tests only". No fault drill, no fixtures. |
| **S4** | **LIVE hides the whole mock cluster** on `/nutrition` (calorie ring, macros, Mealie card, Ana pregnancy card). `/nutrition/pregnancy` is out of scope and unchanged. |

## Findings from exploration

1. `/nutrition/page.tsx` is a `'use client'` component over `getTodaySummaryMock`. `readNutritionProfile` is `server-only`, so the live path needs a server component. The client `AppProvider` result cannot be handed to the server, so the server re-derives the context itself.
2. `AppShell` renders a global banner, "DEMO / MOCK DATA — domain content is illustrative and is not data or access for the selected person", because `layout.tsx` passes `demoContent` unconditionally. On a live `/nutrition` that banner would contradict real data. It must not show on `/nutrition` in LIVE, and must remain on every other page.
3. `F3ActiveContext` is a plain object type. Any code can build `{ kind: 'PERSON', personId }`, so "only `resolveRequestedPerson` output reaches the adapter" is currently a convention, not a guarantee.
4. `loadNutritionProfile` fetches have no timeout. A hung upstream stalls the render for the platform default (about 300 s). Unread response bodies on early-return paths are not cancelled.
5. `playwright.config.ts` already starts `test-support/fake-bff.mjs` (port 3323) and the LIVE Hub on 3322, with `HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930` and no fake behind it. A fake Nutrition server is the missing piece for end-to-end state coverage.
6. Known Nutrition code values are `PREGNANCY` (context) and `REFERENCE_TARGET` / `USER_CONFIGURED` (target source). The set is open, so the UI must tolerate unknown codes.

## Invariants (carried from F3b; F3c must not weaken any)

- The subject comes only from a validated `F3ActiveContext`. No actor, domain, or action input exists on this path.
- Exactly one delegation mint and one Nutrition call per read. No retry inside a request; Try again is a new page load.
- No cache anywhere: `no-store` on the page response, no `unstable_cache`, no `revalidate`, no module-level memo of profile data.
- No mock substitution in LIVE, including on error.
- The delegation and the session cookie never reach the browser. No Person ID appears in the HTML other than the visible, already-validated subject.
- Missing and unauthorized subjects render the same Access restricted panel.
- No production fixtures, Persons, grants, or profiles are created. ABSENT is a valid live proof.

## Architecture

```text
Browser GET /nutrition?person=…
  layout.tsx (existing): bootstrap → login redirect | AppProvider | AppShell
  nutrition/page.tsx  (server component)
    MOCK  → <NutritionDemoCluster/>            (client, today's demo, moved unchanged)
    LIVE  → <NutritionHeader/>                 (client: title, subject name, switcher)
            <Suspense key={personId} fallback={<ProfilePanel model=LOADING/>}>
              <LiveProfilePanel searchParams/>  (async server component)
                resolveLiveSubject(searchParams) → F3ActiveContext | unavailable
                readNutritionProfile(context)    → DataEnvelope<ProfileSummary>
                toProfilePanelModel(envelope, subjectName) → ProfilePanelModel
                <ProfilePanel model/>            (pure presentation)
```

### Components

| Unit | Purpose | Depends on |
| --- | --- | --- |
| `integration/nutrition/profile-panel-model.ts` | Pure `toProfilePanelModel(envelope, subjectName)` → discriminated `ProfilePanelModel`, exhaustive `never` check. No React, no server imports; unit-testable under `node --test`. | `DataEnvelope`, `ProfileSummary`, `SafeUIErrorCode` |
| `integration/nutrition/live-subject.server.ts` | `resolveLiveSubject(searchParams)`: `getBootstrapForRequest()` + `resolveRequestedPerson()`; returns the branded context and the subject's display name, or an unavailable result. The only producer of the context passed to the adapter. | `bootstrap.server`, `active-context` |
| `components/features/nutrition/ProfilePanel.tsx` (+ `.module.css`) | Renders one `ProfilePanelModel`. Server-safe, no hooks, no env access. | model type only |
| `app/nutrition/LiveProfilePanel.tsx` | Async server component wiring the three above; catches a throw from the adapter and treats it as `SERVICE_UNAVAILABLE`. The only importer of `profile.server.ts`. | all above |
| `app/nutrition/NutritionDemoCluster.tsx` | Today's page body, moved verbatim, `'use client'`. Rendered only when mode is MOCK. | mocks |
| `app/nutrition/page.tsx` | Server component: branch on `SERVER_CONFIGURATION.mode`. | the two above |
| `AppShell` + `layout.tsx` | New `liveRoutes` exact-match list. In LIVE the layout passes `['/nutrition']`; `AppShell` suppresses the demo banner when the pathname is in it. MOCK and every other route keep the banner. | — |

### Subject resolution and staleness

`resolveLiveSubject` reads `searchParams.person` as a list, calls `resolveRequestedPerson`, and uses the returned `activeContext`. A `STALE_CONTEXT` result resolves to self, matching F3a canonicalization (the client replaces the URL). The server never calls Nutrition for the stale ID and never returns another Person's data under the fallback. A valid navigable Person whose grant was revoked stays selected and renders Access restricted; denial never falls back to self.

`<Suspense key={personId}>` plus F3a's keyed provider reset means a response for subject A cannot paint under subject B. The server render is per request; there is no client-held result.

Bootstrap is fetched once more by the page (layout and `/api/context` already fetch it). This is accepted; it also guarantees the subject is validated against a fresh session-bound bootstrap, not a value handed over by the browser.

### Panel states

| Envelope | Model | Panel |
| --- | --- | --- |
| streaming | `LOADING` | Skeleton: "Checking Nutrition profile for {name}…" (`role="status"`). |
| READY / PRESENT | `PRESENT` | "Nutrition profile on file" for {name}: context, target source, "N targets configured", `svc-nutrition` provenance badge. States that target values are not shown on this page yet. Codes use a small label map (`PREGNANCY`, `REFERENCE_TARGET`, `USER_CONFIGURED`) and fall back to a humanized code. No numbers are invented. |
| READY / ABSENT | `ABSENT` | "No nutrition profile for {name}." No zeros, rings, mock, or create CTA (onboarding is gated). |
| ERROR / `ACCESS_DENIED` (DENIED) | `DENIED` | "Access restricted." Identical for missing and unauthorized subjects; no reason text; subject stays visible; no fallback to self. |
| `SESSION_INVALID`, `SESSION_REQUIRED` | `SESSION` | "Your session has expired" with a sign-in link to `/login`. No redirect (headers are already sent when streaming). |
| `SERVICE_UNAVAILABLE` (includes timeout and adapter throw) | `UNAVAILABLE` | "Nutrition is temporarily unavailable" plus Try again (link to the same URL = new page load, new mint). |
| `INVALID_RESPONSE` | `INVALID` | Distinct "Nutrition returned something that couldn't be shown safely" plus Try again. |
| `NOT_CONFIGURED` | `NOT_CONFIGURED` | "Nutrition isn't set up on this Hub." No retry, no env var names. |
| unmapped code (`OFFLINE`, `RESOURCE_NOT_AVAILABLE`) | `UNAVAILABLE` | Fails safe to unavailable; covered by the exhaustive test. |

The parent architecture counts "six product states"; F3c maps them as PRESENT, ABSENT, DENIED, UNAVAILABLE (with INVALID as its own distinct panel), SESSION, and LOADING, plus NOT_CONFIGURED, which is an operator condition. The full set is eight models; this is a deliberate refinement, not a contradiction of the six.

Errors render `role="alert"`; loading and empty states `role="status"`. The page `<h1>` stays "Nutrition Hub".

## Entry criteria from the F3b.3 final review (early tasks)

1. **Timeouts and body drain.** `AbortSignal.timeout(4000)` on both fetches in `profile-loader.ts`; every early-return path cancels or drains the unread body. Tested with a fake fetcher that never resolves (asserts `SERVICE_UNAVAILABLE` within the timeout, using an injectable timeout so the test is fast) and a fake whose bodies record `cancel`.
2. **No client-reachable adapter.** `readNutritionProfile` must never be reachable via a `'use server'` action or a route taking a client-supplied context. `test:server-boundary` gains a static check: no file containing `'use server'` and no `route.ts` may import `profile.server.ts`, directly or via re-export, and the only allowed importer is `app/nutrition/LiveProfilePanel.tsx`. The existing build-time probe (client import fails on `server-only`) stays.
3. **Branded context.** `F3ActiveContext` becomes a branded type. `resolveRequestedPerson` is the only issuer; issued objects are frozen and registered in a module-private `WeakSet`. `readNutritionProfile` verifies registry membership at runtime. A cast object literal, a spread copy, or the JSON copy the browser receives makes `readNutritionProfile` throw a `TypeError` before any cookie read or network call (a programming error, not an envelope state; the panel layer's try/catch would render `UNAVAILABLE`). Tests cover forged literal, spread copy, and JSON round-trip. The context type is erased by `--experimental-strip-types`, so the runtime registry is the real guard.
4. **Optional cleanups** (one small task): `ProfileContractError.name`; contract regression tests (`1e999`, `Infinity`, `0x10`, `__proto__` key); case-insensitive header-isolation test; Quadlet test reading the `Network=` value instead of hard-coding it.

## Error handling

- The adapter returns an envelope for every upstream failure; the panel layer additionally wraps the call in try/catch so a thrown error (for example `cookies()` failure) renders `UNAVAILABLE`, never a framework error page and never mock.
- An unavailable bootstrap inside the page (`resolveLiveSubject` cannot resolve) renders `UNAVAILABLE`; the layout has already handled the dead-session redirect.
- Nothing logs envelope internals, IDs, or tokens.

## Testing

- **Unit (`node --test`):** panel-model mapping for every envelope and error code (exhaustive); branded-context issuance and forgery cases; loader timeout, drain, and the cleanup regressions; Quadlet network test.
- **Server boundary:** extended `test:server-boundary` as above.
- **E2E (Playwright, LIVE mode):** add `test-support/fake-nutrition.mjs` on 9930 beside `fake-bff.mjs` (fake BFF gains a `POST /delegation` mode). Scenarios: PRESENT, ABSENT, 403 denied, 401 session, 503, malformed body, hung upstream (timeout path), stale `?person=` (no Nutrition call for the stale ID), tab/subject switch, `?person=` with a Circle ID. Assertions on every scenario: exactly one mint and one Nutrition call per load (fake counters), delegation sentinel and cookie sentinel absent from the HTML and from client-visible requests, `Cache-Control: no-store` on the document, no mock strings from `getTodaySummaryMock`, no demo banner on `/nutrition` in LIVE but present on another route.
- **Gates:** `npm test`, `npm run lint`, `npm run build`, `npm run test:server-boundary`, `npm run test:startup-config`, `npm run test:e2e`.

## Rollout gate R4 (operator-run; Claude runs read-only checks)

1. Merge SHA and evidence baseline: confirm the live image is `89e0550…`, `NRestarts=0`, Quadlet SHA unchanged since R3.
2. Build as `svc-home-hub` from a `git archive` of `apps/home-hub` at the merge SHA (same method as R3); throwaway probe with the unchanged `Network=pasta:-T,9933,-T,9930`.
3. Back up the Quadlet to `/var/backups/episteck/home-f3c-<SHA>/`. The apply diff must be exactly the `Image=` line; `Network=` and `Environment=` are already correct from R3. Reload, restart.
4. Verify: 9933/9930 reachable from the Hub container, 9931/9932/9934 not; host listeners on `127.0.0.1` only; anonymous `/nutrition` redirects to login; second restart repeats the probes with `NRestarts=0`.
5. **Authenticated read-only proof (Erick self):** the page renders the profile panel for `PSN-00013` — PRESENT or ABSENT, whichever production holds. Record: document `Cache-Control: no-store`; HTML contains no delegation, cookie, or other Person ID; no mock strings; no demo banner on `/nutrition`, banner present elsewhere; stale `?person=` falls back to self; Hub, BFF, and Nutrition logs show exactly one mint and one `GET /profile/PSN-00013` per page load and contain no IDs, query strings, or credentials.
6. Evidence wording: an ABSENT result is recorded as "authorized no-profile response", never "populated profile rendered". The record lists which states were observed live and which were proven by tests only.

Rollback: restore the saved Quadlet byte for byte, reload, restart; the `89e0550` image stays on the host. Repeat step 4's checks.

## Out of scope

- Any Nutrition or Home contract/service change; named targets, calories, macros (future spec).
- `/nutrition/pregnancy`, Mealie, other pages' mock content, `GET /daily` and `/gap-v2` adapters.
- Fault-injection drills in production; fixture, Person, grant, or profile creation.
- Cross-person live checks (G2-gated). F3d covers negative and cross-person validation.
- Client-side polling or refetch. Try again is a full navigation.

## Assumptions

- The layout already redirects dead sessions before the page renders, so an in-page `SESSION` panel is a narrow race.
- 4 s per fetch is a reasonable default for a loopback hop; the value is a single constant and can be tuned in review.
- Humanized-code fallback is acceptable for unknown `context` / `target_source` values.

## Open questions

- None blocking. Reviewer may want to tune the timeout and the PRESENT-panel copy.
