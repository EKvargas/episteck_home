import assert from 'node:assert/strict';
import test from 'node:test';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import type { DiaryDay, DiaryItem } from '../../../integration/nutrition/diary-contract.ts';
import { toTodayPanelModel, type TodayPanelModel } from './today-panel-model.ts';

const item = (over: Partial<DiaryItem> = {}): DiaryItem => ({
  label: 'Zumo', amount: '1', unit: 'glass', grams: '200', method: 'PRESET', source: null, freeSugarsG: '17.0', ...over,
});
const day = (over: Partial<DiaryDay> = {}): DiaryDay => ({
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
