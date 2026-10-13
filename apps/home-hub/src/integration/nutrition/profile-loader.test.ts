import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadNutritionProfile, type LoadNutritionProfileOptions } from './profile-loader.ts';
import { createServer } from 'node:http';
import { FETCH_TIMEOUT_MS } from '../state/fetch-timeout.ts';

type Call = { url: string; init: RequestInit | undefined };

function scripted(...responses: Array<Response | Error>) {
  const calls: Call[] = [];
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    const next = responses.shift();
    if (!next) throw new Error('unexpected extra request');
    if (next instanceof Error) throw next;
    return next;
  }) as typeof fetch;
  return { calls, fetcher };
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
const minted = () => json(200, { delegation: 'tok-opaque', audience: 'svc-nutrition', expires_at: 1 });
const PROFILE = { context: 'PREGNANCY', target_source: 'REFERENCE_TARGET', targets: { calcium_mg: '1000' }, preferences: 'private' };
const live = {
  mode: 'LIVE' as const,
  personId: 'PSN-00013',
  cookieValue: 'opaque-session',
  bffBaseUrl: 'http://127.0.0.1:9933',
  nutritionBaseUrl: 'http://127.0.0.1:9930',
};

test('authorized present profile: one mint, one Nutrition call, minimized data', async () => {
  const { calls, fetcher } = scripted(minted(), json(200, PROFILE));
  const result = await loadNutritionProfile({ ...live, fetcher });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'http://127.0.0.1:9933/delegation?audience=svc-nutrition');
  assert.equal(calls[0].init?.method, 'POST');
  assert.equal(calls[1].url, 'http://127.0.0.1:9930/profile/PSN-00013');
  assert.equal(calls[1].init?.method, 'GET');
  assert.deepEqual(result, {
    delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE',
    data: { presence: 'PRESENT', context: 'PREGNANCY', targetSource: 'REFERENCE_TARGET', targetCount: 1 },
  });
});

test('authorized absent profile maps to READY ABSENT, never zeros or mock', async () => {
  const { fetcher } = scripted(minted(), json(404, { detail: 'no profile' }));
  const result = await loadNutritionProfile({ ...live, fetcher });
  assert.equal(result.delivery, 'READY');
  assert.equal(result.environment, 'LIVE');
  assert.deepEqual(result.data, { presence: 'ABSENT' });
});

test('cookie goes only to the BFF; delegation only to Nutrition; both no-store and manual redirect', async () => {
  const { calls, fetcher } = scripted(minted(), json(200, PROFILE));
  const result = await loadNutritionProfile({ ...live, fetcher });
  const bffHeaders = calls[0].init?.headers as Record<string, string>;
  const nutritionHeaders = calls[1].init?.headers as Record<string, string>;
  assert.equal(bffHeaders.Cookie, 'episteck_home_session=opaque-session');
  assert.equal('X-Episteck-Delegation' in bffHeaders, false);
  assert.equal(nutritionHeaders['X-Episteck-Delegation'], 'tok-opaque');
  assert.equal('Cookie' in nutritionHeaders, false);
  for (const call of calls) {
    assert.equal(call.init?.cache, 'no-store');
    assert.equal(call.init?.redirect, 'manual');
  }
  assert.equal(JSON.stringify(result).includes('tok-opaque'), false);
});

test('subject is URL-encoded into the Nutrition path', async () => {
  const { calls, fetcher } = scripted(minted(), json(404, { detail: 'no profile' }));
  await loadNutritionProfile({ ...live, personId: 'PSN-A-1', fetcher });
  assert.equal(calls[1].url, 'http://127.0.0.1:9930/profile/PSN-A-1');
});

test('MOCK makes no network calls', async () => {
  const { calls, fetcher } = scripted();
  const result = await loadNutritionProfile({ ...live, mode: 'MOCK', fetcher });
  assert.equal(calls.length, 0);
  assert.equal(result.environment, 'MOCK');
});

const noNetwork: Array<[string, Partial<LoadNutritionProfileOptions>, string]> = [
  ['no cookie', { cookieValue: undefined }, 'SESSION_REQUIRED'],
  ['invalid person id', { personId: 'PSN/../x' }, 'INVALID_RESPONSE'],
  ['missing Nutrition origin', { nutritionBaseUrl: undefined }, 'NOT_CONFIGURED'],
  ['missing BFF origin', { bffBaseUrl: undefined }, 'NOT_CONFIGURED'],
];
for (const [name, override, code] of noNetwork) {
  test(`${name}: ${code} with no network call`, async () => {
    const { calls, fetcher } = scripted();
    const result = await loadNutritionProfile({ ...live, ...override, fetcher });
    assert.equal(calls.length, 0);
    assert.equal(result.errorCode, code);
    assert.equal(result.data, undefined);
  });
}

const mintFailures: Array<[string, Response | Error, string]> = [
  ['BFF 401 (expired or invalid session)', json(401, { detail: 'no active session' }), 'SESSION_INVALID'],
  ['BFF 500', json(500, {}), 'SERVICE_UNAVAILABLE'],
  ['BFF unreachable', new TypeError('fetch failed'), 'SERVICE_UNAVAILABLE'],
  ['BFF non-JSON', new Response('<html>', { status: 200 }), 'INVALID_RESPONSE'],
  ['BFF missing delegation', json(200, { audience: 'svc-nutrition' }), 'INVALID_RESPONSE'],
  ['BFF empty delegation', json(200, { delegation: '', audience: 'svc-nutrition' }), 'INVALID_RESPONSE'],
  ['BFF wrong audience', json(200, { delegation: 'tok', audience: 'home-control-plane' }), 'INVALID_RESPONSE'],
];
for (const [name, response, code] of mintFailures) {
  test(`mint failure (${name}) maps to ${code} and never calls Nutrition`, async () => {
    const { calls, fetcher } = scripted(response);
    const result = await loadNutritionProfile({ ...live, fetcher });
    assert.equal(calls.length, 1);
    assert.equal(result.errorCode, code);
    assert.equal(result.data, undefined);
  });
}

const nutritionOutcomes: Array<[string, Response | Error, string, string]> = [
  ['403 denial', json(403, { detail: 'ACCESS_DENIED' }), 'ACCESS_DENIED', 'DENIED'],
  ['401 invalid or expired delegation', json(401, { detail: 'SESSION_INVALID' }), 'SESSION_INVALID', 'INDETERMINATE'],
  ['503 policy unavailable', json(503, { detail: 'SERVICE_UNAVAILABLE' }), 'SERVICE_UNAVAILABLE', 'INDETERMINATE'],
  ['500 crash', json(500, {}), 'SERVICE_UNAVAILABLE', 'INDETERMINATE'],
  ['unreachable', new TypeError('fetch failed'), 'SERVICE_UNAVAILABLE', 'INDETERMINATE'],
  ['malformed 200', json(200, { context: 'general' }), 'INVALID_RESPONSE', 'INDETERMINATE'],
  ['non-JSON 200', new Response('<html>', { status: 200 }), 'INVALID_RESPONSE', 'INDETERMINATE'],
  ['route-missing 404', json(404, { detail: 'Not Found' }), 'INVALID_RESPONSE', 'INDETERMINATE'],
  ['unexpected 302', new Response(null, { status: 302 }), 'INVALID_RESPONSE', 'INDETERMINATE'],
];
for (const [name, response, code, authorization] of nutritionOutcomes) {
  test(`Nutrition ${name} maps to ${code} with no data`, async () => {
    const { calls, fetcher } = scripted(minted(), response);
    const result = await loadNutritionProfile({ ...live, fetcher });
    assert.equal(calls.length, 2);
    assert.equal(result.delivery, 'ERROR');
    assert.equal(result.errorCode, code);
    assert.equal(result.authorization, authorization);
    assert.equal(result.data, undefined);
  });
}

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
