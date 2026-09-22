import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSafeUIErrorCode } from './SafeUIErrorCode';

test('normalizeSafeUIErrorCode normalizes unknown strings to INVALID_RESPONSE', () => {
  assert.equal(normalizeSafeUIErrorCode('upstream secret/error body'), 'INVALID_RESPONSE');
  assert.equal(normalizeSafeUIErrorCode(null), 'INVALID_RESPONSE');
  assert.equal(normalizeSafeUIErrorCode(undefined), 'INVALID_RESPONSE');
  assert.equal(normalizeSafeUIErrorCode({ foo: 'bar' }), 'INVALID_RESPONSE');
});

test('normalizeSafeUIErrorCode preserves valid SafeUIErrorCodes', () => {
  assert.equal(normalizeSafeUIErrorCode('ACCESS_DENIED'), 'ACCESS_DENIED');
  assert.equal(normalizeSafeUIErrorCode('SESSION_REQUIRED'), 'SESSION_REQUIRED');
});
