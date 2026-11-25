import { unstable_rethrow } from 'next/navigation';
import { WeeklyPanel } from '@/components/features/nutrition/WeeklyPanel';
import { toWeeklyPanelModel, weeklyOutcome, type WeeklyPanelModel } from '@/components/features/nutrition/weekly-model';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { readDiaryPeriod } from '@/integration/nutrition/period.server';

type SearchParams = Record<string, string | string[] | undefined>;

export const WEEKLY_TITLE = 'Vitaminas y minerales · últimos 7 días';

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, dates, or values. */
function logOutcome(outcome: string) {
  console.info(`nutrition.week outcome=${outcome}`);
}

async function resolveModel(searchParams: SearchParams): Promise<WeeklyPanelModel> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') return { kind: 'SESSION' };
  if (subject.status === 'UNAVAILABLE') return { kind: 'UNAVAILABLE' };
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    return { kind: 'LOADING' };
  }
  return toWeeklyPanelModel(await readDiaryPeriod(subject.context, 7), subject.linkPerson);
}

/** One mint and one 7-day period read. It never touches the day panel, so each degrades on its own. */
export async function LiveWeeklyPanel({ searchParams }: { searchParams: SearchParams }) {
  let model: WeeklyPanelModel;
  try {
    model = await resolveModel(searchParams);
  } catch (error) {
    unstable_rethrow(error);
    model = { kind: 'UNAVAILABLE' };
  }
  logOutcome(weeklyOutcome(model));
  return <WeeklyPanel model={model} title={WEEKLY_TITLE} />;
}
