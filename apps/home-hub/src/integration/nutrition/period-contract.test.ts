import assert from 'node:assert/strict';
import test from 'node:test';
import { DAY_NUTRIENTS } from './diary-contract.ts';
import { parsePeriodWire } from './period-contract.ts';

const block = (known: string | null, percent: string | null = null, over: Record<string, unknown> = {}) => ({
  known, items_total: known === null ? 0 : 2, items_uncounted: 0, status: known === null ? 'NONE' : 'KNOWN',
  target: percent === null ? null : { value: '2250', display_value: '2250', unit: 'kcal', kind: 'ABOUT' },
  percent, ...over,
});
const avg = (known: string | null, percent: string | null, used: number) => ({
  average_known: known, average_percent: percent, days_used: used,
  left_out: { open: 1, no_entries: 0, partial: 0 },
});
const ALL = [...DAY_NUTRIENTS];
const allBlocks = (over: Record<string, unknown> = {}) =>
  ({ ...Object.fromEntries(ALL.map((c) => [c, block(null)])), ...over });
const allAverages = (over: Record<string, unknown> = {}) =>
  ({ ...Object.fromEntries([...ALL, 'free_sugars_g'].map((c) => [c, avg(null, null, 0)])), ...over });
const day = (date: string, over: Record<string, unknown> = {}) => ({
  date, day_status: 'COMPLETE', mode: 'PREGNANCY', trimester: 2, profile_version: 2,
  free_sugars_known_g: '17.0', items_uncounted: 0,
  nutrients: allBlocks({
    energy_kcal: block('2510', '90'), protein_g: block('72.4', '120'), fiber_g: block('14.0', '47'),
    fat_g: block('80'),
  }),
  free_sugars: { known: '17.0', items_uncounted: 0, status: 'KNOWN', limit_g: '50', percent: '34' },
  ...over,
});
const wire = (over: Record<string, unknown> = {}) => ({
  start: '2026-11-20', end: '2026-11-21', has_profile: true,
  days: [day('2026-11-20'), day('2026-11-21', { day_status: 'OPEN', trimester: null, mode: 'GENERAL' })],
  averages: allAverages({
    energy_kcal: avg('2375', '85', 2), protein_g: avg('70', '110', 2), fiber_g: avg(null, null, 0),
    free_sugars_g: avg('17.0', '34', 2), fat_g: avg('80', null, 2),
  }),
  ...over,
});

test('maps days, averages and has_profile', () => {
  const p = parsePeriodWire(wire());
  assert.equal(p.start, '2026-11-20');
  assert.equal(p.end, '2026-11-21');
  assert.equal(p.hasProfile, true);
  assert.equal(p.days.length, 2);
  assert.equal(p.days[0].dayStatus, 'COMPLETE');
  assert.equal(p.days[0].trimester, 2);
  assert.equal(p.days[0].nutrients.energy_kcal.known, '2510');
  assert.equal(p.days[0].nutrients.energy_kcal.percent, '90');
  assert.equal(p.days[0].nutrients.fat_g.known, '80');
  assert.deepEqual(p.days[0].freeSugars, { known: '17.0', itemsUncounted: 0, status: 'KNOWN', limitG: '50', percent: '34' });
  assert.equal(p.days[1].trimester, null);
  assert.deepEqual(p.averages.energy_kcal, {
    averageKnown: '2375', averagePercent: '85', daysUsed: 2, leftOut: { open: 1, noEntries: 0, partial: 0 },
  });
  assert.equal(p.averages.fiber_g.averageKnown, null);
  assert.equal(p.averages.free_sugars_g.averagePercent, '34');
  assert.equal(p.averages.fat_g.averageKnown, '80');
});

test('maps fifteen nutrients per day and sixteen averages', () => {
  const p = parsePeriodWire(wire());
  assert.deepEqual(Object.keys(p.days[0].nutrients), ALL);
  assert.deepEqual(Object.keys(p.averages), [...ALL, 'free_sugars_g']);
});

test('rejects a period missing the iodine_ug average', () => {
  const rest = Object.fromEntries(Object.entries(wire().averages).filter(([k]) => k !== 'iodine_ug'));
  assert.throws(() => parsePeriodWire(wire({ averages: rest })), /iodine_ug/);
});

test('rejects more than 31 days, an unknown day_status, a missing average key', () => {
  const many = Array.from({ length: 32 }, (_, i) => day(`2026-10-${String((i % 28) + 1).padStart(2, '0')}`));
  assert.throws(() => parsePeriodWire(wire({ days: many })), TypeError);
  assert.throws(() => parsePeriodWire(wire({ days: [] })), TypeError);
  assert.throws(() => parsePeriodWire(wire({ days: [day('2026-11-20', { day_status: 'WAT' })] })), TypeError);
  const averages = wire().averages as Record<string, unknown>;
  const rest = Object.fromEntries(Object.entries(averages).filter(([k]) => k !== 'free_sugars_g'));
  assert.throws(() => parsePeriodWire(wire({ averages: rest })), TypeError);
});

test('rejects malformed decimals, dates and a non-boolean has_profile', () => {
  assert.throws(() => parsePeriodWire(wire({ has_profile: 'yes' })), TypeError);
  assert.throws(() => parsePeriodWire(wire({ days: [day('20-11-2026')] })), TypeError);
  assert.throws(() => parsePeriodWire(wire({
    days: [day('2026-11-20', { free_sugars: { known: 'x', items_uncounted: 0, status: 'KNOWN', limit_g: '50', percent: null } })],
  })), TypeError);
  assert.throws(() => parsePeriodWire(wire({
    averages: { ...(wire().averages as object), energy_kcal: avg('abc', null, 1) },
  })), TypeError);
  assert.throws(() => parsePeriodWire(null), TypeError);
});
