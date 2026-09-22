import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ResourceScope } from './ResourceScope';

test('PERSON scope cannot silently become CIRCLE', () => {
  const scope: ResourceScope = {
    type: 'PERSON',
    personId: '123',
    displayName: 'Ana',
  };
  
  // @ts-expect-error - personId cannot be used for circle
  void ({ type: 'CIRCLE', personId: '123', displayName: 'Ana' } as ResourceScope);
  
  assert.equal(scope.type, 'PERSON');
});

test('CIRCLE scope cannot silently become PERSON', () => {
  const scope: ResourceScope = {
    type: 'CIRCLE',
    circleId: 'fam',
    displayName: 'CIR-fam',
  };
  
  // @ts-expect-error - circleId cannot be used for person
  void ({ type: 'PERSON', circleId: 'fam', displayName: 'Ana' } as ResourceScope);
  
  assert.equal(scope.type, 'CIRCLE');
});
