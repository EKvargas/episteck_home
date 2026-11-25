import assert from 'node:assert/strict';
import test from 'node:test';
import { parsePeriodWire, type PeriodSummary } from '../../../integration/nutrition/period-contract.ts';
import { EnvelopeFactory, type DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { PERIOD_THREE, PERIOD_WEEK_PREGNANCY } from '../../../../test-support/nutrition-fixtures.mjs';
import {
  DETAIL_CODES, detailCode, nutrientDetailOutcome, toNutrientDetailModel, type NutrientDetailModel,
} from './nutrient-detail-model.ts';

const ready = (data: PeriodSummary): DataEnvelope<PeriodSummary> => EnvelopeFactory.ready(data, 'LIVE');
const week = () => ready(parsePeriodWire(PERIOD_WEEK_PREGNANCY));

function detail(model: NutrientDetailModel) {
  assert.equal(model.kind, 'DETAIL');
  return model as Extract<NutrientDetailModel, { kind: 'DETAIL' }>;
}

test('energy over the pregnancy week: average, target, state; bars only on closed days', () => {
  const m = detail(toNutrientDetailModel(week(), 'energy_kcal', true, null));
  assert.equal(m.name, 'Energía');
  assert.equal(m.average, '2.246 kcal');
  assert.equal(m.target, '≈ 2.250 kcal');
  assert.deepEqual(m.state, { tone: 'ok', word: 'bien', detail: 'con 4 días' });
  assert.deepEqual(m.days.map((d) => d.note), [null, null, null, null, 'sin cerrar', 'sin registros', 'abierto']);
  assert.deepEqual(m.days[0].bar, { value: '2105', scale: '2241.6', mark: 'band' });
  assert.equal(m.days[0].day, 'Mié 18');
  assert.equal(m.days[6].value, '1.640 kcal');
  assert.equal(m.days[5].value, null);
  assert.equal(m.targetLine, 'Objetivo diario: alrededor de 2.250 kcal.');
});

test('every closed day carries its state word; days without a bar carry their reason, never both', () => {
  const m = detail(toNutrientDetailModel(week(), 'energy_kcal', true, null));
  assert.deepEqual(m.days.map((d) => d.word), ['bien', 'bajo', 'bien', 'por encima', null, null, null]);
  for (const d of m.days) assert.ok((d.bar !== null && d.word !== null) !== (d.note !== null), d.day);
  assert.deepEqual(m.days.filter((d) => d.bar === null).map((d) => d.bar), [null, null, null]);
});

test('iron reads corto con 4 días against ≥ 27 mg', () => {
  const m = detail(toNutrientDetailModel(week(), 'iron_mg', true, null));
  assert.equal(m.average, '9,8 mg');
  assert.equal(m.target, '≥ 27 mg');
  assert.deepEqual(m.state, { tone: 'caution', word: 'corto', detail: 'con 4 días' });
  assert.equal(m.targetLine, 'Objetivo diario: al menos 27 mg.');
  assert.equal(m.days[0].bar?.mark, 'tick');
});

test('free sugars use the limit: cap marks and the Límite line', () => {
  const m = detail(toNutrientDetailModel(week(), 'free_sugars_g', true, null));
  assert.equal(m.name, 'Azúcares libres');
  assert.equal(m.target, '≤ 50 g');
  assert.equal(m.targetLine, 'Límite diario: como máximo 50 g.');
  assert.equal(m.days[0].bar?.mark, 'cap');
  assert.deepEqual(m.days[0].bar, { value: '18.0', scale: '50', mark: 'cap' });
  assert.equal(m.days[1].word, 'pasado del límite');
  assert.equal(m.days[1].tone, 'caution');
});

test('a closed day with an unknown value has no bar and says faltan datos', () => {
  const m = detail(toNutrientDetailModel(week(), 'free_sugars_g', true, null));
  assert.equal(m.days[3].bar, null);
  assert.equal(m.days[3].note, 'faltan datos');
  assert.equal(m.days[3].value, null);
});

test('open and unclosed days show their value but no bar', () => {
  const m = detail(toNutrientDetailModel(week(), 'protein_g', true, null));
  assert.equal(m.days[4].bar, null);
  assert.equal(m.days[4].note, 'sin cerrar');
  assert.equal(m.days[4].value, '40 g');
  assert.equal(m.days[6].note, 'abierto');
});

test('without a target: values only, no bar, no state, no target line', () => {
  const m = detail(toNutrientDetailModel(ready(parsePeriodWire(PERIOD_THREE)), 'calcium_mg', true, null));
  assert.equal(m.target, null);
  assert.equal(m.targetLine, null);
  assert.equal(m.state.tone, 'plain');
  assert.ok(m.days.every((d) => d.bar === null));
  assert.equal(m.average, 'sin dato');
});

test('the profile link: tu perfil for the person, su perfil for a viewer, person kept', () => {
  const self = detail(toNutrientDetailModel(week(), 'iron_mg', true, null));
  assert.deepEqual(self.profileLink, { text: 'Ver de dónde sale en tu perfil', href: '/app/nutrition/perfil' });
  const viewer = detail(toNutrientDetailModel(week(), 'iron_mg', false, 'PSN-00007'));
  assert.deepEqual(viewer.profileLink, { text: 'Ver de dónde sale en su perfil', href: '/app/nutrition/perfil?person=PSN-00007' });
});

test('a viewer gets "Ver de dónde sale en su perfil"', () => {
  const m = detail(toNutrientDetailModel(week(), 'energy_kcal', false, 'PSN-00007'));
  assert.equal(m.profileLink.text, 'Ver de dónde sale en su perfil');
});

test('detailCode accepts the 15 codes and free sugars only', () => {
  assert.equal(DETAIL_CODES.length, 16);
  assert.equal(DETAIL_CODES.at(-1), 'free_sugars_g');
  for (const code of DETAIL_CODES) assert.equal(detailCode(code), code);
  for (const raw of ['magnesium_mg', '../x', '', 'constructor', '__proto__', 'IRON_MG']) assert.equal(detailCode(raw), null, raw);
});

test('errors map to the shared panel kinds; a non-LIVE read is not configured', () => {
  assert.equal(toNutrientDetailModel(EnvelopeFactory.error('ACCESS_DENIED', 'LIVE'), 'iron_mg', true, null).kind, 'DENIED');
  assert.equal(toNutrientDetailModel(EnvelopeFactory.error('SESSION_INVALID', 'LIVE'), 'iron_mg', true, null).kind, 'SESSION');
  assert.equal(toNutrientDetailModel(EnvelopeFactory.error('INVALID_RESPONSE', 'LIVE'), 'iron_mg', true, null).kind, 'INVALID');
  assert.equal(toNutrientDetailModel(EnvelopeFactory.error('SERVICE_UNAVAILABLE', 'LIVE'), 'iron_mg', true, null).kind, 'UNAVAILABLE');
  assert.equal(toNutrientDetailModel(EnvelopeFactory.loading('LIVE'), 'iron_mg', true, null).kind, 'LOADING');
  assert.equal(toNutrientDetailModel(EnvelopeFactory.ready(parsePeriodWire(PERIOD_THREE), 'MOCK'), 'iron_mg', true, null).kind, 'NOT_CONFIGURED');
});

test('the outcome is the fixed kind', () => {
  assert.equal(nutrientDetailOutcome({ kind: 'DENIED' }), 'DENIED');
  assert.equal(nutrientDetailOutcome(detail(toNutrientDetailModel(week(), 'iron_mg', true, null))), 'DETAIL');
});

test('a closed day with no target is never an empty row: the value or sin dato, plus sin objetivo', () => {
  const base = parsePeriodWire(PERIOD_WEEK_PREGNANCY);
  const stripped: PeriodSummary = {
    ...base,
    days: base.days.map((d, i) => ({
      ...d,
      nutrients: { ...d.nutrients, energy_kcal: {
        ...d.nutrients.energy_kcal, target: null, ...(i === 1 ? { known: null } : {}),
      } },
    })),
  };
  const m = detail(toNutrientDetailModel(ready(stripped), 'energy_kcal', true, null));
  assert.equal(m.days[0].value, '2.105 kcal');
  assert.equal(m.days[0].note, 'sin objetivo');
  assert.equal(m.days[0].bar, null);
  assert.equal(m.days[1].value, 'sin dato');
  assert.equal(m.days[1].note, 'sin objetivo');
  for (const d of m.days) assert.ok(d.word !== null || d.note !== null, d.day);
});
