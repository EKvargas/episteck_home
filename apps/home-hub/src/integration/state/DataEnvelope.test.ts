import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EnvelopeFactory } from './DataEnvelope';

test('UNKNOWN != ZERO', () => {
  const env = EnvelopeFactory.loading();
  assert.equal(env.delivery, 'LOADING');
  assert.equal(env.data, undefined);
  assert.equal(env.freshness, 'UNKNOWN');
});

test('DENIED envelope contains no data', () => {
  const env = EnvelopeFactory.denied();
  assert.equal(env.delivery, 'ERROR');
  assert.equal(env.authorization, 'DENIED');
  assert.equal(env.errorCode, 'ACCESS_DENIED');
  assert.equal(env.data, undefined);
});

test('NOT_CONFIGURED != ACCESS_DENIED', () => {
  const env = EnvelopeFactory.error('NOT_CONFIGURED');
  assert.equal(env.delivery, 'ERROR');
  assert.notEqual(env.authorization, 'DENIED');
  assert.equal(env.errorCode, 'NOT_CONFIGURED');
});

test('ERROR does not masquerade as successful READY data', () => {
  const env = EnvelopeFactory.error('SERVICE_UNAVAILABLE');
  assert.equal(env.delivery, 'ERROR');
  assert.equal(env.data, undefined);
});

test('INDETERMINATE authorization contains no protected data', () => {
  const env = EnvelopeFactory.loading();
  assert.equal(env.authorization, 'INDETERMINATE');
  assert.equal(env.data, undefined);
  
  const env2 = EnvelopeFactory.error('SERVICE_UNAVAILABLE');
  assert.equal(env2.authorization, 'INDETERMINATE');
  assert.equal(env2.data, undefined);
});

test('unsafe arbitrary upstream error text is not part of the UI-safe error contract', () => {
  // @ts-expect-error - testing invalid string
  const env = EnvelopeFactory.error('arbitrary upstream error text');
  assert.equal(env.errorCode as unknown as string, 'arbitrary upstream error text');
});
