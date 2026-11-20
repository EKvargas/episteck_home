import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDayWire } from './diary-contract.ts';

const item = (over: Record<string, unknown> = {}) => ({
  label: 'manzana', food_id: 'F1', food_name: 'Manzana', amount: 1.5, unit: 'unit', grams: '180',
  conversion: { method: 'PRESET', detail: 'x', table_version: 'v1' },
  facts: { nutrients_per_100g: {}, source: 'USDA', provider_version: '1', category: 'fruit', retrieved_at: 't', serving_g: null, density_g_per_ml: null },
  free_sugar_class: 'INTRINSIC', free_sugar_map_version: 'v1', free_sugars_g: '0.5', extra: 'ignored',
  ...over,
});
const day = (over: Record<string, unknown> = {}) => ({
  date: '2026-11-20', mode: 'PREGNANCY', trimester: 2, day_status: 'OPEN', sugar_status: 'KNOWN',
  free_sugars_known_g: '12.5', items_total: 1, items_uncounted: 0,
  limit: { rule_id: 'r', version: '1', value_g: '25', basis: 'b', energy_basis_kcal: 2000, origin: 'o', sources: [{ title: 'WHO', url: 'https://who.int' }], adaptation: null },
  entries: [{ id: 'E1', consumed_at: '2026-11-20T08:00:00Z', items: [item()] }],
  attribution: ['USDA'],
  ...over,
});

test('maps a full day to camelCase, keeping amount as a string', () => {
  const d = parseDayWire(day());
  assert.equal(d.dayStatus, 'OPEN');
  assert.equal(d.trimester, 2);
  assert.equal(d.freeSugarsKnownG, '12.5');
  assert.deepEqual(d.limit, { valueG: '25', sources: [{ title: 'WHO', url: 'https://who.int' }] });
  assert.deepEqual(d.entries[0].items[0], {
    label: 'manzana', amount: '1.5', unit: 'unit', grams: '180', method: 'PRESET', source: 'USDA', freeSugarsG: '0.5',
  });
  assert.equal(JSON.stringify(d).includes('ignored'), false);
});

test('a null free-sugar figure stays null, never "0"', () => {
  const d = parseDayWire(day({
    sugar_status: 'PARTIAL', free_sugars_known_g: null,
    entries: [{ id: 'E1', consumed_at: 't', items: [item({ free_sugars_g: null, facts: null })] }],
  }));
  assert.equal(d.freeSugarsKnownG, null);
  assert.equal(d.entries[0].items[0].freeSugarsG, null);
  assert.equal(d.entries[0].items[0].source, null);
});

test('an empty day parses to NO_ENTRIES with a null total', () => {
  const d = parseDayWire(day({ day_status: 'NO_ENTRIES', sugar_status: 'NONE', free_sugars_known_g: null, items_total: 0, entries: [], limit: null, trimester: null, mode: 'GENERAL' }));
  assert.equal(d.dayStatus, 'NO_ENTRIES');
  assert.equal(d.freeSugarsKnownG, null);
  assert.equal(d.limit, null);
  assert.deepEqual(d.entries, []);
});

const bad: Array<[string, unknown]> = [
  ['non-object', 'x'],
  ['bad day_status', day({ day_status: 'DONE' })],
  ['bad mode', day({ mode: 'X' })],
  ['bad trimester', day({ trimester: 4 })],
  ['bad decimal', day({ free_sugars_known_g: '-1' })],
  ['numeric decimal', day({ free_sugars_known_g: 12 })],
  ['bad method', day({ entries: [{ id: 'E', consumed_at: 't', items: [item({ conversion: { method: 'GUESS' } })] }] })],
  ['bad grams', day({ entries: [{ id: 'E', consumed_at: 't', items: [item({ grams: 'abc' })] }] })],
  ['bad amount', day({ entries: [{ id: 'E', consumed_at: 't', items: [item({ amount: 'abc' })] }] })],
  ['entries not array', day({ entries: {} })],
  ['bad items_total', day({ items_total: -1 })],
  ['attribution not strings', day({ attribution: [1] })],
  ['limit without value', day({ limit: { sources: [] } })],
];
for (const [name, body] of bad) {
  test(`malformed (${name}) throws TypeError`, () => {
    assert.throws(() => parseDayWire(body), TypeError);
  });
}
