import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DAY_NUTRIENTS, parseDayWire } from './diary-contract.ts';

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
const none = () => block({ known: null, status: 'NONE', items_total: 0, target: null, percent: null });
const nutrients = (over: Record<string, unknown> = {}) => ({
  energy_kcal: block(),
  protein_g: block({ known: '72.4', target: { value: '60', display_value: '60', unit: 'g', kind: 'MIN' }, percent: null }),
  fiber_g: block({ known: null, status: 'NONE', target: null, percent: null }),
  fat_g: block({ known: '58.0', target: { value: '75', display_value: '75', unit: 'g', kind: 'ABOUT' }, percent: '77' }),
  carb_g: block({ known: '190.4', target: null, percent: null }),
  calcium_mg: none(), iron_mg: block({ known: '14.2', status: 'PARTIAL', items_uncounted: 1, target: { value: '27', display_value: '27', unit: 'mg', kind: 'MIN' }, percent: '53' }),
  folate_ug: none(), vitamin_b12_ug: none(), vitamin_d_ug: none(), iodine_ug: none(), zinc_mg: none(),
  selenium_ug: none(), choline_mg: none(), dha_g: none(),
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
    label: 'manzana', amount: '1.5', unit: 'unit', grams: '180', method: 'PRESET', source: 'USDA', freeSugarsG: '0.5', withFacts: [],
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

test("maps all fifteen nutrient blocks in Nutrition's order", () => {
  const d = parseDayWire(day());
  assert.equal(d.profileVersion, 2);
  assert.deepEqual(Object.keys(d.nutrients), [...DAY_NUTRIENTS]);
  assert.deepEqual(d.nutrients.energy_kcal, {
    known: '1640.3', itemsTotal: 2, itemsUncounted: 0, status: 'KNOWN',
    target: { value: '2241.6', displayValue: '2250', unit: 'kcal', kind: 'ABOUT' }, percent: '73',
  });
  assert.deepEqual(d.nutrients.iron_mg, {
    known: '14.2', itemsTotal: 2, itemsUncounted: 1, status: 'PARTIAL',
    target: { value: '27', displayValue: '27', unit: 'mg', kind: 'MIN' }, percent: '53',
  });
  assert.equal(d.nutrients.fiber_g.target, null);
  assert.equal(d.nutrients.fiber_g.known, null);
  assert.equal(parseDayWire(day({ profile_version: null })).profileVersion, null);
});

test('rejects a day missing one of the fifteen', () => {
  const n = nutrients() as Record<string, unknown>;
  delete n.dha_g;
  assert.throws(() => parseDayWire(day({ nutrients: n })), /dha_g/);
});

test('withFacts lists the headline nutrients the food data has', () => {
  const entry = (it: unknown) => [{ id: 'E1', consumed_at: 't', items: [it] }];
  const withFacts = (it: unknown) => parseDayWire(day({ entries: entry(it) })).entries[0].items[0].withFacts;
  const facts = { nutrients_per_100g: { energy_kcal: '52', protein_g: '0.3', calcium_mg: '5' }, source: 'USDA' };
  assert.deepEqual(withFacts(item({ facts })), ['energy_kcal', 'protein_g']);
  assert.deepEqual(withFacts(item({ facts: null })), []);
});

test('rejects facts whose nutrients_per_100g is not an object', () => {
  const entries = (facts: unknown) => [{ id: 'E1', consumed_at: 't', items: [item({ facts })] }];
  assert.throws(() => parseDayWire(day({ entries: entries({ source: 'USDA' }) })), TypeError);
  assert.throws(() => parseDayWire(day({ entries: entries({ source: 'USDA', nutrients_per_100g: [] }) })), TypeError);
  assert.throws(() => parseDayWire(day({ entries: entries({ source: 'USDA', nutrients_per_100g: 'x' }) })), TypeError);
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
