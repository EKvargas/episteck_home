import assert from 'node:assert/strict';
import test from 'node:test';
import { parseDayWire } from './diary-contract.ts';
import { parsePeriodWire } from './period-contract.ts';
import { parseProfileWire } from './profile-contract.ts';
import { chipFrom, chipFromDay, chipFromPeriod, chipFromProfile, UNKNOWN_CHIP } from './profile-chip.ts';
import {
  EMPTY_DAY, NO_PROFILE_DAY, PERIOD_NO_PROFILE, PERIOD_THREE, PERIOD_WEEK_PREGNANCY, PREGNANCY_DAY, PRESENT,
} from '../../../test-support/nutrition-fixtures.mjs';

test('chipFrom: pregnancy with a trimester shows it; a profile is Perfil; none is NONE', () => {
  assert.deepEqual(chipFrom('PREGNANCY', 2, true), { kind: 'MODE', label: 'Embarazo · 2.º trimestre' });
  assert.deepEqual(chipFrom('PREGNANCY', 1, true), { kind: 'MODE', label: 'Embarazo · 1.er trimestre' });
  assert.deepEqual(chipFrom('PREGNANCY', 3, true), { kind: 'MODE', label: 'Embarazo · 3.er trimestre' });
  assert.deepEqual(chipFrom('GENERAL', null, true), { kind: 'PROFILE' });
  assert.deepEqual(chipFrom('GENERAL', null, false), { kind: 'NONE' });
});

test('chipFrom: pregnancy without a trimester is never guessed', () => {
  assert.deepEqual(chipFrom('PREGNANCY', null, true), { kind: 'PROFILE' });
  assert.deepEqual(chipFrom('PREGNANCY', null, false), { kind: 'NONE' });
});

test('the unknown chip reads Perfil', () => {
  assert.deepEqual(UNKNOWN_CHIP, { kind: 'PROFILE' });
});

test('chips from the three payloads', () => {
  assert.deepEqual(chipFromDay(parseDayWire(PREGNANCY_DAY)), { kind: 'MODE', label: 'Embarazo · 2.º trimestre' });
  assert.deepEqual(chipFromDay(parseDayWire(NO_PROFILE_DAY)), { kind: 'NONE' });
  assert.deepEqual(chipFromDay(parseDayWire(EMPTY_DAY)), { kind: 'PROFILE' });
  assert.deepEqual(chipFromPeriod(parsePeriodWire(PERIOD_WEEK_PREGNANCY)), { kind: 'MODE', label: 'Embarazo · 2.º trimestre' });
  assert.deepEqual(chipFromPeriod(parsePeriodWire(PERIOD_THREE)), { kind: 'PROFILE' });
  assert.deepEqual(chipFromPeriod(parsePeriodWire(PERIOD_NO_PROFILE)), { kind: 'NONE' });
  assert.deepEqual(chipFromProfile(parseProfileWire(PRESENT)), { kind: 'MODE', label: 'Embarazo · 2.º trimestre' });
  assert.deepEqual(chipFromProfile({ presence: 'ABSENT' }), { kind: 'NONE' });
});
