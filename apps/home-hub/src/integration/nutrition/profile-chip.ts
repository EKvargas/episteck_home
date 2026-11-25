import type { DiaryDay } from './diary-contract.ts';
import { TRIMESTERS } from './nutrition-format.ts';
import type { PeriodSummary } from './period-contract.ts';
import type { ProfileRead } from './profile-contract.ts';

/** What the header chip says about the profile, read only from the page's own payload. */
export type ProfileChip = { kind: 'MODE'; label: string } | { kind: 'PROFILE' } | { kind: 'NONE' };

/** Nothing known yet (loading, error, help): the chip reads "Perfil". */
export const UNKNOWN_CHIP: ProfileChip = { kind: 'PROFILE' };

export function chipFrom(mode: 'GENERAL' | 'PREGNANCY', trimester: 1 | 2 | 3 | null, hasProfile: boolean): ProfileChip {
  if (mode === 'PREGNANCY' && trimester !== null) return { kind: 'MODE', label: `Embarazo · ${TRIMESTERS[trimester]}` };
  return hasProfile ? { kind: 'PROFILE' } : { kind: 'NONE' };
}

export function chipFromDay(day: DiaryDay): ProfileChip {
  return chipFrom(day.mode, day.trimester, day.profileVersion !== null);
}

export function chipFromPeriod(summary: PeriodSummary): ProfileChip {
  const last = summary.days.at(-1);
  return chipFrom(last?.mode ?? 'GENERAL', last?.trimester ?? null, summary.hasProfile);
}

export function chipFromProfile(read: ProfileRead): ProfileChip {
  return read.presence === 'PRESENT' ? chipFrom(read.profile.mode, read.profile.trimester, true) : { kind: 'NONE' };
}
