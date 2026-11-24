import assert from 'node:assert/strict';
import test from 'node:test';
import { berlinDate, parseRange, periodStart } from './period-range.ts';

test('parseRange accepts 3, 7, 14 and falls back to 7', () => {
  assert.equal(parseRange('3'), 3);
  assert.equal(parseRange('14'), 14);
  assert.equal(parseRange('7'), 7);
  assert.equal(parseRange('30'), 7);
  assert.equal(parseRange(['3', '14']), 7);
  assert.equal(parseRange(undefined), 7);
});

test('periodStart uses the Berlin date after midnight', () => {
  const now = new Date('2026-11-24T23:30:00Z'); // 00:30 on the 25th in Berlin
  assert.equal(berlinDate(now), '2026-11-25');
  assert.equal(periodStart(3, now), '2026-11-23');
  assert.equal(periodStart(7, new Date('2026-03-29T12:00:00Z')), '2026-03-23'); // across the DST change
});

test('periodStart crosses a month and a year boundary', () => {
  assert.equal(periodStart(14, new Date('2026-01-05T10:00:00Z')), '2025-12-23');
});
