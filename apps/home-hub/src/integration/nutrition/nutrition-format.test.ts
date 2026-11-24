import assert from 'node:assert/strict';
import test from 'node:test';
import {
  TRIMESTERS, amount, measurement, fieldLabel, longDate, nutrientLabel, shortDate, targetValue, unitLabel, weekdayDay,
  nutrientName, unitOf, spanishList, weekdayInitial, dayOfMonth, berlinClock,
} from './nutrition-format.ts';

test('amount groups thousands and rounds by unit', () => {
  assert.equal(amount('1640.3', 'kcal'), '1.640');
  assert.equal(amount('2250', 'kcal'), '2.250');
  assert.equal(amount('72.4', 'g'), '72');
  assert.equal(amount('2.35', 'mg'), '2,4');
  assert.equal(amount('17.0', 'g'), '17');
});
test('targetValue signs by kind and spells µg', () => {
  assert.equal(targetValue('ABOUT', '2250', 'kcal'), '≈ 2.250 kcal');
  assert.equal(targetValue('MIN', '60', 'g'), '≥ 60 g');
  assert.equal(targetValue('MAX', '50', 'g'), '≤ 50 g');
  assert.equal(targetValue('MIN', '550', 'ug'), '≥ 550 µg');
});
test('a display value that is not a plain decimal is shown as given, never NaN', () => {
  assert.equal(targetValue('ABOUT', 'x', 'kcal'), '≈ x kcal');
  assert.equal(amount('1e3 aprox', 'g'), '1e3 aprox');
});
test('dates never shift by a day', () => {
  assert.equal(shortDate('2026-11-24'), '24 nov');
  assert.equal(longDate('2027-04-12'), '12 abr 2027');
  assert.equal(weekdayDay('2026-11-20'), 'Vie 20');
});
test('labels fall back to a readable form', () => {
  assert.equal(nutrientLabel('iodine_ug'), 'Yodo');
  assert.equal(nutrientLabel('magnesium_mg'), 'Magnesium');
  assert.equal(fieldLabel('pre_pregnancy_weight_kg'), 'peso antes del embarazo');
  assert.equal(fieldLabel('shoe_size'), 'Shoe size');
  assert.equal(unitLabel('ug'), 'µg');
  assert.equal(unitLabel('mg'), 'mg');
  assert.equal(TRIMESTERS[2], '2.º trimestre');
});

test('measurement uses es-ES, at most one decimal, no forced decimals', () => {
  assert.equal(measurement('62.5'), '62,5');
  assert.equal(measurement('165'), '165');
  assert.equal(measurement('64.0'), '64');
  assert.equal(measurement('1234.5'), '1.234,5');
  assert.equal(measurement('abc'), 'abc');
});

test('sentence names keep acronyms and the vitamin letter', () => {
  assert.equal(nutrientName('energy_kcal'), 'energía');
  assert.equal(nutrientName('vitamin_d_ug'), 'vitamina D');
  assert.equal(nutrientName('dha_g'), 'DHA');
  assert.equal(nutrientName('free_sugars_g'), 'azúcares libres');
});
test('units, lists, weekday initials and the Berlin clock', () => {
  assert.equal(unitOf('folate_ug'), 'ug');
  assert.equal(unitOf('energy_kcal'), 'kcal');
  assert.equal(spanishList([]), '');
  assert.equal(spanishList(['a']), 'a');
  assert.equal(spanishList(['proteína', 'fibra']), 'proteína y fibra');
  assert.equal(spanishList(['a', 'b', 'c']), 'a, b y c');
  assert.equal(weekdayInitial('2026-11-18'), 'X');
  assert.equal(weekdayInitial('2026-11-20'), 'V');
  assert.equal(dayOfMonth('2026-11-08'), '8');
  assert.equal(berlinClock(new Date('2026-11-24T13:05:00Z')), '14:05');
  assert.equal(berlinClock(new Date('2026-07-01T13:05:00Z')), '15:05');
});
