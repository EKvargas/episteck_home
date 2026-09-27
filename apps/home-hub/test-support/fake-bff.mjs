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
  if (request.url !== '/bootstrap' || request.method !== 'GET') {
    response.writeHead(404).end();
    return;
  }

  lastCookieHeader = request.headers.cookie ?? null;
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
    response.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' }).end(JSON.stringify(fixture));
  }
}).listen(3323, '127.0.0.1');
