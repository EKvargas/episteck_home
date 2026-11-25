import assert from 'node:assert/strict';
import test from 'node:test';
import { isLiveRoute } from './live-routes.ts';

test('isLiveRoute: exact entries, and prefix entries ending in /', () => {
  assert.equal(isLiveRoute('/nutrition/nutriente/iron_mg', ['/nutrition/nutriente/']), true);
  assert.equal(isLiveRoute('/nutrition/nutriente', ['/nutrition/nutriente/']), false);
  assert.equal(isLiveRoute('/nutrition/pregnancy', ['/nutrition', '/nutrition/hoy']), false);
  assert.equal(isLiveRoute('/nutrition/hoy', ['/nutrition', '/nutrition/hoy']), true);
});
