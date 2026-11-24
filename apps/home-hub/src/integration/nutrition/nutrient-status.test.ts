import assert from 'node:assert/strict';
import test from 'node:test';
import {
  barFor, dayPhase, dayState, groupWeekly, latestTarget, limitTarget, missingAmount, verdict, weeklyState,
  type Headline, type NutrientState, type Target, type Tone,
} from './nutrient-status.ts';

const MIN = { value: '65', displayValue: '65', unit: 'g', kind: 'MIN' } as const;
const ABOUT = { value: '2241.6', displayValue: '2250', unit: 'kcal', kind: 'ABOUT' } as const;
const s = (tone: Tone, word: string | null, detail: string | null = null): NutrientState => ({ tone, word, detail });
const h = (code: string, kind: Headline['kind'], tone: Tone, word: string | null): Headline => ({ code, kind, state: s(tone, word) });

test('MIN: today open is bien or en curso · faltan X; closed is bien, faltan datos or corto', () => {
  assert.deepEqual(dayState({ known: '65.0', status: 'KNOWN', target: MIN, percent: '100' }, 'OPEN_TODAY'), s('ok', 'bien'));
  assert.deepEqual(dayState({ known: '48.2', status: 'PARTIAL', target: MIN, percent: '74' }, 'OPEN_TODAY'), s('progress', 'en curso · faltan 17 g'));
  assert.deepEqual(dayState({ known: '70.0', status: 'PARTIAL', target: MIN, percent: '108' }, 'CLOSED'), s('ok', 'bien'));
  assert.deepEqual(dayState({ known: '48.2', status: 'PARTIAL', target: MIN, percent: '74' }, 'CLOSED'), s('unknown', 'faltan datos'));
  assert.deepEqual(dayState({ known: '48.2', status: 'KNOWN', target: MIN, percent: '74' }, 'CLOSED'), s('caution', 'corto'));
});
test('ABOUT: 90–110 % is bien when closed; open days only warn above 110 %', () => {
  assert.deepEqual(dayState({ known: '1640.3', status: 'KNOWN', target: ABOUT, percent: '73' }, 'OPEN_TODAY'), s('progress', 'en curso · faltan ~610 kcal'));
  assert.deepEqual(dayState({ known: '2490.0', status: 'KNOWN', target: ABOUT, percent: '111' }, 'OPEN_TODAY'), s('caution', 'por encima'));
  assert.deepEqual(dayState({ known: '2260.0', status: 'KNOWN', target: ABOUT, percent: '101' }, 'OPEN_TODAY'), s('progress', 'en curso'));
  for (const p of ['90', '110']) assert.equal(dayState({ known: '2100.0', status: 'KNOWN', target: ABOUT, percent: p }, 'CLOSED').word, 'bien');
  assert.deepEqual(dayState({ known: '1990.0', status: 'KNOWN', target: ABOUT, percent: '89' }, 'CLOSED'), s('caution', 'bajo'));
  assert.deepEqual(dayState({ known: '2490.0', status: 'PARTIAL', target: ABOUT, percent: '111' }, 'CLOSED'), s('caution', 'por encima'));
  assert.deepEqual(dayState({ known: '1790.0', status: 'PARTIAL', target: ABOUT, percent: '80' }, 'CLOSED'), s('unknown', 'faltan datos'));
  assert.deepEqual(dayState({ known: '1790.0', status: 'KNOWN', target: ABOUT, percent: null }, 'CLOSED'), s('unknown', 'faltan datos'));
});
test('limit: over is amber in any phase, partial is grey, at the limit is bien', () => {
  const L = limitTarget('50');
  assert.deepEqual(L, { value: '50', displayValue: '50', unit: 'g', kind: 'MAX' });
  for (const phase of ['OPEN_TODAY', 'CLOSED'] as const) {
    assert.deepEqual(dayState({ known: '51.0', status: 'PARTIAL', target: L, percent: null }, phase), s('caution', 'pasado del límite'));
  }
  assert.deepEqual(dayState({ known: '12.0', status: 'PARTIAL', target: L, percent: null }, 'OPEN_TODAY'), s('unknown', 'faltan datos'));
  assert.deepEqual(dayState({ known: '50.0', status: 'KNOWN', target: L, percent: null }, 'CLOSED'), s('ok', 'bien'));
});
test('no entries, no target, nothing counted and a past day left open', () => {
  assert.deepEqual(dayState({ known: null, status: 'NONE', target: MIN, percent: null }, 'NO_ENTRIES'), s('empty', 'Sin registros'));
  assert.deepEqual(dayState({ known: '58.0', status: 'KNOWN', target: null, percent: null }, 'CLOSED'), s('plain', null));
  assert.deepEqual(dayState({ known: null, status: 'PARTIAL', target: MIN, percent: null }, 'CLOSED'), s('unknown', 'faltan datos'));
  assert.deepEqual(dayState({ known: '20.0', status: 'KNOWN', target: MIN, percent: '31' }, 'OPEN_PAST'), s('unclosed', 'sin cerrar'));
});
test('dayPhase: only today is open; a past open day is OPEN_PAST', () => {
  assert.equal(dayPhase('OPEN', true), 'OPEN_TODAY');
  assert.equal(dayPhase('OPEN', false), 'OPEN_PAST');
  assert.equal(dayPhase('COMPLETE', false), 'CLOSED');
  assert.equal(dayPhase('NO_ENTRIES', true), 'NO_ENTRIES');
});
test('missingAmount uses the displayed numbers, never the raw decimals', () => {
  assert.equal(missingAmount('65', '48.2', 'g'), '17');
  assert.equal(missingAmount('2250', '1640.3', 'kcal'), '610');
  assert.equal(missingAmount('2250', '200', 'kcal'), '2.050');
  assert.equal(missingAmount('30', '9.5', 'mg'), '20,5');
  assert.equal(missingAmount('60', '59.6', 'g'), null);
  assert.equal(missingAmount('2250', '2260', 'kcal'), null);
  assert.equal(missingAmount('x', '10', 'g'), null);
  assert.equal(missingAmount('65', 'sin dato', 'g'), null);
});
test('weeklyState: 0 days, 1–2 days, judged with con N días, no target', () => {
  const IRON = { value: '27', displayValue: '27', unit: 'mg', kind: 'MIN' } as const;
  assert.deepEqual(weeklyState({ averageKnown: null, averagePercent: null, daysUsed: 0 }, IRON), s('unknown', 'faltan datos'));
  assert.deepEqual(weeklyState({ averageKnown: '120.0', averagePercent: '55', daysUsed: 2 }, IRON), s('unknown', 'pocos días (2)'));
  assert.deepEqual(weeklyState({ averageKnown: '9.8', averagePercent: '36', daysUsed: 4 }, IRON), s('caution', 'corto', 'con 4 días'));
  assert.deepEqual(weeklyState({ averageKnown: '27.5', averagePercent: '100', daysUsed: 3 }, IRON), s('ok', 'bien', 'con 3 días'));
  assert.deepEqual(weeklyState({ averageKnown: '9.8', averagePercent: null, daysUsed: 4 }, IRON), s('unknown', 'faltan datos'));
  assert.deepEqual(weeklyState({ averageKnown: '9.8', averagePercent: null, daysUsed: 5 }, null), s('plain', null));
  assert.equal(weeklyState({ averageKnown: '2400', averagePercent: '115', daysUsed: 4 }, ABOUT).word, 'por encima');
  assert.equal(weeklyState({ averageKnown: '2000', averagePercent: '85', daysUsed: 4 }, ABOUT).word, 'bajo');
  assert.equal(weeklyState({ averageKnown: '31', averagePercent: '101', daysUsed: 4 }, limitTarget('50')).word, 'pasado del límite');
});
test('barFor: tick, band and cap; an empty track without entries; no bar without a target', () => {
  assert.deepEqual(barFor(MIN, '48.2', 'OPEN_TODAY'), { value: '48.2', scale: '65', mark: 'tick' });
  assert.deepEqual(barFor(ABOUT, '1640.3', 'CLOSED'), { value: '1640.3', scale: '2241.6', mark: 'band' });
  assert.deepEqual(barFor(limitTarget('50'), '12.0', 'CLOSED'), { value: '12.0', scale: '50', mark: 'cap' });
  assert.deepEqual(barFor(MIN, null, 'NO_ENTRIES'), { value: null, scale: '65', mark: 'tick' });
  assert.deepEqual(barFor(MIN, '10', 'NO_ENTRIES'), { value: null, scale: '65', mark: 'tick' });
  assert.deepEqual(barFor(MIN, null, 'CLOSED'), { value: null, scale: '65', mark: 'tick' });
  assert.equal(barFor(null, '58.0', 'CLOSED'), null);
});
test('latestTarget takes the most recent day that has one', () => {
  const day = (target: Target) => ({ nutrients: { protein_g: { target } } });
  assert.deepEqual(latestTarget([day(ABOUT), day(MIN), day(null)], 'protein_g'), MIN);
  assert.equal(latestTarget([day(null), day(null)], 'protein_g'), null);
  assert.equal(latestTarget([day(MIN)], 'fiber_g'), null);
});
test('verdict: open day, with the singular and plural of faltar and the partial suffix', () => {
  const open = [h('energy_kcal', 'ABOUT', 'progress', 'en curso · faltan ~610 kcal'), h('protein_g', 'MIN', 'progress', 'en curso · faltan 17 g'),
    h('fiber_g', 'MIN', 'ok', 'bien'), h('free_sugars_g', 'MAX', 'unknown', 'faltan datos')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: open, uncounted: 2, self: true }),
    'Vas en camino. Te falta proteína. Faltan datos de 2 alimentos.');
  const both = [...open]; both[2] = h('fiber_g', 'MIN', 'progress', 'en curso · faltan 4 g');
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: both, uncounted: 1, self: true }),
    'Vas en camino. Te faltan proteína y fibra. Faltan datos de 1 alimento.');
});
test('verdict: no entries, sugars over the limit, energy above on an open day, no targets', () => {
  const none = [h('energy_kcal', 'ABOUT', 'empty', 'Sin registros'), h('protein_g', 'MIN', 'empty', 'Sin registros'),
    h('fiber_g', 'MIN', 'empty', 'Sin registros'), h('free_sugars_g', 'MAX', 'empty', 'Sin registros')];
  assert.equal(verdict({ phase: 'NO_ENTRIES', headline: none, uncounted: 0, self: true }), 'Aún no has anotado nada hoy.');
  const sugar = [h('energy_kcal', 'ABOUT', 'progress', 'en curso'), h('protein_g', 'MIN', 'progress', 'en curso · faltan 5 g'),
    h('fiber_g', 'MIN', 'ok', 'bien'), h('free_sugars_g', 'MAX', 'caution', 'pasado del límite')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: sugar, uncounted: 0, self: true }), 'Hoy te has pasado de azúcares libres.');
  assert.equal(verdict({ phase: 'CLOSED', headline: sugar, uncounted: 1, self: true }), 'Hoy te has pasado de azúcares libres. Faltan datos de 1 alimento.');
  const above = [h('energy_kcal', 'ABOUT', 'caution', 'por encima'), h('protein_g', 'MIN', 'ok', 'bien'),
    h('fiber_g', 'MIN', 'progress', 'en curso · faltan 4 g'), h('free_sugars_g', 'MAX', 'ok', 'bien')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: above, uncounted: 0, self: true }), 'Vas por encima en energía. Te falta fibra.');
  const plain = [h('energy_kcal', null, 'plain', null), h('protein_g', null, 'plain', null), h('fiber_g', null, 'plain', null),
    h('free_sugars_g', 'MAX', 'ok', 'bien')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: plain, uncounted: 1, self: true }), 'Día abierto. Faltan datos de 1 alimento.');
});
test('verdict: closed day lists bien, corto and por encima; all grey is just Día cerrado.', () => {
  const a = [h('energy_kcal', 'ABOUT', 'ok', 'bien'), h('protein_g', 'MIN', 'ok', 'bien'),
    h('fiber_g', 'MIN', 'caution', 'corto'), h('free_sugars_g', 'MAX', 'unknown', 'faltan datos')];
  assert.equal(verdict({ phase: 'CLOSED', headline: a, uncounted: 0, self: true }), 'Día cerrado: bien en energía y proteína; corto en fibra.');
  const b = [h('energy_kcal', 'ABOUT', 'caution', 'por encima'), h('protein_g', 'MIN', 'ok', 'bien'),
    h('fiber_g', 'MIN', 'ok', 'bien'), h('free_sugars_g', 'MAX', 'ok', 'bien')];
  assert.equal(verdict({ phase: 'CLOSED', headline: b, uncounted: 0, self: true }),
    'Día cerrado: bien en proteína, fibra y azúcares libres; por encima en energía.');
  const c = [h('energy_kcal', 'ABOUT', 'unknown', 'faltan datos'), h('protein_g', 'MIN', 'unknown', 'faltan datos'),
    h('fiber_g', 'MIN', 'unknown', 'faltan datos'), h('free_sugars_g', 'MAX', 'unknown', 'faltan datos')];
  assert.equal(verdict({ phase: 'CLOSED', headline: c, uncounted: 0, self: true }), 'Día cerrado.');
});
test('verdict: a viewer reads neutral copy', () => {
  const none = [h('energy_kcal', 'ABOUT', 'empty', 'Sin registros')];
  assert.equal(verdict({ phase: 'NO_ENTRIES', headline: none, uncounted: 0, self: false }), 'Aún no hay nada anotado hoy.');
  const sugar = [h('free_sugars_g', 'MAX', 'caution', 'pasado del límite')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: sugar, uncounted: 0, self: false }), 'Hoy se ha pasado de azúcares libres.');
  const open = [h('energy_kcal', 'ABOUT', 'progress', 'en curso'), h('protein_g', 'MIN', 'progress', 'en curso · faltan 17 g'),
    h('fiber_g', 'MIN', 'ok', 'bien'), h('free_sugars_g', 'MAX', 'unknown', 'faltan datos')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: open, uncounted: 2, self: false }), 'Va en camino. Le falta proteína. Faltan datos de 2 alimentos.');
  const above = [h('energy_kcal', 'ABOUT', 'caution', 'por encima'), h('protein_g', 'MIN', 'progress', 'en curso · faltan 1 g'),
    h('fiber_g', 'MIN', 'progress', 'en curso · faltan 4 g'), h('free_sugars_g', 'MAX', 'ok', 'bien')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: above, uncounted: 0, self: false }), 'Va por encima en energía. Le faltan proteína y fibra.');
});
test('groupWeekly: Corto lists names, the others count; empty groups are hidden', () => {
  const g = groupWeekly([
    { code: 'calcium_mg', state: s('ok', 'bien') }, { code: 'iron_mg', state: s('caution', 'corto') },
    { code: 'folate_ug', state: s('caution', 'corto') }, { code: 'vitamin_b12_ug', state: s('unknown', 'faltan datos') },
    { code: 'iodine_ug', state: s('unknown', 'pocos días (2)') }, { code: 'dha_g', state: s('plain', null) },
  ]);
  assert.deepEqual(g.map((x) => x.summary), ['Corto: hierro, folato', 'Bien: 1', 'Faltan datos: 2', 'Sin objetivo: 1']);
  assert.deepEqual(groupWeekly([{ code: 'zinc_mg', state: s('ok', 'bien') }]).map((x) => x.key), ['fine']);
});
