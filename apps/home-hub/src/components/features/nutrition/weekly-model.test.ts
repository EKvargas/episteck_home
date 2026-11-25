import assert from 'node:assert/strict';
import test from 'node:test';
import { parsePeriodWire } from '../../../integration/nutrition/period-contract.ts';
import { EnvelopeFactory, type DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { PERIOD_THREE, PERIOD_WEEK_PREGNANCY } from '../../../../test-support/nutrition-fixtures.mjs';
import { microGroups, toWeeklyPanelModel, weeklyOutcome, WEEKLY_TITLE } from './weekly-model.ts';
import type { PeriodSummary } from '../../../integration/nutrition/period-contract.ts';

const summary = parsePeriodWire(PERIOD_WEEK_PREGNANCY);

test('the pregnancy week groups as Corto (4), Bien (3), Faltan datos (3)', () => {
  const g = microGroups(summary, 7, 'PSN-00007');
  assert.deepEqual(g.map((x) => x.summary), ['Corto: hierro, folato, vitamina D, colina', 'Bien: 3', 'Faltan datos: 3']);
  assert.deepEqual(g[0].items[0], {
    code: 'iron_mg', name: 'Hierro', average: '8,4 mg', target: '≥ 27 mg',
    state: { tone: 'caution', word: 'corto', detail: 'con 3 días' },
    href: '/app/nutrition/nutriente/iron_mg?person=PSN-00007&rango=7',
  });
  assert.deepEqual(g[2].items.map((r) => r.state.word), ['faltan datos', 'pocos días (2)', 'pocos días (1)']);
});

test('no targets at all: one Sin objetivo group with values only', () => {
  const g = microGroups(parsePeriodWire(PERIOD_THREE), 7, null);
  assert.deepEqual(g.map((x) => x.summary), ['Sin objetivo: 10']);
  assert.ok(g[0].items.every((r) => r.target === null && r.state.word === null));
  assert.ok(g[0].items.every((r) => r.average === 'sin dato'));
  assert.equal(g[0].items[0].href, '/app/nutrition/nutriente/calcium_mg?rango=7');
});

test('an unknown average reads sin dato, never 0', () => {
  const rows = microGroups(summary, 7, null).flatMap((x) => x.items);
  const b12 = rows.find((r) => r.code === 'vitamin_b12_ug');
  assert.equal(b12?.average, 'sin dato');
  assert.ok(rows.every((r) => !/(^|\D)0 /.test(r.average)));
});

const ready = (data: PeriodSummary): DataEnvelope<PeriodSummary> => EnvelopeFactory.ready(data, 'LIVE');

test('errors map to panel kinds', () => {
  assert.equal(toWeeklyPanelModel(EnvelopeFactory.error('ACCESS_DENIED', 'LIVE'), null).kind, 'DENIED');
  assert.equal(toWeeklyPanelModel(EnvelopeFactory.error('SESSION_INVALID', 'LIVE'), null).kind, 'SESSION');
  assert.equal(toWeeklyPanelModel(EnvelopeFactory.error('INVALID_RESPONSE', 'LIVE'), null).kind, 'INVALID');
  assert.equal(toWeeklyPanelModel(EnvelopeFactory.error('SERVICE_UNAVAILABLE', 'LIVE'), null).kind, 'UNAVAILABLE');
  assert.equal(toWeeklyPanelModel(EnvelopeFactory.loading('LIVE'), null).kind, 'LOADING');
});

test('a ready LIVE envelope becomes a WEEK; MOCK is not configured', () => {
  const model = toWeeklyPanelModel(ready(summary), null);
  assert.equal(model.kind, 'WEEK');
  assert.equal(weeklyOutcome(model), 'WEEK');
  assert.equal(toWeeklyPanelModel(EnvelopeFactory.ready(summary, 'MOCK'), null).kind, 'NOT_CONFIGURED');
});

test('the Hoy title keeps "·" off a line start with a no-break space', () => {
  assert.equal(WEEKLY_TITLE, 'Vitaminas y minerales\u00a0· últimos 7 días');
  assert.equal(WEEKLY_TITLE.replace(/\s+/g, ' '), 'Vitaminas y minerales · últimos 7 días');
});
