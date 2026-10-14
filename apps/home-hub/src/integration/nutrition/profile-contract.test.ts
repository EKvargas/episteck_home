import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isAbsentProfileBody, parseProfileWire, ProfileContractError } from './profile-contract.ts';

const general = { context: 'GENERAL', target_source: 'USER_CONFIGURED', targets: { energy_kcal: 2000, protein_g: 70.5 } };

test('maps a numeric-target profile to the three summary fields only', () => {
  assert.deepEqual(parseProfileWire(general), {
    presence: 'PRESENT', context: 'GENERAL', targetSource: 'USER_CONFIGURED', targetCount: 2,
  });
});

test('accepts the decimal-string targets that pregnancy profiles store', () => {
  const pregnancy = {
    context: 'PREGNANCY', target_source: 'REFERENCE_TARGET',
    targets: { calcium_mg: '1000', iron_mg: '27', folate_ug: '600', energy_kcal: '2300.5' },
    targets_detail: [{ secret: true }], preferences: 'no fish', dislikes: 'okra',
    explicit_intolerances: 'lactose', pregnancy_stage: 'T2',
  };
  const summary = parseProfileWire(pregnancy);
  assert.deepEqual(summary, { presence: 'PRESENT', context: 'PREGNANCY', targetSource: 'REFERENCE_TARGET', targetCount: 4 });
  assert.equal(JSON.stringify(summary).includes('fish'), false);
  assert.equal(JSON.stringify(summary).includes('lactose'), false);
});

test('an empty targets object is a valid present profile with zero targets', () => {
  assert.equal((parseProfileWire({ ...general, targets: {} }) as { targetCount: number }).targetCount, 0);
});

const invalid: Array<[string, unknown]> = [
  ['null body', null],
  ['array body', [general]],
  ['missing context', { target_source: 'X', targets: {} }],
  ['lowercase context', { ...general, context: 'general' }],
  ['overlong context', { ...general, context: 'A'.repeat(33) }],
  ['non-string target_source', { ...general, target_source: 3 }],
  ['missing targets', { context: 'GENERAL', target_source: 'X' }],
  ['array targets', { ...general, targets: [1, 2] }],
  ['non-finite target', { ...general, targets: { a: Number.POSITIVE_INFINITY } }],
  ['non-numeric string target', { ...general, targets: { a: '12abc' } }],
  ['overlong string target', { ...general, targets: { a: '1'.repeat(33) } }],
  ['object target', { ...general, targets: { a: { v: 1 } } }],
  ['too many targets', { ...general, targets: Object.fromEntries(Array.from({ length: 65 }, (_, i) => [`t${i}`, i])) }],
];

for (const [name, body] of invalid) {
  test(`rejects ${name}`, () => {
    assert.throws(() => parseProfileWire(body), ProfileContractError);
  });
}

test('recognizes only the exact absent-profile body', () => {
  assert.equal(isAbsentProfileBody({ detail: 'no profile' }), true);
  assert.equal(isAbsentProfileBody({ detail: 'Not Found' }), false);
  assert.equal(isAbsentProfileBody({ detail: 'no profile', extra: 1 }), false);
  assert.equal(isAbsentProfileBody(null), false);
});

test('ProfileContractError carries its own name', () => {
  try { parseProfileWire(null); assert.fail('expected a throw'); } catch (error) {
    assert.ok(error instanceof ProfileContractError);
    assert.equal((error as Error).name, 'ProfileContractError');
  }
});

for (const [name, value] of [
  ['exponent overflow string', '1e999'],
  ['Infinity string', 'Infinity'],
  ['hex string', '0x10'],
  ['NaN string', 'NaN'],
] as const) {
  test(`rejects ${name} as a target value`, () => {
    assert.throws(() => parseProfileWire({ ...general, targets: { a: value } }), ProfileContractError);
  });
}

test('a __proto__ key is plain data: no prototype pollution, object values rejected', () => {
  const base = '{"context":"GENERAL","target_source":"USER_CONFIGURED","targets":';
  assert.throws(() => parseProfileWire(JSON.parse(`${base}{"__proto__":{"polluted":true}}}`)), ProfileContractError);
  const summary = parseProfileWire(JSON.parse(`${base}{"__proto__":1}}`));
  assert.equal(summary.presence === 'PRESENT' && summary.targetCount, 1);
  assert.equal(({} as Record<string, unknown>).polluted, undefined);
});
