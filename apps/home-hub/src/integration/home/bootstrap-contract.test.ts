import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseBootstrapWire } from './bootstrap-contract.ts';

const fixture = {
  version: 1,
  viewer: { personId: 'PSN-00001', displayName: 'Erick' },
  personContexts: [
    { type: 'PERSON', personId: 'PSN-00001', displayName: 'Erick' },
    { type: 'PERSON', personId: 'PSN-00007', displayName: 'Ana' },
  ],
  circleContexts: [{ type: 'CIRCLE', circleId: 'CIR-00001', displayName: 'Family' }],
  careRelationships: [
    { subjectPersonId: 'PSN-00007', relationshipType: 'CAREGIVER' },
  ],
};

test('accepts and reconstructs the F2a wire v1 fixture', () => {
  assert.deepEqual(parseBootstrapWire(fixture), {
    viewer: fixture.viewer,
    personContexts: fixture.personContexts,
    circleContexts: fixture.circleContexts,
    careRelationships: fixture.careRelationships,
  });
});

test('drops all wire fields outside the serialized bootstrap allowlist', () => {
  const payload = JSON.parse(JSON.stringify({
    ...fixture,
    viewer: { ...fixture.viewer, token: 'secret' },
    sessionId: 'sid-secret',
    grants: ['admin'],
    principal: 'principal-secret',
    bffUrl: 'http://private.invalid',
    cookie: 'cookie-secret',
  }));
  const serialized = JSON.stringify(parseBootstrapWire(payload));
  assert.deepEqual(Object.keys(JSON.parse(serialized)).sort(), [
    'careRelationships', 'circleContexts', 'personContexts', 'viewer',
  ]);
  for (const secret of ['secret', 'sid-secret', 'admin', 'principal-secret', 'private.invalid', 'cookie-secret']) {
    assert.equal(serialized.includes(secret), false);
  }
});

test('rejects malformed wire data as a whole', () => {
  const malformed = JSON.parse(JSON.stringify(fixture));
  malformed.careRelationships[0].relationshipType = 'FRIEND';
  assert.throws(() => parseBootstrapWire(malformed));
});

test('rejects identifiers with trailing line terminators', () => {
  const personId = JSON.parse(JSON.stringify(fixture));
  personId.viewer.personId = 'PSN-00001\n';
  assert.throws(() => parseBootstrapWire(personId));

  const circleId = JSON.parse(JSON.stringify(fixture));
  circleId.circleContexts[0].circleId = 'CIR-00001\n';
  assert.throws(() => parseBootstrapWire(circleId));
});

test('rejects dangling, duplicate, and non-viewer-first contexts', () => {
  const dangling = JSON.parse(JSON.stringify(fixture));
  dangling.personContexts.pop();
  assert.throws(() => parseBootstrapWire(dangling));

  const duplicate = JSON.parse(JSON.stringify(fixture));
  duplicate.personContexts.push(duplicate.personContexts[1]);
  assert.throws(() => parseBootstrapWire(duplicate));

  const notViewerFirst = JSON.parse(JSON.stringify(fixture));
  notViewerFirst.personContexts.reverse();
  assert.throws(() => parseBootstrapWire(notViewerFirst));
});
