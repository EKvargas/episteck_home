import { test } from 'node:test';
import assert from 'node:assert/strict';
import { contextAccessibleLabel } from './contextLabel.ts';

test('context labels describe Person, Care, and Circle options consistently', () => {
  assert.equal(contextAccessibleLabel('Erick', 'PERSONAL'), 'Erick Personal Context');
  assert.equal(contextAccessibleLabel('Ana', 'CARE_FOR_ANOTHER_PERSON'), 'Ana Care Context');
  assert.equal(contextAccessibleLabel('Family', 'FAMILY'), 'Family Circle Context');
});
