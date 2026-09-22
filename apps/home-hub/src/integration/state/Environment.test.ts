import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateEnvironmentMode } from './Environment';

test('throws in production if MOCK is configured', () => {
  assert.throws(() => validateEnvironmentMode('MOCK', true), /FATAL/);
  assert.throws(() => validateEnvironmentMode(undefined, true), /FATAL/);
});

test('allows LIVE in production', () => {
  assert.equal(validateEnvironmentMode('LIVE', true), 'LIVE');
});

test('defaults to MOCK in non-production if not LIVE', () => {
  assert.equal(validateEnvironmentMode('MOCK', false), 'MOCK');
  assert.equal(validateEnvironmentMode(undefined, false), 'MOCK');
  assert.equal(validateEnvironmentMode('ANYTHING', false), 'MOCK');
});

test('allows LIVE in non-production', () => {
  assert.equal(validateEnvironmentMode('LIVE', false), 'LIVE');
});
