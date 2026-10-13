import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { loadBootstrap } from './bootstrap-loader.ts';
import { FETCH_TIMEOUT_MS } from '../state/fetch-timeout.ts';

const fixture = {
  version: 1,
  viewer: { personId: 'PSN-00001', displayName: 'Erick' },
  personContexts: [{ type: 'PERSON', personId: 'PSN-00001', displayName: 'Erick' }],
  circleContexts: [],
  careRelationships: [],
};

function response(status: number, body: unknown = fixture): Response {
  return new Response(JSON.stringify(body), { status });
}

test('MOCK mode uses local bootstrap data and never calls fetch', async () => {
  let fetchCalls = 0;
  const result = await loadBootstrap({
    mode: 'MOCK',
    cookieValue: undefined,
    bffBaseUrl: undefined,
    fetcher: async () => { fetchCalls += 1; return response(200); },
  });
  assert.equal(fetchCalls, 0);
  assert.equal(result.delivery, 'READY');
  assert.equal(result.environment, 'MOCK');
  assert.equal(result.data?.viewer.displayName, 'Erick');
});

test('LIVE mode fetches exactly trusted /bootstrap with no-store and one cookie', async () => {
  let requestUrl = '';
  let requestInit: RequestInit | undefined;
  const result = await loadBootstrap({
    mode: 'LIVE',
    cookieValue: 'opaque-session',
    bffBaseUrl: 'http://127.0.0.1:9933',
    fetcher: async (input, init) => {
      requestUrl = String(input);
      requestInit = init;
      return response(200);
    },
  });
  assert.equal(result.delivery, 'READY');
  assert.equal(requestUrl, 'http://127.0.0.1:9933/bootstrap');
  assert.equal(requestInit?.cache, 'no-store');
  assert.deepEqual(requestInit?.headers, {
    Accept: 'application/json',
    Cookie: 'episteck_home_session=opaque-session',
  });
});

test('request host headers cannot steer the trusted BFF URL', async () => {
  let target = '';
  await loadBootstrap({
    mode: 'LIVE',
    cookieValue: 'opaque-session',
    bffBaseUrl: 'http://trusted-bff:9933',
    fetcher: async (input) => { target = String(input); return response(200); },
  });
  assert.equal(target, 'http://trusted-bff:9933/bootstrap');
  const { readFile } = await import('node:fs/promises');
  const { resolve } = await import('node:path');
  const serverAdapter = await readFile(resolve('src/integration/home/bootstrap.server.ts'), 'utf8');
  assert.match(serverAdapter, /cookies\(\)/);
  assert.doesNotMatch(serverAdapter, /headers\(\)|x-forwarded-host|request\.url/i);
});

test('401 requests one login handoff; 502 and 503 remain safe failures', async () => {
  const load = (status: number) => loadBootstrap({
    mode: 'LIVE', cookieValue: 'opaque-session', bffBaseUrl: 'http://127.0.0.1:9933',
    fetcher: async () => response(status),
  });
  assert.equal((await load(401)).errorCode, 'SESSION_INVALID');
  assert.equal((await load(502)).errorCode, 'INVALID_RESPONSE');
  assert.equal((await load(503)).errorCode, 'SERVICE_UNAVAILABLE');
});

test('logs contain no identifiers, cookies, URLs, or bootstrap data', async () => {
  const logged: unknown[][] = [];
  const originalError = console.error;
  console.error = (...values: unknown[]) => { logged.push(values); };
  const malformed = await loadBootstrap({
    mode: 'LIVE',
    cookieValue: 'opaque-session-secret',
    bffBaseUrl: 'http://trusted-bff:9933',
    fetcher: async () => response(200, { viewer: { personId: 'PSN-99999', displayName: 'private' } }),
  });
  console.error = originalError;
  assert.equal(malformed.errorCode, 'INVALID_RESPONSE');
  assert.equal(malformed.delivery, 'ERROR');
  assert.deepEqual(logged, []);
});

test('server adapter has a server-only guard and is not imported by client modules', async () => {
  const { readFile } = await import('node:fs/promises');
  const { resolve } = await import('node:path');
  const adapter = await readFile(resolve('src/integration/home/bootstrap.server.ts'), 'utf8');
  assert.match(adapter, /import ['"]server-only['"]/);
  const clientImport = spawnSync(process.execPath, ['-e', "require('server-only')"], {
    cwd: process.cwd(),
    encoding: 'utf8',
  });
  assert.notEqual(clientImport.status, 0);
  assert.match(clientImport.stderr, /cannot be imported from a Client Component module/i);
  const clientSources = await Promise.all([
    'src/components/providers/AppProvider.tsx',
    'src/components/layout/AppShell.tsx',
  ].map((path) => readFile(resolve(path), 'utf8')));
  assert.equal(clientSources.some((source) => /bootstrap\.server/.test(source)), false);
});

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
