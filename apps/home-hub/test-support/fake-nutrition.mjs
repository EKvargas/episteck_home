import { createServer } from 'node:http';

const calls = new Map();
const ENERGY = {
  nutrient: 'energy_kcal', value: '2241.6', display_value: '2250', unit: 'kcal', kind: 'ABOUT',
  source_org: 'Mifflin-St Jeor (1990); DGE/D-A-CH', source_ref: 'Am J Clin Nutr 51(2):241-247',
  explanation: 'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2.',
};
const PROTEIN = {
  nutrient: 'protein_g', value: '65', display_value: '65', unit: 'g', kind: 'MIN',
  source_org: 'DGE/D-A-CH', source_ref: 'DGE 2017',
  explanation: 'Referencia para el embarazo, 2.º trimestre.',
};
// The full profile view of Ana. The flat `targets` map, `context` and `target_source` are legacy
// fields the Hub must ignore; the sentinels prove it.
const PRESENT = {
  person_id: 'PSN-00001', version: 2, valid_from: '2026-11-24', origin: 'PROFILE', onboarded: true,
  mode: 'PREGNANCY', due_date: '2027-03-01', trimester: 2,
  inputs: {
    birth_date: '1990-05-01', age: 36, sex: 'FEMALE', height_cm: '165', weight_kg: '62.5',
    weight_measured_on: '2026-11-20', activity_pal: '1.6', training_sessions_per_week: 2,
    training_note: 'Yoga', goal: 'MAINTAIN', pre_pregnancy_weight_kg: '58',
    UNKNOWN_FIELD_SENTINEL: 'x',
  },
  food: { preferences: 'PRIVATE_PREF_SENTINEL', dislikes: 'PRIVATE_DISLIKE_SENTINEL', intolerances: 'lactosa' },
  targets: { energy_kcal: '9999.9', calcium_mg: '1000' },
  target_set: {
    method: 'episteck-targets-1', on: '2026-11-24', items: [{ ...ENERGY }, { ...PROTEIN }],
    missing: [],
  },
  history: [
    { version: 1, valid_from: '2026-11-24', origin: 'MODE', changed: ['mode', 'due_date'] },
    { version: 2, valid_from: '2026-11-24', origin: 'PROFILE', changed: ['height_cm'] },
  ],
  context: 'PREGNANCY', target_source: 'REFERENCE_TARGET',
  UNKNOWN_FIELD_SENTINEL: 'x',
};
const MODE_ONLY = {
  ...PRESENT, version: 1, origin: 'MODE', onboarded: false,
  inputs: {
    birth_date: null, age: null, sex: null, height_cm: null, weight_kg: null, weight_measured_on: null,
    activity_pal: null, training_sessions_per_week: null, training_note: null, goal: null,
    pre_pregnancy_weight_kg: null,
  },
  food: { preferences: null, dislikes: null, intolerances: null },
  targets: {},
  target_set: { method: 'episteck-targets-1', on: '2026-11-24', items: [], missing: [] },
  history: [PRESENT.history[0]],
};
const LONG_TEXT = {
  ...PRESENT,
  inputs: { ...PRESENT.inputs, training_note: 'T'.repeat(120) },
  food: {
    preferences: 'P'.repeat(500),
    dislikes: 'dislike '.repeat(60).trim().slice(0, 500),
    intolerances: 'I'.repeat(500),
  },
};

const block = (known, target, over = {}) => ({
  known, items_total: known === null ? 0 : 2, items_uncounted: 0, status: known === null ? 'NONE' : 'KNOWN', target, percent: null, ...over,
});
const T_ENERGY = { value: '2250', display_value: '2250', unit: 'kcal', kind: 'ABOUT' };
const T_PROTEIN = { value: '60', display_value: '60', unit: 'g', kind: 'MIN' };
const T_FIBER = { value: '30', display_value: '30', unit: 'g', kind: 'MIN' };
const EMPTY_DAY = {
  profile_version: 2,
  nutrients: {
    energy_kcal: block(null, T_ENERGY), protein_g: block(null, T_PROTEIN), fiber_g: block(null, T_FIBER),
    fat_g: block(null, null),
  },
  date: '2026-11-18', mode: 'GENERAL', trimester: null, day_status: 'NO_ENTRIES', sugar_status: 'NONE',
  free_sugars_known_g: null, items_total: 0, items_uncounted: 0,
  limit: { value_g: '50', sources: [{ title: 'WHO', url: 'https://example.test/who' }] },
  entries: [], attribution: [],
};
const PARTIAL_DAY = {
  ...EMPTY_DAY,
  nutrients: {
    ...EMPTY_DAY.nutrients,
    energy_kcal: block('436.0', T_ENERGY), protein_g: block('12.4', T_PROTEIN),
    fiber_g: block('3.0', T_FIBER, { status: 'PARTIAL', items_uncounted: 1 }),
  }, day_status: 'OPEN', sugar_status: 'PARTIAL', free_sugars_known_g: '17.0', items_total: 2, items_uncounted: 1,
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

const NO_PROFILE_DAY = {
  ...EMPTY_DAY, day_status: 'OPEN', profile_version: null,
  nutrients: { ...PARTIAL_DAY.nutrients, energy_kcal: block('436.0', null), protein_g: block('12.4', null), fiber_g: block('3.0', null) },
  entries: PARTIAL_DAY.entries, free_sugars_known_g: '17.0', sugar_status: 'PARTIAL', items_total: 2, items_uncounted: 1,
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
      case 'today-no-profile': return json(200, NO_PROFILE_DAY);
      case 'today-partial': return json(200, PARTIAL_DAY);
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
