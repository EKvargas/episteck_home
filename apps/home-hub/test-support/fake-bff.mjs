import { createServer } from 'node:http';

const fixture = {
  version: 1,
  viewer: {
    personId: 'PSN-00001', displayName: 'Synthetic Viewer',
    access_token: 'ACCESS_TOKEN_SENTINEL', refresh_token: 'REFRESH_TOKEN_SENTINEL',
    user: { name: 'USER_NAME_SENTINEL', email: 'USER_EMAIL_SENTINEL' },
  },
  personContexts: [
    { type: 'PERSON', personId: 'PSN-00001', displayName: 'Synthetic Viewer' },
    { type: 'PERSON', personId: 'PSN-00007', displayName: 'Synthetic Care Context' },
  ],
  circleContexts: [{ type: 'CIRCLE', circleId: 'CIR-00001', displayName: 'Synthetic Circle' }],
  careRelationships: [
    { subjectPersonId: 'PSN-00007', relationshipType: 'CAREGIVER' },
  ],
  cookie: 'COOKIE_SENTINEL',
  bffUrl: 'http://BFF_URL_SENTINEL',
  home_session_id: 'HOME_SESSION_ID_SENTINEL',
  delegation: 'DELEGATION_SENTINEL',
  principals: ['PRINCIPAL_SENTINEL'],
  grants: ['GRANT_SENTINEL'],
  rawUpstreamResponse: 'RAW_UPSTREAM_SENTINEL',
};

let lastCookieHeader = null;

const mints = new Map();
const bootstraps = new Map();
const runOf = (cookie) => /run([a-z0-9]+)/.exec(cookie)?.[1] ?? 'none';
const scenarioOf = (cookie) => /nutr-([a-z0-9]+)/.exec(cookie)?.[1] ?? 'absent';
const bump = (map, run) => map.set(run, (map.get(run) ?? 0) + 1);

createServer((request, response) => {
  if (request.url === '/health') {
    response.writeHead(200).end('ok');
    return;
  }
  if (request.url === '/logout' && request.method === 'POST') {
    response.writeHead(200, {
      'content-type': 'application/json',
      'set-cookie': 'episteck_home_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax',
      'cache-control': 'no-store',
    }).end('{"status":"logged_out"}');
    return;
  }
  if (request.url === '/__test/last-cookie') {
    response.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ cookie: lastCookieHeader }));
    return;
  }
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
  if (request.url !== '/bootstrap' || request.method !== 'GET') {
    response.writeHead(404).end();
    return;
  }

  lastCookieHeader = request.headers.cookie ?? null;
  bump(bootstraps, runOf(request.headers.cookie ?? ''));
  const cookie = request.headers.cookie ?? '';
  if (!cookie.includes('episteck_home_session=authenticated')) {
    response.writeHead(401, { 'content-type': 'application/json' }).end('{"error":"SESSION_INVALID"}');
  } else if (cookie.includes('status-502')) {
    response.writeHead(502, { 'content-type': 'application/json' }).end('{"error":"INVALID_RESPONSE"}');
  } else if (cookie.includes('status-503')) {
    response.writeHead(503, { 'content-type': 'application/json' }).end('{"error":"SERVICE_UNAVAILABLE"}');
  } else if (cookie.includes('malformed')) {
    response.writeHead(200, { 'content-type': 'application/json' }).end('{"version":1,"viewer":{}}');
  } else {
    const payload = cookie.includes('authenticated-self-only')
      ? { ...fixture, personContexts: fixture.personContexts.slice(0, 1), careRelationships: [] }
      : fixture;
    response.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' }).end(JSON.stringify(payload));
  }
}).listen(3323, '127.0.0.1');
