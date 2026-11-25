// Synthetic wire bodies shared by the fake Nutrition server and the unit tests.
// Every day carries all 15 nutrient blocks and every period all 16 averages, like Nutrition.
// Like Nutrition, a block carries a `percent` exactly when it has both a known value and a target.

export const DAY_CODES = [
  'energy_kcal', 'protein_g', 'fat_g', 'carb_g', 'fiber_g', 'calcium_mg', 'iron_mg', 'folate_ug',
  'vitamin_b12_ug', 'vitamin_d_ug', 'iodine_ug', 'zinc_mg', 'selenium_ug', 'choline_mg', 'dha_g',
];
export const AVERAGE_CODES = [...DAY_CODES, 'free_sugars_g'];

const NONE_BLOCK = { known: null, items_total: 0, items_uncounted: 0, status: 'NONE', target: null, percent: null };
const NONE_AVERAGE = {
  average_known: null, average_percent: null, days_used: 0, left_out: { open: 0, no_entries: 0, partial: 0 },
};

/** All 15 blocks in Nutrition's order; `over` replaces some, the rest are empty. */
export const fullBlocks = (over = {}) =>
  Object.fromEntries(DAY_CODES.map((c) => [c, { ...(over[c] ?? NONE_BLOCK) }]));
/** All 16 averages in Nutrition's order; `over` replaces some, the rest are `days_used: 0`. */
export const fullAverages = (over = {}) =>
  Object.fromEntries(AVERAGE_CODES.map((c) => [c, { ...(over[c] ?? NONE_AVERAGE) }]));

// ---------------------------------------------------------------- profiles
const ENERGY = {
  nutrient: 'energy_kcal', value: '2241.6', display_value: '2250', unit: 'kcal', kind: 'ABOUT',
  source_org: 'Mifflin-St Jeor (1990); DGE/D-A-CH', source_ref: 'Am J Clin Nutr 51(2):241-247',
  explanation: 'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2.',
};
const PROTEIN = {
  nutrient: 'protein_g', value: '65', display_value: '65', unit: 'g', kind: 'MIN',
  source_org: 'DGE/D-A-CH', source_ref: 'DGE 2017',
  explanation: 'Referencia para el embarazo, 2.º trimestre.',
};
// A full profile view of a synthetic pregnant member. The flat `targets` map, `context` and
// `target_source` are legacy fields the Hub must ignore; the sentinels prove it.
export const PRESENT = {
  person_id: 'PSN-00001', version: 2, valid_from: '2026-11-24', origin: 'PROFILE', onboarded: true,
  mode: 'PREGNANCY', due_date: '2027-03-01', trimester: 2,
  inputs: {
    birth_date: '1990-05-01', age: 36, sex: 'FEMALE', height_cm: '165', weight_kg: '62.5',
    weight_measured_on: '2026-11-20', activity_pal: '1.6', training_sessions_per_week: 2,
    training_note: 'Yoga', goal: 'MAINTAIN', pre_pregnancy_weight_kg: '58',
    UNKNOWN_FIELD_SENTINEL: 'x',
  },
  food: { preferences: 'PRIVATE_PREF_SENTINEL', dislikes: 'PRIVATE_DISLIKE_SENTINEL', intolerances: 'lactosa; frutos secos' },
  targets: { energy_kcal: '9999.9', calcium_mg: '1000' },
  target_set: {
    method: 'episteck-targets-1', on: '2026-11-24', items: [{ ...ENERGY }, { ...PROTEIN }],
    missing: [],
  },
  history: [
    { version: 1, valid_from: '2026-11-24', origin: 'MODE', changed: ['mode', 'due_date'] },
    { version: 2, valid_from: '2026-11-24', origin: 'PROFILE', changed: ['height_cm'] },
  ],
  context: 'PREGNANCY', target_source: 'REFERENCE_TARGET',
  UNKNOWN_FIELD_SENTINEL: 'x',
};
export const MODE_ONLY = {
  ...PRESENT, version: 1, origin: 'MODE', onboarded: false,
  inputs: {
    birth_date: null, age: null, sex: null, height_cm: null, weight_kg: null, weight_measured_on: null,
    activity_pal: null, training_sessions_per_week: null, training_note: null, goal: null,
    pre_pregnancy_weight_kg: null,
  },
  food: { preferences: null, dislikes: null, intolerances: null },
  targets: {},
  target_set: { method: 'episteck-targets-1', on: '2026-11-24', items: [], missing: [] },
  history: [PRESENT.history[0]],
};
export const LONG_TEXT = {
  ...PRESENT,
  inputs: { ...PRESENT.inputs, training_note: 'T'.repeat(120) },
  food: {
    preferences: 'P'.repeat(500),
    dislikes: 'dislike '.repeat(60).trim().slice(0, 500),
    intolerances: 'I'.repeat(500),
  },
};

// -------------------------------------------------------------------- days
const block = (known, target, over = {}) => ({
  known, items_total: known === null ? 0 : 2, items_uncounted: 0, status: known === null ? 'NONE' : 'KNOWN',
  target, percent: null, ...over,
});
const T_ENERGY = { value: '2250', display_value: '2250', unit: 'kcal', kind: 'ABOUT' };
const T_PROTEIN = { value: '60', display_value: '60', unit: 'g', kind: 'MIN' };
const T_FIBER = { value: '30', display_value: '30', unit: 'g', kind: 'MIN' };

export const EMPTY_DAY = {
  profile_version: 2,
  nutrients: fullBlocks({
    energy_kcal: block(null, T_ENERGY), protein_g: block(null, T_PROTEIN), fiber_g: block(null, T_FIBER),
  }),
  date: '2026-11-18', mode: 'GENERAL', trimester: null, day_status: 'NO_ENTRIES', sugar_status: 'NONE',
  free_sugars_known_g: null, items_total: 0, items_uncounted: 0,
  limit: { value_g: '50', sources: [{ title: 'WHO', url: 'https://example.test/who' }] },
  entries: [], attribution: [],
};

export const PARTIAL_DAY = {
  ...EMPTY_DAY,
  nutrients: fullBlocks({
    ...EMPTY_DAY.nutrients,
    energy_kcal: block('436.0', T_ENERGY, { percent: '19' }),
    protein_g: block('12.4', T_PROTEIN, { percent: '21' }),
    fiber_g: block('3.0', T_FIBER, { status: 'PARTIAL', items_uncounted: 1, percent: '10' }),
  }),
  day_status: 'OPEN', sugar_status: 'PARTIAL', free_sugars_known_g: '17.0', items_total: 2, items_uncounted: 1,
  entries: [
    { id: 'e-1', consumed_at: '2026-11-18T09:15:00+01:00', items: [{
      label: 'Zumo', amount: '1', unit: 'glass', grams: '200', conversion: { method: 'PRESET' },
      facts: { source: 'PRESET', nutrients_per_100g: { energy_kcal: '45', protein_g: '0.6', fiber_g: '0.2' } },
      free_sugars_g: '17.0',
    }] },
    { id: 'e-2', consumed_at: '2026-11-18T12:40:00+01:00', items: [{
      label: 'Pan integral', amount: '2', unit: 'slice', grams: '60', conversion: { method: 'AGENT_ESTIMATE' },
      facts: { source: 'BLS', nutrients_per_100g: { energy_kcal: '250', protein_g: '9.0', fiber_g: '7.0' } },
      free_sugars_g: null,
    }] },
  ],
  attribution: ['Bundeslebensmittelschlüssel (BLS) 4.0, Max Rubner-Institut'],
};

export const NO_PROFILE_DAY = {
  ...EMPTY_DAY, day_status: 'OPEN', profile_version: null,
  nutrients: fullBlocks({
    ...PARTIAL_DAY.nutrients,
    energy_kcal: block('436.0', null), protein_g: block('12.4', null), fiber_g: block('3.0', null),
  }),
  entries: PARTIAL_DAY.entries, free_sugars_known_g: '17.0', sugar_status: 'PARTIAL', items_total: 2, items_uncounted: 1,
};

// ---- pregnancy day: second trimester, targets for all but carbohydrate
const target = (value, display, unit, kind) => ({ value, display_value: display, unit, kind });
const PREG_TARGETS = {
  energy_kcal: target('2241.6', '2250', 'kcal', 'ABOUT'),
  protein_g: target('65', '65', 'g', 'MIN'),
  fiber_g: target('30', '30', 'g', 'MIN'),
  fat_g: target('75', '75', 'g', 'ABOUT'),
  carb_g: null,
  calcium_mg: target('1000', '1000', 'mg', 'MIN'),
  iron_mg: target('27', '27', 'mg', 'MIN'),
  folate_ug: target('550', '550', 'ug', 'MIN'),
  vitamin_b12_ug: target('4.5', '4.5', 'ug', 'MIN'),
  vitamin_d_ug: target('20', '20', 'ug', 'MIN'),
  iodine_ug: target('220', '220', 'ug', 'MIN'),
  zinc_mg: target('11', '11', 'mg', 'MIN'),
  selenium_ug: target('60', '60', 'ug', 'MIN'),
  choline_mg: target('480', '480', 'mg', 'MIN'),
  dha_g: target('0.2', '0.2', 'g', 'MIN'),
};
// [known, percent] for the nutrients that are not headline nutrients.
const PREG_OTHERS = {
  fat_g: ['58.0', '77'], carb_g: ['190.4', null], calcium_mg: ['640.2', '64'], iron_mg: ['14.2', '53'],
  folate_ug: ['310.5', '56'], vitamin_b12_ug: ['2.1', '47'], vitamin_d_ug: ['3.4', '17'],
  iodine_ug: ['120.0', '55'], zinc_mg: ['8.0', '73'], selenium_ug: ['42.5', '71'],
  choline_mg: ['260.0', '54'], dha_g: ['0.1', '50'],
};
const pregBlock = (code, known, percent, over = {}) => ({
  known, items_total: known === null ? 0 : 4, items_uncounted: 0, status: known === null ? 'NONE' : 'KNOWN',
  target: PREG_TARGETS[code], percent, ...over,
});
/** The twelve non-headline blocks of a pregnant day; a day with no entries has none known. */
const pregOthers = (status, uncounted) => Object.fromEntries(Object.entries(PREG_OTHERS).map(([code, [known, percent]]) => [
  code,
  status === 'NONE' ? pregBlock(code, null, null) : pregBlock(code, known, percent, { status, items_uncounted: uncounted }),
]));

const nut100 = (over = {}) => ({
  energy_kcal: '120', protein_g: '4.0', fat_g: '3.0', carb_g: '18.0', fiber_g: '2.5', calcium_mg: '90',
  iron_mg: '1.2', folate_ug: '30', vitamin_b12_ug: '0.2', vitamin_d_ug: '0.1', iodine_ug: '8', zinc_mg: '0.8',
  selenium_ug: '4', choline_mg: '25', dha_g: '0.01', ...over,
});
const withoutFiber = (n) => Object.fromEntries(Object.entries(n).filter(([k]) => k !== 'fiber_g'));
const meta = { provider_version: '1', category: 'food', retrieved_at: '2026-11-01T00:00:00Z', serving_g: null, density_g_per_ml: null };

export const PREGNANCY_DAY = {
  profile_version: 2,
  nutrients: fullBlocks({
    energy_kcal: pregBlock('energy_kcal', '1640.3', '73', { items_total: 4, items_uncounted: 1, status: 'PARTIAL' }),
    protein_g: pregBlock('protein_g', '48.2', '74', { items_total: 4, items_uncounted: 1, status: 'PARTIAL' }),
    fiber_g: pregBlock('fiber_g', '31.0', '103', { items_total: 4, items_uncounted: 2, status: 'PARTIAL' }),
    ...pregOthers('PARTIAL', 1),
  }),
  date: '2026-11-24', mode: 'PREGNANCY', trimester: 2, day_status: 'OPEN', sugar_status: 'PARTIAL',
  free_sugars_known_g: '12.0', items_total: 4, items_uncounted: 1,
  limit: { value_g: '50', sources: [{ title: 'WHO', url: 'https://example.test/who' }] },
  entries: [
    { id: 'p-1', consumed_at: '2026-11-24T08:10:00+01:00', items: [
      { label: 'Avena con leche', amount: '1', unit: 'cup', grams: '250', conversion: { method: 'PRESET' },
        facts: { ...meta, source: 'USDA', nutrients_per_100g: nut100() }, free_sugars_g: '2.5' },
      { label: 'Plátano', amount: '1', unit: 'piece', grams: '120', conversion: { method: 'AGENT_ESTIMATE' },
        facts: { ...meta, source: 'USDA', nutrients_per_100g: withoutFiber(nut100({ energy_kcal: '89' })) }, free_sugars_g: '0.5' },
    ] },
    { id: 'p-2', consumed_at: '2026-11-24T13:30:00+01:00', items: [
      { label: 'Lentejas con arroz', amount: '1', unit: 'plate', grams: '300', conversion: { method: 'USER_STATED' },
        facts: { ...meta, source: 'BLS', nutrients_per_100g: nut100({ energy_kcal: '110', fiber_g: '4.0' }) }, free_sugars_g: '1.0' },
      { label: 'Tarta casera', amount: '1', unit: 'slice', grams: '90', conversion: { method: 'AGENT_ESTIMATE' },
        facts: null, free_sugars_g: null },
    ] },
  ],
  attribution: ['Bundeslebensmittelschlüssel (BLS) 4.0, Max Rubner-Institut'],
};

// ----------------------------------------------------------------- periods
const pblock = (known, percent, over = {}) => ({
  known, items_total: known === null ? 0 : 2, items_uncounted: 0, status: known === null ? 'NONE' : 'KNOWN',
  target: percent === null ? null : { value: '2250', display_value: '2250', unit: 'kcal', kind: 'ABOUT' },
  percent, ...over,
});
const pavg = (known, percent, used) => ({
  average_known: known, average_percent: percent, days_used: used, left_out: { open: 1, no_entries: 0, partial: 0 },
});
const pday = (date, dayStatus, nutrients, free) => ({
  date, day_status: dayStatus, mode: 'GENERAL', trimester: null, profile_version: 2,
  free_sugars_known_g: free.known, items_uncounted: 0, nutrients: fullBlocks(nutrients), free_sugars: free,
});
const NO_FREE = { known: null, items_uncounted: 0, status: 'NONE', limit_g: null, percent: null };

export const PERIOD_THREE = {
  start: '2026-11-20', end: '2026-11-22', has_profile: true,
  days: [
    pday('2026-11-20', 'COMPLETE',
      { energy_kcal: pblock('2510', '90'), protein_g: pblock('98.4', '120'), fiber_g: pblock('24.0', '80'), fat_g: pblock('80', null) },
      { known: '17.0', items_uncounted: 0, status: 'KNOWN', limit_g: '50', percent: '34' }),
    pday('2026-11-21', 'COMPLETE',
      { energy_kcal: pblock('2240', '80'), protein_g: pblock('82', '102'), fiber_g: pblock('20.0', '67') }, NO_FREE),
    pday('2026-11-22', 'OPEN',
      { energy_kcal: pblock('1200', '53'), protein_g: pblock('40', null, { status: 'PARTIAL' }), fiber_g: pblock(null, null) },
      { known: '12.0', items_uncounted: 1, status: 'PARTIAL', limit_g: '50', percent: null }),
  ],
  averages: fullAverages({
    energy_kcal: pavg('2375', '85', 2), protein_g: pavg('90', '111', 2), fiber_g: pavg('22.0', '73', 2),
    free_sugars_g: pavg(null, null, 0), fat_g: pavg('80', null, 1),
  }),
};

// No profile: no targets or percents for any nutrient; the free-sugar limit still applies.
const stripPercents = (d) => ({
  ...d,
  nutrients: Object.fromEntries(Object.entries(d.nutrients).map(([k, b]) => [k, { ...b, target: null, percent: null }])),
});
export const PERIOD_NO_PROFILE = {
  ...PERIOD_THREE, has_profile: false, days: PERIOD_THREE.days.map(stripPercents),
  averages: Object.fromEntries(Object.entries(PERIOD_THREE.averages).map(([k, a]) => [k, { ...a, average_percent: null }])),
};

// ---- a pregnancy week ending on PREGNANCY_DAY's date
const wblock = (code, known, percent, status = 'KNOWN') => pregBlock(code, known, percent, {
  status, items_uncounted: status === 'PARTIAL' ? 1 : 0,
});
const wsugar = (known, status, percent) => ({
  known, items_uncounted: status === 'PARTIAL' ? 1 : 0, status, limit_g: '50', percent,
});
const wday = (date, dayStatus, c) => ({
  date, day_status: dayStatus, mode: 'PREGNANCY', trimester: 2, profile_version: 2,
  free_sugars_known_g: c.sugar.known, items_uncounted: c.sugar.items_uncounted,
  nutrients: fullBlocks({
    energy_kcal: wblock('energy_kcal', c.energy[0], c.energy[1], c.energy[2]),
    protein_g: wblock('protein_g', c.protein[0], c.protein[1], c.protein[2]),
    fiber_g: wblock('fiber_g', c.fiber[0], c.fiber[1], c.fiber[2]),
    ...Object.fromEntries(Object.entries(PREG_OTHERS).map(([code, [known, percent]]) => [
      code, c.empty ? wblock(code, null, null, 'NONE') : wblock(code, known, percent, c.others ?? 'KNOWN'),
    ])),
  }),
  free_sugars: c.sugar,
});
const NONE_C = { energy: [null, null, 'NONE'], protein: [null, null, 'NONE'], fiber: [null, null, 'NONE'] };
const WEEK_DAYS = [
  wday('2026-11-18', 'COMPLETE', {
    energy: ['2105', '94'], protein: ['70', '108'], fiber: ['31', '103'], sugar: wsugar('18.0', 'KNOWN', '36'),
  }),
  wday('2026-11-19', 'COMPLETE', {
    energy: ['1980', '88'], protein: ['60', '92'], fiber: ['22', '73'], sugar: wsugar('55.0', 'KNOWN', '110'),
  }),
  wday('2026-11-20', 'COMPLETE', {
    energy: ['2300', '103'], protein: ['66', '102'], fiber: ['30', '100'], sugar: wsugar('20.0', 'KNOWN', '40'),
  }),
  wday('2026-11-21', 'COMPLETE', {
    energy: ['2600', '116'], protein: ['50', '77', 'PARTIAL'], fiber: ['25', '83'], sugar: wsugar(null, 'PARTIAL', null),
    others: 'PARTIAL',
  }),
  wday('2026-11-22', 'OPEN', {
    energy: ['1500', '67'], protein: ['40', '62'], fiber: ['18', '60'], sugar: wsugar('10.0', 'KNOWN', '20'),
  }),
  wday('2026-11-23', 'NO_ENTRIES', { ...NONE_C, sugar: wsugar(null, 'NONE', null), empty: true }),
  wday('2026-11-24', 'OPEN', {
    energy: ['1640.3', '73', 'PARTIAL'], protein: ['48.2', '74', 'PARTIAL'], fiber: ['31.0', '103', 'PARTIAL'],
    sugar: wsugar('12.0', 'PARTIAL', '24'), others: 'PARTIAL',
  }),
];
const wavg = (known, percent, used) => ({
  average_known: known, average_percent: percent, days_used: used, left_out: { open: 2, no_entries: 1, partial: 1 },
});
const WEEK_AVERAGES = fullAverages({
  energy_kcal: wavg('2246.3', '100', 4), protein_g: wavg('61.5', '95', 3), fiber_g: wavg('27.0', '90', 4),
  free_sugars_g: wavg('31.0', '62', 3), fat_g: wavg('70.2', '94', 4), carb_g: wavg('260.0', null, 4),
  iron_mg: wavg('9.8', '36', 4), folate_ug: wavg('310.0', '56', 4), vitamin_d_ug: wavg('2.1', '11', 4),
  choline_mg: wavg('260.0', '54', 4), calcium_mg: wavg('1050.0', '105', 4), zinc_mg: wavg('11.2', '102', 4),
  selenium_ug: wavg('70.0', '117', 4), vitamin_b12_ug: wavg(null, null, 0), iodine_ug: wavg('120.0', '55', 2),
  dha_g: wavg('0.1', '50', 1),
});

export const PERIOD_WEEK_PREGNANCY = {
  start: '2026-11-18', end: '2026-11-24', has_profile: true, days: WEEK_DAYS, averages: WEEK_AVERAGES,
};

const shiftDate = (iso, days) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};
export const PERIOD_FOURTEEN = {
  start: '2026-11-11', end: '2026-11-24', has_profile: true,
  days: [...WEEK_DAYS.map((d) => ({ ...d, date: shiftDate(d.date, -7) })), ...WEEK_DAYS],
  averages: WEEK_AVERAGES,
};
