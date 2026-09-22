import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getEnvironmentMode } from './Environment';

const originalEnv = process.env;

test('MOCK/LIVE mode cannot be browser-controlled', () => {
  process.env = { ...originalEnv, HOME_HUB_DATA_MODE: 'LIVE' };
  assert.equal(getEnvironmentMode(), 'LIVE');
  
  process.env = { ...originalEnv, HOME_HUB_DATA_MODE: 'MOCK' };
  assert.equal(getEnvironmentMode(), 'MOCK');
  
  process.env = originalEnv;
});

test('throws in production if MOCK is configured', () => {
  process.env = { ...originalEnv, NODE_ENV: 'production', HOME_HUB_DATA_MODE: 'MOCK' };
  assert.throws(() => getEnvironmentMode(), /FATAL/);
  
  process.env = originalEnv;
});

test('allows LIVE in production', () => {
  process.env = { ...originalEnv, NODE_ENV: 'production', HOME_HUB_DATA_MODE: 'LIVE' };
  assert.equal(getEnvironmentMode(), 'LIVE');
  
  process.env = originalEnv;
});
