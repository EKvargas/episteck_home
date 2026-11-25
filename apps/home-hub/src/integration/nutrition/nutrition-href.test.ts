import assert from 'node:assert/strict';
import test from 'node:test';
import { hoyRedirectPath, nutritionHref, nutritionPath } from './nutrition-href.ts';

test('nutritionHref puts person first and keeps the basePath', () => {
  assert.equal(nutritionHref('/nutrition/nutriente/iron_mg', 'PSN-00007', { rango: '7' }), '/app/nutrition/nutriente/iron_mg?person=PSN-00007&rango=7');
  assert.equal(nutritionHref('/nutrition/ayuda', null), '/app/nutrition/ayuda');
  assert.equal(nutritionPath('/nutrition/dias', 'PSN-00001', { dias: '3' }), '/nutrition/dias?person=PSN-00001&dias=3');
});

test('hoyRedirectPath keeps every person value and drops the rest', () => {
  assert.equal(hoyRedirectPath({}), '/nutrition/hoy');
  assert.equal(hoyRedirectPath({ person: 'PSN-00007', dias: '3' }), '/nutrition/hoy?person=PSN-00007');
  assert.equal(hoyRedirectPath({ person: ['a', 'b'] }), '/nutrition/hoy?person=a&person=b');
});
