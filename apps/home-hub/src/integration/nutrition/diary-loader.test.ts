import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadDiaryToday } from './diary-loader.ts';

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
const NONE = { known: null, items_total: 0, items_uncounted: 0, status: 'NONE', target: null, percent: null };
const DAY = {
  profile_version: null, nutrients: { energy_kcal: NONE, protein_g: NONE, fiber_g: NONE },
  date: '2026-11-20', mode: 'GENERAL', trimester: null, day_status: 'NO_ENTRIES', sugar_status: 'NONE',
  free_sugars_known_g: null, items_total: 0, items_uncounted: 0, limit: null, entries: [], attribution: [],
};
const live = {
  mode: 'LIVE' as const,
  personId: 'PSN-00001',
  cookieValue: 'opaque-session',
  bffBaseUrl: 'http://127.0.0.1:9933',
  nutritionBaseUrl: 'http://127.0.0.1:9930',
};

test('MOCK never fetches and returns a non-LIVE empty day', async () => {
  const { calls, fetcher } = scripted();
  const r = await loadDiaryToday({ ...live, mode: 'MOCK', fetcher });
  assert.equal(calls.length, 0);
  assert.equal(r.delivery, 'READY');
  assert.equal(r.environment, 'MOCK');
  assert.equal(r.data?.dayStatus, 'NO_ENTRIES');
  assert.equal(r.data?.freeSugarsKnownG, null);
});

const noNetwork: Array<[string, Partial<Parameters<typeof loadDiaryToday>[0]>, string]> = [
  ['missing Nutrition URL', { nutritionBaseUrl: undefined }, 'NOT_CONFIGURED'],
  ['missing BFF URL', { bffBaseUrl: undefined }, 'NOT_CONFIGURED'],
  ['missing cookie', { cookieValue: undefined }, 'SESSION_REQUIRED'],
  ['bad person id', { personId: 'PSN/../x' }, 'INVALID_RESPONSE'],
];
test('missing URLs, missing cookie and a bad person id fail before any fetch', async () => {
  for (const [name, override, code] of noNetwork) {
    const { calls, fetcher } = scripted();
    const r = await loadDiaryToday({ ...live, ...override, fetcher });
    assert.equal(calls.length, 0, name);
    assert.equal(r.errorCode, code, name);
    assert.equal(r.data, undefined, name);
  }
});

test('one mint, then one GET /diary/PSN-00001/days/today with the delegation and without the cookie', async () => {
  const { calls, fetcher } = scripted(minted(), json(200, DAY));
  const r = await loadDiaryToday({ ...live, fetcher });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, 'http://127.0.0.1:9933/delegation?audience=svc-nutrition');
  assert.equal(calls[0].init?.method, 'POST');
  assert.equal(calls[1].url, 'http://127.0.0.1:9930/diary/PSN-00001/days/today');
  assert.equal(calls[1].init?.method, 'GET');
  const h = calls[1].init?.headers as Record<string, string>;
  assert.equal(h['X-Episteck-Delegation'], 'tok-opaque');
  assert.equal('Cookie' in h, false);
  assert.equal(calls[1].init?.cache, 'no-store');
  assert.equal(calls[1].init?.redirect, 'manual');
  assert.ok(calls[1].init?.signal);
  assert.equal(r.delivery, 'READY');
  assert.equal(r.environment, 'LIVE');
  assert.equal(JSON.stringify(r).includes('tok-opaque'), false);
});

test('a mint 401 is SESSION_INVALID and Nutrition is never called', async () => {
  const { calls, fetcher } = scripted(json(401, {}));
  const r = await loadDiaryToday({ ...live, fetcher });
  assert.equal(calls.length, 1);
  assert.equal(r.errorCode, 'SESSION_INVALID');
});

test('Nutrition 401, 403, 404 and 500 map to SESSION_INVALID, ACCESS_DENIED, INVALID_RESPONSE, SERVICE_UNAVAILABLE', async () => {
  const cases: Array<[number, string]> = [
    [401, 'SESSION_INVALID'], [403, 'ACCESS_DENIED'], [404, 'INVALID_RESPONSE'], [500, 'SERVICE_UNAVAILABLE'],
  ];
  for (const [status, code] of cases) {
    const { fetcher } = scripted(minted(), json(status, { detail: 'x' }));
    const r = await loadDiaryToday({ ...live, fetcher });
    assert.equal(r.delivery, 'ERROR', String(status));
    assert.equal(r.errorCode, code, String(status));
  }
});

test('a malformed day is INVALID_RESPONSE', async () => {
  const { fetcher } = scripted(minted(), json(200, { ...DAY, day_status: 'WAT' }));
  const r = await loadDiaryToday({ ...live, fetcher });
  assert.equal(r.errorCode, 'INVALID_RESPONSE');
  assert.equal(r.data, undefined);
});
