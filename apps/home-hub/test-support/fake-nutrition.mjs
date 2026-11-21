import { createServer } from 'node:http';

const calls = new Map();
const PRESENT = {
  context: 'PREGNANCY',
  target_source: 'REFERENCE_TARGET',
  targets: { calcium_mg: '1000', iron_mg: '27' },
  preferences: 'PRIVATE_PREF_SENTINEL',
  dislikes: 'PRIVATE_DISLIKE_SENTINEL',
};

const EMPTY_DAY = {
  date: '2026-11-18', mode: 'GENERAL', trimester: null, day_status: 'NO_ENTRIES', sugar_status: 'NONE',
  free_sugars_known_g: null, items_total: 0, items_uncounted: 0,
  limit: { value_g: '50', sources: [{ title: 'WHO', url: 'https://example.test/who' }] },
  entries: [], attribution: [],
};
const PARTIAL_DAY = {
  ...EMPTY_DAY, day_status: 'OPEN', sugar_status: 'PARTIAL', free_sugars_known_g: '17.0', items_total: 2, items_uncounted: 1,
  entries: [
    { id: 'e-1', consumed_at: '2026-11-18T09:15:00+01:00', items: [{
      label: 'Zumo', amount: '1', unit: 'glass', grams: '200', conversion: { method: 'PRESET' },
      facts: { source: 'PRESET' }, free_sugars_g: '17.0',
    }] },
    { id: 'e-2', consumed_at: '2026-11-18T12:40:00+01:00', items: [{
      label: 'Pan integral', amount: '2', unit: 'slice', grams: '60', conversion: { method: 'AGENT_ESTIMATE' },
      facts: { source: 'BLS' }, free_sugars_g: null,
    }] },
  ],
  attribution: ['Bundeslebensmittelschlüssel (BLS) 4.0, Max Rubner-Institut'],
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
  const match = /^\/profile\/([A-Za-z0-9-]+)$/.exec(url.pathname) ?? /^\/diary\/([A-Za-z0-9-]+)\/days\/today$/.exec(url.pathname);
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
  if (url.pathname.startsWith('/diary/')) {
    switch (scenario) {
      case 'today-two-subjects':
        return match[1] === 'PSN-00001' ? json(200, PARTIAL_DAY) : json(403, { detail: 'ACCESS_DENIED' });
      case 'today-updated': return json(200, list.length === 1 ? EMPTY_DAY : PARTIAL_DAY);
      case 'today-partial': return json(200, PARTIAL_DAY);
      case 'today-denied': return json(403, { detail: 'ACCESS_DENIED' });
      case 'today-error': return json(500, { detail: 'boom' });
      default: return json(200, EMPTY_DAY);
    }
  }
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
