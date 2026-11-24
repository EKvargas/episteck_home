import assert from 'node:assert/strict';
import test from 'node:test';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import type { NutrientBlock } from '../../../integration/nutrition/diary-contract.ts';
import type { PeriodAverage, PeriodDay, PeriodSummary } from '../../../integration/nutrition/period-contract.ts';
import { periodOutcome, toPeriodPanelModel, type PeriodPanelModel } from './period-panel-model.ts';

const block = (known: string | null, percent: string | null = null, over: Partial<NutrientBlock> = {}): NutrientBlock => ({
  known, itemsTotal: known === null ? 0 : 2, itemsUncounted: 0, status: known === null ? 'NONE' : 'KNOWN',
  target: null, percent, ...over,
});
const sugars = (known: string | null, percent: string | null, status: 'NONE' | 'KNOWN' | 'PARTIAL' = 'KNOWN') =>
  ({ known, itemsUncounted: 0, status, limitG: percent === null ? null : '50', percent });
const mkDay = (date: string, dayStatus: PeriodDay['dayStatus'], over: Partial<PeriodDay> = {}): PeriodDay => ({
  date, dayStatus, mode: 'GENERAL', trimester: null,
  nutrients: {
    energy_kcal: block('2510', '90'), protein_g: block('98.4', '120'), fiber_g: block('24.0', '80'),
  },
  freeSugars: sugars('17.0', '34'), ...over,
});
const avg = (known: string | null, percent: string | null, used: number): PeriodAverage => ({
  averageKnown: known, averagePercent: percent, daysUsed: used, leftOut: { open: 1, noEntries: 0, partial: 0 },
});
const threeDays = (over: Partial<PeriodSummary> = {}): PeriodSummary => ({
  start: '2026-11-20', end: '2026-11-22', hasProfile: true,
  days: [
    mkDay('2026-11-20', 'COMPLETE'),
    mkDay('2026-11-21', 'COMPLETE', { freeSugars: sugars(null, null, 'NONE') }),
    mkDay('2026-11-22', 'OPEN', {
      nutrients: {
        energy_kcal: block('1200', '53'), protein_g: block('40', null, { status: 'PARTIAL' }),
        fiber_g: block(null),
      },
      freeSugars: sugars('12.0', null, 'PARTIAL'),
    }),
  ],
  averages: {
    energy_kcal: avg('2375', '85', 2), protein_g: avg('90', '110', 2), fiber_g: avg('24.0', null, 1),
    free_sugars_g: avg(null, null, 0),
  },
  ...over,
});
const ready = (data: PeriodSummary, environment: 'LIVE' | 'MOCK' = 'LIVE'): DataEnvelope<PeriodSummary> =>
  ({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data });
type Period = Extract<PeriodPanelModel, { kind: 'PERIOD' }>;
const period = (model: PeriodPanelModel): Period => {
  assert.equal(model.kind, 'PERIOD');
  return model as Period;
};

test('rows, cells and the average row', () => {
  const m = period(toPeriodPanelModel(ready(threeDays()), 3));
  assert.equal(m.title, 'Últimos 3 días');
  assert.equal(m.range, 3);
  assert.deepEqual(m.rows.map((r) => [r.day, r.status]), [['Vie 20', 'Cerrado'], ['Sáb 21', 'Cerrado'], ['Dom 22', 'Abierto']]);
  assert.deepEqual(m.rows.map((r) => r.tone), ['ok', 'ok', 'open']);
  assert.deepEqual(m.rows[0].cells[0], { value: '2.510', detail: '90 %', unknown: false });
  assert.deepEqual(m.rows[0].cells[1], { value: '98 g', detail: '120 %', unknown: false });
  assert.deepEqual(m.rows[0].cells[3], { value: '17 g', detail: '34 %', unknown: false });
  assert.deepEqual(m.rows[1].cells[3], { value: 'sin dato', detail: null, unknown: true });
  assert.deepEqual(m.rows[2].cells[1], { value: '40 g', detail: 'parcial', unknown: false });
  assert.deepEqual(m.rows[2].cells[3], { value: '12 g', detail: 'parcial', unknown: false });
  assert.deepEqual(m.rows[2].cells[2], { value: 'sin dato', detail: null, unknown: true });
  assert.equal(m.average.day, 'Media');
  assert.equal(m.average.status, null);
  assert.equal(m.average.tone, null);
  assert.deepEqual(m.average.cells[0], { value: '2.375', detail: '85 % · 2 días', unknown: false });
  assert.deepEqual(m.average.cells[2], { value: '24 g', detail: '1 día', unknown: false });
  assert.deepEqual(m.average.cells[3], { value: 'sin dato', detail: null, unknown: true });
});

test('a partial energy figure keeps its percent and adds parcial', () => {
  const days = threeDays().days;
  days[0] = mkDay('2026-11-20', 'OPEN', {
    nutrients: { ...days[0].nutrients, energy_kcal: block('1000', '44', { status: 'PARTIAL' }) },
  });
  const m = period(toPeriodPanelModel(ready(threeDays({ days })), 3));
  assert.equal(m.rows[0].cells[0].detail, '44 % · parcial');
});

test('a day without entries shows — and never 0', () => {
  const none = mkDay('2026-11-22', 'NO_ENTRIES', {
    nutrients: { energy_kcal: block(null), protein_g: block(null), fiber_g: block(null) },
    freeSugars: sugars(null, null, 'NONE'),
  });
  const m = period(toPeriodPanelModel(ready(threeDays({ days: [none] })), 7));
  assert.equal(m.rows[0].status, 'Sin registros');
  assert.equal(m.rows[0].tone, 'none');
  for (const cell of m.rows[0].cells) assert.deepEqual(cell, { value: '—', detail: null, unknown: false });
  const text = JSON.stringify(m);
  assert.doesNotMatch(text, /(^|\D)0 (g|kcal|%)/);
});

test('without a profile: no percentages and the hint', () => {
  const days = threeDays().days.map((d) => ({
    ...d,
    nutrients: {
      energy_kcal: { ...d.nutrients.energy_kcal, percent: null },
      protein_g: { ...d.nutrients.protein_g, percent: null },
      fiber_g: { ...d.nutrients.fiber_g, percent: null },
    },
    freeSugars: { ...d.freeSugars, percent: null },
  }));
  const averages = {
    energy_kcal: avg('2375', null, 2), protein_g: avg('90', null, 2), fiber_g: avg('24.0', null, 2),
    free_sugars_g: avg('17.0', null, 2),
  };
  const m = period(toPeriodPanelModel(ready(threeDays({ hasProfile: false, days, averages })), 3));
  assert.equal(m.profileHint, true);
  assert.doesNotMatch(JSON.stringify(m), /%/);
  assert.equal(m.average.cells[0].detail, '2 días');
  assert.equal(period(toPeriodPanelModel(ready(threeDays()), 3)).profileHint, false);
});

test('errors and MOCK map to deliberate panels', () => {
  const err = (errorCode: string): DataEnvelope<PeriodSummary> =>
    ({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE', errorCode } as DataEnvelope<PeriodSummary>);
  assert.equal(toPeriodPanelModel(err('ACCESS_DENIED'), 7).kind, 'DENIED');
  assert.equal(toPeriodPanelModel(err('SESSION_INVALID'), 7).kind, 'SESSION');
  assert.equal(toPeriodPanelModel(err('SESSION_REQUIRED'), 7).kind, 'SESSION');
  assert.equal(toPeriodPanelModel(err('INVALID_RESPONSE'), 7).kind, 'INVALID');
  assert.equal(toPeriodPanelModel(err('NOT_CONFIGURED'), 7).kind, 'NOT_CONFIGURED');
  assert.equal(toPeriodPanelModel(err('SERVICE_UNAVAILABLE'), 7).kind, 'UNAVAILABLE');
  assert.equal(toPeriodPanelModel(ready(threeDays(), 'MOCK'), 7).kind, 'NOT_CONFIGURED');
  assert.equal(periodOutcome({ kind: 'DENIED' }), 'DENIED');
});
