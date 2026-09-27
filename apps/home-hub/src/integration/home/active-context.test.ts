import assert from 'node:assert/strict';
import test from 'node:test';
import type { BootstrapContext } from './Viewer.ts';
import { resolveRequestedPerson } from './active-context.ts';

const bootstrap: BootstrapContext = {
  viewer: { personId: 'PSN-00001', displayName: 'Viewer' },
  personContexts: [
    { type: 'PERSON', personId: 'PSN-00001', displayName: 'Viewer' },
    { type: 'PERSON', personId: 'PSN-00002', displayName: 'Care subject' },
  ],
  careRelationships: [{ subjectPersonId: 'PSN-00002', relationshipType: 'CAREGIVER' }],
  circleContexts: [{ type: 'CIRCLE', circleId: 'CIR-00001', displayName: 'Circle' }],
};

function resolve(query: string, current = bootstrap) {
  return resolveRequestedPerson(new URLSearchParams(query), current);
}

test('missing and explicit self resolve to the viewer, independent of array position', () => {
  const reversed = { ...bootstrap, personContexts: [...bootstrap.personContexts].reverse() };
  assert.deepEqual(resolve('', reversed), { status: 'CURRENT', activeContext: { kind: 'PERSON', personId: 'PSN-00001' } });
  assert.deepEqual(resolve('person=PSN-00001'), { status: 'CURRENT', activeContext: { kind: 'PERSON', personId: 'PSN-00001' } });
});

test('a current care subject is navigable without an authorization result', () => {
  assert.deepEqual(resolve('person=PSN-00002'), { status: 'CURRENT', activeContext: { kind: 'PERSON', personId: 'PSN-00002' } });
});

test('unknown, malformed, Circle, and duplicate selections are stale', () => {
  for (const query of [
    'person=PSN-00999', 'person=psn-00002', 'person=PSN-2', 'person=CIR-00001',
    'person=%7B%22personId%22%3A%22PSN-00002%22%7D', 'person=PSN-00002%0A',
    'person=PSN-00002&person=PSN-00001', 'person=',
  ]) {
    assert.deepEqual(resolve(query), { status: 'STALE_CONTEXT', activeContext: { kind: 'PERSON', personId: 'PSN-00001' } }, query);
  }
});

test('a previous-session URL resolves against the current viewer and topology', () => {
  const nextSession: BootstrapContext = {
    viewer: { personId: 'PSN-00003', displayName: 'Next viewer' },
    personContexts: [{ type: 'PERSON', personId: 'PSN-00003', displayName: 'Next viewer' }],
    careRelationships: [], circleContexts: [],
  };
  assert.deepEqual(resolve('person=PSN-00002', nextSession), { status: 'STALE_CONTEXT', activeContext: { kind: 'PERSON', personId: 'PSN-00003' } });
});

test('each URL resolves independently; query noise cannot nominate an actor', () => {
  assert.equal(resolve('person=PSN-00001').activeContext.personId, 'PSN-00001');
  assert.equal(resolve('person=PSN-00002').activeContext.personId, 'PSN-00002');
  assert.deepEqual(resolve('person=PSN-00002&actorPersonId=PSN-00999'), resolve('person=PSN-00002'));
});
