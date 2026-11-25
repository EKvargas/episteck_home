import { createServer } from 'node:http';

import {
  EMPTY_DAY, LONG_TEXT, MODE_ONLY, NO_PROFILE_DAY, PARTIAL_DAY, PERIOD_FOURTEEN, PERIOD_NO_PROFILE, PERIOD_THREE,
  PERIOD_WEEK_PREGNANCY, PREGNANCY_DAY, PRESENT,
} from './nutrition-fixtures.mjs';

const calls = new Map();

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
  const match = /^\/profile\/([A-Za-z0-9-]+)$/.exec(url.pathname) ?? /^\/diary\/([A-Za-z0-9-]+)\/days\/today$/.exec(url.pathname)
    ?? /^\/diary\/([A-Za-z0-9-]+)\/period$/.exec(url.pathname);
  if (!match || request.method !== 'GET') {
    response.writeHead(404).end();
    return;
  }
  const token = request.headers['x-episteck-delegation'];
  const [, scenario = 'absent', run = 'none'] = typeof token === 'string' ? token.split('.') : [];
  const list = calls.get(run) ?? [];
  list.push({ path: url.pathname + url.search, hasCookie: 'cookie' in request.headers });
  calls.set(run, list);

  const json = (status, body) => response.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body));
  if (url.pathname.endsWith('/period')) {
    switch (scenario) {
      case 'days-three': return json(200, PERIOD_THREE);
      case 'days-no-profile': return json(200, PERIOD_NO_PROFILE);
      case 'days-pregnancy':
      case 'today-pregnancy': return json(200, PERIOD_WEEK_PREGNANCY);
      case 'days-fourteen': return json(200, PERIOD_FOURTEEN);
      case 'days-denied':
      case 'today-denied': return json(403, { detail: 'ACCESS_DENIED' });
      case 'days-error':
      case 'today-week-error': return json(500, { detail: 'boom' });
      case 'today-two-subjects':
        return match[1] === 'PSN-00001' ? json(200, PERIOD_THREE) : json(403, { detail: 'ACCESS_DENIED' });
      default:
        return scenario.startsWith('today-') ? json(200, PERIOD_THREE) : json(404, { detail: 'no period' });
    }
  }
  if (url.pathname.startsWith('/diary/')) {
    switch (scenario) {
      case 'today-two-subjects':
        return match[1] === 'PSN-00001' ? json(200, PARTIAL_DAY) : json(403, { detail: 'ACCESS_DENIED' });
      case 'today-updated': // count day reads only: the weekly panel reads the period for the same run
        return json(200, list.filter((call) => call.path.includes('/days/today')).length === 1 ? EMPTY_DAY : PARTIAL_DAY);
      case 'today-no-profile': return json(200, NO_PROFILE_DAY);
      case 'today-partial':
      case 'today-week-error': return json(200, PARTIAL_DAY);
      case 'today-pregnancy': return json(200, PREGNANCY_DAY);
      case 'today-denied': return json(403, { detail: 'ACCESS_DENIED' });
      case 'today-error': return json(500, { detail: 'boom' });
      default: return json(200, EMPTY_DAY);
    }
  }
  switch (scenario) {
    case 'present': return json(200, PRESENT);
    case 'mode-only': return json(200, MODE_ONLY);
    case 'long-text': return json(200, LONG_TEXT);
    case '403': return json(403, { detail: 'ACCESS_DENIED' });
    case '401': return json(401, { detail: 'SESSION_INVALID' });
    case '503': return json(503, { detail: 'SERVICE_UNAVAILABLE' });
    case 'badbody': return json(200, { context: 'general' });
    case 'hang': return undefined; // never answer; the Hub must time out
    default: return json(404, { detail: 'no profile' });
  }
}).listen(9930, '127.0.0.1');
