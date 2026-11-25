import assert from 'node:assert/strict';
import test from 'node:test';
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
