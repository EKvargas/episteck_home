import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadDiaryPeriod } from './period-loader.ts';

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
const BLOCK = { known: null, items_total: 0, items_uncounted: 0, status: 'NONE', target: null, percent: null };
const AVG = { average_known: null, average_percent: null, days_used: 0, left_out: { open: 0, no_entries: 1, partial: 0 } };
const DAY = {
  date: '2026-11-18', day_status: 'NO_ENTRIES', mode: 'GENERAL', trimester: null, profile_version: null,
  free_sugars_known_g: null, items_uncounted: 0,
  nutrients: { energy_kcal: BLOCK, protein_g: BLOCK, fiber_g: BLOCK },
  free_sugars: { known: null, items_uncounted: 0, status: 'NONE', limit_g: null, percent: null },
};
const PERIOD = {
  start: '2026-11-18', end: '2026-11-18', has_profile: false, days: [DAY],
  averages: { energy_kcal: AVG, protein_g: AVG, fiber_g: AVG, free_sugars_g: AVG },
};
const live = {
  mode: 'LIVE' as const,
  personId: 'PSN-00001',
  cookieValue: 'opaque-session',
  bffBaseUrl: 'http://127.0.0.1:9933',
  nutritionBaseUrl: 'http://127.0.0.1:9930',
  start: '2026-11-18',
};

test('MOCK never fetches and returns a non-LIVE envelope', async () => {
  const { calls, fetcher } = scripted();
  const r = await loadDiaryPeriod({ ...live, mode: 'MOCK', fetcher });
  assert.equal(calls.length, 0);
  assert.equal(r.delivery, 'READY');
  assert.equal(r.environment, 'MOCK');
});

const noNetwork: Array<[string, Partial<Parameters<typeof loadDiaryPeriod>[0]>, string]> = [
  ['missing Nutrition URL', { nutritionBaseUrl: undefined }, 'NOT_CONFIGURED'],
  ['missing BFF URL', { bffBaseUrl: undefined }, 'NOT_CONFIGURED'],
  ['missing cookie', { cookieValue: undefined }, 'SESSION_REQUIRED'],
  ['bad person id', { personId: 'PSN/../x' }, 'INVALID_RESPONSE'],
  ['bad start', { start: '2026-11-18&x=1' }, 'INVALID_RESPONSE'],
];
test('missing URLs, missing cookie, a bad person id and a bad start fail before any fetch', async () => {
  for (const [name, override, code] of noNetwork) {
    const { calls, fetcher } = scripted();
    const r = await loadDiaryPeriod({ ...live, ...override, fetcher });
    assert.equal(calls.length, 0, name);
    assert.equal(r.errorCode, code, name);
    assert.equal(r.data, undefined, name);
  }
});

test('one mint, then one GET /diary/PSN-00001/period?start=2026-11-18 with the delegation and without the cookie', async () => {
  const { calls, fetcher } = scripted(minted(), json(200, PERIOD));
  const r = await loadDiaryPeriod({ ...live, fetcher });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'http://127.0.0.1:9933/delegation?audience=svc-nutrition');
  assert.equal(calls[0].init?.method, 'POST');
  assert.equal(calls[1].url, 'http://127.0.0.1:9930/diary/PSN-00001/period?start=2026-11-18');
  assert.equal(calls[1].init?.method, 'GET');
  const h = calls[1].init?.headers as Record<string, string>;
  assert.equal(h['X-Episteck-Delegation'], 'tok-opaque');
  assert.equal('Cookie' in h, false);
  assert.equal(calls[1].init?.cache, 'no-store');
  assert.equal(calls[1].init?.redirect, 'manual');
  assert.ok(calls[1].init?.signal);
  assert.equal(r.delivery, 'READY');
  assert.equal(r.environment, 'LIVE');
  assert.equal(r.data?.days.length, 1);
  assert.equal(JSON.stringify(r).includes('tok-opaque'), false);
});

test('a mint 401 is SESSION_INVALID and Nutrition is never called', async () => {
  const { calls, fetcher } = scripted(json(401, {}));
  const r = await loadDiaryPeriod({ ...live, fetcher });
  assert.equal(calls.length, 1);
  assert.equal(r.errorCode, 'SESSION_INVALID');
});

test('Nutrition 401, 403, 400, 404 and 500 map to SESSION_INVALID, ACCESS_DENIED, INVALID_RESPONSE, INVALID_RESPONSE, SERVICE_UNAVAILABLE', async () => {
  const cases: Array<[number, string]> = [
    [401, 'SESSION_INVALID'], [403, 'ACCESS_DENIED'], [400, 'INVALID_RESPONSE'], [404, 'INVALID_RESPONSE'],
    [500, 'SERVICE_UNAVAILABLE'],
  ];
  for (const [status, code] of cases) {
    const { calls, fetcher } = scripted(minted(), json(status, { detail: 'x' }));
    const r = await loadDiaryPeriod({ ...live, fetcher });
    assert.equal(calls.length, 2, String(status));
    assert.equal(r.delivery, 'ERROR', String(status));
    assert.equal(r.errorCode, code, String(status));
  }
});

test('a malformed period is INVALID_RESPONSE', async () => {
  const { fetcher } = scripted(minted(), json(200, { ...PERIOD, days: [] }));
  const r = await loadDiaryPeriod({ ...live, fetcher });
  assert.equal(r.errorCode, 'INVALID_RESPONSE');
  assert.equal(r.data, undefined);
});

function hangingFetch(): typeof fetch {
  return ((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
  })) as typeof fetch;
}

test('a hung BFF mint times out as SERVICE_UNAVAILABLE', async () => {
  const keepAlive = setTimeout(() => {}, 2000);
  try {
    const started = Date.now();
    const r = await loadDiaryPeriod({ ...live, fetcher: hangingFetch(), timeoutMs: 25 });
    assert.equal(r.errorCode, 'SERVICE_UNAVAILABLE');
    assert.ok(Date.now() - started < 1500);
  } finally {
    clearTimeout(keepAlive);
  }
});

test('a hung Nutrition call times out as SERVICE_UNAVAILABLE after one mint, with no retry', async () => {
  const keepAlive = setTimeout(() => {}, 2000);
  try {
    let calls = 0;
    const hang = hangingFetch();
    const fetcher = ((input: RequestInfo | URL, init?: RequestInit) => {
      calls += 1;
      return calls === 1 ? Promise.resolve(minted()) : hang(input, init);
    }) as typeof fetch;
    const r = await loadDiaryPeriod({ ...live, fetcher, timeoutMs: 25 });
    assert.equal(r.errorCode, 'SERVICE_UNAVAILABLE');
    assert.equal(calls, 2);
  } finally {
    clearTimeout(keepAlive);
  }
});
