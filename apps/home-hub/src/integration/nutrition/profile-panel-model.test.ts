import assert from 'node:assert/strict';
import test from 'node:test';
import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import type { Mode, ProfileRead } from './profile-contract.ts';
import { humanizeCode, outcomeLabel, toProfilePanelModel } from './profile-panel-model.ts';

function present(mode: Mode, itemCount: number): ProfileRead {
  const item = { nutrient: 'energy_kcal', value: '2000', displayValue: '2000', unit: 'kcal', kind: 'ABOUT' as const, sourceOrg: 'o', sourceRef: 'r', explanation: 'e' };
  return {
    presence: 'PRESENT',
    profile: {
      version: 1, validFrom: '2026-11-24', origin: 'PROFILE', onboarded: true, mode, dueDate: null, trimester: null,
      inputs: {
        birthDate: null, age: null, sex: null, heightCm: null, weightKg: null, weightMeasuredOn: null,
        activityPal: null, trainingSessionsPerWeek: null, trainingNote: null, goal: null, prePregnancyWeightKg: null,
      },
      food: { preferences: null, dislikes: null, intolerances: null },
      targets: { method: 'M', on: '2026-11-24', items: Array.from({ length: itemCount }, () => item), missing: [] },
      history: [],
    },
  };
}

const ready = (data: ProfileRead): DataEnvelope<ProfileRead> =>
  ({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE', data });
const error = (errorCode: SafeUIErrorCode): DataEnvelope<ProfileRead> =>
  ({ delivery: 'ERROR', authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE', errorCode });

test('PRESENT maps known codes to labels and keeps only the summary', () => {
  assert.deepEqual(
    toProfilePanelModel(ready(present('PREGNANCY', 4)), 'Erick'),
    { kind: 'PRESENT', subjectName: 'Erick', contextLabel: 'Pregnancy', targetSourceLabel: 'Reference targets', targetCount: 4 },
  );
});

test('an unknown future mode falls back to a readable label instead of failing', () => {
  const model = toProfilePanelModel(ready(present('POST_PARTUM' as Mode, 1)), null);
  assert.equal(model.kind === 'PRESENT' && model.contextLabel, 'Post partum');
  assert.equal(model.kind === 'PRESENT' && model.targetSourceLabel, 'Reference targets');
});

test('a PRESENT profile with zero targets stays PRESENT (not ABSENT)', () => {
  const model = toProfilePanelModel(ready(present('GENERAL', 0)), 'Erick');
  assert.equal(model.kind, 'PRESENT');
  assert.equal(model.kind === 'PRESENT' && model.targetCount, 0);
});

test('authorized ABSENT is its own state', () => {
  assert.deepEqual(toProfilePanelModel(ready({ presence: 'ABSENT' }), 'Erick'), { kind: 'ABSENT', subjectName: 'Erick' });
});

const errors: Array<[SafeUIErrorCode, string]> = [
  ['ACCESS_DENIED', 'DENIED'],
  ['SESSION_INVALID', 'SESSION'],
  ['SESSION_REQUIRED', 'SESSION'],
  ['SERVICE_UNAVAILABLE', 'UNAVAILABLE'],
  ['OFFLINE', 'UNAVAILABLE'],
  ['RESOURCE_NOT_AVAILABLE', 'UNAVAILABLE'],
  ['INVALID_RESPONSE', 'INVALID'],
  ['NOT_CONFIGURED', 'NOT_CONFIGURED'],
];
for (const [code, kind] of errors) {
  test(`${code} maps to ${kind}`, () => {
    assert.equal(toProfilePanelModel(error(code), 'Erick').kind, kind);
  });
}

test('every SafeUIErrorCode is covered by the table above', async () => {
  const { isSafeUIErrorCode } = await import('../state/SafeUIErrorCode.ts');
  for (const [code] of errors) assert.equal(isSafeUIErrorCode(code), true);
  assert.equal(errors.length, 8);
});

test('an envelope that is READY but not GRANTED, or has no data, fails safe to UNAVAILABLE', () => {
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'INDETERMINATE', freshness: 'FRESH', environment: 'LIVE', data: { presence: 'ABSENT' } }, 'E').kind, 'UNAVAILABLE');
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'LIVE' }, 'E').kind, 'UNAVAILABLE');
  assert.equal(toProfilePanelModel({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }, 'E').kind, 'UNAVAILABLE');
});

test('a READY envelope that is not LIVE fails safe to UNAVAILABLE (no mock in LIVE)', () => {
  assert.equal(toProfilePanelModel({ delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment: 'MOCK', data: { presence: 'ABSENT' } }, 'E').kind, 'UNAVAILABLE');
});

test('a LOADING envelope maps to LOADING', () => {
  assert.equal(toProfilePanelModel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }, 'E').kind, 'LOADING');
});

test('outcomeLabel is a fixed vocabulary that never carries identifiers or codes from the body', () => {
  assert.equal(outcomeLabel(ready({ presence: 'ABSENT' })), 'ABSENT');
  assert.equal(outcomeLabel(ready(present('PREGNANCY', 2))), 'PRESENT');
  for (const [code] of errors) assert.equal(outcomeLabel(error(code)), code);
  assert.equal(outcomeLabel({ delivery: 'LOADING', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }), 'UNEXPECTED');
  assert.equal(outcomeLabel({ delivery: 'ERROR', authorization: 'INDETERMINATE', freshness: 'UNKNOWN', environment: 'LIVE' }), 'UNEXPECTED');
});

test('the model never carries target values or raw upstream fields', () => {
  const model = toProfilePanelModel(ready(present('GENERAL', 2)), 'E');
  assert.deepEqual(Object.keys(model).sort(), ['contextLabel', 'kind', 'subjectName', 'targetCount', 'targetSourceLabel']);
});

test('humanizeCode', () => {
  assert.equal(humanizeCode('SOME_CODE'), 'Some code');
  assert.equal(humanizeCode('X'), 'X');
});
