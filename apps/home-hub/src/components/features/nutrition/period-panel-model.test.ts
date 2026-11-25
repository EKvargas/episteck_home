import assert from 'node:assert/strict';
import test from 'node:test';
import { parsePeriodWire, type PeriodSummary } from '../../../integration/nutrition/period-contract.ts';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { PERIOD_FOURTEEN, PERIOD_NO_PROFILE, PERIOD_WEEK_PREGNANCY } from '../../../../test-support/nutrition-fixtures.mjs';
import { periodOutcome, toPeriodPanelModel, type PeriodPanelModel } from './period-panel-model.ts';

const ready = (data: PeriodSummary, environment: 'LIVE' | 'MOCK' = 'LIVE'): DataEnvelope<PeriodSummary> =>
  ({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data });
type Period = Extract<PeriodPanelModel, { kind: 'PERIOD' }>;
const period = (model: PeriodPanelModel): Period => {
  assert.equal(model.kind, 'PERIOD');
  return model as Period;
};

test('one 7-day grid: initials, day numbers, tones by phase, Media on the last grid', () => {
  const m = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_WEEK_PREGNANCY)), 7, null));
  assert.equal(m.title, 'Últimos 7 días');
  assert.equal(m.range, 7);
  assert.equal(m.grids.length, 1);
  assert.deepEqual(m.grids[0].columns.map((c) => `${c.initial} ${c.day}`), ['X 18', 'J 19', 'V 20', 'S 21', 'D 22', 'L 23', 'M 24']);
  assert.deepEqual(m.grids[0].rows.map((r) => r.name), ['Energía', 'Proteína', 'Fibra', 'Azúcares libres']);
  assert.deepEqual(m.grids[0].rows[0].cells.map((c) => c.tone), ['ok', 'caution', 'ok', 'caution', 'unclosed', 'empty', 'progress']);
  assert.deepEqual(m.grids[0].rows[0].cells.map((c) => c.text),
    ['bien', 'bajo', 'bien', 'por encima', 'sin cerrar', 'Sin registros', 'en curso · faltan ~610 kcal']);
  assert.equal(m.grids[0].rows[0].average, '2.246 kcal');
  assert.deepEqual(m.grids[0].rows[3].cells.slice(0, 4).map((c) => c.text), ['bien', 'pasado del límite', 'bien', 'faltan datos']);
  assert.equal(m.profileHint, false);
});

test('14 days: two stacked grids, Media only on the second', () => {
  const m = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_FOURTEEN)), 14, null));
  assert.equal(m.title, 'Últimos 14 días');
  assert.equal(m.grids.length, 2);
  assert.deepEqual(m.grids.map((g) => g.columns.length), [7, 7]);
  assert.equal(m.grids[0].columns[0].day, '11');
  assert.equal(m.grids[1].columns[0].day, '18');
  for (const r of m.grids[0].rows) assert.equal(r.average, null);
  assert.equal(m.grids[1].rows[0].average, '2.246 kcal');
});

test('rows link to the nutrient detail for the same range, keeping the person', () => {
  const m = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_FOURTEEN)), 14, 'PSN-00007'));
  assert.deepEqual(m.grids[0].rows.map((r) => r.href), [
    '/app/nutrition/nutriente/energy_kcal?person=PSN-00007&rango=14',
    '/app/nutrition/nutriente/protein_g?person=PSN-00007&rango=14',
    '/app/nutrition/nutriente/fiber_g?person=PSN-00007&rango=14',
    '/app/nutrition/nutriente/free_sugars_g?person=PSN-00007&rango=14',
  ]);
  const own = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_WEEK_PREGNANCY)), 7, null));
  assert.equal(own.grids[0].rows[2].href, '/app/nutrition/nutriente/fiber_g?rango=7');
});

test('the micronutrient groups follow the range', () => {
  const week = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_WEEK_PREGNANCY)), 7, 'PSN-00007'));
  assert.deepEqual(week.micro.map((g) => g.summary), ['Corto: hierro, folato, vitamina D, colina', 'Bien: 3', 'Faltan datos: 3']);
  assert.equal(week.micro[0].items[0].href, '/app/nutrition/nutriente/iron_mg?person=PSN-00007&rango=7');
  const two = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_FOURTEEN)), 14, null));
  assert.equal(two.micro[0].items[0].href, '/app/nutrition/nutriente/iron_mg?rango=14');
});

test('no profile: plain cells carry their values and the hint shows', () => {
  const m = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_NO_PROFILE)), 3, null));
  assert.equal(m.profileHint, true);
  const energy = m.grids[0].rows[0].cells[0];
  assert.equal(energy.tone, 'plain');
  assert.equal(energy.text, '2.510 kcal');
  assert.doesNotMatch(JSON.stringify(m.grids), /(^|\D)0 (g|kcal|%)/);
});

test('errors and MOCK map to deliberate panels', () => {
  const err = (errorCode: string): DataEnvelope<PeriodSummary> =>
    ({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE', errorCode } as DataEnvelope<PeriodSummary>);
  assert.equal(toPeriodPanelModel(err('ACCESS_DENIED'), 7, null).kind, 'DENIED');
  assert.equal(toPeriodPanelModel(err('SESSION_INVALID'), 7, null).kind, 'SESSION');
  assert.equal(toPeriodPanelModel(err('SESSION_REQUIRED'), 7, null).kind, 'SESSION');
  assert.equal(toPeriodPanelModel(err('INVALID_RESPONSE'), 7, null).kind, 'INVALID');
  assert.equal(toPeriodPanelModel(err('NOT_CONFIGURED'), 7, null).kind, 'NOT_CONFIGURED');
  assert.equal(toPeriodPanelModel(err('SERVICE_UNAVAILABLE'), 7, null).kind, 'UNAVAILABLE');
  assert.equal(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_WEEK_PREGNANCY), 'MOCK'), 7, null).kind, 'NOT_CONFIGURED');
  assert.equal(periodOutcome({ kind: 'DENIED' }), 'DENIED');
});
