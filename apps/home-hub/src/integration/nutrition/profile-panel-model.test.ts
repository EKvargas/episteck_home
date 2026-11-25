import assert from 'node:assert/strict';
import test from 'node:test';
import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import type { NutritionProfile, ProfileRead, ProfileTarget } from './profile-contract.ts';
import { outcomeLabel, toProfilePanelModel, type ProfilePanelModel } from './profile-panel-model.ts';

const target = (nutrient: string, displayValue: string, unit: string, kind: ProfileTarget['kind'] = 'ABOUT',
  explanation = 'e.', sourceOrg = 'DGE'): ProfileTarget =>
  ({ nutrient, value: displayValue, displayValue, unit, kind, sourceOrg, sourceRef: 'ref', explanation });

const NO_INPUTS: NutritionProfile['inputs'] = {
  birthDate: null, age: null, sex: null, heightCm: null, weightKg: null, weightMeasuredOn: null,
  activityPal: null, trainingSessionsPerWeek: null, trainingNote: null, goal: null, prePregnancyWeightKg: null,
};

function base(over: Partial<NutritionProfile>): NutritionProfile {
  return {
    version: 2, validFrom: '2026-11-24', origin: 'PROFILE', onboarded: true, mode: 'GENERAL', dueDate: null, trimester: null,
    inputs: NO_INPUTS, food: { preferences: null, dislikes: null, intolerances: null },
    targets: { method: 'M', on: '2026-11-25', items: [], missing: [] }, history: [], ...over,
  };
}
const read = (p: NutritionProfile): ProfileRead => ({ presence: 'PRESENT', profile: p });

function ana(): ProfileRead {
  return read(base({
    mode: 'PREGNANCY', dueDate: '2027-04-12', trimester: 2,
    inputs: { ...NO_INPUTS, birthDate: '1992-03-01', age: 34, heightCm: '165', weightKg: '64', weightMeasuredOn: '2026-11-20',
      activityPal: '1.4', trainingSessionsPerWeek: 0, prePregnancyWeightKg: '58' },
    targets: { method: 'M', on: '2026-11-25', missing: [], items: [
      target('protein_g', '80', 'g', 'MIN'),
      target('energy_kcal', '2250', 'kcal', 'ABOUT',
        'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2.', 'Mifflin-St Jeor (1990); DGE/D-A-CH'),
    ] },
    history: [
      { version: 2, validFrom: '2026-11-24', origin: 'PROFILE', changed: ['height_cm'] },
      { version: 1, validFrom: '2026-11-24', origin: 'MODE', changed: ['mode'] },
    ],
  }));
}
function erick(): ProfileRead {
  return read(base({
    inputs: { ...NO_INPUTS, birthDate: '1984-05-02', age: 42, sex: 'MALE', heightCm: '180', weightKg: '82', weightMeasuredOn: '2026-11-23',
      activityPal: '1.6', trainingSessionsPerWeek: 3, trainingNote: 'fútbol: 2 entrenos + 1 partido', goal: 'PERFORMANCE' },
  }));
}
function modeOnly(): ProfileRead {
  return read(base({
    onboarded: false, mode: 'PREGNANCY', dueDate: '2027-04-12', trimester: 2, origin: 'MODE',
    targets: { method: 'M', on: '2026-11-25',
      items: [target('fiber_g', '30', 'g', 'MIN'), target('free_sugars_g', '50', 'g', 'MAX')],
      missing: [{ nutrient: 'energy_kcal', fields: ['birth_date', 'height_cm', 'pre_pregnancy_weight_kg', 'activity_pal'] }] },
  }));
}

const ready = (data: ProfileRead): DataEnvelope<ProfileRead> =>
  ({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE', data });
const error = (errorCode: SafeUIErrorCode): DataEnvelope<ProfileRead> =>
  ({ delivery: 'ERROR', authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE', errorCode });

type Profile = Extract<ProfilePanelModel, { kind: 'PROFILE' }>;
function profile(m: ProfilePanelModel): Profile {
  assert.equal(m.kind, 'PROFILE');
  return m as Profile;
}

test('Ana: pregnancy pill, pregnancy rows, no goal or sex row, the trimester-2 note', () => {
  const m = profile(toProfilePanelModel(ready(ana()), 'Ana'));
  assert.equal(m.modePill, 'Embarazo · 2.º trimestre');
  assert.deepEqual(m.basics.map((b) => b.label),
    ['Edad', 'Altura', 'Peso', 'Peso antes del embarazo', 'Actividad diaria', 'Entrenamiento', 'Modo']);
  assert.deepEqual(m.targets[0], { label: 'Energía', value: '≈ 2.250 kcal',
    source: 'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2 · Mifflin-St Jeor (1990); DGE/D-A-CH' });
  assert.equal(m.targets[1].label, 'Proteína');
  assert.equal(m.note, 'Al entrar en el 3.er trimestre, la energía sube sola (+500 kcal, DGE).');
  assert.deepEqual(m.history, ['24 nov: perfil creado por chat', '24 nov: modo cambiado por chat']);
  assert.equal(m.targetsSince, 'vigentes desde 24 nov');
});

test('Ana basics carry the exact Spanish values', () => {
  const m = profile(toProfilePanelModel(ready(ana()), 'Ana'));
  const v = Object.fromEntries(m.basics.map((b) => [b.label, b.value]));
  assert.equal(v['Edad'], '34 años');
  assert.equal(v['Altura'], '165 cm');
  assert.equal(v['Peso'], '64 kg (20 nov)');
  assert.equal(v['Peso antes del embarazo'], '58 kg');
  assert.equal(v['Fecha prevista de parto'], undefined);
  assert.equal(v['Actividad diaria'], 'Sobre todo sentado, poca actividad (1,4)');
  assert.equal(v['Entrenamiento'], 'Sin entrenamiento');
  assert.equal(v['Modo'], 'Embarazo');
});

test('Erick: sex and goal rows, training with its note, no pill', () => {
  const m = profile(toProfilePanelModel(ready(erick()), 'Erick'));
  assert.equal(m.modePill, null);
  assert.ok(m.basics.some((b) => b.label === 'Sexo' && b.value === 'Hombre'));
  assert.ok(m.basics.some((b) => b.label === 'Objetivo' && b.value === 'Rendimiento'));
  assert.ok(m.basics.some((b) => b.label === 'Entrenamiento' && b.value === '3 sesiones por semana · fútbol: 2 entrenos + 1 partido'));
  assert.ok(m.basics.some((b) => b.label === 'Peso' && b.value === '82 kg (23 nov)'));
  assert.equal(m.note, 'Si cambias tu peso o tu objetivo, los valores nuevos rigen desde ese día. Los días pasados se miden con los objetivos que tenían entonces.');
});

test('a mode-only pregnancy profile shows mode and due date, falta rows, missing targets and onboarded false', () => {
  const m = profile(toProfilePanelModel(ready(modeOnly()), 'Ana'));
  assert.equal(m.onboarded, false);
  assert.equal(m.modePill, 'Embarazo · 2.º trimestre');
  assert.ok(m.basics.some((b) => b.label === 'Altura' && b.value === 'falta'));
  assert.equal(m.dueDate, '12 abr 2027');
  assert.deepEqual(m.missing, ['Energía: falta fecha de nacimiento, altura, peso antes del embarazo, actividad diaria']);
  assert.deepEqual(m.targets.map((t) => t.label), ['Fibra', 'Azúcares libres']);
});

test('an unknown nutrient is listed last with a fallback label; sugars follow fiber', () => {
  const p = base({ targets: { method: 'M', on: '2026-11-25', missing: [], items: [
    target('magnesium_mg', '320', 'mg', 'MIN', '', 'DGE'),
    target('free_sugars_g', '50', 'g', 'MAX'), target('iron_mg', '27', 'mg', 'MIN'),
    target('fiber_g', '30', 'g', 'MIN'), target('energy_kcal', '2000', 'kcal'),
  ] } });
  const m = profile(toProfilePanelModel(ready(read(p)), 'E'));
  assert.deepEqual(m.targets.map((t) => t.label), ['Energía', 'Fibra', 'Azúcares libres', 'Hierro', 'Magnesium']);
  assert.equal(m.targets[4].source, 'DGE');
  assert.equal(m.targets[4].value, '≥ 320 mg');
});

test('a later PROFILE version reads "perfil actualizado por chat (peso)"', () => {
  const p = base({ history: [
    { version: 3, validFrom: '2026-11-24', origin: 'PROFILE', changed: ['weight_kg', 'weight_measured_on'] },
    { version: 2, validFrom: '2026-11-22', origin: 'MIGRATED', changed: [] },
    { version: 1, validFrom: '2026-11-20', origin: 'PROFILE', changed: ['height_cm'] },
  ] });
  const m = profile(toProfilePanelModel(ready(read(p)), 'E'));
  assert.deepEqual(m.history, [
    '24 nov: perfil actualizado por chat (peso, fecha del peso)',
    '22 nov: perfil anterior importado',
    '20 nov: perfil creado por chat',
  ]);
});

test('history lists at most 5, caps field labels at 3 with an ellipsis, deduplicates, names other origins', () => {
  const rows = Array.from({ length: 7 }, (_, i) => ({ version: 7 - i, validFrom: '2026-11-24', origin: i === 0 ? 'ODD' : 'PROFILE',
    changed: i === 1 ? ['height_cm', 'weight_kg', 'goal', 'sex'] : ['training_note', 'training_sessions_per_week'] }));
  const m = profile(toProfilePanelModel(ready(read(base({ history: rows }))), 'E'));
  assert.equal(m.history.length, 5);
  assert.equal(m.history[0], '24 nov: cambio');
  assert.equal(m.history[1], '24 nov: perfil actualizado por chat (altura, peso, objetivo…)');
  assert.equal(m.history[2], '24 nov: perfil actualizado por chat (entrenamiento)');
});

test('a later PROFILE version with no changed fields has no empty parentheses', () => {
  const p = base({ history: [
    { version: 2, validFrom: '2026-11-24', origin: 'PROFILE', changed: [] },
    { version: 1, validFrom: '2026-11-20', origin: 'PROFILE', changed: ['height_cm'] },
  ] });
  const m = profile(toProfilePanelModel(ready(read(p)), 'E'));
  assert.equal(m.history[0], '24 nov: perfil actualizado por chat');
});

test('measurements use es-ES decimals and activity levels compare numerically', () => {
  const p = base({ inputs: { ...NO_INPUTS, heightCm: '165.0', weightKg: '62.5', prePregnancyWeightKg: '58.25', activityPal: '2' } });
  const m = profile(toProfilePanelModel(ready(read(p)), 'E'));
  const v = Object.fromEntries(m.basics.map((b) => [b.label, b.value]));
  assert.equal(v['Altura'], '165 cm');
  assert.equal(v['Peso'], '62,5 kg');
  assert.equal(v['Actividad diaria'], 'Trabajo físico intenso (2,0)');
  const q = base({ inputs: { ...NO_INPUTS, activityPal: '1.60' } });
  const w = Object.fromEntries(profile(toProfilePanelModel(ready(read(q)), 'E')).basics.map((b) => [b.label, b.value]));
  assert.equal(w['Actividad diaria'], 'Sentado, con algo de caminar o estar de pie (1,6)');
});

test('the due date moves to the top and out of Datos', () => {
  const m = profile(toProfilePanelModel(ready(ana()), 'Ana'));
  assert.equal(m.dueDate, '12 abr 2027');
  assert.ok(!m.basics.some((b) => b.label === 'Fecha prevista de parto'));
  assert.equal(profile(toProfilePanelModel(ready(erick()), 'Erick')).dueDate, null);
});

test('food text becomes chips split on commas and semicolons', () => {
  const p = base({ food: { preferences: 'Mucha verdura, pescado', dislikes: null, intolerances: 'lactosa; frutos secos;; ' } });
  const m = profile(toProfilePanelModel(ready(read(p)), 'E'));
  assert.deepEqual(m.food, [
    { label: 'Preferencias', chips: ['Mucha verdura', 'pescado'] },
    { label: 'No le gusta', chips: [] },
    { label: 'Intolerancias', chips: ['lactosa', 'frutos secos'] },
  ]);
});

test('a 500-character food text without separators stays one chip', () => {
  const long = 'P'.repeat(500);
  const m = profile(toProfilePanelModel(ready(read(base({ food: { preferences: long, dislikes: null, intolerances: null } }))), 'E'));
  assert.deepEqual(m.food[0].chips, [long]);
});

test('pregnancy notes: trimester 1, 3 and unknown', () => {
  const note = (trimester: 1 | 2 | 3 | null) =>
    profile(toProfilePanelModel(ready(read(base({ mode: 'PREGNANCY', trimester }))), 'E'));
  assert.equal(note(1).note, 'Al entrar en el 2.º trimestre, la energía sube sola (+250 kcal, DGE).');
  assert.match(note(3).note, /^Si cambias tu peso/);
  assert.match(note(null).note, /^Si cambias tu peso/);
  assert.equal(note(null).modePill, 'Embarazo');
});

test('authorized ABSENT is its own state', () => {
  assert.deepEqual(toProfilePanelModel(ready({ presence: 'ABSENT' }), 'Erick'), { kind: 'ABSENT', subjectName: 'Erick' });
});

const errors: Array<[SafeUIErrorCode, string]> = [
  ['ACCESS_DENIED', 'DENIED'],
  ['SESSION_INVALID', 'SESSION'],
  ['SESSION_REQUIRED', 'SESSION'],
  ['SERVICE_UNAVAILABLE', 'UNAVAILABLE'],
  ['OFFLINE', 'UNAVAILABLE'],
  ['RESOURCE_NOT_AVAILABLE', 'UNAVAILABLE'],
  ['INVALID_RESPONSE', 'INVALID'],
  ['NOT_CONFIGURED', 'NOT_CONFIGURED'],
];
for (const [code, kind] of errors) {
  test(`${code} maps to ${kind}`, () => {
    assert.equal(toProfilePanelModel(error(code), 'Erick').kind, kind);
  });
}

test('every SafeUIErrorCode is covered by the table above', async () => {
  const { isSafeUIErrorCode } = await import('../state/SafeUIErrorCode.ts');
  for (const [code] of errors) assert.equal(isSafeUIErrorCode(code), true);
  assert.equal(errors.length, 8);
});

test('an envelope that is READY but not GRANTED, or has no data, fails safe to UNAVAILABLE', () => {
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'INDETERMINATE', freshness: 'FRESH', environment: 'LIVE', data: { presence: 'ABSENT' } }, 'E').kind, 'UNAVAILABLE');
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE' }, 'E').kind, 'UNAVAILABLE');
  assert.equal(toProfilePanelModel({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }, 'E').kind, 'UNAVAILABLE');
});

test('a READY envelope that is not LIVE fails safe to UNAVAILABLE (no mock in LIVE)', () => {
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'MOCK', data: { presence: 'ABSENT' } }, 'E').kind, 'UNAVAILABLE');
});

test('a LOADING envelope maps to LOADING', () => {
  assert.equal(toProfilePanelModel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }, 'E').kind, 'LOADING');
});

test('outcomeLabel is a fixed vocabulary that never carries identifiers or codes from the body', () => {
  assert.equal(outcomeLabel(ready({ presence: 'ABSENT' })), 'ABSENT');
  assert.equal(outcomeLabel(ready(ana())), 'PRESENT');
  for (const [code] of errors) assert.equal(outcomeLabel(error(code)), code);
  assert.equal(outcomeLabel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }), 'UNEXPECTED');
  assert.equal(outcomeLabel({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }), 'UNEXPECTED');
});

