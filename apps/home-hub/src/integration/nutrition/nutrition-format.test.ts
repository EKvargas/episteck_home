import assert from 'node:assert/strict';
import test from 'node:test';
import {
  TRIMESTERS, amount, fieldLabel, longDate, nutrientLabel, shortDate, targetValue, unitLabel, weekdayDay,
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
