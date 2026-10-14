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
