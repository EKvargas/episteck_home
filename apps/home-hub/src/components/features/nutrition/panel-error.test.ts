import assert from 'node:assert/strict';
import test from 'node:test';
import type { SafeUIErrorCode } from '../../../integration/state/SafeUIErrorCode.ts';
import { panelError } from './panel-error.ts';

test('every error code maps to one panel kind', () => {
  assert.equal(panelError('ACCESS_DENIED'), 'DENIED');
  assert.equal(panelError('SESSION_INVALID'), 'SESSION');
  assert.equal(panelError('SESSION_REQUIRED'), 'SESSION');
  assert.equal(panelError('NOT_CONFIGURED'), 'NOT_CONFIGURED');
  assert.equal(panelError('INVALID_RESPONSE'), 'INVALID');
  for (const code of ['RESOURCE_NOT_AVAILABLE', 'SERVICE_UNAVAILABLE', 'OFFLINE'] as const) {
    assert.equal(panelError(code), 'UNAVAILABLE');
  }
  assert.equal(panelError(undefined), 'UNAVAILABLE');
});

test('a code the type does not know still reads as unavailable at runtime', () => {
  // tsc pins the switch as exhaustive; a value from outside the type falls back safely.
  assert.equal(panelError('SOMETHING_NEW' as unknown as SafeUIErrorCode), 'UNAVAILABLE');
});
