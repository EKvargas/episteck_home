import assert from 'node:assert/strict';
import test from 'node:test';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import {
  DAY_NUTRIENTS, parseDayWire, type DayNutrient, type DiaryDay, type DiaryItem, type NutrientBlock,
} from '../../../integration/nutrition/diary-contract.ts';
import { toTodayPanelModel, todayOutcome, type TodayPanelModel } from './today-panel-model.ts';
import { EMPTY_DAY, NO_PROFILE_DAY, PARTIAL_DAY, PREGNANCY_DAY } from '../../../../test-support/nutrition-fixtures.mjs';

const ready = (data: DiaryDay, environment: 'LIVE' | 'MOCK' = 'LIVE'): DataEnvelope<DiaryDay> =>
  ({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data });
type Today = Extract<TodayPanelModel, { kind: 'TODAY' }>;
const today = (model: TodayPanelModel): Today => {
  assert.equal(model.kind, 'TODAY');
  return model as Today;
};
const day = parseDayWire(PREGNANCY_DAY);
const NO_ZERO = /(^|\D)0 (g|kcal)/;

// ------------------------------------------------------------ fixture days

test('four rows in fixed order with amounts, bars and words', () => {
  const m = today(toTodayPanelModel(ready(day), true));
  assert.deepEqual(m.rows.map((r) => r.code), ['energy_kcal', 'protein_g', 'fiber_g', 'free_sugars_g']);
  assert.deepEqual(m.rows[0], { code: 'energy_kcal', name: 'Energía', amount: '1.640 de 2.250 kcal',
    bar: { value: '1640.3', scale: '2241.6', mark: 'band' }, state: { tone: 'progress', word: 'en curso · faltan ~610 kcal', detail: null } });
  assert.deepEqual(m.rows[1], { code: 'protein_g', name: 'Proteína', amount: '48 de 65 g',
    bar: { value: '48.2', scale: '65', mark: 'tick' }, state: { tone: 'progress', word: 'en curso · faltan 17 g', detail: null } });
  assert.equal(m.rows[2].state.word, 'bien');
  assert.deepEqual(m.rows[3], { code: 'free_sugars_g', name: 'Azúcares libres', amount: '12 de 50 g',
    bar: { value: '12.0', scale: '50', mark: 'cap' }, state: { tone: 'unknown', word: 'faltan datos', detail: null } });
  assert.equal(m.verdict, 'Vas en camino. Te falta proteína. Faltan datos de 2 alimentos.');
  assert.equal(m.quietLine, 'Grasa 58 g · Carbohidratos 190 g');
  assert.equal(m.profileHint, null);
  assert.equal(m.prenatalNote, 'Tu prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos.');
});

test('meals: one line per entry; notes for unmatched food and missing nutrients', () => {
  const m = today(toTodayPanelModel(ready(day), true));
  assert.deepEqual(m.meals.map((x) => x.summary), ['08:10 · Avena con leche, Plátano', '13:30 · Lentejas con arroz, Tarta casera']);
  assert.deepEqual(m.meals.map((x) => x.time), ['08:10', '13:30']);
  assert.deepEqual(m.meals[0].items.map((i) => i.text), ['Avena con leche, 1 taza (~250 g)', 'Plátano, 1 unidad (~120 g)']);
  assert.equal(m.meals[0].items[0].note, null);
  assert.equal(m.meals[0].items[1].note, 'sin datos de fibra');
  assert.equal(m.meals[1].items[1].note, 'sin coincidencia en la base de alimentos');
  assert.deepEqual(m.meals[1].items.map((i) => i.sugar), ['1 g', 'sin dato']);
  assert.equal(m.meals[1].items[0].text, 'Lentejas con arroz, 1 plato (300 g)');
});

test('an empty day keeps four rows with empty tracks and never shows 0', () => {
  const m = today(toTodayPanelModel(ready(parseDayWire(EMPTY_DAY)), true));
  assert.equal(m.verdict, 'Aún no has anotado nada hoy.');
  assert.deepEqual(m.rows.map((r) => r.code), ['energy_kcal', 'protein_g', 'fiber_g', 'free_sugars_g']);
  assert.deepEqual(m.rows.map((r) => r.state), Array(4).fill({ tone: 'empty', word: 'Sin registros', detail: null }));
  assert.deepEqual(m.rows.map((r) => r.amount), [null, null, null, null]);
  assert.deepEqual(m.rows.map((r) => r.bar?.value), [null, null, null, null]);
  assert.deepEqual(m.rows.map((r) => r.bar?.mark), ['band', 'tick', 'tick', 'cap']);
  assert.equal(m.quietLine, null);
  assert.deepEqual(m.meals, []);
  assert.doesNotMatch(JSON.stringify(m), NO_ZERO);
});

test('without an energy target: values only, SELF hint for the person and VIEWER for others', () => {
  const noProfile = parseDayWire(NO_PROFILE_DAY);
  const m = today(toTodayPanelModel(ready(noProfile), true));
  assert.deepEqual(m.rows[0], { code: 'energy_kcal', name: 'Energía', amount: '436 kcal', bar: null,
    state: { tone: 'plain', word: null, detail: null } });
  assert.deepEqual(m.rows.map((r) => r.amount), ['436 kcal', '12 g', '3 g', '17 de 50 g']);
  assert.deepEqual(m.rows.map((r) => r.bar === null), [true, true, true, false]);
  assert.equal(m.verdict, 'Día abierto. Faltan datos de 1 alimento.');
  assert.equal(m.profileHint, 'SELF');
  assert.equal(today(toTodayPanelModel(ready(noProfile), false)).profileHint, 'VIEWER');
  assert.equal(m.quietLine, 'Grasa sin dato · Carbohidratos sin dato');
});

test('a consent viewer reads neutral copy and the neutral prenatal note', () => {
  const m = today(toTodayPanelModel(ready(day), false));
  assert.equal(m.verdict, 'Va en camino. Le falta proteína. Faltan datos de 2 alimentos.');
  assert.equal(m.prenatalNote, 'El prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos.');
  assert.doesNotMatch(JSON.stringify(m), /Te falta|Tu prenatal|Vas |has anotado|tu perfil/);
  const empty = today(toTodayPanelModel(ready(parseDayWire(EMPTY_DAY)), false));
  assert.equal(empty.verdict, 'Aún no hay nada anotado hoy.');
});

test('free sugars over the limit lead the verdict', () => {
  const over = parseDayWire({ ...PREGNANCY_DAY, free_sugars_known_g: '55.0' });
  const m = today(toTodayPanelModel(ready(over), true));
  assert.equal(m.verdict, 'Hoy te has pasado de azúcares libres. Faltan datos de 2 alimentos.');
  assert.deepEqual(m.rows[3].state, { tone: 'caution', word: 'pasado del límite', detail: null });
  assert.equal(m.rows[3].amount, '55 de 50 g');
  assert.deepEqual(m.rows[3].bar, { value: '55.0', scale: '50', mark: 'cap' });
});

test('energy far above its target: the real value, a raw bar value, an amber word', () => {
  const high = parseDayWire({
    ...PREGNANCY_DAY,
    nutrients: { ...PREGNANCY_DAY.nutrients, energy_kcal: { ...PREGNANCY_DAY.nutrients.energy_kcal, known: '3400.0', percent: '152' } },
  });
  const m = today(toTodayPanelModel(ready(high), true));
  assert.equal(m.rows[0].amount, '3.400 de 2.250 kcal');
  assert.deepEqual(m.rows[0].bar, { value: '3400.0', scale: '2241.6', mark: 'band' });
  assert.deepEqual(m.rows[0].state, { tone: 'caution', word: 'por encima', detail: null });
  assert.equal(m.verdict, 'Vas por encima en energía. Te falta proteína. Faltan datos de 2 alimentos.');
});

test('a GENERAL day has no prenatal note', () => {
  const m = today(toTodayPanelModel(ready(parseDayWire(PARTIAL_DAY)), true));
  assert.equal(m.prenatalNote, null);
  assert.equal(today(toTodayPanelModel(ready(parseDayWire(PARTIAL_DAY)), false)).prenatalNote, null);
});

test('a partial GENERAL day: words for every row, the uncounted food in the verdict, no 0', () => {
  const m = today(toTodayPanelModel(ready(parseDayWire(PARTIAL_DAY)), true));
  assert.equal(m.verdict, 'Vas en camino. Te faltan proteína y fibra. Faltan datos de 1 alimento.');
  assert.deepEqual(m.rows.map((r) => r.amount), ['436 de 2.250 kcal', '12 de 60 g', '3 de 30 g', '17 de 50 g']);
  assert.deepEqual(m.rows.map((r) => r.state.word), [
    'en curso · faltan ~1.814 kcal', 'en curso · faltan 48 g', 'en curso · faltan 27 g', 'faltan datos',
  ]);
  assert.deepEqual(m.meals.map((x) => x.summary), ['09:15 · Zumo', '12:40 · Pan integral']);
  assert.deepEqual(m.meals[1].items, [{ text: 'Pan integral, 2 rebanadas (~60 g)', sugar: 'sin dato', note: 'sin datos de azúcares libres' }]);
  assert.equal(m.sources.reference, 'Referencia general: 50 g de azúcares libres al día (OMS, DGE). No es una indicación médica.');
  assert.deepEqual(m.sources.attribution, ['Bundeslebensmittelschlüssel (BLS) 4.0, Max Rubner-Institut']);
  assert.doesNotMatch(JSON.stringify(m), NO_ZERO);
});

// --------------------------------------------------- focused synthetic days

const item = (over: Partial<DiaryItem> = {}): DiaryItem => ({
  label: 'Zumo', amount: '1', unit: 'glass', grams: '200', method: 'PRESET', source: 'PRESET', freeSugarsG: '17.0',
  withFacts: ['energy_kcal', 'protein_g', 'fiber_g'], ...over,
});
const block = (known: string | null, target: NutrientBlock['target'], over: Partial<NutrientBlock> = {}): NutrientBlock => ({
  known, itemsTotal: 1, itemsUncounted: 0, status: known === null ? 'NONE' : 'KNOWN', target, percent: null, ...over,
});
const TARGETS = {
  energy: { value: '2241.6', displayValue: '2250', unit: 'kcal', kind: 'ABOUT' } as const,
  protein: { value: '60', displayValue: '60', unit: 'g', kind: 'MIN' } as const,
  fiber: { value: '30', displayValue: '30', unit: 'g', kind: 'MIN' } as const,
};
const blocks = (over: Partial<Record<DayNutrient, NutrientBlock>> = {}): Record<DayNutrient, NutrientBlock> => ({
  ...(Object.fromEntries(DAY_NUTRIENTS.map((c) => [c, block(null, null)])) as Record<DayNutrient, NutrientBlock>),
  energy_kcal: block('1640.3', TARGETS.energy, { percent: '73' }),
  protein_g: block('72.4', TARGETS.protein, { percent: '121' }),
  fiber_g: block('14.0', TARGETS.fiber, { percent: '47' }),
  ...over,
});
const synthetic = (over: Partial<DiaryDay> = {}): DiaryDay => ({
  profileVersion: 2, nutrients: blocks(),
  date: '2026-11-18', mode: 'GENERAL', trimester: null, dayStatus: 'OPEN', sugarStatus: 'KNOWN',
  freeSugarsKnownG: '17.0', itemsTotal: 1, itemsUncounted: 0, limit: { valueG: '50', sources: [] },
  entries: [{ id: 'e1', consumedAt: '2026-11-18T09:15:00+01:00', items: [item()] }], attribution: [], ...over,
});
const model = (over: Partial<DiaryDay> = {}, self = true) => today(toTodayPanelModel(ready(synthetic(over)), self));

test('estimates carry ~ and stated amounts do not', () => {
  const m = model({
    entries: [{ id: 'e1', consumedAt: '2026-11-18T09:15:00+01:00', items: [
      item(),
      item({ label: 'Cola', amount: '330', unit: 'ml', grams: '330', method: 'USER_STATED', freeSugarsG: '35.0' }),
      item({ label: 'Té', amount: '2', unit: 'cup', grams: '480', method: 'AGENT_ESTIMATE', freeSugarsG: null }),
      item({ label: 'Pan', amount: '1', unit: 'slice', grams: '30', method: 'SOURCE_SERVING', freeSugarsG: '1.5' }),
      item({ label: 'Leche', amount: '250', unit: 'g', grams: '250', method: 'USER_STATED', freeSugarsG: null }),
      item({ label: 'Arroz', amount: '1', unit: 'plate', grams: '1250', method: 'PRESET', freeSugarsG: '0.0' }),
    ] }],
  });
  assert.deepEqual(m.meals[0].items.map((i) => i.text), [
    'Zumo, 1 vaso (~200 g)', 'Cola, 330 ml', 'Té, 2 tazas (~480 g)', 'Pan, 1 rebanada (30 g)', 'Leche, 250 g',
    'Arroz, 1 plato (~1.250 g)',
  ]);
  assert.deepEqual(m.meals[0].items.map((i) => i.sugar), ['17 g', '35 g', 'sin dato', '1,5 g', 'sin dato', '0 g']);
  assert.equal(m.meals[0].summary, '09:15 · Zumo, Cola, Té, Pan, Leche, Arroz');
});

test('times are Berlin clock times', () => {
  const at = (consumedAt: string) => model({ entries: [{ id: 'e', consumedAt, items: [item()] }] }).meals[0].time;
  assert.equal(at('2026-11-18T23:30:00+01:00'), '23:30');
  assert.equal(at('2026-11-18T23:30:00Z'), '00:30');
});

test('item notes: an unmatched food, a matched food without values, and a fully known food', () => {
  const m = model({
    sugarStatus: 'PARTIAL', itemsUncounted: 2,
    entries: [{ id: 'e1', consumedAt: '2026-11-18T09:15:00+01:00', items: [
      item({ label: 'Comida casera', source: null, freeSugarsG: null, withFacts: [] }),
      item({ label: 'Yogur', source: 'BLS', freeSugarsG: null, withFacts: ['energy_kcal'] }),
      item({ label: 'Agua', source: 'BLS', freeSugarsG: '0.0' }),
    ] }],
  });
  assert.deepEqual(m.meals[0].items.map((i) => [i.sugar, i.note]), [
    ['sin dato', 'sin coincidencia en la base de alimentos'],
    ['sin dato', 'sin datos de proteína, fibra y azúcares libres'],
    ['0 g', null],
  ]);
});

test('decimal comma and no trailing ,0', () => {
  const m = model({
    nutrients: blocks({ fiber_g: block('3.5', TARGETS.fiber, { percent: '12' }) }),
    entries: [{ id: 'e1', consumedAt: '2026-11-18T09:15:00+01:00', items: [item({ freeSugarsG: '15.9' }), item({ freeSugarsG: '17.0' })] }],
  });
  assert.equal(m.rows[2].amount, '3,5 de 30 g');
  assert.deepEqual(m.meals[0].items.map((i) => i.sugar), ['15,9 g', '17 g']);
});

test('no limit: free sugars read the value only and the reference is omitted', () => {
  const m = model({ limit: null });
  assert.deepEqual(m.rows[3], { code: 'free_sugars_g', name: 'Azúcares libres', amount: '17 g', bar: null,
    state: { tone: 'plain', word: null, detail: null } });
  assert.equal(m.sources.reference, null);
  const unknown = model({ limit: null, freeSugarsKnownG: null, sugarStatus: 'PARTIAL', itemsUncounted: 1 });
  assert.equal(unknown.rows[3].amount, 'sin dato');
});

test('an unknown nutrient on a day with entries reads sin dato and faltan datos, never 0', () => {
  const m = model({ nutrients: blocks({ energy_kcal: block(null, TARGETS.energy, { itemsUncounted: 1 }) }) });
  assert.equal(m.rows[0].amount, 'sin dato');
  assert.deepEqual(m.rows[0].bar, { value: null, scale: '2241.6', mark: 'band' });
  assert.deepEqual(m.rows[0].state, { tone: 'unknown', word: 'faltan datos', detail: null });
  assert.doesNotMatch(JSON.stringify(m.rows), NO_ZERO);
});

test('the verdict counts the largest uncounted figure among the four headline rows', () => {
  const partial = model({
    nutrients: blocks({ protein_g: block('72.4', TARGETS.protein, { status: 'PARTIAL', itemsUncounted: 3, percent: '121' }) }),
    sugarStatus: 'PARTIAL', itemsUncounted: 1,
  });
  assert.match(partial.verdict, / Faltan datos de 3 alimentos\.$/);
  assert.doesNotMatch(model().verdict, /Faltan datos/);
  // A day whose only food is unmatched has no PARTIAL block, yet every row lacks data.
  const unmatched = model({
    nutrients: blocks({
      energy_kcal: block(null, TARGETS.energy, { itemsUncounted: 1 }),
      protein_g: block(null, TARGETS.protein, { itemsUncounted: 1 }),
      fiber_g: block(null, TARGETS.fiber, { itemsUncounted: 1 }),
    }),
    sugarStatus: 'NONE', freeSugarsKnownG: null, itemsUncounted: 1,
  });
  assert.match(unmatched.verdict, / Faltan datos de 1 alimento\.$/);
});

test('a closed day judges each row and says so in the verdict', () => {
  const m = model({ dayStatus: 'COMPLETE', nutrients: blocks({ energy_kcal: block('2200.0', TARGETS.energy, { percent: '98' }) }) });
  assert.deepEqual(m.rows.map((r) => r.state.word), ['bien', 'bien', 'corto', 'bien']);
  assert.equal(m.verdict, 'Día cerrado: bien en energía, proteína y azúcares libres; corto en fibra.');
});

// ----------------------------------------------------------- envelope kinds

test('a READY envelope that is not LIVE is NOT_CONFIGURED', () => {
  assert.deepEqual(toTodayPanelModel(ready(parseDayWire(EMPTY_DAY), 'MOCK'), true), { kind: 'NOT_CONFIGURED' });
});

test('envelope states map to deliberate kinds, and the outcome is the kind', () => {
  const err = (errorCode: NonNullable<DataEnvelope<DiaryDay>['errorCode']>): DataEnvelope<DiaryDay> =>
    ({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE', errorCode });
  assert.equal(toTodayPanelModel(err('ACCESS_DENIED'), true).kind, 'DENIED');
  assert.equal(toTodayPanelModel(err('SESSION_REQUIRED'), true).kind, 'SESSION');
  assert.equal(toTodayPanelModel(err('SESSION_INVALID'), true).kind, 'SESSION');
  assert.equal(toTodayPanelModel(err('SERVICE_UNAVAILABLE'), true).kind, 'UNAVAILABLE');
  assert.equal(toTodayPanelModel(err('INVALID_RESPONSE'), true).kind, 'INVALID');
  assert.equal(toTodayPanelModel(err('NOT_CONFIGURED'), true).kind, 'NOT_CONFIGURED');
  const loading = toTodayPanelModel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }, true);
  assert.equal(loading.kind, 'LOADING');
  assert.equal(todayOutcome(loading), 'LOADING');
  assert.equal(todayOutcome(toTodayPanelModel(ready(day), true)), 'TODAY');
});
