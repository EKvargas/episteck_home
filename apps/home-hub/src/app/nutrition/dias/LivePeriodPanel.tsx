import { unstable_rethrow } from 'next/navigation';
import { PeriodPanel } from '@/components/features/nutrition/PeriodPanel';
import { periodOutcome, toPeriodPanelModel, type PeriodPanelModel } from '@/components/features/nutrition/period-panel-model';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { readDiaryPeriod } from '@/integration/nutrition/period.server';
import type { RangeDays } from '@/integration/nutrition/period-range';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';

type SearchParams = Record<string, string | string[] | undefined>;

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, dates, or values. */
function logOutcome(outcome: string) {
  console.info(`nutrition.period outcome=${outcome}`);
}

async function resolvePanel(searchParams: SearchParams, range: RangeDays): Promise<PeriodPanelModel> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') return { kind: 'SESSION' };
  if (subject.status === 'UNAVAILABLE') return { kind: 'UNAVAILABLE' };
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    return { kind: 'LOADING' };
  }
  return toPeriodPanelModel(await readDiaryPeriod(subject.context, range), range);
}

export async function LivePeriodPanel({ searchParams, range }: { searchParams: SearchParams; range: RangeDays }) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let model: PeriodPanelModel;
  try {
    model = await resolvePanel(searchParams, range);
  } catch (error) {
    unstable_rethrow(error);
    model = { kind: 'UNAVAILABLE' };
  }
  logOutcome(periodOutcome(model));
  return <PeriodPanel model={model} signInHref={signInHref} />;
}
