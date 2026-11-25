import assert from 'node:assert/strict';
import test from 'node:test';
import { parseDayWire } from '../src/integration/nutrition/diary-contract.ts';
import { parsePeriodWire } from '../src/integration/nutrition/period-contract.ts';
import { parseProfileWire } from '../src/integration/nutrition/profile-contract.ts';
import {
  EMPTY_DAY, LONG_TEXT, MODE_ONLY, NO_PROFILE_DAY, PARTIAL_DAY, PERIOD_FOURTEEN, PERIOD_NO_PROFILE, PERIOD_THREE,
  PERIOD_WEEK_PREGNANCY, PREGNANCY_DAY, PRESENT, AVERAGE_CODES, DAY_CODES,
} from './nutrition-fixtures.mjs';

const DAYS = [EMPTY_DAY, PARTIAL_DAY, NO_PROFILE_DAY, PREGNANCY_DAY];
const PERIODS = [PERIOD_THREE, PERIOD_NO_PROFILE, PERIOD_WEEK_PREGNANCY, PERIOD_FOURTEEN];

test('every day fixture parses with the real day mapper', () => {
  for (const day of DAYS) assert.doesNotThrow(() => parseDayWire(day));
});

test('every period fixture parses, and the pregnancy week ends today with 7 days', () => {
  for (const p of PERIODS) assert.doesNotThrow(() => parsePeriodWire(p));
  assert.equal(parsePeriodWire(PERIOD_WEEK_PREGNANCY).days.length, 7);
  assert.equal(parsePeriodWire(PERIOD_FOURTEEN).days.length, 14);
  assert.equal(PERIOD_WEEK_PREGNANCY.end, PREGNANCY_DAY.date);
  assert.equal(PERIOD_FOURTEEN.days[0].date, '2026-11-11');
  assert.equal(PERIOD_FOURTEEN.days[7].date, '2026-11-18');
});

test('every profile fixture parses', () => {
  for (const p of [PRESENT, MODE_ONLY, LONG_TEXT]) assert.doesNotThrow(() => parseProfileWire(p));
});

test('every day carries fifteen blocks and every period sixteen averages', () => {
  for (const d of DAYS) assert.deepEqual(Object.keys(d.nutrients), DAY_CODES);
  for (const p of PERIODS) {
    assert.deepEqual(Object.keys(p.averages), AVERAGE_CODES);
    for (const d of p.days) assert.deepEqual(Object.keys(d.nutrients), DAY_CODES);
  }
});

test('a percent appears exactly where a known value and a target both do', () => {
  const blocks = [
    ...DAYS.flatMap((d) => Object.entries(d.nutrients)),
    ...PERIODS.flatMap((p) => p.days.flatMap((d) => Object.entries(d.nutrients))),
  ];
  assert.ok(blocks.length > 0);
  for (const [code, b] of blocks) {
    assert.equal(b.percent !== null, b.known !== null && b.target !== null, code);
  }
});

test('the pregnancy day matches the brief on its headline numbers', () => {
  const d = parseDayWire(PREGNANCY_DAY);
  assert.equal(d.mode, 'PREGNANCY');
  assert.equal(d.nutrients.energy_kcal.known, '1640.3');
  assert.equal(d.nutrients.energy_kcal.percent, '73');
  assert.equal(d.nutrients.carb_g.target, null);
  assert.equal(d.entries.length, 2);
  assert.deepEqual(d.entries[1].items[1].withFacts, []);
  assert.equal(d.entries[0].items[1].withFacts.includes('fiber_g'), false);
});

test('the pregnancy week reports the pinned averages', () => {
  const p = parsePeriodWire(PERIOD_WEEK_PREGNANCY);
  assert.equal(p.averages.energy_kcal.averageKnown, '2246.3');
  assert.equal(p.averages.free_sugars_g.daysUsed, 3);
  assert.equal(p.averages.vitamin_b12_ug.averageKnown, null);
  assert.equal(p.days[5].dayStatus, 'NO_ENTRIES');
});
