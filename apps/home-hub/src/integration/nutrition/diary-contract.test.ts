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
const block = (over: Record<string, unknown> = {}) => ({
  known: '1640.3', items_total: 2, items_uncounted: 0, status: 'KNOWN',
  target: { value: '2241.6', display_value: '2250', unit: 'kcal', kind: 'ABOUT' }, percent: '73', ...over,
});
const nutrients = (over: Record<string, unknown> = {}) => ({
  energy_kcal: block(),
  protein_g: block({ known: '72.4', target: { value: '60', display_value: '60', unit: 'g', kind: 'MIN' }, percent: null }),
  fiber_g: block({ known: null, status: 'NONE', target: null, percent: null }),
  fat_g: { ignored: true },
  ...over,
});
const day = (over: Record<string, unknown> = {}) => ({
  profile_version: 2, nutrients: nutrients(),
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

test('maps the three shown nutrient blocks and profile_version', () => {
  const d = parseDayWire(day());
  assert.equal(d.profileVersion, 2);
  assert.deepEqual(Object.keys(d.nutrients), ['energy_kcal', 'protein_g', 'fiber_g']);
  assert.deepEqual(d.nutrients.energy_kcal, {
    known: '1640.3', itemsTotal: 2, itemsUncounted: 0, status: 'KNOWN',
    target: { value: '2241.6', displayValue: '2250', unit: 'kcal', kind: 'ABOUT' }, percent: '73',
  });
  assert.equal(d.nutrients.fiber_g.target, null);
  assert.equal(d.nutrients.fiber_g.known, null);
  assert.equal(parseDayWire(day({ profile_version: null })).profileVersion, null);
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
  ['missing nutrients', day({ nutrients: undefined })],
  ['missing a shown nutrient', day({ nutrients: nutrients({ fiber_g: undefined }) })],
  ['bad nutrient status', day({ nutrients: nutrients({ energy_kcal: block({ status: 'UNKNOWN' }) }) })],
  ['comma decimal known', day({ nutrients: nutrients({ energy_kcal: block({ known: '1,5' }) }) })],
  ['bad target kind', day({ nutrients: nutrients({ energy_kcal: block({ target: { value: '1', display_value: '1', unit: 'kcal', kind: 'GOAL' } }) }) })],
  ['bad profile_version', day({ profile_version: -1 })],
  ['limit without value', day({ limit: { sources: [] } })],
];
for (const [name, body] of bad) {
  test(`malformed (${name}) throws TypeError`, () => {
    assert.throws(() => parseDayWire(body), TypeError);
  });
}
