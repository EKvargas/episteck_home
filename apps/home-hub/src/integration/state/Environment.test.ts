import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateEnvironmentMode } from './Environment.ts';

test('throws in production if MOCK is configured', () => {
  assert.throws(() => validateEnvironmentMode('MOCK', true), /FATAL/);
  assert.throws(() => validateEnvironmentMode(undefined, true), /FATAL/);
});

test('allows LIVE in production', () => {
  assert.equal(validateEnvironmentMode('LIVE', true), 'LIVE');
});

test('defaults to MOCK only when development mode is omitted', () => {
  assert.equal(validateEnvironmentMode('MOCK', false), 'MOCK');
  assert.equal(validateEnvironmentMode(undefined, false), 'MOCK');
  assert.throws(() => validateEnvironmentMode('ANYTHING', false), /HOME_HUB_DATA_MODE/);
  assert.throws(() => validateEnvironmentMode('ANYTHING', true), /HOME_HUB_DATA_MODE/);
});

test('allows LIVE in non-production', () => {
  assert.equal(validateEnvironmentMode('LIVE', false), 'LIVE');
});
