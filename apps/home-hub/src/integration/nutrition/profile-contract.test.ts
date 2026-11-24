import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isAbsentProfileBody, parseProfileWire, ProfileContractError, type ProfileRead } from './profile-contract.ts';

const ENERGY = {
  nutrient: 'energy_kcal', value: '2241.6', display_value: '2250', unit: 'kcal', kind: 'ABOUT',
  source_org: 'Mifflin-St Jeor (1990); DGE/D-A-CH', source_ref: 'Am J Clin Nutr 51(2):241-247',
  explanation: 'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2.',
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Body = Record<string, any>;

function wire(): Body {
  return {
    person_id: 'PSN-00013', version: 2, valid_from: '2026-11-24', origin: 'PROFILE', onboarded: true,
    mode: 'PREGNANCY', due_date: '2027-03-01', trimester: 2,
    inputs: {
      birth_date: '1990-05-01', age: 36, sex: 'FEMALE', height_cm: '165', weight_kg: '62.5',
      weight_measured_on: '2026-11-20', activity_pal: '1.55', training_sessions_per_week: 2,
      training_note: 'Yoga', goal: 'MAINTAIN', pre_pregnancy_weight_kg: '58',
      UNKNOWN_FIELD_SENTINEL: 'x',
    },
    food: { preferences: 'pescado', dislikes: null, intolerances: 'lactosa' },
    targets: { energy_kcal: '2241.6' },
    target_set: {
      method: 'episteck-targets-1', on: '2026-11-24', items: [{ ...ENERGY }],
      missing: [{ nutrient: 'protein_g', fields: ['weight_kg'] }],
    },
    history: [
      { version: 1, valid_from: '2026-11-24', origin: 'MODE', changed: ['mode', 'due_date'] },
      { version: 2, valid_from: '2026-11-24', origin: 'PROFILE', changed: ['height_cm'] },
    ],
    context: 'PREGNANCY', target_source: 'REFERENCE_TARGET',
    UNKNOWN_FIELD_SENTINEL: 'x',
  };
}

function present(read: ProfileRead) {
  assert.equal(read.presence, 'PRESENT');
  return (read as Extract<ProfileRead, { presence: 'PRESENT' }>).profile;
}

test('maps the full profile from target_set and ignores the flat targets map', () => {
  const read = parseProfileWire(wire());
  const p = present(read);
  assert.equal(p.mode, 'PREGNANCY');
  assert.equal(p.trimester, 2);
  assert.equal(p.onboarded, true);
  assert.deepEqual(p.targets.items[0], { nutrient: 'energy_kcal', value: '2241.6', displayValue: '2250', unit: 'kcal',
    kind: 'ABOUT', sourceOrg: 'Mifflin-St Jeor (1990); DGE/D-A-CH', sourceRef: 'Am J Clin Nutr 51(2):241-247',
    explanation: 'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2.' });
  assert.deepEqual(p.targets.missing, [{ nutrient: 'protein_g', fields: ['weight_kg'] }]);
  assert.equal(p.inputs.heightCm, '165');
  assert.equal(p.inputs.trainingSessionsPerWeek, 2);
  assert.equal(p.food.intolerances, 'lactosa');
  assert.deepEqual(p.history.map((h) => h.origin), ['MODE', 'PROFILE']);
  assert.deepEqual(p.history[0].changed, ['mode', 'due_date']);
  assert.ok(!JSON.stringify(read).includes('UNKNOWN_FIELD_SENTINEL'));
});

test('a mode-only body (onboarded false, no energy target) is PRESENT, not ABSENT', () => {
  const body = wire();
  body.onboarded = false;
  body.version = 1;
  body.origin = 'MODE';
  body.inputs = {
    birth_date: null, age: null, sex: null, height_cm: null, weight_kg: null, weight_measured_on: null,
    activity_pal: null, training_sessions_per_week: null, training_note: null, goal: null,
    pre_pregnancy_weight_kg: null,
  };
  body.food = { preferences: null, dislikes: null, intolerances: null };
  body.target_set = { method: 'episteck-targets-1', on: '2026-11-24', items: [], missing: [] };
  body.history = [body.history[0]];
  const p = present(parseProfileWire(body));
  assert.equal(p.onboarded, false);
  assert.equal(p.mode, 'PREGNANCY');
  assert.equal(p.dueDate, '2027-03-01');
  assert.deepEqual(p.targets.items, []);
  assert.equal(p.inputs.age, null);
});

test('the live method id and a free-text display_value pass', () => {
  const body = wire();
  body.target_set.items[0].display_value = '2.25E+3';
  const p = present(parseProfileWire(body));
  assert.equal(p.targets.method, 'episteck-targets-1');
  assert.equal(p.targets.items[0].displayValue, '2.25E+3');
});

test('a null version is accepted', () => {
  const body = wire();
  body.version = null;
  assert.equal(present(parseProfileWire(body)).version, null);
});

test('an unknown target nutrient code passes the mapper', () => {
  const body = wire();
  body.target_set.items.push({ ...ENERGY, nutrient: 'magnesium_mg', value: '310', display_value: '310', unit: 'mg' });
  const p = present(parseProfileWire(body));
  assert.equal(p.targets.items[1].nutrient, 'magnesium_mg');
});

test('text over the limits is rejected', () => {
  const cases: Array<[string, (b: Body) => void]> = [
    ['preferences 501', (b) => { b.food.preferences = 'a'.repeat(501); }],
    ['dislikes 501', (b) => { b.food.dislikes = 'a'.repeat(501); }],
    ['intolerances 501', (b) => { b.food.intolerances = 'a'.repeat(501); }],
    ['training_note 121', (b) => { b.inputs.training_note = 'a'.repeat(121); }],
    ['explanation 301', (b) => { b.target_set.items[0].explanation = 'a'.repeat(301); }],
    ['source_org 301', (b) => { b.target_set.items[0].source_org = 'a'.repeat(301); }],
    ['source_ref 301', (b) => { b.target_set.items[0].source_ref = 'a'.repeat(301); }],
  ];
  for (const [name, mutate] of cases) {
    const body = wire();
    mutate(body);
    assert.throws(() => parseProfileWire(body), ProfileContractError, name);
  }
  const emoji = wire();
  emoji.inputs.training_note = '🏃'.repeat(120);
  assert.doesNotThrow(() => parseProfileWire(emoji), '120 code points');
  emoji.inputs.training_note = '🏃'.repeat(121);
  assert.throws(() => parseProfileWire(emoji), ProfileContractError, '121 code points');
  const edge = wire();
  edge.food.preferences = 'a'.repeat(500);
  edge.inputs.training_note = 'a'.repeat(120);
  assert.doesNotThrow(() => parseProfileWire(edge));
});

test('array caps are enforced', () => {
  const items = wire();
  items.target_set.items = Array.from({ length: 65 }, () => ({ ...ENERGY }));
  assert.throws(() => parseProfileWire(items), ProfileContractError);
  const missing = wire();
  missing.target_set.missing = Array.from({ length: 65 }, () => ({ nutrient: 'a', fields: [] }));
  assert.throws(() => parseProfileWire(missing), ProfileContractError);
  const history = wire();
  history.history = Array.from({ length: 201 }, (_, i) => ({ version: i, valid_from: '2026-11-24', origin: 'PROFILE', changed: [] }));
  assert.throws(() => parseProfileWire(history), ProfileContractError);
  const ok = wire();
  ok.target_set.items = Array.from({ length: 64 }, () => ({ ...ENERGY }));
  assert.doesNotThrow(() => parseProfileWire(ok));
});

test('malformed bodies are rejected', () => {
  const cases: Array<[string, (b: Body) => void]> = [
    ['mode lowercase', (b) => { b.mode = 'pregnancy'; }],
    ['trimester 4', (b) => { b.trimester = 4; }],
    ['kind TARGET', (b) => { b.target_set.items[0].kind = 'TARGET'; }],
    ['value with comma', (b) => { b.target_set.items[0].value = '12,5'; }],
    ['valid_from dotted', (b) => { b.valid_from = '24.11.2026'; }],
    ['missing target_set', (b) => { delete b.target_set; }],
    ['history not an array', (b) => { b.history = {}; }],
    ['sex unknown', (b) => { b.inputs.sex = 'OTHER'; }],
    ['goal unknown', (b) => { b.inputs.goal = 'BULK'; }],
    ['origin lowercase', (b) => { b.origin = 'profile'; }],
    ['nutrient uppercase', (b) => { b.target_set.items[0].nutrient = 'ENERGY'; }],
    ['negative age', (b) => { b.inputs.age = -1; }],
    ['fractional sessions', (b) => { b.inputs.training_sessions_per_week = 1.5; }],
    ['onboarded not boolean', (b) => { b.onboarded = 'yes'; }],
    ['height number not string', (b) => { b.inputs.height_cm = 165; }],
    ['due_date bad', (b) => { b.due_date = '2027-3-1'; }],
    ['food missing', (b) => { delete b.food; }],
    ['missing fields not strings', (b) => { b.target_set.missing[0].fields = [1]; }],
    ['history changed not array', (b) => { b.history[0].changed = 'mode'; }],
  ];
  for (const [name, mutate] of cases) {
    const body = wire();
    mutate(body);
    assert.throws(() => parseProfileWire(body), ProfileContractError, name);
  }
  for (const body of [null, [], 'x', 3]) assert.throws(() => parseProfileWire(body), ProfileContractError);
});

test('a __proto__ key in the body is plain data and never pollutes', () => {
  const json = JSON.stringify(wire()).replace('{"person_id"', '{"__proto__":{"polluted":true},"person_id"');
  const p = present(parseProfileWire(JSON.parse(json)));
  assert.equal(p.mode, 'PREGNANCY');
  assert.equal(({} as Record<string, unknown>).polluted, undefined);
});

test('the no-profile body is ABSENT only when it is exactly {"detail":"no profile"}', () => {
  assert.equal(isAbsentProfileBody({ detail: 'no profile' }), true);
  assert.equal(isAbsentProfileBody({ detail: 'Not Found' }), false);
  assert.equal(isAbsentProfileBody({ detail: 'no profile', extra: 1 }), false);
  assert.equal(isAbsentProfileBody(null), false);
});

test('ProfileContractError carries its own name', () => {
  try { parseProfileWire(null); assert.fail('expected a throw'); } catch (error) {
    assert.ok(error instanceof ProfileContractError);
    assert.equal((error as Error).name, 'ProfileContractError');
  }
});
