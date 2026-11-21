import { unstable_rethrow } from 'next/navigation';
import { TodayPanel } from '@/components/features/nutrition/TodayPanel';
import { todayOutcome, toTodayPanelModel, type TodayPanelModel } from '@/components/features/nutrition/today-panel-model';
import { readDiaryToday } from '@/integration/nutrition/diary.server';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';

type SearchParams = Record<string, string | string[] | undefined>;

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, URLs, or tokens. */
function logOutcome(outcome: string) {
  console.info(`nutrition.today outcome=${outcome}`);
}

async function resolvePanel(searchParams: SearchParams): Promise<TodayPanelModel> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') return { kind: 'SESSION' };
  if (subject.status === 'UNAVAILABLE') return { kind: 'UNAVAILABLE' };
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    return { kind: 'LOADING' };
  }
  return toTodayPanelModel(await readDiaryToday(subject.context));
}

export async function LiveTodayPanel({ searchParams, compact }: { searchParams: SearchParams; compact?: boolean }) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let model: TodayPanelModel;
  try {
    model = await resolvePanel(searchParams);
  } catch (error) {
    unstable_rethrow(error); // let Next's own redirect and dynamic-rendering signals through
    model = { kind: 'UNAVAILABLE' };
  }
  logOutcome(todayOutcome(model));
  return <TodayPanel model={model} signInHref={signInHref} compact={compact} />;
}
