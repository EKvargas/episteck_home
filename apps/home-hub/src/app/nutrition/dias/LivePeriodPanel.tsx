import { unstable_rethrow } from 'next/navigation';
import { PeriodPanel, RangeLinks } from '@/components/features/nutrition/PeriodPanel';
import { periodOutcome, toPeriodPanelModel, type PeriodPanelModel } from '@/components/features/nutrition/period-panel-model';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { berlinClock } from '@/integration/nutrition/nutrition-format';
import { readDiaryPeriod } from '@/integration/nutrition/period.server';
import { chipFromPeriod, UNKNOWN_CHIP, type ProfileChip } from '@/integration/nutrition/profile-chip';
import type { RangeDays } from '@/integration/nutrition/period-range';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionHeader } from '../NutritionHeader';

type SearchParams = Record<string, string | string[] | undefined>;

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, dates, or values. */
function logOutcome(outcome: string) {
  console.info(`nutrition.period outcome=${outcome}`);
}

type Resolved = { model: PeriodPanelModel; chip: ProfileChip };

async function resolvePanel(searchParams: SearchParams, range: RangeDays): Promise<Resolved> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') return { model: { kind: 'SESSION' }, chip: UNKNOWN_CHIP };
  if (subject.status === 'UNAVAILABLE') return { model: { kind: 'UNAVAILABLE' }, chip: UNKNOWN_CHIP };
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    return { model: { kind: 'LOADING' }, chip: UNKNOWN_CHIP };
  }
  const envelope = await readDiaryPeriod(subject.context, range);
  const model = toPeriodPanelModel(envelope, range);
  // The chip comes from this same payload: no second mint or read.
  return { model, chip: model.kind === 'PERIOD' && envelope.data ? chipFromPeriod(envelope.data) : UNKNOWN_CHIP };
}

export async function LivePeriodPanel({ searchParams, range }: { searchParams: SearchParams; range: RangeDays }) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let resolved: Resolved;
  try {
    resolved = await resolvePanel(searchParams, range);
  } catch (error) {
    unstable_rethrow(error);
    resolved = { model: { kind: 'UNAVAILABLE' }, chip: UNKNOWN_CHIP };
  }
  logOutcome(periodOutcome(resolved.model));
  const person = typeof searchParams.person === 'string' ? searchParams.person : null;
  return (
    <>
      <NutritionHeader view="days" chip={resolved.chip} updatedAt={berlinClock(new Date())} />
      <RangeLinks range={range} person={person} />
      <PeriodPanel model={resolved.model} signInHref={signInHref} />
    </>
  );
}
