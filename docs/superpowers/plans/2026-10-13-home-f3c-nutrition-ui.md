# Home F3c — Nutrition UI wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mock Nutrition cluster on `/nutrition` with a server-rendered, streamed profile panel driven by `readNutritionProfile`, keeping every F3b invariant, and prove it live read-only (rollout gate R4).

**Architecture:** `/nutrition/page.tsx` becomes a server component. In MOCK it renders today's demo unchanged (moved into a client `NutritionDemoCluster`). In LIVE it renders a client header (title and switcher) plus `<Suspense key=…>` around an async server `LiveProfilePanel` that resolves the subject from the request's bootstrap, calls the adapter once (or not at all for a stale selection), and maps the envelope to a deliberate panel through a pure, exhaustive view-model function. The panel path first gets hardened (per-fetch timeouts and body drain on the bootstrap, mint, and profile fetches; one `cache()`-shared bootstrap per render; branded context; caller guard).

**Tech Stack:** Next.js 16.3.5 (App Router, `basePath: '/app'`), React 19.2.8, TypeScript run under `node --experimental-strip-types --test`, Playwright (LIVE mode against fake BFF and fake Nutrition servers), Python pytest for the Quadlet/runbook tests.

**Spec:** `docs/superpowers/specs/2026-10-12-home-f3c-nutrition-ui-design.md` (approved 2026-10-13, revised 2026-10-13). Parent: `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` §10 F3c, §11. Predecessor: `docs/superpowers/specs/2026-10-05-home-f3b-nutrition-adapter-design.md`.

**Revision 2026-10-13 (post-review):** new Task 1b (bootstrap timeout, drain, and React `cache()`); shared `fetch-timeout.ts` module (Task 1); `'use server'` guard narrowed to Nutrition (Task 3); full PR-A gate (Task 4); non-LIVE guard, `outcomeLabel`, copy (Tasks 5–6); stale flag kept (Task 7); `LiveProfilePanel` guards the whole path, skips the read on stale, logs one line, no nested `<main>` (Task 8); e2e adds document-only, prefetch, CSP, response-scan, exact stale and Back assertions, and keeps the claims check on LIVE `/nutrition` (Task 9); verification order fixed everywhere (`test:server-boundary` last); PR-B stacked on PR-A; R4 read count comes from the Hub's outcome log line.

## Global Constraints

- Scope A: stay within `ProfileSummary` (`presence`, `context`, `targetSource`, `targetCount`). No Nutrition or Home change, no contract widening, no named targets, calories, or macros.
- Subject comes only from a `F3ActiveContext` issued by `resolveRequestedPerson`. No actor, domain, or action input on this path.
- Exactly one delegation mint and one Nutrition call per read; no retry inside a request (Try again is a new page load).
- `no-store` throughout; no `unstable_cache`, `revalidate`, or module-level memo of profile data. The one allowed memo is React `cache()` around `getBootstrapForRequest` (request-scoped; never crosses requests; no profile data).
- No mock substitution in LIVE, including on error. LIVE `/nutrition` shows no calorie ring, macros, Mealie card, or Ana pregnancy card. `/nutrition/pregnancy` is unchanged.
- The delegation and session cookie never reach the browser. Missing and unauthorized subjects render the same Access restricted panel.
- Per-fetch timeout `AbortSignal.timeout(4000)` on the BFF bootstrap, the delegation mint, and the Nutrition read: one constant, `FETCH_TIMEOUT_MS` in `src/integration/state/fetch-timeout.ts`.
- Logging: exactly one line per panel render, `nutrition.profile outcome=<LABEL>`, fixed vocabulary only. Never log IDs, names, URLs, query strings, or tokens.
- No production fixtures, Persons, grants, or profiles are created. Production changes are run by the operator via `!` ssh; Claude only runs read-only checks.
- Hub files import runtime modules with explicit `.ts` extensions where tests load them (`node --experimental-strip-types`); follow the surrounding file's style. When a snippet appends imports to an existing test file, merge them into the file's import block at the top.
- **Verification order:** `npm run test:server-boundary` runs two `next build` probes that fail on purpose, and `next build` deletes `.next` before compiling. Run it **last**, after `test:startup-config` and `test:e2e`, or rebuild before anything that needs a build.
- Commits follow `.claude/rules/git-and-branching.md` (`type: summary`, lowercase, imperative, no period) and end with the attribution line your session requires. Branch from `origin/main`.

## Review Focus

Failure modes the spec implies that no single task's headline tests cover. Each has a pinning test in the owning task.

1. `?person=` that is duplicated, empty, array-shaped, or oversized → falls back to self; the stale render makes no Nutrition call at all, and the canonical self URL makes exactly one. (Task 7 unit, Task 8, Task 9 e2e)
2. Future or unknown Nutrition `context` / `target_source` codes → readable fallback label, no crash. (Task 5)
3. A PRESENT profile with `targetCount` 0 → says "None configured", is not mistaken for ABSENT. (Task 5)
4. Upstream stalls after headers (body never finishes) or never answers, on the bootstrap, mint, or profile fetch → `SERVICE_UNAVAILABLE` in about one timeout, not a 300 s stall. (Task 1 and Task 1b unit tests, Task 9 hang scenario)
5. Rapid subject switch → a response for subject A never paints under subject B; Back restores the entry's own earlier render without a new read (documented behavior). (Task 9 switch test)
6. Session dies between the layout's bootstrap and the panel's mint → "session expired" panel with sign-in link, never a blank panel or a framework error. (Task 9 `401` scenario)
7. Any throw on the panel path (bootstrap, subject, adapter, mapping) → `UNAVAILABLE` panel, never Next's error page (the app has no `error.tsx`); Next's control-flow errors are rethrown. (Task 8)
8. A `<Link>` prefetch of `/nutrition` from another page never mints or calls Nutrition. (Task 9 prefetch test)
9. The layout and the panel share one bootstrap per document render. (Task 1b, Task 9 document-only test)

## File Map

PR-A (hardening, no UI): Tasks 1, 1b, 2, 3, 4.
- Create: `apps/home-hub/src/integration/state/fetch-timeout.ts`
- Modify: `apps/home-hub/src/integration/nutrition/profile-loader.ts`, `profile-loader.test.ts`, `profile-contract.ts`, `profile-contract.test.ts`, `profile.server.ts`
- Modify: `apps/home-hub/src/integration/home/bootstrap-loader.ts`, `bootstrap-loader.test.ts`, `bootstrap.server.ts`
- Modify: `apps/home-hub/src/integration/home/active-context.ts`, `active-context.test.ts`, `apps/home-hub/src/components/providers/AppProvider.tsx` (type only)
- Create: `apps/home-hub/test-support/verify-adapter-callers.mjs`, `verify-adapter-callers.test.mjs`
- Modify: `apps/home-hub/package.json`, `deploy/home-hub/tests/test_home_hub_quadlet.py`

PR-B (UI + proof): Tasks 5–10.
- Create: `src/integration/nutrition/profile-panel-model.ts` (+ test), `src/integration/nutrition/live-subject.ts` (+ test), `live-subject.server.ts`
- Create: `src/components/features/nutrition/ProfilePanel.tsx`, `ProfilePanel.module.css`, `RetryButton.tsx`
- Create: `src/app/nutrition/LiveProfilePanel.tsx`, `NutritionHeader.tsx`, `NutritionDemoCluster.tsx` (moved from `page.tsx`)
- Modify: `src/app/nutrition/page.tsx`, `src/components/layout/AppShell.tsx`, `src/app/layout.tsx`
- Create: `test-support/fake-nutrition.mjs`, `e2e/nutrition-profile.spec.ts`; Modify: `test-support/fake-bff.mjs`, `playwright.config.ts`, `e2e/bootstrap.spec.ts`
- Modify only if the Task 9 prefetch contingency fires: `src/components/layout/Sidebar.tsx`, `src/components/layout/BottomNav.tsx`
- Modify: `deploy/home-hub/README.md`, `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md`, the spec status line

All paths below are relative to `apps/home-hub/` unless they start with `deploy/` or `docs/`.

## Branches and PRs

Run the `git worktree` commands from the repo root (`episteck_home/`), not from `apps/home-hub/`.

1. PR-A worktree from `origin/main`: `git fetch origin && git worktree add -b feature/home-f3c-hardening ../.worktrees/home-f3c-hardening origin/main`. Tasks 1, 1b, 2, 3, 4; push; one PR: `feat: harden Nutrition adapter for first live caller`.
2. **Stack PR-B on PR-A** instead of waiting for the merge: `git worktree add -b feature/home-f3c-nutrition-ui ../.worktrees/home-f3c-impl feature/home-f3c-hardening`. Tasks 5–10; push; one PR: `feat: show live Nutrition profile panel on /nutrition`, opened with base `feature/home-f3c-hardening` (`gh pr create --base feature/home-f3c-hardening`) and a first line "Stacked on PR-A (#<n>); review the commits after it."
3. If PR-A changes in review: pull it, then from the PR-B worktree `git rebase feature/home-f3c-hardening`. After PR-A merges into `main`: `git fetch origin && git rebase --onto origin/main feature/home-f3c-hardening`, rerun the PR-B gate (Task 10 Step 3), `git push --force-with-lease`, and `gh pr edit <PR-B> --base main`.
4. Gate R4 runs after PR-B merges. No merge or deploy without the operator's explicit go.

Test command from `apps/home-hub/` (all unit tests): `npm test`. Single file: `node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test src/integration/nutrition/profile-loader.test.ts`. Bash tool calls here end with a spurious "claude-XXXX-cwd" error and exit 1: judge from the output, and append `; echo EXIT=$?` to see a real code.

---

## PR-A — adapter hardening

### Task 1: Timeouts and body drain in the loader

**Files:**
- Create: `src/integration/state/fetch-timeout.ts`
- Modify: `src/integration/nutrition/profile-loader.ts` (whole file replaced below)
- Test: `src/integration/nutrition/profile-loader.test.ts` (append)

**Interfaces:**
- Produces (`src/integration/state/fetch-timeout.ts`): `export const FETCH_TIMEOUT_MS = 4000`; `isAbortError(error: unknown): boolean`; `discardBody(response: Response): void`. Task 1b reuses all three for the bootstrap read.
- Produces (`profile-loader.ts`): `LoadNutritionProfileOptions.timeoutMs?: number`. Everything else in the module's public surface is unchanged.

- [ ] **Step 1: Write the failing tests** — append to `profile-loader.test.ts`:

```ts
import { createServer } from 'node:http';
import { FETCH_TIMEOUT_MS } from '../state/fetch-timeout.ts';

test('the default per-fetch timeout is 4 seconds', () => {
  assert.equal(FETCH_TIMEOUT_MS, 4000);
});

function hangingFetch(): typeof fetch {
  return ((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
  })) as typeof fetch;
}

test('a hung BFF mint times out as SERVICE_UNAVAILABLE and never calls Nutrition', async () => {
  // AbortSignal.timeout timers are unref'd; keep the loop alive while we wait.
  const keepAlive = setTimeout(() => {}, 2000);
  try {
    const started = Date.now();
    const result = await loadNutritionProfile({ ...live, fetcher: hangingFetch(), timeoutMs: 25 });
    assert.equal(result.errorCode, 'SERVICE_UNAVAILABLE');
    assert.ok(Date.now() - started < 1500);
  } finally {
    clearTimeout(keepAlive);
  }
});

test('a hung Nutrition call times out as SERVICE_UNAVAILABLE after one mint', async () => {
  const keepAlive = setTimeout(() => {}, 2000);
  try {
    let calls = 0;
    const fetcher = ((input: RequestInfo | URL, init?: RequestInit) => {
      calls += 1;
      return calls === 1 ? Promise.resolve(minted()) : hangingFetch()(input, init);
    }) as typeof fetch;
    const result = await loadNutritionProfile({ ...live, fetcher, timeoutMs: 25 });
    assert.equal(calls, 2);
    assert.equal(result.errorCode, 'SERVICE_UNAVAILABLE');
  } finally {
    clearTimeout(keepAlive);
  }
});

test('a body that stalls after the headers also times out as SERVICE_UNAVAILABLE (real sockets)', async () => {
  const server = createServer((request, response) => {
    if (request.method === 'POST') {
      response.writeHead(200, { 'content-type': 'application/json' })
        .end(JSON.stringify({ delegation: 'tok-opaque', audience: 'svc-nutrition', expires_at: 1 }));
      return;
    }
    response.writeHead(200, { 'content-type': 'application/json' });
    response.write('{"context":');
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const { port } = server.address() as { port: number };
    const origin = `http://127.0.0.1:${port}`;
    const started = Date.now();
    const result = await loadNutritionProfile({
      ...live, bffBaseUrl: origin, nutritionBaseUrl: origin, fetcher: fetch, timeoutMs: 150,
    });
    assert.equal(result.errorCode, 'SERVICE_UNAVAILABLE');
    assert.ok(Date.now() - started < 3000);
  } finally {
    server.closeAllConnections();
    server.close();
  }
});

function cancellable(status: number) {
  let cancelled = false;
  const body = new ReadableStream({
    start(controller) { controller.enqueue(new TextEncoder().encode('x')); },
    cancel() { cancelled = true; },
  });
  return { response: new Response(body, { status }), wasCancelled: () => cancelled };
}

const drained: Array<[string, number, boolean]> = [
  ['mint 401', 401, true],
  ['mint 500', 500, true],
  ['Nutrition 403', 403, false],
  ['Nutrition 503', 503, false],
  ['Nutrition unexpected 302', 302, false],
];
for (const [name, status, isMint] of drained) {
  test(`${name}: the unread response body is cancelled`, async () => {
    const unread = cancellable(status);
    const { fetcher } = isMint ? scripted(unread.response) : scripted(minted(), unread.response);
    await loadNutritionProfile({ ...live, fetcher });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(unread.wasCancelled(), true);
  });
}

test('both fetches carry an abort signal', async () => {
  const { calls, fetcher } = scripted(minted(), json(404, { detail: 'no profile' }));
  await loadNutritionProfile({ ...live, fetcher });
  for (const call of calls) assert.ok(call.init?.signal instanceof AbortSignal);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test src/integration/nutrition/profile-loader.test.ts`
Expected: FAIL (`../state/fetch-timeout.ts` does not exist; the hung-fetch tests do not terminate within the timeout).

- [ ] **Step 3a: Create `src/integration/state/fetch-timeout.ts`**

```ts
/**
 * Per-fetch budget for every Hub call on a page render: the BFF bootstrap, the delegation
 * mint, and the Nutrition read. The layout's bootstrap bounds the shell; the panel adds at
 * most two more budgets (mint, profile) because it shares the layout's bootstrap.
 */
export const FETCH_TIMEOUT_MS = 4000;

/** True when a fetch or a body read was aborted by its timeout signal. */
export function isAbortError(error: unknown): boolean {
  return error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
}

/** Release an unread body so the upstream connection is not held open. */
export function discardBody(response: Response): void {
  response.body?.cancel().catch(() => {});
}
```

- [ ] **Step 3b: Replace `profile-loader.ts` with the hardened version**

```ts
import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import { discardBody, FETCH_TIMEOUT_MS, isAbortError } from '../state/fetch-timeout.ts';
import { isAbsentProfileBody, parseProfileWire, type ProfileSummary } from './profile-contract.ts';

const NUTRITION_AUDIENCE = 'svc-nutrition';
const DELEGATION_HEADER = 'X-Episteck-Delegation';
const PERSON_ID = /^[A-Za-z0-9-]{1,64}$/;

export interface LoadNutritionProfileOptions {
  mode: 'MOCK' | 'LIVE';
  personId: string;
  cookieValue: string | undefined;
  bffBaseUrl: string | undefined;
  nutritionBaseUrl: string | undefined;
  fetcher: typeof fetch;
  /** Per-fetch timeout in milliseconds. Defaults to FETCH_TIMEOUT_MS. */
  timeoutMs?: number;
}

type Envelope = DataEnvelope<ProfileSummary>;
type JsonRead = { ok: true; body: unknown } | { ok: false; timedOut: boolean };

function ready(data: ProfileSummary, environment: 'MOCK' | 'LIVE'): Envelope {
  return { delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data };
}

function failed(errorCode: SafeUIErrorCode): Envelope {
  return {
    delivery: 'ERROR',
    authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE',
    freshness: 'UNKNOWN',
    environment: 'LIVE',
    errorCode,
  };
}

async function readJson(response: Response): Promise<JsonRead> {
  try {
    return { ok: true, body: await response.json() };
  } catch (error) {
    return { ok: false, timedOut: isAbortError(error) };
  }
}

/** One delegation for one Nutrition call. Never retried, logged, or returned. */
async function mintDelegation(
  options: LoadNutritionProfileOptions & { bffBaseUrl: string; cookieValue: string },
): Promise<{ token: string } | { error: SafeUIErrorCode }> {
  let response: Response;
  try {
    response = await options.fetcher(
      new URL(`/delegation?audience=${NUTRITION_AUDIENCE}`, options.bffBaseUrl).toString(),
      {
        method: 'POST',
        cache: 'no-store',
        redirect: 'manual',
        signal: AbortSignal.timeout(options.timeoutMs ?? FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json', Cookie: `episteck_home_session=${options.cookieValue}` },
      },
    );
  } catch {
    return { error: 'SERVICE_UNAVAILABLE' };
  }
  if (response.status === 401) {
    discardBody(response);
    return { error: 'SESSION_INVALID' };
  }
  if (response.status !== 200) {
    discardBody(response);
    return { error: 'SERVICE_UNAVAILABLE' };
  }
  const parsed = await readJson(response);
  if (!parsed.ok) return { error: parsed.timedOut ? 'SERVICE_UNAVAILABLE' : 'INVALID_RESPONSE' };
  if (typeof parsed.body !== 'object' || parsed.body === null) return { error: 'INVALID_RESPONSE' };
  const { delegation, audience } = parsed.body as Record<string, unknown>;
  if (typeof delegation !== 'string' || delegation.length === 0 || audience !== NUTRITION_AUDIENCE) {
    return { error: 'INVALID_RESPONSE' };
  }
  return { token: delegation };
}

/** Cancel the unread body, then fail. */
function reject(response: Response, errorCode: SafeUIErrorCode): Envelope {
  discardBody(response);
  return failed(errorCode);
}

/**
 * Read one Person's Nutrition profile summary for the current session.
 * No actor, domain, or action input exists: Home derives the actor, Nutrition fixes
 * NUTRITION/VIEW, and the subject is the already-validated active context.
 */
export async function loadNutritionProfile(options: LoadNutritionProfileOptions): Promise<Envelope> {
  if (options.mode === 'MOCK') return ready({ presence: 'ABSENT' }, 'MOCK');
  if (!options.bffBaseUrl || !options.nutritionBaseUrl) return failed('NOT_CONFIGURED');
  if (!options.cookieValue) return failed('SESSION_REQUIRED');
  if (!PERSON_ID.test(options.personId)) return failed('INVALID_RESPONSE');

  const minted = await mintDelegation({
    ...options,
    bffBaseUrl: options.bffBaseUrl,
    cookieValue: options.cookieValue,
  });
  if ('error' in minted) return failed(minted.error);

  let response: Response;
  try {
    response = await options.fetcher(
      new URL(`/profile/${encodeURIComponent(options.personId)}`, options.nutritionBaseUrl).toString(),
      {
        method: 'GET',
        cache: 'no-store',
        redirect: 'manual',
        signal: AbortSignal.timeout(options.timeoutMs ?? FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json', [DELEGATION_HEADER]: minted.token },
      },
    );
  } catch {
    return failed('SERVICE_UNAVAILABLE');
  }

  if (response.status === 403) return reject(response, 'ACCESS_DENIED');
  if (response.status === 401) return reject(response, 'SESSION_INVALID');
  if (response.status >= 500) return reject(response, 'SERVICE_UNAVAILABLE');
  if (response.status !== 200 && response.status !== 404) return reject(response, 'INVALID_RESPONSE');

  const parsed = await readJson(response);
  if (!parsed.ok) return failed(parsed.timedOut ? 'SERVICE_UNAVAILABLE' : 'INVALID_RESPONSE');
  if (response.status === 404) {
    return isAbsentProfileBody(parsed.body) ? ready({ presence: 'ABSENT' }, 'LIVE') : failed('INVALID_RESPONSE');
  }
  try {
    return ready(parseProfileWire(parsed.body), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE');
  }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: the same command as Step 2.
Expected: PASS, including all pre-existing loader tests (they use fake `Response` objects; `signal` in `init` is ignored by them).

- [ ] **Step 5: Commit**

```bash
git add src/integration/state/fetch-timeout.ts src/integration/nutrition/profile-loader.ts src/integration/nutrition/profile-loader.test.ts
git commit -m "fix: time out Nutrition adapter fetches and drain unread bodies"
```

### Task 1b: Bound the bootstrap read and share it per render

**Files:**
- Modify: `src/integration/home/bootstrap-loader.ts`, `src/integration/home/bootstrap.server.ts`
- Test: `src/integration/home/bootstrap-loader.test.ts` (append)

**Interfaces:**
- Consumes: `FETCH_TIMEOUT_MS`, `isAbortError`, `discardBody` (Task 1).
- Produces: `LoadBootstrapOptions.timeoutMs?: number`. `getBootstrapForRequest()` keeps its signature but is wrapped in React `cache()`, so the root layout and the Nutrition panel (Task 7) share one bootstrap fetch per server render. Route handlers (`/api/context`) run outside a render and still fetch per request.
- Why: the panel's own bootstrap call had no timeout, so its worst case was unbounded, not the spec's 8 s. Sharing also removes one BFF call per page load and guarantees the layout's redirect decision and the panel's subject come from the same snapshot.
- Keep `bootstrap.server.ts` free of the text `headers()`, `x-forwarded-host`, and `request.url`: an existing test greps for them.

- [ ] **Step 1: Write the failing tests** — append to `bootstrap-loader.test.ts`:

```ts
import { FETCH_TIMEOUT_MS } from '../state/fetch-timeout.ts';

const liveBootstrap = { mode: 'LIVE' as const, cookieValue: 'opaque-session', bffBaseUrl: 'http://127.0.0.1:9933' };

test('the LIVE bootstrap fetch carries an abort signal with the shared budget', async () => {
  let init: RequestInit | undefined;
  await loadBootstrap({ ...liveBootstrap, fetcher: async (_input, requestInit) => { init = requestInit; return response(200); } });
  assert.ok(init?.signal instanceof AbortSignal);
  assert.equal(FETCH_TIMEOUT_MS, 4000);
});

test('a hung BFF bootstrap times out as SERVICE_UNAVAILABLE', async () => {
  // AbortSignal.timeout timers are unref'd; keep the loop alive while we wait.
  const keepAlive = setTimeout(() => {}, 2000);
  try {
    const started = Date.now();
    const result = await loadBootstrap({
      ...liveBootstrap,
      timeoutMs: 25,
      fetcher: ((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
      })) as typeof fetch,
    });
    assert.equal(result.errorCode, 'SERVICE_UNAVAILABLE');
    assert.ok(Date.now() - started < 1500);
  } finally {
    clearTimeout(keepAlive);
  }
});

test('a bootstrap body that stalls past the budget is SERVICE_UNAVAILABLE, not INVALID_RESPONSE', async () => {
  const keepAlive = setTimeout(() => {}, 2000);
  try {
    const result = await loadBootstrap({
      ...liveBootstrap,
      timeoutMs: 25,
      fetcher: (async (_input: RequestInfo | URL, init?: RequestInit) => new Response(new ReadableStream({
        start(controller) {
          init?.signal?.addEventListener('abort', () => controller.error(init.signal?.reason), { once: true });
        },
      }), { status: 200 })) as typeof fetch,
    });
    assert.equal(result.errorCode, 'SERVICE_UNAVAILABLE');
  } finally {
    clearTimeout(keepAlive);
  }
});

for (const status of [401, 500, 502, 503]) {
  test(`bootstrap ${status}: the unread response body is cancelled`, async () => {
    let cancelled = false;
    const body = new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode('x')); },
      cancel() { cancelled = true; },
    });
    await loadBootstrap({ ...liveBootstrap, fetcher: async () => new Response(body, { status }) });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(cancelled, true);
  });
}

test('the server bootstrap is request-scoped through React cache(), never a cross-request cache', async () => {
  const { readFile } = await import('node:fs/promises');
  const { resolve } = await import('node:path');
  const adapter = await readFile(resolve('src/integration/home/bootstrap.server.ts'), 'utf8');
  assert.match(adapter, /import \{ cache \} from 'react'/);
  assert.match(adapter, /export const getBootstrapForRequest = cache\(/);
  assert.doesNotMatch(adapter, /unstable_cache|revalidate|'use cache'/);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test src/integration/home/bootstrap-loader.test.ts`
Expected: FAIL (no signal is passed; the hung tests resolve as `INVALID_RESPONSE` or hang to the keep-alive; bodies are not cancelled; `cache(` is absent).

- [ ] **Step 3: Implement**

In `bootstrap-loader.ts`:
- Add `import { discardBody, FETCH_TIMEOUT_MS, isAbortError } from '../state/fetch-timeout.ts';` beside the existing `./bootstrap-contract.ts` import.
- Add to `LoadBootstrapOptions`: `/** Per-fetch timeout in milliseconds. Defaults to FETCH_TIMEOUT_MS. */ timeoutMs?: number;`
- Add `signal: AbortSignal.timeout(options.timeoutMs ?? FETCH_TIMEOUT_MS),` to the fetch init (after `redirect: 'manual'`).
- Replace everything after the fetch `try/catch` with:

```ts
  if (response.status !== 200) {
    discardBody(response);
    if (response.status === 401) return failed('SESSION_INVALID', 'LIVE');
    if (response.status === 502) return failed('INVALID_RESPONSE', 'LIVE');
    return failed('SERVICE_UNAVAILABLE', 'LIVE');
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    return failed(isAbortError(error) ? 'SERVICE_UNAVAILABLE' : 'INVALID_RESPONSE', 'LIVE');
  }
  try {
    return ready(parseBootstrapWire(body), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE', 'LIVE');
  }
}
```

Replace `bootstrap.server.ts`:

```ts
import 'server-only';
import { cache } from 'react';
import { cookies } from 'next/headers';
import { loadBootstrap } from './bootstrap-loader';
import { SERVER_CONFIGURATION } from '../state/Environment.server';

/**
 * One bootstrap read per server render: the root layout and the Nutrition panel share it.
 * React cache() is request-scoped; nothing is kept across requests or sessions.
 */
export const getBootstrapForRequest = cache(async () => {
  if (SERVER_CONFIGURATION.mode === 'MOCK') {
    return loadBootstrap({
      mode: 'MOCK',
      cookieValue: undefined,
      bffBaseUrl: undefined,
      fetcher: fetch,
    });
  }

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('episteck_home_session')?.value;
  return loadBootstrap({
    mode: 'LIVE',
    cookieValue: sessionCookie,
    bffBaseUrl: SERVER_CONFIGURATION.bffBaseUrl,
    fetcher: fetch,
  });
});
```

- [ ] **Step 4: Run to verify it passes**

Run: Step 2's command, then `npm test` and `npx tsc --noEmit -p .`
Expected: PASS, including the pre-existing bootstrap-loader tests (they check `cache`, headers, and status mapping, not the full init). `tsc` shows no new errors. The shared-bootstrap behavior itself is pinned end to end in Task 9 (document-only test).

- [ ] **Step 5: Commit**

```bash
git add src/integration/home/bootstrap-loader.ts src/integration/home/bootstrap-loader.test.ts src/integration/home/bootstrap.server.ts
git commit -m "fix: time out the bootstrap read and share it per render"
```

### Task 2: Branded, registry-checked active context

**Files:**
- Modify: `src/integration/home/active-context.ts`
- Modify: `src/integration/nutrition/profile.server.ts`
- Modify: `src/components/providers/AppProvider.tsx:6,11,18` (types only)
- Test: `src/integration/home/active-context.test.ts` (append)

**Interfaces:**
- Produces: `PersonContextView = { readonly kind: 'PERSON'; readonly personId: string }` (wire shape, browser-safe); `F3ActiveContext` (branded, server-issued); `isIssuedContext(value: unknown): value is F3ActiveContext`; `assertIssuedContext(value: unknown): asserts value is F3ActiveContext` (throws `TypeError`). `PersonNavigation.activeContext` stays `F3ActiveContext`. `resolveRequestedPerson` signature unchanged.
- Design note (deviation from the spec's "module-private WeakSet"): Next.js can instantiate a module once per server layer (RSC, SSR, route handler). The registry is therefore a `WeakSet` stored on `globalThis` under `Symbol.for('episteck.home-hub.issued-active-contexts')`, so every instance of this module shares it. The guard defends against accidents (a cast literal, a JSON copy), not against hostile code inside the server process.

- [ ] **Step 1: Write the failing tests** — append to `active-context.test.ts`:

```ts
import { assertIssuedContext, isIssuedContext } from './active-context.ts';

test('contexts issued by resolveRequestedPerson are accepted and frozen', () => {
  for (const query of ['', 'person=PSN-00001', 'person=PSN-00002', 'person=PSN-00999']) {
    const { activeContext } = resolve(query);
    assert.equal(isIssuedContext(activeContext), true, query);
    assert.doesNotThrow(() => assertIssuedContext(activeContext));
    assert.equal(Object.isFrozen(activeContext), true);
  }
});

test('a hand-built literal, a spread copy, and a JSON round-trip are rejected', () => {
  const { activeContext } = resolve('person=PSN-00002');
  const forged = { kind: 'PERSON', personId: 'PSN-00002' };
  const spread = { ...activeContext };
  const roundTrip = JSON.parse(JSON.stringify(activeContext));
  for (const candidate of [forged, spread, roundTrip, null, undefined, 'PSN-00002', 7]) {
    assert.equal(isIssuedContext(candidate), false);
    assert.throws(() => assertIssuedContext(candidate), TypeError);
  }
});

test('the same inputs issue distinct objects (no shared mutable context)', () => {
  assert.notEqual(resolve('').activeContext, resolve('').activeContext);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test src/integration/home/active-context.test.ts`
Expected: FAIL (`isIssuedContext` / `assertIssuedContext` are not exported).

- [ ] **Step 3: Implement** — replace `active-context.ts`:

```ts
import type { BootstrapContext } from './Viewer';

declare const issuedBrand: unique symbol;

/** Wire shape of an active context. Carries no authority; safe for the browser. */
export type PersonContextView = { readonly kind: 'PERSON'; readonly personId: string };

/**
 * A requested navigation subject issued on the server by resolveRequestedPerson.
 * The Nutrition adapter accepts only this type, and checks the runtime registry.
 */
export type F3ActiveContext = PersonContextView & { readonly [issuedBrand]: true };

export type PersonNavigation = {
  status: 'CURRENT' | 'STALE_CONTEXT';
  activeContext: F3ActiveContext;
};

const REGISTRY_KEY = Symbol.for('episteck.home-hub.issued-active-contexts');

/** Shared across module instances: Next.js may load this module once per server layer. */
function registry(): WeakSet<object> {
  const holder = globalThis as unknown as Record<symbol, WeakSet<object> | undefined>;
  return (holder[REGISTRY_KEY] ??= new WeakSet<object>());
}

function issue(personId: string): F3ActiveContext {
  const context = Object.freeze({ kind: 'PERSON' as const, personId });
  registry().add(context);
  return context as F3ActiveContext;
}

export function isIssuedContext(value: unknown): value is F3ActiveContext {
  return typeof value === 'object' && value !== null && registry().has(value);
}

export function assertIssuedContext(value: unknown): asserts value is F3ActiveContext {
  if (!isIssuedContext(value)) {
    throw new TypeError('active context was not issued by resolveRequestedPerson');
  }
}

const personIdPattern = /^PSN-[0-9]{5,}(?![\s\S])/;

export function resolveRequestedPerson(query: URLSearchParams, bootstrap: BootstrapContext): PersonNavigation {
  const requested = query.getAll('person');
  const self = issue(bootstrap.viewer.personId);
  if (requested.length === 0) return { status: 'CURRENT', activeContext: self };
  if (requested.length !== 1 || !personIdPattern.test(requested[0])) {
    return { status: 'STALE_CONTEXT', activeContext: self };
  }

  const personId = requested[0];
  const careSubjectIds = new Set(bootstrap.careRelationships.map((relationship) => relationship.subjectPersonId));
  const navigable = personId === self.personId
    || (careSubjectIds.has(personId) && bootstrap.personContexts.some((context) => context.personId === personId));
  return navigable
    ? { status: 'CURRENT', activeContext: personId === self.personId ? self : issue(personId) }
    : { status: 'STALE_CONTEXT', activeContext: self };
}
```

In `src/components/providers/AppProvider.tsx` make the client side use the wire type:
- line 6: `import type { PersonContextView, PersonNavigation } from '@/integration/home/active-context';`
- line 11: `  activeContext: PersonContextView;`
- line 18: `type ValidatedNavigation = Omit<PersonNavigation, 'activeContext'> & { activeContext: PersonContextView; bootstrap: BootstrapContext; environment: 'MOCK' | 'LIVE' };`

In `src/integration/nutrition/profile.server.ts` add the guard as the first statement:

```ts
import { assertIssuedContext, type F3ActiveContext } from '../home/active-context';
// …
export async function readNutritionProfile(context: F3ActiveContext) {
  assertIssuedContext(context);
  const cookieValue = …
```

- [ ] **Step 4: Run to verify it passes**

Run: Step 2's command, then `npm test` and `npx tsc --noEmit -p .`
Expected: PASS. The old tests that `deepEqual` a plain `{ kind, personId }` still pass (frozen objects compare equal). `tsc` shows no new errors; pre-existing errors, if any, are unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/integration/home/active-context.ts src/integration/home/active-context.test.ts src/integration/nutrition/profile.server.ts src/components/providers/AppProvider.tsx
git commit -m "feat: issue branded active contexts and verify them in the adapter"
```

### Task 3: Static guard for who may call the adapter

**Files:**
- Create: `test-support/verify-adapter-callers.mjs`, `test-support/verify-adapter-callers.test.mjs`
- Modify: `package.json` (script `test:server-boundary`)

**Interfaces:**
- Produces: `findViolations(root: string): Promise<string[]>` (human-readable violation lines, empty when clean) and `ALLOWED_ADAPTER_IMPORTERS = ['src/app/nutrition/LiveProfilePanel.tsx']`. The CLI exits 1 with the violations printed.

- [ ] **Step 1: Write the failing test** — `test-support/verify-adapter-callers.test.mjs`:

```js
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { findViolations } from './verify-adapter-callers.mjs';

const GOOD_SERVER = "import 'server-only';\nexport async function readNutritionProfile(context) {\n  assertIssuedContext(context);\n  return cookies();\n}\n";
const ALLOWED = 'src/app/nutrition/LiveProfilePanel.tsx';

async function tree(files) {
  const root = await mkdtemp(join(tmpdir(), 'adapter-callers-'));
  for (const [path, text] of Object.entries(files)) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), text);
  }
  return root;
}

async function violationsFor(files) {
  const root = await tree({ 'src/integration/nutrition/profile.server.ts': GOOD_SERVER, ...files });
  try { return await findViolations(root); } finally { await rm(root, { recursive: true, force: true }); }
}

test('the single allowed server importer is clean', async () => {
  assert.deepEqual(await violationsFor({
    [ALLOWED]: "import { readNutritionProfile } from '@/integration/nutrition/profile.server';\nexport async function LiveProfilePanel() { return readNutritionProfile(); }\n",
  }), []);
});

test('any other importer is a violation', async () => {
  const v = await violationsFor({ 'src/app/other/page.tsx': "import { readNutritionProfile } from '@/integration/nutrition/profile.server';\n" });
  assert.equal(v.length, 1);
  assert.match(v[0], /src\/app\/other\/page\.tsx/);
});

test('a route handler that touches the nutrition integration is a violation', async () => {
  const v = await violationsFor({ 'src/app/api/profile/route.ts': "import { loadNutritionProfile } from '@/integration/nutrition/profile-loader';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module that imports the Nutrition integration is a violation", async () => {
  const v = await violationsFor({ 'src/actions.ts': "'use server';\nimport { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module reaching Nutrition through a relative path is a violation", async () => {
  const v = await violationsFor({ 'src/integration/home/actions.ts': "'use server';\nimport { loadNutritionProfile } from '../nutrition/profile-loader';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module may use other server modules (the rule is scoped to Nutrition)", async () => {
  assert.deepEqual(await violationsFor({ 'src/actions.ts': "'use server';\nimport { getBootstrapForRequest } from '@/integration/home/bootstrap.server';\n" }), []);
});

test('the allowed importer must not be a client component', async () => {
  const v = await violationsFor({ [ALLOWED]: "'use client';\nimport { readNutritionProfile } from '@/integration/nutrition/profile.server';\n" });
  assert.equal(v.length, 1);
});

test('profile.server.ts must verify the context before reading cookies', async () => {
  const root = await tree({ 'src/integration/nutrition/profile.server.ts': "export async function readNutritionProfile(context) {\n  const c = cookies();\n  assertIssuedContext(context);\n}\n" });
  try { assert.equal((await findViolations(root)).length, 1); } finally { await rm(root, { recursive: true, force: true }); }
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --test test-support/verify-adapter-callers.test.mjs`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** — `test-support/verify-adapter-callers.mjs`:

```js
import { readdir, readFile } from 'node:fs/promises';
import { join, relative, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

export const ALLOWED_ADAPTER_IMPORTERS = ['src/app/nutrition/LiveProfilePanel.tsx'];
const ADAPTER_MODULE = 'src/integration/nutrition/profile.server.ts';
const USE_SERVER = /^\s*['"]use server['"]/m;
const USE_CLIENT = /^\s*['"]use client['"]/m;
/** Any module specifier that reaches into a nutrition/ directory, by alias or relative path. */
const NUTRITION_SPECIFIER = /['"][^'"\n]*\bnutrition\/[^'"\n]*['"]/;

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true }).catch(() => []);
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await walk(path));
    else if (/\.(ts|tsx|js|jsx|mjs)$/.test(entry.name)) files.push(path);
  }
  return files;
}

/** Static proof that readNutritionProfile is reachable only from its one server component. */
export async function findViolations(root) {
  const violations = [];
  for (const file of await walk(join(root, 'src'))) {
    const rel = relative(root, file).split(sep).join('/');
    if (/\.test\.(ts|tsx)$/.test(rel)) continue;
    const text = await readFile(file, 'utf8');

    if (rel === ADAPTER_MODULE) {
      const guard = text.indexOf('assertIssuedContext(');
      const cookies = text.indexOf('cookies()');
      if (guard === -1 || (cookies !== -1 && cookies < guard)) {
        violations.push(`${rel}: must call assertIssuedContext(...) before reading cookies`);
      }
      continue;
    }

    const mentionsAdapter = /profile\.server/.test(text);
    if (mentionsAdapter && !ALLOWED_ADAPTER_IMPORTERS.includes(rel)) {
      violations.push(`${rel}: imports profile.server but is not an allowed importer`);
    }
    if (mentionsAdapter && USE_CLIENT.test(text)) {
      violations.push(`${rel}: a client component must never import profile.server`);
    }
    if (USE_SERVER.test(text) && NUTRITION_SPECIFIER.test(text)) {
      violations.push(`${rel}: a 'use server' module must not import the Nutrition integration`);
    }
    if (/\/route\.(ts|tsx|js)$/.test(rel) && NUTRITION_SPECIFIER.test(text)) {
      violations.push(`${rel}: a route handler must not import the Nutrition integration`);
    }
  }
  return violations;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const violations = await findViolations(process.cwd());
  if (violations.length > 0) {
    process.stderr.write(`${violations.join('\n')}\n`);
    process.exit(1);
  }
  process.stdout.write('Adapter callers verified: only the allowed server component reaches profile.server.\n');
}
```

In `package.json` change the script to chain the static check first:

```json
"test:server-boundary": "node test-support/verify-adapter-callers.mjs && node test-support/verify-server-only-client-import.mjs",
```

- [ ] **Step 4: Run to verify it passes**

Run: `node --test test-support/verify-adapter-callers.test.mjs` → PASS. Then `node test-support/verify-adapter-callers.mjs; echo EXIT=$?`
Expected: `Adapter callers verified…` and `EXIT=0` (today nothing imports the adapter, and `profile.server.ts` has the Task 2 guard first).

- [ ] **Step 5: Commit**

```bash
git add test-support/verify-adapter-callers.mjs test-support/verify-adapter-callers.test.mjs package.json
git commit -m "test: guard which modules may reach the Nutrition adapter"
```

### Task 4: Small cleanups and regression tests

**Files:**
- Modify: `src/integration/nutrition/profile-contract.ts` (error name)
- Test: `src/integration/nutrition/profile-contract.test.ts`, `profile-loader.test.ts`
- Modify: `deploy/home-hub/tests/test_home_hub_quadlet.py`

- [ ] **Step 1: Write the failing tests**

Append to `profile-contract.test.ts`:

```ts
test('ProfileContractError carries its own name', () => {
  try { parseProfileWire(null); assert.fail('expected a throw'); } catch (error) {
    assert.ok(error instanceof ProfileContractError);
    assert.equal((error as Error).name, 'ProfileContractError');
  }
});

for (const [name, value] of [
  ['exponent overflow string', '1e999'],
  ['Infinity string', 'Infinity'],
  ['hex string', '0x10'],
  ['NaN string', 'NaN'],
] as const) {
  test(`rejects ${name} as a target value`, () => {
    assert.throws(() => parseProfileWire({ ...general, targets: { a: value } }), ProfileContractError);
  });
}

test('a __proto__ key is plain data: no prototype pollution, object values rejected', () => {
  const base = '{"context":"GENERAL","target_source":"USER_CONFIGURED","targets":';
  assert.throws(() => parseProfileWire(JSON.parse(`${base}{"__proto__":{"polluted":true}}}`)), ProfileContractError);
  const summary = parseProfileWire(JSON.parse(`${base}{"__proto__":1}}`));
  assert.equal(summary.presence === 'PRESENT' && summary.targetCount, 1);
  assert.equal(({} as Record<string, unknown>).polluted, undefined);
});
```

Append to `profile-loader.test.ts`:

```ts
test('header isolation holds case-insensitively', async () => {
  const { calls, fetcher } = scripted(minted(), json(404, { detail: 'no profile' }));
  await loadNutritionProfile({ ...live, fetcher });
  const names = (index: number) => Object.keys(calls[index].init?.headers as Record<string, string>).map((n) => n.toLowerCase());
  assert.deepEqual(names(0).filter((n) => n === 'x-episteck-delegation' || n === 'authorization'), []);
  assert.deepEqual(names(1).filter((n) => n === 'cookie' || n === 'authorization'), []);
});
```

Replace `test_hub_quadlet_publishes_only_loopback_and_uses_narrow_pasta_forwards` in `deploy/home-hub/tests/test_home_hub_quadlet.py` so it reads the value instead of hard-coding it:

```python
def _network_value() -> str:
    lines = [line for line in QUADLET.splitlines() if line.startswith('Network=')]
    assert len(lines) == 1
    return lines[0].removeprefix('Network=')


def test_hub_quadlet_publishes_only_loopback_and_uses_narrow_pasta_forwards():
    assert QUADLET.count('PublishPort=') == 1
    assert 'PublishPort=127.0.0.1:9940:3000' in QUADLET
    network = _network_value()
    assert network.startswith('pasta:')
    options = network.removeprefix('pasta:').split(',')
    forwarded = {options[i + 1] for i, option in enumerate(options) if option == '-T'}
    assert forwarded == {'9933', '9930'}
    assert options.count('-T') == len(forwarded)
    assert len(options) == 2 * len(forwarded)
    assert 'Network=host' not in QUADLET
    assert '--map-gw' not in QUADLET
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm test` (the `name` test fails: the default `Error` name is `Error`); `python -m pytest deploy/home-hub/tests -q` from the repo root (passes already against the current Quadlet; it must still pass after the rewrite).
Expected: the `ProfileContractError carries its own name` test FAILS; the other new contract tests may already pass, which is fine: they are regressions.

- [ ] **Step 3: Implement** — in `profile-contract.ts` replace `export class ProfileContractError extends Error {}` with:

```ts
export class ProfileContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProfileContractError';
  }
}
```

- [ ] **Step 4: Run the full PR-A gate** (from `apps/home-hub/`, in this order; `test:server-boundary` is last because its probe builds delete `.next`):

```bash
npm test; npm run lint
HOME_HUB_DATA_MODE=LIVE HOME_HUB_BFF_BASE_URL=http://127.0.0.1:3323 HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930 HOME_HUB_PUBLIC_ORIGIN=http://127.0.0.1:3322 npm run build
npm run test:startup-config
npm run test:e2e
npm run test:server-boundary
```
Then from the repo root: `python -m pytest deploy/home-hub/tests -q`.
Expected: all PASS. The existing e2e suite is the regression check for Task 1b (every page's layout now uses the `cache()`-wrapped, time-bounded bootstrap); `/nutrition` is still the demo in PR-A.

- [ ] **Step 5: Commit, then open PR-A**

```bash
git add src/integration/nutrition ../../deploy/home-hub/tests/test_home_hub_quadlet.py
git commit -m "test: add Nutrition contract regressions and a value-reading Quadlet test"
git push -u origin feature/home-f3c-hardening
```

PR title `feat: harden Nutrition adapter for first live caller`; description lists Tasks 1, 1b, 2, 3, 4 and pastes the Step 4 pass summaries under "Testing". Do not merge without the operator's go.

---

## PR-B — live panel and proof

### Task 5: Panel view model

**Files:**
- Create: `src/integration/nutrition/profile-panel-model.ts`
- Test: `src/integration/nutrition/profile-panel-model.test.ts`

**Interfaces:**
- Produces:

```ts
export type ProfilePanelModel =
  | { kind: 'LOADING'; subjectName: string | null }
  | { kind: 'PRESENT'; subjectName: string | null; contextLabel: string; targetSourceLabel: string; targetCount: number }
  | { kind: 'ABSENT'; subjectName: string | null }
  | { kind: 'DENIED'; subjectName: string | null }
  | { kind: 'SESSION' }
  | { kind: 'UNAVAILABLE'; subjectName: string | null }
  | { kind: 'INVALID'; subjectName: string | null }
  | { kind: 'NOT_CONFIGURED' };
export function toProfilePanelModel(envelope: DataEnvelope<ProfileSummary>, subjectName: string | null): ProfilePanelModel;
export function humanizeCode(code: string): string;
/** Fixed-vocabulary label for the one log line per read: 'PRESENT' | 'ABSENT' | a SafeUIErrorCode | 'UNEXPECTED'. */
export function outcomeLabel(envelope: DataEnvelope<ProfileSummary>): string;
```

- [ ] **Step 1: Write the failing tests**

```ts
import assert from 'node:assert/strict';
import test from 'node:test';
import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import type { ProfileSummary } from './profile-contract.ts';
import { humanizeCode, outcomeLabel, toProfilePanelModel } from './profile-panel-model.ts';

const ready = (data: ProfileSummary): DataEnvelope<ProfileSummary> =>
  ({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE', data });
const error = (errorCode: SafeUIErrorCode): DataEnvelope<ProfileSummary> =>
  ({ delivery: 'ERROR', authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE', errorCode });

test('PRESENT maps known codes to labels and keeps only the summary', () => {
  assert.deepEqual(
    toProfilePanelModel(ready({ presence: 'PRESENT', context: 'PREGNANCY', targetSource: 'REFERENCE_TARGET', targetCount: 4 }), 'Erick'),
    { kind: 'PRESENT', subjectName: 'Erick', contextLabel: 'Pregnancy', targetSourceLabel: 'Reference targets', targetCount: 4 },
  );
});

test('unknown future codes fall back to a readable label instead of failing', () => {
  const model = toProfilePanelModel(ready({ presence: 'PRESENT', context: 'POST_PARTUM', targetSource: 'COACH_SET', targetCount: 1 }), null);
  assert.equal(model.kind === 'PRESENT' && model.contextLabel, 'Post partum');
  assert.equal(model.kind === 'PRESENT' && model.targetSourceLabel, 'Coach set');
});

test('a PRESENT profile with zero targets stays PRESENT (not ABSENT)', () => {
  const model = toProfilePanelModel(ready({ presence: 'PRESENT', context: 'GENERAL', targetSource: 'USER_CONFIGURED', targetCount: 0 }), 'Erick');
  assert.equal(model.kind, 'PRESENT');
  assert.equal(model.kind === 'PRESENT' && model.targetCount, 0);
});

test('authorized ABSENT is its own state', () => {
  assert.deepEqual(toProfilePanelModel(ready({ presence: 'ABSENT' }), 'Erick'), { kind: 'ABSENT', subjectName: 'Erick' });
});

const errors: Array<[SafeUIErrorCode, string]> = [
  ['ACCESS_DENIED', 'DENIED'],
  ['SESSION_INVALID', 'SESSION'],
  ['SESSION_REQUIRED', 'SESSION'],
  ['SERVICE_UNAVAILABLE', 'UNAVAILABLE'],
  ['OFFLINE', 'UNAVAILABLE'],
  ['RESOURCE_NOT_AVAILABLE', 'UNAVAILABLE'],
  ['INVALID_RESPONSE', 'INVALID'],
  ['NOT_CONFIGURED', 'NOT_CONFIGURED'],
];
for (const [code, kind] of errors) {
  test(`${code} maps to ${kind}`, () => {
    assert.equal(toProfilePanelModel(error(code), 'Erick').kind, kind);
  });
}

test('every SafeUIErrorCode is covered by the table above', async () => {
  const { isSafeUIErrorCode } = await import('../state/SafeUIErrorCode.ts');
  for (const [code] of errors) assert.equal(isSafeUIErrorCode(code), true);
  assert.equal(errors.length, 8);
});

test('an envelope that is READY but not GRANTED, or has no data, fails safe to UNAVAILABLE', () => {
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'INDETERMINATE', freshness: 'FRESH', environment: 'LIVE', data: { presence: 'ABSENT' } }, 'E').kind, 'UNAVAILABLE');
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE' }, 'E').kind, 'UNAVAILABLE');
  assert.equal(toProfilePanelModel({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }, 'E').kind, 'UNAVAILABLE');
});

test('a READY envelope that is not LIVE fails safe to UNAVAILABLE (no mock in LIVE)', () => {
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'MOCK', data: { presence: 'ABSENT' } }, 'E').kind, 'UNAVAILABLE');
});

test('a LOADING envelope maps to LOADING', () => {
  assert.equal(toProfilePanelModel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }, 'E').kind, 'LOADING');
});

test('outcomeLabel is a fixed vocabulary that never carries identifiers or codes from the body', () => {
  assert.equal(outcomeLabel(ready({ presence: 'ABSENT' })), 'ABSENT');
  assert.equal(outcomeLabel(ready({ presence: 'PRESENT', context: 'PREGNANCY', targetSource: 'REFERENCE_TARGET', targetCount: 2 })), 'PRESENT');
  for (const [code] of errors) assert.equal(outcomeLabel(error(code)), code);
  assert.equal(outcomeLabel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }), 'UNEXPECTED');
  assert.equal(outcomeLabel({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }), 'UNEXPECTED');
});

test('the model never carries target values or raw upstream fields', () => {
  const model = toProfilePanelModel(ready({ presence: 'PRESENT', context: 'GENERAL', targetSource: 'USER_CONFIGURED', targetCount: 2 }), 'E');
  assert.deepEqual(Object.keys(model).sort(), ['contextLabel', 'kind', 'subjectName', 'targetCount', 'targetSourceLabel']);
});

test('humanizeCode', () => {
  assert.equal(humanizeCode('SOME_CODE'), 'Some code');
  assert.equal(humanizeCode('X'), 'X');
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test src/integration/nutrition/profile-panel-model.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** — `profile-panel-model.ts`:

```ts
import type { DataEnvelope } from '../state/DataEnvelope.ts';
import { isSafeUIErrorCode, type SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import type { ProfileSummary } from './profile-contract.ts';

export type ProfilePanelModel =
  | { kind: 'LOADING'; subjectName: string | null }
  | { kind: 'PRESENT'; subjectName: string | null; contextLabel: string; targetSourceLabel: string; targetCount: number }
  | { kind: 'ABSENT'; subjectName: string | null }
  | { kind: 'DENIED'; subjectName: string | null }
  | { kind: 'SESSION' }
  | { kind: 'UNAVAILABLE'; subjectName: string | null }
  | { kind: 'INVALID'; subjectName: string | null }
  | { kind: 'NOT_CONFIGURED' };

const CONTEXT_LABELS: Record<string, string> = { PREGNANCY: 'Pregnancy', GENERAL: 'General' };
const TARGET_SOURCE_LABELS: Record<string, string> = {
  REFERENCE_TARGET: 'Reference targets',
  USER_CONFIGURED: 'Personalized targets',
};

/** Fixed-vocabulary label for the one log line per read. Never IDs, names, or body content. */
export function outcomeLabel(envelope: DataEnvelope<ProfileSummary>): string {
  if (envelope.delivery === 'READY' && envelope.data) return envelope.data.presence;
  if (envelope.delivery === 'ERROR' && isSafeUIErrorCode(envelope.errorCode)) return envelope.errorCode;
  return 'UNEXPECTED';
}

/** SOME_CODE → "Some code". Used for codes the UI does not know yet. */
export function humanizeCode(code: string): string {
  const words = code.toLowerCase().replace(/_/g, ' ');
  return code.length === 0 ? code : words.charAt(0).toUpperCase() + words.slice(1);
}

function label(table: Record<string, string>, code: string): string {
  return Object.hasOwn(table, code) ? table[code] : humanizeCode(code);
}

function errorModel(code: SafeUIErrorCode | undefined, subjectName: string | null): ProfilePanelModel {
  if (code === undefined) return { kind: 'UNAVAILABLE', subjectName };
  switch (code) {
    case 'ACCESS_DENIED':
      return { kind: 'DENIED', subjectName };
    case 'SESSION_INVALID':
    case 'SESSION_REQUIRED':
      return { kind: 'SESSION' };
    case 'NOT_CONFIGURED':
      return { kind: 'NOT_CONFIGURED' };
    case 'INVALID_RESPONSE':
      return { kind: 'INVALID', subjectName };
    case 'SERVICE_UNAVAILABLE':
    case 'OFFLINE':
    case 'RESOURCE_NOT_AVAILABLE':
      return { kind: 'UNAVAILABLE', subjectName };
    default: {
      const unmapped: never = code;
      void unmapped;
      return { kind: 'UNAVAILABLE', subjectName };
    }
  }
}

/** Map one adapter envelope to exactly one deliberate panel. Pure; no React, no server imports. */
export function toProfilePanelModel(
  envelope: DataEnvelope<ProfileSummary>,
  subjectName: string | null,
): ProfilePanelModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING', subjectName };
    case 'ERROR':
      return errorModel(envelope.errorCode, subjectName);
    case 'READY': {
      const data = envelope.data;
      // A non-LIVE READY envelope is never shown on the live path: no mock in LIVE, structurally.
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !data) {
        return { kind: 'UNAVAILABLE', subjectName };
      }
      if (data.presence === 'ABSENT') return { kind: 'ABSENT', subjectName };
      return {
        kind: 'PRESENT',
        subjectName,
        contextLabel: label(CONTEXT_LABELS, data.context),
        targetSourceLabel: label(TARGET_SOURCE_LABELS, data.targetSource),
        targetCount: data.targetCount,
      };
    }
    default: {
      const unmapped: never = envelope.delivery;
      void unmapped;
      return { kind: 'UNAVAILABLE', subjectName };
    }
  }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: Step 2's command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/integration/nutrition/profile-panel-model.ts src/integration/nutrition/profile-panel-model.test.ts
git commit -m "feat: map Nutrition envelopes to deliberate panel states"
```

### Task 6: Presentation component

**Files:**
- Create: `src/components/features/nutrition/ProfilePanel.tsx`, `ProfilePanel.module.css`, `RetryButton.tsx`

**Interfaces:**
- Consumes: `ProfilePanelModel` (Task 5).
- Produces: `ProfilePanel({ model, signInHref }: { model: ProfilePanelModel; signInHref: string })` (server-safe, no hooks); `RetryButton()` (client; `router.refresh()`).
- No unit test: `node --experimental-strip-types` cannot load TSX or CSS modules. This component is covered by the Playwright suite in Task 9. Keep it free of logic: the model decides everything.
- Copy rules: do not use the words "authorized", "Consent required", "live data", or "Provenance: svc-nutrition" anywhere (the prototype-claims e2e regex forbids them and, after Task 9 Step 5, still checks LIVE `/nutrition`). Do not show internal service names: the provenance badge says "Source: Nutrition service".

- [ ] **Step 1: Create `RetryButton.tsx`**

```tsx
'use client';
import { useRouter } from 'next/navigation';
import { useTransition } from 'react';
import styles from './ProfilePanel.module.css';

/** Try again is a fresh server render: a new mint and a new Nutrition call. */
export function RetryButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <button type="button" className={styles.retry} disabled={pending} onClick={() => startTransition(() => router.refresh())}>
      {pending ? 'Trying again…' : 'Try again'}
    </button>
  );
}
```

- [ ] **Step 2: Create `ProfilePanel.tsx`**

```tsx
import type { ReactNode } from 'react';
import type { ProfilePanelModel } from '@/integration/nutrition/profile-panel-model';
import { RetryButton } from './RetryButton';
import styles from './ProfilePanel.module.css';

function Frame({ title, role, tone, busy, children }: {
  title: string; role?: 'status' | 'alert'; tone?: 'warn'; busy?: boolean; children?: ReactNode;
}) {
  return (
    <section
      className={`${styles.panel} ${tone === 'warn' ? styles.warn : ''}`}
      role={role}
      aria-busy={busy || undefined}
      data-testid="profile-panel"
    >
      <h2 className={styles.title}>{title}</h2>
      {children}
    </section>
  );
}

const who = (name: string | null) => name ?? 'this person';

export function ProfilePanel({ model, signInHref }: { model: ProfilePanelModel; signInHref: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame title="Checking Nutrition profile…" role="status" busy>
          <p className={styles.body}>Looking up the profile for {who(model.subjectName)}.</p>
          <div className={styles.skeleton} aria-hidden="true" />
        </Frame>
      );
    case 'PRESENT':
      return (
        <Frame title="Nutrition profile on file">
          <dl className={styles.facts}>
            <dt>Person</dt><dd>{who(model.subjectName)}</dd>
            <dt>Profile type</dt><dd>{model.contextLabel}</dd>
            <dt>Target source</dt><dd>{model.targetSourceLabel}</dd>
            <dt>Targets</dt><dd>{model.targetCount === 0 ? 'None configured' : `${model.targetCount} configured`}</dd>
          </dl>
          <p className={styles.body}>Target values are not shown on this page yet.</p>
          <p className={styles.badge}>Source: Nutrition service</p>
        </Frame>
      );
    case 'ABSENT':
      return (
        <Frame title={`No nutrition profile for ${who(model.subjectName)}`} role="status">
          <p className={styles.body}>Nothing has been set up in Nutrition for this person yet.</p>
        </Frame>
      );
    case 'DENIED':
      return (
        <Frame title="Access restricted" role="alert" tone="warn">
          <p className={styles.body}>Nutrition information for {who(model.subjectName)} is not available to you.</p>
        </Frame>
      );
    case 'SESSION':
      return (
        <Frame title="Your session has expired" role="alert" tone="warn">
          <p className={styles.body}>Sign in again to see Nutrition information.</p>
          <a className={styles.retry} href={signInHref}>Sign in again</a>
        </Frame>
      );
    case 'UNAVAILABLE':
      return (
        <Frame title="Nutrition is temporarily unavailable" role="alert" tone="warn">
          <p className={styles.body}>We could not reach Nutrition for {who(model.subjectName)}. Nothing is shown rather than guessing.</p>
          <RetryButton />
        </Frame>
      );
    case 'INVALID':
      return (
        <Frame title="This profile could not be shown safely" role="alert" tone="warn">
          <p className={styles.body}>Nutrition answered with something unexpected, so it was not displayed.</p>
          <RetryButton />
        </Frame>
      );
    case 'NOT_CONFIGURED':
      return (
        <Frame title="Nutrition is not set up on this Hub" role="alert" tone="warn">
          <p className={styles.body}>Ask the Episteck team to finish the Nutrition connection.</p>
        </Frame>
      );
    default: {
      const unmapped: never = model;
      void unmapped;
      return null;
    }
  }
}
```

- [ ] **Step 3: Create `ProfilePanel.module.css`**

```css
.panel {
  grid-column: 1 / -1;
  background: var(--olin-surface-card);
  border: 1px solid var(--olin-surface-border);
  border-radius: var(--olin-card-radius, 16px);
  box-shadow: var(--olin-shadow-elevation);
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.warn { border-left: 4px solid var(--olin-accent); }
.title { margin: 0; font-size: 1.25rem; color: var(--olin-text-main); }
.body { margin: 0; color: var(--olin-text-muted); max-width: 40rem; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1.5rem; margin: 0; }
.facts dt { color: var(--olin-text-muted); }
.facts dd { margin: 0; font-weight: 600; color: var(--olin-text-main); }
.badge {
  margin: 0; align-self: flex-start; font-size: 0.875rem;
  background: var(--olin-badge-bg); padding: 4px 10px; border-radius: 999px;
  color: var(--olin-text-main);
}
.retry {
  align-self: flex-start; padding: 0.625rem 1.25rem; border-radius: 8px; border: 0;
  background: var(--olin-accent); color: white; font-weight: 500; text-decoration: none; cursor: pointer;
}
.retry:disabled { opacity: 0.6; cursor: progress; }
.skeleton { height: 3rem; border-radius: 8px; background: var(--olin-badge-bg); animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.5; } }
@media (prefers-reduced-motion: reduce) { .skeleton { animation: none; } }
```

- [ ] **Step 4: Verify it compiles**

Run: `npx tsc --noEmit -p . ; npm run lint`
Expected: no new errors from these three files.

- [ ] **Step 5: Commit**

```bash
git add src/components/features/nutrition
git commit -m "feat: add Nutrition profile panel component"
```

### Task 7: Live subject resolution

**Files:**
- Create: `src/integration/nutrition/live-subject.ts` (pure), `live-subject.server.ts`
- Test: `src/integration/nutrition/live-subject.test.ts`

**Interfaces:**
- Consumes: `resolveRequestedPerson`, `F3ActiveContext` (Task 2); `getBootstrapForRequest` (`cache()`-wrapped in Task 1b, so this reuses the layout's read).
- Produces:

```ts
export type SearchParamsRecord = Record<string, string | string[] | undefined>;
export function pickSubject(bootstrap: BootstrapContext, searchParams: SearchParamsRecord):
  { context: F3ActiveContext; subjectName: string | null; stale: boolean };
// server-only:
export type LiveSubject =
  | { status: 'OK'; context: F3ActiveContext; subjectName: string | null; stale: boolean }
  | { status: 'SESSION' }
  | { status: 'UNAVAILABLE' };
export function resolveLiveSubject(searchParams: SearchParamsRecord): Promise<LiveSubject>;
```
- `stale` must reach the caller: Task 8 skips the Nutrition read on a stale selection.

- [ ] **Step 1: Write the failing tests**

```ts
import assert from 'node:assert/strict';
import test from 'node:test';
import type { BootstrapContext } from '../home/Viewer.ts';
import { isIssuedContext } from '../home/active-context.ts';
import { pickSubject } from './live-subject.ts';

const bootstrap: BootstrapContext = {
  viewer: { personId: 'PSN-00001', displayName: 'Viewer' },
  personContexts: [
    { type: 'PERSON', personId: 'PSN-00001', displayName: 'Viewer' },
    { type: 'PERSON', personId: 'PSN-00002', displayName: 'Care subject' },
  ],
  careRelationships: [{ subjectPersonId: 'PSN-00002', relationshipType: 'CAREGIVER' }],
  circleContexts: [{ type: 'CIRCLE', circleId: 'CIR-00001', displayName: 'Circle' }],
};

test('no person parameter resolves to self with a name', () => {
  const picked = pickSubject(bootstrap, {});
  assert.equal(picked.context.personId, 'PSN-00001');
  assert.equal(picked.subjectName, 'Viewer');
  assert.equal(isIssuedContext(picked.context), true);
  assert.equal(picked.stale, false);
});

test('a navigable care subject resolves with its own display name', () => {
  const picked = pickSubject(bootstrap, { person: 'PSN-00002' });
  assert.equal(picked.context.personId, 'PSN-00002');
  assert.equal(picked.subjectName, 'Care subject');
});

const stale: Array<[string, Record<string, string | string[] | undefined>]> = [
  ['unknown', { person: 'PSN-00999' }],
  ['circle', { person: 'CIR-00001' }],
  ['empty', { person: '' }],
  ['duplicated', { person: ['PSN-00002', 'PSN-00001'] }],
  ['malformed', { person: 'broken' }],
  ['oversized', { person: `PSN-${'9'.repeat(5000)}` }],
  ['trailing newline', { person: 'PSN-00002\n' }],
];
for (const [name, params] of stale) {
  test(`${name} selection falls back to self and is marked stale`, () => {
    const picked = pickSubject(bootstrap, params);
    assert.equal(picked.context.personId, 'PSN-00001');
    assert.equal(picked.stale, true);
  });
}

test('actor-shaped query noise cannot change the subject', () => {
  const picked = pickSubject(bootstrap, { person: 'PSN-00001', actorPersonId: 'PSN-00999', actor: 'PSN-00002' });
  assert.equal(picked.context.personId, 'PSN-00001');
  assert.equal(picked.stale, false);
});
```

- [ ] **Step 2: Run to verify it fails** — same node test command on `live-subject.test.ts`. Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`live-subject.ts`:

```ts
import type { BootstrapContext } from '../home/Viewer.ts';
import { resolveRequestedPerson, type F3ActiveContext } from '../home/active-context.ts';

export type SearchParamsRecord = Record<string, string | string[] | undefined>;

/** Pure: pick the validated subject for a page request. Only `person` is read. */
export function pickSubject(
  bootstrap: BootstrapContext,
  searchParams: SearchParamsRecord,
): { context: F3ActiveContext; subjectName: string | null; stale: boolean } {
  const raw = searchParams.person;
  const query = new URLSearchParams();
  for (const value of raw === undefined ? [] : Array.isArray(raw) ? raw : [raw]) query.append('person', value);
  const { status, activeContext } = resolveRequestedPerson(query, bootstrap);
  const named = bootstrap.personContexts.find((person) => person.personId === activeContext.personId)?.displayName;
  const subjectName = named
    ?? (activeContext.personId === bootstrap.viewer.personId ? bootstrap.viewer.displayName : null);
  return { context: activeContext, subjectName, stale: status === 'STALE_CONTEXT' };
}
```

`live-subject.server.ts`:

```ts
import 'server-only';
import { getBootstrapForRequest } from '../home/bootstrap.server';
import type { F3ActiveContext } from '../home/active-context';
import { pickSubject, type SearchParamsRecord } from './live-subject';

export type LiveSubject =
  | { status: 'OK'; context: F3ActiveContext; subjectName: string | null; stale: boolean }
  | { status: 'SESSION' }
  | { status: 'UNAVAILABLE' };

/**
 * The only producer of the context handed to readNutritionProfile on a page request.
 * Uses this request's session-bound bootstrap (shared with the layout through React
 * cache()); nothing the browser sends is trusted beyond the `person` selector, which
 * resolveRequestedPerson validates.
 */
export async function resolveLiveSubject(searchParams: SearchParamsRecord): Promise<LiveSubject> {
  const result = await getBootstrapForRequest();
  if (result.delivery !== 'READY' || !result.data) {
    return result.errorCode === 'SESSION_REQUIRED' || result.errorCode === 'SESSION_INVALID'
      ? { status: 'SESSION' }
      : { status: 'UNAVAILABLE' };
  }
  return { status: 'OK', ...pickSubject(result.data, searchParams) };
}
```

On a stale selection the panel does not read at all (Task 8): the client `AppProvider` (F3a) replaces the URL with self before it shows children, and that render makes the one read. The stale render's result would never be shown, so reading would only cost a mint.

- [ ] **Step 4: Run to verify it passes** — Step 2's command, then `npx tsc --noEmit -p .`. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/integration/nutrition/live-subject.ts src/integration/nutrition/live-subject.server.ts src/integration/nutrition/live-subject.test.ts
git commit -m "feat: resolve the live Nutrition subject from a fresh bootstrap"
```

### Task 8: Restructure the page; hide the demo in LIVE

**Files:**
- Move: `src/app/nutrition/page.tsx` → `src/app/nutrition/NutritionDemoCluster.tsx` (`git mv`; rename the default export function to `export function NutritionDemoCluster()`, add nothing else; the body is moved verbatim)
- Create: `src/app/nutrition/NutritionHeader.tsx`, `src/app/nutrition/LiveProfilePanel.tsx`, new `src/app/nutrition/page.tsx`
- Modify: `src/components/layout/AppShell.tsx`, `src/app/layout.tsx`

**Interfaces:**
- Consumes: `ProfilePanel`, `toProfilePanelModel`, `outcomeLabel`, `readNutritionProfile`, `resolveLiveSubject`, `SERVER_CONFIGURATION`, `unstable_rethrow` (`next/navigation`, present in 16.3.5).
- Produces: `AppShell` gains `liveRoutes?: string[]` (exact pathnames, relative to `basePath`, for which the demo banner is suppressed).
- `LiveProfilePanel` rules: the **whole** path (subject, read, mapping) sits inside one try/catch, because the app has no `error.tsx` and an escaped throw would show Next's default error page; the catch calls `unstable_rethrow(error)` first; a stale selection renders LOADING with no read; exactly one `nutrition.profile outcome=<LABEL>` line per render.

- [ ] **Step 1: Move the demo**

```bash
git mv src/app/nutrition/page.tsx src/app/nutrition/NutritionDemoCluster.tsx
```
In the moved file change `export default function NutritionPage() {` to `export function NutritionDemoCluster() {`. Leave everything else untouched, including `import styles from './page.module.css'`.

- [ ] **Step 2: Create `NutritionHeader.tsx`**

```tsx
'use client';

import React from 'react';
import { useAppContext } from '@/components/providers/AppProvider';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import styles from './page.module.css';

/** LIVE header: title and the F3a Person switcher. Selecting a Person changes `?person=`; the server re-renders. */
export function NutritionHeader() {
  const { activeContext, setContext, availableContexts } = useAppContext();
  return (
    <header className={styles.header}>
      <div>
        <h1 className={styles.title}>Nutrition Hub</h1>
        <div style={{ marginTop: '0.75rem' }}>
          <DefaultRelationshipSwitcher
            contexts={availableContexts}
            activeContextId={activeContext.personId}
            onSelectContext={(id) => setContext(id)}
          />
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 3: Create `LiveProfilePanel.tsx`** (the only importer of `profile.server`)

```tsx
import { unstable_rethrow } from 'next/navigation';
import { ProfilePanel } from '@/components/features/nutrition/ProfilePanel';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { outcomeLabel, toProfilePanelModel, type ProfilePanelModel } from '@/integration/nutrition/profile-panel-model';
import { readNutritionProfile } from '@/integration/nutrition/profile.server';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';

type SearchParams = Record<string, string | string[] | undefined>;

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, URLs, or tokens. */
function logOutcome(outcome: string) {
  console.info(`nutrition.profile outcome=${outcome}`);
}

async function resolvePanel(searchParams: SearchParams): Promise<ProfilePanelModel> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') {
    logOutcome('BOOTSTRAP_SESSION');
    return { kind: 'SESSION' };
  }
  if (subject.status === 'UNAVAILABLE') {
    logOutcome('BOOTSTRAP_UNAVAILABLE');
    return { kind: 'UNAVAILABLE', subjectName: null };
  }
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    logOutcome('STALE_SKIPPED');
    return { kind: 'LOADING', subjectName: null };
  }
  const envelope = await readNutritionProfile(subject.context);
  logOutcome(outcomeLabel(envelope));
  return toProfilePanelModel(envelope, subject.subjectName);
}

export async function LiveProfilePanel({ searchParams }: { searchParams: SearchParams }) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let model: ProfilePanelModel;
  try {
    model = await resolvePanel(searchParams);
  } catch (error) {
    unstable_rethrow(error); // let Next's own redirect and dynamic-rendering signals through
    const name = error instanceof Error && /^[A-Za-z]{1,40}$/.test(error.name) ? error.name : 'Error';
    console.error(`nutrition.profile outcome=THREW error=${name}`);
    model = { kind: 'UNAVAILABLE', subjectName: null };
  }
  return <ProfilePanel model={model} signInHref={signInHref} />;
}
```

- [ ] **Step 4: Create the new `page.tsx`**

```tsx
import { Suspense } from 'react';
import { ProfilePanel } from '@/components/features/nutrition/ProfilePanel';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { LiveProfilePanel } from './LiveProfilePanel';
import { NutritionDemoCluster } from './NutritionDemoCluster';
import { NutritionHeader } from './NutritionHeader';
import styles from './page.module.css';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function NutritionPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (SERVER_CONFIGURATION.mode === 'MOCK') return <NutritionDemoCluster />;

  const params = await searchParams;
  return (
    <div className={styles.nutritionCanvas}>
      <NutritionHeader />
      {/* A div, not <main>: AppShell already renders the page's one main landmark. */}
      <div className={styles.grid}>
        {/* Keyed on the raw selector so one subject's panel can never paint under another's. */}
        <Suspense
          key={JSON.stringify(params.person ?? null)}
          fallback={<ProfilePanel model={{ kind: 'LOADING', subjectName: null }} signInHref="" />}
        >
          <LiveProfilePanel searchParams={params} />
        </Suspense>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Suppress the demo banner on live routes**

`AppShell.tsx`: change the signature and the notice:

```tsx
export function AppShell({ children, demoContent = false, liveRoutes = [] }: {
  children: React.ReactNode; demoContent?: boolean; liveRoutes?: string[];
}) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const pathname = usePathname();

  const demoNotice = demoContent && !liveRoutes.includes(pathname) ? (
```
(keep the notice's JSX body as is). `usePathname()` excludes `basePath`, so the value is `/nutrition`.

`layout.tsx`: replace `<AppShell demoContent>{children}</AppShell>` with

```tsx
<AppShell demoContent liveRoutes={SERVER_CONFIGURATION.mode === 'LIVE' ? ['/nutrition'] : []}>{children}</AppShell>
```

- [ ] **Step 6: Verify build, boundary, and unit tests**

Run (from `apps/home-hub/`, in this order):
```bash
npm test; npm run lint
HOME_HUB_DATA_MODE=LIVE HOME_HUB_BFF_BASE_URL=http://127.0.0.1:3323 HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930 HOME_HUB_PUBLIC_ORIGIN=http://127.0.0.1:3322 npm run build
node test-support/verify-adapter-callers.mjs; echo EXIT=$?
npm run test:startup-config
npm run test:server-boundary
```
Expected: tests and lint pass; the build succeeds; `Adapter callers verified…` and `EXIT=0` (now `LiveProfilePanel.tsx` is the one allowed importer and is not a client component); startup-config passes; server-boundary passes. `test:server-boundary` runs last because it deletes `.next`; Task 9 rebuilds before e2e.

- [ ] **Step 7: Commit**

```bash
git add -A src/app/nutrition src/components/layout/AppShell.tsx src/app/layout.tsx
git commit -m "feat: serve a live Nutrition profile panel and hide the demo in LIVE"
```

### Task 9: Fakes and end-to-end suite

**Files:**
- Modify: `test-support/fake-bff.mjs`, `playwright.config.ts`, `e2e/bootstrap.spec.ts`
- Create: `test-support/fake-nutrition.mjs`, `e2e/nutrition-profile.spec.ts`

**Interfaces:**
- Scenario selection is by session cookie: `episteck_home_session=authenticated[-self-only]-nutr-<scenario>-run<id>`, where `<scenario>` ∈ `present | absent | 403 | 401 | 503 | badbody | hang` and optional `mint-401` / `mint-503` make the BFF mint fail. `<id>` is a lowercase alphanumeric run id so parallel tests never share counters. Do not name a scenario `malformed` or `status-5xx` (the existing bootstrap fake keys on those substrings).
- Fake BFF: `POST /delegation?audience=svc-nutrition` returns `delegation = DELEGATION_SENTINEL.<scenario>.<id>`; `GET /__test/mints/<id>` → `{ count }`; `GET /__test/bootstraps/<id>` → `{ count }` of `/bootstrap` reads for that run.
- Fake Nutrition (port 9930): `GET /profile/<PSN>` reads the delegation header; `GET /__test/calls/<id>` → `{ calls: [{ path, hasCookie }] }`.
- Run ids come from `crypto.randomUUID()` with the dashes removed (lowercase hex), so they never collide and never contain the bootstrap fake's trigger substrings.

- [ ] **Step 1: Extend `fake-bff.mjs`.** Add above the `createServer(` call:

```js
const mints = new Map();
const bootstraps = new Map();
const runOf = (cookie) => /run([a-z0-9]+)/.exec(cookie)?.[1] ?? 'none';
const scenarioOf = (cookie) => /nutr-([a-z0-9]+)/.exec(cookie)?.[1] ?? 'absent';
const bump = (map, run) => map.set(run, (map.get(run) ?? 0) + 1);
```

In the existing `/bootstrap` path, right after `lastCookieHeader = request.headers.cookie ?? null;`, add `bump(bootstraps, runOf(request.headers.cookie ?? ''));`.
and add these branches inside the handler, before the `request.url !== '/bootstrap'` check:

```js
  if (request.url === '/delegation?audience=svc-nutrition' && request.method === 'POST') {
    const cookie = request.headers.cookie ?? '';
    if (!cookie.includes('episteck_home_session=authenticated')) {
      response.writeHead(401, { 'content-type': 'application/json' }).end('{"detail":"no active session"}');
      return;
    }
    const run = runOf(cookie);
    bump(mints, run);
    const failure = /mint-(401|503)/.exec(cookie)?.[1];
    if (failure) {
      response.writeHead(Number(failure), { 'content-type': 'application/json' }).end('{"detail":"mint failed"}');
      return;
    }
    response.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' }).end(JSON.stringify({
      delegation: `DELEGATION_SENTINEL.${scenarioOf(cookie)}.${run}`,
      audience: 'svc-nutrition',
      expires_at: Math.floor(Date.now() / 1000) + 60,
    }));
    return;
  }
  if (request.url?.startsWith('/__test/mints/') || request.url?.startsWith('/__test/bootstraps/')) {
    const run = request.url.split('/').pop();
    const counts = request.url.startsWith('/__test/mints/') ? mints : bootstraps;
    response.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ count: counts.get(run) ?? 0 }));
    return;
  }
```

- [ ] **Step 2: Create `test-support/fake-nutrition.mjs`**

```js
import { createServer } from 'node:http';

const calls = new Map();
const PRESENT = {
  context: 'PREGNANCY',
  target_source: 'REFERENCE_TARGET',
  targets: { calcium_mg: '1000', iron_mg: '27' },
  preferences: 'PRIVATE_PREF_SENTINEL',
  dislikes: 'PRIVATE_DISLIKE_SENTINEL',
};

createServer((request, response) => {
  const url = new URL(request.url ?? '/', 'http://127.0.0.1:9930');
  if (url.pathname === '/health') {
    response.writeHead(200).end('ok');
    return;
  }
  if (url.pathname.startsWith('/__test/calls/')) {
    const run = url.pathname.split('/').pop();
    response.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ calls: calls.get(run) ?? [] }));
    return;
  }
  const match = /^\/profile\/([A-Za-z0-9-]+)$/.exec(url.pathname);
  if (!match || request.method !== 'GET') {
    response.writeHead(404).end();
    return;
  }
  const token = request.headers['x-episteck-delegation'];
  const [, scenario = 'absent', run = 'none'] = typeof token === 'string' ? token.split('.') : [];
  const list = calls.get(run) ?? [];
  list.push({ path: url.pathname, hasCookie: 'cookie' in request.headers });
  calls.set(run, list);

  const json = (status, body) => response.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body));
  switch (scenario) {
    case 'present': return json(200, PRESENT);
    case '403': return json(403, { detail: 'ACCESS_DENIED' });
    case '401': return json(401, { detail: 'SESSION_INVALID' });
    case '503': return json(503, { detail: 'SERVICE_UNAVAILABLE' });
    case 'badbody': return json(200, { context: 'general' });
    case 'hang': return undefined; // never answer; the Hub must time out
    default: return json(404, { detail: 'no profile' });
  }
}).listen(9930, '127.0.0.1');
```

- [ ] **Step 3: Start it from Playwright.** In `playwright.config.ts` add to `webServer`, before the Hub entry:

```ts
    {
      command: 'node test-support/fake-nutrition.mjs',
      url: 'http://127.0.0.1:9930/health',
      reuseExistingServer: false,
      timeout: 30_000,
    },
```

- [ ] **Step 4: Write `e2e/nutrition-profile.spec.ts`**

```ts
import { randomUUID } from 'node:crypto';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const HUB = 'http://127.0.0.1:3322';
const BFF = 'http://127.0.0.1:3323';
const NUTRITION = 'http://127.0.0.1:9930';
const newRun = () => randomUUID().replace(/-/g, '');

/** Sets the scenario cookie and returns its value, so tests can assert the value never leaks. */
async function signIn(page: Page, scenario: string, run: string, variant = '') {
  const value = `authenticated${variant}-nutr-${scenario}-run${run}`;
  await page.context().addCookies([{
    name: 'episteck_home_session', value, url: HUB, httpOnly: true, sameSite: 'Lax',
  }]);
  return value;
}

async function observed(request: APIRequestContext, run: string) {
  const mints = (await (await request.get(`${BFF}/__test/mints/${run}`)).json()).count as number;
  const calls = (await (await request.get(`${NUTRITION}/__test/calls/${run}`)).json()).calls as Array<{ path: string; hasCookie: boolean }>;
  return { mints, calls };
}

async function bootstrapReads(request: APIRequestContext, run: string) {
  return (await (await request.get(`${BFF}/__test/bootstraps/${run}`)).json()).count as number;
}

/** Every document and fetch body (RSC payloads, /api/context) the browser receives from the Hub. */
function captureHubBodies(page: Page) {
  const pending: Array<Promise<string>> = [];
  page.on('response', (response) => {
    const type = response.request().resourceType();
    if (response.url().startsWith(`${HUB}/`) && (type === 'document' || type === 'fetch')) {
      pending.push(response.text().catch(() => ''));
    }
  });
  return async () => (await Promise.all(pending)).join('\n');
}

async function trackCspViolations(page: Page) {
  await page.addInitScript(() => {
    const w = window as typeof window & { __cspViolations?: string[] };
    w.__cspViolations = [];
    window.addEventListener('securitypolicyviolation', (event) => {
      w.__cspViolations?.push(`${event.violatedDirective}: ${event.blockedURI}`);
    });
  });
  return () => page.evaluate(() => (window as typeof window & { __cspViolations?: string[] }).__cspViolations ?? []);
}

const panel = (page: Page) => page.getByTestId('profile-panel');
const MOCK_STRINGS = /kcal|Protein|Carbs|Mealie|View Dashboard|Pregnancy Nutrition|Consent required/i;
const SECRETS = ['DELEGATION_SENTINEL', 'COOKIE_SENTINEL', 'PRIVATE_PREF_SENTINEL', 'PRIVATE_DISLIKE_SENTINEL', 'episteck_home_session'];

function expectNoSecrets(text: string, cookieValue: string) {
  for (const secret of [...SECRETS, cookieValue]) expect(text, secret).not.toContain(secret);
}

test('PRESENT: one mint, one call, minimized, no-store, no mock, no secrets, no CSP violations, no demo banner', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'present', run, '-self-only');
  const cspViolations = await trackCspViolations(page);
  const hubBodies = captureHubBodies(page);
  const response = await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Nutrition profile on file');
  await expect(panel(page)).toContainText('Pregnancy');
  await expect(panel(page)).toContainText('Reference targets');
  await expect(panel(page)).toContainText('2 configured');
  await expect(panel(page)).toContainText('Source: Nutrition service');

  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);

  expect(response?.headers()['cache-control']).toContain('no-store');
  const html = (await response?.text()) ?? '';
  expect(new Set(html.match(/PSN-\d{5,}/g) ?? [])).toEqual(new Set(html.includes('PSN-00001') ? ['PSN-00001'] : []));
  expectNoSecrets(await hubBodies(), cookieValue);
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_STRINGS);
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  await expect.poll(cspViolations).toEqual([]);
});

test('one document render: layout and panel share one bootstrap, one mint, one Nutrition call', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  // Document only: no hydration and no /api/context, so the counters see the server render alone.
  const response = await page.request.get(`${HUB}/app/nutrition`);
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('No nutrition profile');
  expect(await bootstrapReads(request, run)).toBe(1);
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toHaveLength(1);
});

test('other pages never prefetch or render the Nutrition read', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run);
  await page.goto('/app');
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  await page.getByRole('link', { name: 'Nutrition', exact: true }).first().hover();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1_000);
  expect(await observed(request, run)).toEqual({ mints: 0, calls: [] });
});

test('the demo banner still shows on other routes in LIVE', async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/health');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toBeVisible();
});

test('ABSENT renders an honest empty state, not zeros or mock', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_STRINGS);
  expect((await observed(request, run)).mints).toBe(1);
});

test('DENIED shows Access restricted with no reason and keeps the subject', async ({ page }) => {
  await signIn(page, '403', newRun());
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('Access restricted');
  await expect(panel(page)).toContainText('Synthetic Care Context');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');
  await expect(page).toHaveURL(/person=PSN-00007$/);
});

test('a session that dies after the layout shows a sign-in panel', async ({ page }) => {
  await signIn(page, '401', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Your session has expired');
  await expect(page.getByRole('link', { name: 'Sign in again' })).toHaveAttribute('href', 'http://127.0.0.1:3322/login');
});

test('unavailable offers Try again; a retry mints a fresh delegation and leaks nothing', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, '503', run);
  const hubBodies = captureHubBodies(page);
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('temporarily unavailable');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(2);
  expect((await observed(request, run)).calls).toHaveLength(2);
  await expect(page.getByRole('button', { name: 'Try again' })).toBeEnabled();
  expectNoSecrets(await hubBodies(), cookieValue);
});

test('a failed mint shows unavailable and never calls Nutrition', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run, '-mint-503');
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('temporarily unavailable');
  expect((await observed(request, run)).calls).toEqual([]);
});

test('a malformed Nutrition body is shown as could-not-be-shown-safely', async ({ page }) => {
  await signIn(page, 'badbody', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('could not be shown safely');
});

test('a hung Nutrition upstream streams a skeleton, then times out to unavailable', async ({ page }) => {
  test.setTimeout(30_000);
  await signIn(page, 'hang', newRun());
  await page.goto('/app/nutrition', { waitUntil: 'commit' });
  await expect(page.getByRole('heading', { name: 'Nutrition Hub' })).toBeVisible();
  await expect(panel(page)).toContainText('Checking Nutrition profile');
  await expect(panel(page)).toContainText('temporarily unavailable', { timeout: 15_000 });
});

for (const person of ['PSN-00999', 'CIR-00001', 'broken', '']) {
  test(`stale selection "${person}" makes no read for it; the canonical self URL makes exactly one`, async ({ page, request }) => {
    const run = newRun();
    await signIn(page, 'absent', run);
    await page.goto(`/app/nutrition?person=${person}`);
    await expect(page).toHaveURL(/person=PSN-00001$/);
    await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
    const { mints, calls } = await observed(request, run);
    expect(mints).toBe(1);
    expect(calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
  });
}

test('actor-shaped query noise cannot change the subject', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition?person=PSN-00001&actorPersonId=PSN-00999');
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
  expect((await observed(request, run)).calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
});

test('switching subject re-reads for the new subject; Back restores the earlier panel without a new read', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'absent', run);
  const hubBodies = captureHubBodies(page);
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Care Context');
  await page.getByRole('tab', { name: /Synthetic Viewer/ }).click();
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
  await expect(panel(page)).not.toContainText('Synthetic Care Context');
  await page.goBack();
  await expect(page).toHaveURL(/person=PSN-00007$/);
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Care Context');
  await expect(panel(page)).not.toContainText('Synthetic Viewer');
  await page.waitForLoadState('networkidle');
  // Pinned (spec Invariants (b)): Next restores the history entry from its client router cache, so Back makes no new read.
  const paths = (await observed(request, run)).calls.map((call) => call.path);
  expect(paths).toEqual(['/profile/PSN-00007', '/profile/PSN-00001']);
  expectNoSecrets(await hubBodies(), cookieValue);
});
```

- [ ] **Step 5: Update `e2e/bootstrap.spec.ts`** (it asserted the LIVE mock cluster):
  - Delete the test `prototype Nutrition content is clearly marked as demo mock data`.
  - Replace `prototype routes label domain content and make no consent or live-source claims` with the version below. LIVE `/nutrition` keeps the claims check (the panel copy must pass it) but has no demo note, and its "View Dashboard" click-through is gone (that card is demo-only; `/nutrition/pregnancy` is still visited directly in the first loop).

```ts
test('prototype routes label domain content and make no consent or live-source claims', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  const forbiddenClaims = /Consent Granted|Consent required|Full Clinical Consent|authorized|Active care consent|Care Circle Access|Home Secure|Source: FHIR Gateway|Source: Device Gateway|Provenance: svc-nutrition|Live Status|live data|Active Care Link|Shared with you/i;
  const demoNote = page.getByRole('note', { name: 'Demo mock data' });
  // In LIVE, /app/nutrition renders the real panel (the fake answers "no profile"): no demo note, same claims rule.
  async function settled(path: string, subject: string) {
    if (path === '/app/nutrition') await expect(page.getByTestId('profile-panel')).toContainText(`No nutrition profile for ${subject}`);
    else await expect(demoNote).toBeVisible();
  }
  for (const path of [
    '/app', '/app/health', '/app/nutrition', '/app/nutrition/pregnancy',
    '/app/calendar', '/app/memory', '/app/ask', '/app/kiosk', '/app/settings/privacy',
  ]) {
    await page.goto(path);
    await settled(path, 'Synthetic Viewer');
    expect(await page.locator('body').innerText(), path).not.toMatch(forbiddenClaims);
  }
  for (const path of ['/app', '/app/health', '/app/nutrition']) {
    await page.goto(path);
    await page.getByRole('tab', { name: 'Synthetic Care Context' }).click();
    await settled(path, 'Synthetic Care Context');
    expect(await page.locator('body').innerText(), `${path} care context`).not.toMatch(forbiddenClaims);
  }
});
```

- [ ] **Step 6: Build and run e2e**

```bash
HOME_HUB_DATA_MODE=LIVE HOME_HUB_BFF_BASE_URL=http://127.0.0.1:3323 HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930 HOME_HUB_PUBLIC_ORIGIN=http://127.0.0.1:3322 npm run build
npm run test:e2e
```
Expected: all new tests plus the pre-existing specs pass. Contingencies, to be handled in this task and not deferred:
  - If the `cache-control` assertion fails (document lacks `no-store`), add to `next.config.ts` a `headers()` entry for `/nutrition` returning `Cache-Control: no-store` and `Referrer-Policy: no-referrer`, then rerun.
  - If a `mints` or `calls` count is 2 where 1 is expected, a Link prefetch or double render is executing the panel: find the source (do not loosen the assertion), because "one mint per read" is a load-bearing invariant.
  - If the Playwright run reports a port 9930 conflict, stop the local process using it.
  - If the prefetch test sees a mint or a call, a `<Link>` prefetch is executing the page: set `prefetch={false}` on the `/nutrition` links in `src/components/layout/Sidebar.tsx` and `BottomNav.tsx`, rerun, and say so in the PR. Do not loosen the test.
  - If the document-only test counts 2 bootstrap reads, React `cache()` is not shared between the layout and the panel (Task 1b): find why (for example a second module instance of `bootstrap.server.ts`) before touching the assertion.
  - If the switch test sees a third call after `goBack()`, this Next version re-reads on history navigation. Either behavior is acceptable, but the test and the spec must agree: expect `['/profile/PSN-00007', '/profile/PSN-00001', '/profile/PSN-00007']`, change the spec's Invariants exception (b), Finding 8, and the matching Assumptions line to say Back re-reads, and report it.
  - If a sentinel or the cookie value shows up in a captured body, find which response carries it (log `response.url()` in `captureHubBodies` temporarily). Never narrow the scan.

Report which contingencies fired in the PR description.

- [ ] **Step 7: Commit**

```bash
git add test-support/fake-bff.mjs test-support/fake-nutrition.mjs playwright.config.ts e2e
git commit -m "test: cover every Nutrition panel state with fake upstreams"
```
If the prefetch contingency fired, commit the `Sidebar.tsx`/`BottomNav.tsx` change separately first: `fix: do not prefetch the live Nutrition page`.

### Task 10: Runbook, docs, and PR-B

**Files:**
- Modify: `deploy/home-hub/README.md` (new section after "F3b live rollout (2026-10-12)")
- Modify: `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` (F3c status in the header and §10 implementation-status paragraph)
- Modify: `docs/superpowers/specs/2026-10-12-home-f3c-nutrition-ui-design.md` (status line → merged-plan reference)

- [ ] **Step 1: Add the R4 runbook** to the README as `## F3c rollout gate R4 (runbook, not yet run)`, containing, in order: (1) baseline confirmation read-only (live image is the F3b `89e0550…`, `NRestarts=0`, Quadlet SHA-256 `f75178fc…` plus the R3 `Network=`/`Environment=` lines present); (2) build as `svc-home-hub` from a `git archive` of `apps/home-hub` at the merge SHA, and the throwaway probe with `--network pasta:-T,9933,-T,9930`, reusing the exact R3 commands from "F3b live rollout (2026-10-12)"; (3) Quadlet backup to `/var/backups/episteck/home-f3c-<SHA>/` and the apply, whose diff must be exactly the `Image=` line; (4) verification (9933/9930 reachable, 9931/9932/9934 refused, host listeners on `127.0.0.1`, anonymous `/app/nutrition` 307 to `/login`, second restart with `NRestarts=0`); (5) the authenticated read-only proof from the spec's R4 steps 5–6: the read count from the Hub journal over the proof window (exactly one `nutrition.profile outcome=` line per page load; the stale `?person=` check shows `outcome=STALE_SKIPPED` followed by one read line), read with the same journal access as the R3 log-hygiene check; the log-hygiene grep over Hub, BFF, and Nutrition logs (`PSN-`, cookie, bearer, JWT-shaped, delegation: no matches); the exact wording rule ("authorized no-profile response", never "populated profile rendered"); and the observed-live versus tests-only table, with per-load mint and Nutrition-call counts marked "tests only"; (6) rollback (restore the saved Quadlet byte for byte, reload, restart, repeat step 4).

- [ ] **Step 2: Update the proposal and spec status.** In the proposal header note F3b live (R3 PASS 2026-10-12) and F3c spec/plan approved (revised 2026-10-13), implementation in review (PR-A #<n>, PR-B #<n>). In the spec change only the `**Status:**` line, to `Approved 2026-10-13; revised 2026-10-13. Implemented in PR-A #<n> and PR-B #<n>; gate R4 not yet run. Implementation plan: docs/superpowers/plans/2026-10-13-home-f3c-nutrition-ui.md`. (The branded-context entry already describes the `globalThis` registry.) If a Task 9 contingency changed documented behavior (for example Back/Forward), that spec edit belongs in this commit too.

- [ ] **Step 3: Verify docs and the whole suite**

Run (repo root): `grep -n "F3c rollout gate R4" deploy/home-hub/README.md` (one match); `python -m pytest deploy/home-hub/tests -q`. Run (from `apps/home-hub/`, in this order):

```bash
npm test; npm run lint
HOME_HUB_DATA_MODE=LIVE HOME_HUB_BFF_BASE_URL=http://127.0.0.1:3323 HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930 HOME_HUB_PUBLIC_ORIGIN=http://127.0.0.1:3322 npm run build
npm run test:startup-config
npm run test:e2e
npm run test:server-boundary
```
Expected: every command passes. `test:server-boundary` is last because it deletes `.next`. Paste the pass summaries in the PR description under "Testing".

- [ ] **Step 4: Commit and open PR-B** (from the repo root)

```bash
git add deploy/home-hub/README.md docs
git commit -m "docs: add F3c rollout gate R4 runbook and status"
git push -u origin feature/home-f3c-nutrition-ui
gh pr create --base feature/home-f3c-hardening --title "feat: show live Nutrition profile panel on /nutrition"
```
PR body: first line "Stacked on PR-A (#<n>); review the commits after it.", then Summary, Changes (Tasks 5–10), Testing (the command output above), Contingencies (which Task 9 Step 6 items fired, or "none"), and "Not run: gate R4, which needs the operator". When PR-A merges, follow "Branches and PRs" step 3 to rebase and retarget. No merge or deploy without the operator's go.

---

## Rollout gate R4 (operator-run; Claude runs read-only checks)

Follow the runbook added in Task 10 after PR-A and PR-B are merged and the operator gives the go. Claude prepares the exact `!` ssh commands and the byte-for-byte rollback up front, the operator runs the Quadlet change, and Claude verifies read-only and writes the evidence PR. A live Erick page load is the only authenticated proof; no fixtures, Persons, grants, profiles, or fault drills are created. The live read count comes from the Hub's `nutrition.profile outcome=` journal lines (one per page load, `STALE_SKIPPED` for the stale check); per-load mint and Nutrition-call counts and every error state are recorded as "tests only" in the evidence.

## Self-review record

- **Spec coverage:** S1 scope A (Tasks 5–6 render only summary fields; the model test pins the key set); S2 streaming and 4 s per-fetch timeout on bootstrap, mint, and profile (Tasks 1, 1b, 8, 9 hang scenario); S3 read-only proof (R4 section, Task 10, outcome log line from Task 8); S4 hide the cluster in LIVE (Task 8, Task 9 mock-string and banner assertions); demo-banner finding (Task 8 Step 5, Task 9 banner tests); fake-Nutrition finding (Task 9); entry criteria 1 (Tasks 1 and 1b), 2 (Task 3 and Task 2 guard), 3 (Task 2), 4 (Task 4); subject re-derivation, stale no-read, switch race, Back/Forward pin (Tasks 7, 8, 9); shared bootstrap (Task 1b, Task 9 document-only test); prefetch invariant (Task 9); whole-path error guard (Task 8); claims check on LIVE `/nutrition` (Task 9 Step 5); every envelope state has a model case (Task 5) and a rendered panel (Task 6) and an e2e scenario (Task 9) except NOT_CONFIGURED, which is unit-tested only because the e2e Hub is always configured.
- **Placeholders:** none; the one runbook task (Task 10) points to existing R3 commands in the same README rather than repeating them, which is deliberate since they must be copied from the live record at gate time. `<n>` in PR references is filled in when the PRs exist.
- **Type consistency:** `F3ActiveContext` (branded) is produced only in Task 2 and consumed in Tasks 7 and 8; `PersonContextView` is the client wire type used by `AppProvider`; `ProfilePanelModel` and `outcomeLabel` (Task 5) feed `ProfilePanel` (Task 6) and `LiveProfilePanel` (Task 8); `LiveSubject.stale` (Task 7) is consumed in Task 8; `SearchParamsRecord` (Task 7) matches `page.tsx` and `LiveProfilePanel`'s `Record<string, string | string[] | undefined>`; `FETCH_TIMEOUT_MS`, `isAbortError`, and `discardBody` live in `src/integration/state/fetch-timeout.ts` (Task 1) and are used by both loaders (Tasks 1 and 1b).
- **Verification order:** every gate runs `test:server-boundary` last (Tasks 4, 8, 10), because its failing probe builds delete `.next` (Next 16.3.5 `dist/build/index.js:623`).
- **Known gaps stated honestly:** the MOCK branch of the page and the `ProfilePanel`/`NutritionHeader` TSX are not unit-tested (strip-types cannot load TSX); MOCK is dev-only and the demo cluster is moved verbatim, and the LIVE e2e suite covers the TSX. A stale render whose client bootstrap disagrees (topology changed in the same instant) leaves the panel loading until the next navigation; accepted in the spec. The outcome log line is not asserted in e2e (Hub stdout is not captured); `outcomeLabel` is unit-tested and R4 reads the line live.
