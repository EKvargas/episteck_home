import assert from 'node:assert/strict';
import test from 'node:test';
import type { BootstrapContext } from '../home/Viewer.ts';
import { isIssuedContext } from '../home/active-context.ts';
import { pickSubject } from './live-subject.ts';

const bootstrap: BootstrapContext = {
  viewer: { personId: 'PSN-00001', displayName: 'Viewer' },
  personContexts: [
    { type: 'PERSON', personId: 'PSN-00001', displayName: 'Viewer' },
    { type: 'PERSON', personId: 'PSN-00002', displayName: 'Care subject' },
  ],
  careRelationships: [{ subjectPersonId: 'PSN-00002', relationshipType: 'CAREGIVER' }],
  circleContexts: [{ type: 'CIRCLE', circleId: 'CIR-00001', displayName: 'Circle' }],
};

test('no person parameter resolves to self with a name', () => {
  const picked = pickSubject(bootstrap, {});
  assert.equal(picked.context.personId, 'PSN-00001');
  assert.equal(picked.subjectName, 'Viewer');
  assert.equal(isIssuedContext(picked.context), true);
  assert.equal(picked.stale, false);
});

test('a navigable care subject resolves with its own display name', () => {
  const picked = pickSubject(bootstrap, { person: 'PSN-00002' });
  assert.equal(picked.context.personId, 'PSN-00002');
  assert.equal(picked.subjectName, 'Care subject');
});

const stale: Array<[string, Record<string, string | string[] | undefined>]> = [
  ['unknown', { person: 'PSN-00999' }],
  ['circle', { person: 'CIR-00001' }],
  ['empty', { person: '' }],
  ['duplicated', { person: ['PSN-00002', 'PSN-00001'] }],
  ['malformed', { person: 'broken' }],
  ['oversized', { person: `PSN-${'9'.repeat(5000)}` }],
  ['trailing newline', { person: 'PSN-00002\n' }],
];
for (const [name, params] of stale) {
  test(`${name} selection falls back to self and is marked stale`, () => {
    const picked = pickSubject(bootstrap, params);
    assert.equal(picked.context.personId, 'PSN-00001');
    assert.equal(picked.stale, true);
  });
}

test('actor-shaped query noise cannot change the subject', () => {
  const picked = pickSubject(bootstrap, { person: 'PSN-00001', actorPersonId: 'PSN-00999', actor: 'PSN-00002' });
  assert.equal(picked.context.personId, 'PSN-00001');
  assert.equal(picked.stale, false);
});
