import assert from 'node:assert/strict';
import test from 'node:test';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { DAY_NUTRIENTS, type DiaryDay, type DiaryItem, type NutrientBlock, type DayNutrient } from '../../../integration/nutrition/diary-contract.ts';
import { toTodayPanelModel, type TodayPanelModel } from './today-panel-model.ts';

const item = (over: Partial<DiaryItem> = {}): DiaryItem => ({
  label: 'Zumo', amount: '1', unit: 'glass', grams: '200', method: 'PRESET', source: null, freeSugarsG: '17.0', withFacts: [], ...over,
});
const block = (known: string | null, target: NutrientBlock['target'], over: Partial<NutrientBlock> = {}): NutrientBlock => ({
  known, itemsTotal: 1, itemsUncounted: 0, status: known === null ? 'NONE' : 'KNOWN', target, percent: null, ...over,
});
const TARGETS = {
  energy: { value: '2241.6', displayValue: '2250', unit: 'kcal', kind: 'ABOUT' } as const,
  protein: { value: '60', displayValue: '60', unit: 'g', kind: 'MIN' } as const,
  fiber: { value: '30', displayValue: '30', unit: 'g', kind: 'MIN' } as const,
};
const noBlocks = (): Record<DayNutrient, NutrientBlock> =>
  Object.fromEntries(DAY_NUTRIENTS.map((c) => [c, block(null, null)])) as Record<DayNutrient, NutrientBlock>;
const blocks = (known: { energy?: string | null; protein?: string | null; fiber?: string | null } = {}): Record<DayNutrient, NutrientBlock> => ({
  ...noBlocks(),
  energy_kcal: block(known.energy === undefined ? '1640.3' : known.energy, TARGETS.energy),
  protein_g: block(known.protein === undefined ? '72.4' : known.protein, TARGETS.protein),
  fiber_g: block(known.fiber === undefined ? '14.0' : known.fiber, TARGETS.fiber),
});
const day = (over: Partial<DiaryDay> = {}): DiaryDay => ({
  profileVersion: 2, nutrients: blocks(),
  date: '2026-11-18', mode: 'GENERAL', trimester: null, dayStatus: 'OPEN', sugarStatus: 'KNOWN',
  freeSugarsKnownG: '17.0', itemsTotal: 1, itemsUncounted: 0, limit: { valueG: '50', sources: [] },
  entries: [{ id: 'e1', consumedAt: '2026-11-18T09:15:00+01:00', items: [item()] }], attribution: [], ...over,
});
const ready = (data: DiaryDay, environment: 'LIVE' | 'MOCK' = 'LIVE'): DataEnvelope<DiaryDay> =>
  ({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data });
type Today = Extract<TodayPanelModel, { kind: 'TODAY' }>;
const today = (model: TodayPanelModel): Today => {
  assert.equal(model.kind, 'TODAY');
  return model as Today;
};
const empty = day({
  dayStatus: 'NO_ENTRIES', sugarStatus: 'NONE', freeSugarsKnownG: null, itemsTotal: 0, entries: [],
});

test('an empty day never shows 0 g anywhere', () => {
  const m = today(toTodayPanelModel(ready(empty)));
  assert.equal(m.meter, null);
  assert.equal(m.sugarLine, 'Azúcares libres: sin registros todavía');
  assert.equal(m.statusLine, 'Sin registros hoy');
  assert.doesNotMatch(JSON.stringify(m), /(^|\D)0 g/);
});

test('a partial day shows the known sum and the uncounted count', () => {
  const m = today(toTodayPanelModel(ready(day({ sugarStatus: 'PARTIAL', itemsTotal: 2, itemsUncounted: 1 }))));
  assert.equal(m.sugarLine, 'Azúcares libres: 17 g de 50 g');
  assert.equal(m.statusLine, 'Día abierto · 1 alimento sin contar');
  assert.deepEqual(m.meter, { valueG: 17, limitG: 50 });
  assert.equal(m.referenceLine, 'Referencia general: 50 g de azúcares libres al día (OMS, DGE). No es una indicación médica.');
});

test('two uncounted items use the plural', () => {
  const m = today(toTodayPanelModel(ready(day({ dayStatus: 'COMPLETE', sugarStatus: 'PARTIAL', itemsUncounted: 2 }))));
  assert.equal(m.statusLine, 'Día cerrado · 2 alimentos sin contar');
});

test('entries but a null total says sin dato, and no limit omits the reference', () => {
  const m = today(toTodayPanelModel(ready(day({ freeSugarsKnownG: null, sugarStatus: 'PARTIAL', limit: null, itemsUncounted: 1 }))));
  assert.equal(m.sugarLine, 'Azúcares libres: sin dato');
  assert.equal(m.meter, null);
  assert.equal(m.referenceLine, null);
  const known = today(toTodayPanelModel(ready(day({ limit: null }))));
  assert.equal(known.sugarLine, 'Azúcares libres: 17 g');
  assert.equal(known.meter, null);
});

test('estimates carry ~ and stated amounts do not', () => {
  const m = today(toTodayPanelModel(ready(day({
    entries: [{ id: 'e1', consumedAt: '2026-11-18T09:15:00+01:00', items: [
      item(),
      item({ label: 'Cola', amount: '330', unit: 'ml', grams: '330', method: 'USER_STATED', freeSugarsG: '35.0' }),
      item({ label: 'Té', amount: '2', unit: 'cup', grams: '480', method: 'AGENT_ESTIMATE', freeSugarsG: null }),
      item({ label: 'Pan', amount: '1', unit: 'slice', grams: '30', method: 'SOURCE_SERVING', freeSugarsG: '1.5' }),
      item({ label: 'Leche', amount: '250', unit: 'g', grams: '250', method: 'USER_STATED', freeSugarsG: null }),
    ] }],
  }))));
  assert.deepEqual(m.entries[0].items.map((i) => i.text), [
    'Zumo, 1 vaso (~200 g)', 'Cola, 330 ml', 'Té, 2 tazas (~480 g)', 'Pan, 1 rebanada (30 g)', 'Leche, 250 g',
  ]);
  assert.deepEqual(m.entries[0].items.map((i) => i.sugar), ['17 g', '35 g', 'sin dato', '1,5 g', 'sin dato']);
});

test('times are Berlin clock times', () => {
  const at = (consumedAt: string) =>
    today(toTodayPanelModel(ready(day({ entries: [{ id: 'e', consumedAt, items: [item()] }] })))).entries[0].time;
  assert.equal(at('2026-11-18T23:30:00+01:00'), '23:30');
  assert.equal(at('2026-11-18T23:30:00Z'), '00:30');
});

test('unknown free sugars distinguish an unmatched food from a matched food without a value', () => {
  const m = today(toTodayPanelModel(ready(day({
    sugarStatus: 'PARTIAL',
    itemsUncounted: 2,
    entries: [{ id: 'e1', consumedAt: '2026-11-18T09:15:00+01:00', items: [
      item({ label: 'Comida casera', source: null, freeSugarsG: null }),
      item({ label: 'Yogur', source: 'BLS', freeSugarsG: null }),
      item({ label: 'Agua', source: 'BLS', freeSugarsG: '0.0' }),
    ] }],
  }))));
  assert.deepEqual(m.entries[0].items.map((entry) => [entry.sugar, entry.nutrientNote]), [
    ['sin dato', 'Sin coincidencia en la base de alimentos'],
    ['sin dato', 'Alimento identificado con azúcares libres desconocidos'],
    ['0 g', null],
  ]);
  assert.equal(m.hasUnmatchedFood, true);
});

test('decimal comma, no trailing ,0', () => {
  assert.equal(today(toTodayPanelModel(ready(day({ freeSugarsKnownG: '15.9' })))).sugarLine, 'Azúcares libres: 15,9 g de 50 g');
  assert.equal(today(toTodayPanelModel(ready(day({ freeSugarsKnownG: '17.0' })))).sugarLine, 'Azúcares libres: 17 g de 50 g');
});

test('pregnancy heading per trimester and without one', () => {
  const h = (mode: DiaryDay['mode'], trimester: DiaryDay['trimester']) =>
    today(toTodayPanelModel(ready(day({ mode, trimester })))).heading;
  assert.equal(h('GENERAL', null), 'Hoy');
  assert.equal(h('PREGNANCY', 1), 'Hoy · Embarazo, 1.er trimestre');
  assert.equal(h('PREGNANCY', 2), 'Hoy · Embarazo, 2.º trimestre');
  assert.equal(h('PREGNANCY', 3), 'Hoy · Embarazo, 3.er trimestre');
  assert.equal(h('PREGNANCY', null), 'Hoy · Embarazo');
});

test('over the reference says so in words', () => {
  const m = today(toTodayPanelModel(ready(day({ freeSugarsKnownG: '62.5' }))));
  assert.equal(m.sugarLine, 'Azúcares libres: 62,5 g de 50 g (por encima de la referencia)');
  assert.deepEqual(m.meter, { valueG: 62.5, limitG: 50 });
});

test('BLS attribution passes through', () => {
  const m = today(toTodayPanelModel(ready(day({ attribution: ['Bundeslebensmittelschlüssel (BLS) 4.0'] }))));
  assert.deepEqual(m.attribution, ['Bundeslebensmittelschlüssel (BLS) 4.0']);
});

test('a READY envelope that is not LIVE is NOT_CONFIGURED', () => {
  assert.deepEqual(toTodayPanelModel(ready(empty, 'MOCK')), { kind: 'NOT_CONFIGURED' });
});

test('envelope states map to deliberate kinds', () => {
  const err = (errorCode: NonNullable<DataEnvelope<DiaryDay>['errorCode']>): DataEnvelope<DiaryDay> =>
    ({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE', errorCode });
  assert.equal(toTodayPanelModel(err('ACCESS_DENIED')).kind, 'DENIED');
  assert.equal(toTodayPanelModel(err('SESSION_REQUIRED')).kind, 'SESSION');
  assert.equal(toTodayPanelModel(err('SESSION_INVALID')).kind, 'SESSION');
  assert.equal(toTodayPanelModel(err('SERVICE_UNAVAILABLE')).kind, 'UNAVAILABLE');
  assert.equal(toTodayPanelModel(err('INVALID_RESPONSE')).kind, 'INVALID');
  assert.equal(toTodayPanelModel(err('NOT_CONFIGURED')).kind, 'NOT_CONFIGURED');
  assert.equal(toTodayPanelModel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }).kind, 'LOADING');
});

test('energy, protein and fiber read against the day target', () => {
  const m = today(toTodayPanelModel(ready(day({ nutrients: blocks({ energy: '1640.3', protein: '72.4', fiber: '14.0' }) }))));
  assert.deepEqual(m.nutrientLines.map((l) => l.line),
    ['Energía: 1.640 de 2.250 kcal', 'Proteína: 72 de 60 g', 'Fibra: 14 de 30 g']);
  assert.deepEqual(m.nutrientLines[0].meter, { value: 1640.3, max: 2241.6 });
  assert.equal(m.profileHint, false);
});

test('a value above its target shows the real value and clamps the meter', () => {
  const m = today(toTodayPanelModel(ready(day({ nutrients: blocks({ energy: '3400.0' }) }))));
  assert.equal(m.nutrientLines[0].line, 'Energía: 3.400 de 2.250 kcal');
  assert.deepEqual(m.nutrientLines[0].meter, { value: 2241.6, max: 2241.6 });
  assert.ok(!/por encima|demasiado|debes/i.test(JSON.stringify(m.nutrientLines)));
});

test('partial and unknown nutrients never read 0', () => {
  const partial = blocks();
  partial.energy_kcal = block('1640.3', TARGETS.energy, { status: 'PARTIAL', itemsUncounted: 1 });
  const m = today(toTodayPanelModel(ready(day({ nutrients: partial }))));
  assert.equal(m.nutrientLines[0].line, 'Energía: 1.640 de 2.250 kcal (1 sin contar)');
  const unknown = today(toTodayPanelModel(ready(day({ nutrients: blocks({ energy: null }) }))));
  assert.equal(unknown.nutrientLines[0].line, 'Energía: sin dato');
  assert.equal(unknown.nutrientLines[0].meter, null);
  assert.doesNotMatch(JSON.stringify(unknown.nutrientLines), /(^|\D)0 (g|kcal)/);
});

test('an empty day reads "sin registros todavía" per nutrient', () => {
  const m = today(toTodayPanelModel(ready(day({
    dayStatus: 'NO_ENTRIES', sugarStatus: 'NONE', freeSugarsKnownG: null, itemsTotal: 0, entries: [],
    nutrients: blocks({ energy: null, protein: null, fiber: null }),
  }))));
  assert.deepEqual(m.nutrientLines.map((l) => l.line),
    ['Energía: sin registros todavía', 'Proteína: sin registros todavía', 'Fibra: sin registros todavía']);
  assert.ok(m.nutrientLines.every((l) => l.meter === null));
});

test('no energy target shows the hint and no energy line', () => {
  const n = blocks();
  n.energy_kcal = block('1640.3', null);
  n.protein_g = block('72.4', null);
  const m = today(toTodayPanelModel(ready(day({ nutrients: n, profileVersion: null }))));
  assert.deepEqual(m.nutrientLines.map((l) => l.line), ['Fibra: 14 de 30 g']);
  assert.equal(m.profileHint, true);
});
