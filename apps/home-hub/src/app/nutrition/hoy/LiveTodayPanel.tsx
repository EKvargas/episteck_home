import { unstable_rethrow } from 'next/navigation';
import { TodayPanel } from '@/components/features/nutrition/TodayPanel';
import { todayOutcome, toTodayPanelModel, type TodayPanelModel } from '@/components/features/nutrition/today-panel-model';
import { readDiaryToday } from '@/integration/nutrition/diary.server';
import { berlinClock } from '@/integration/nutrition/nutrition-format';
import { chipFromDay, UNKNOWN_CHIP, type ProfileChip } from '@/integration/nutrition/profile-chip';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionHeader } from '../NutritionHeader';

type SearchParams = Record<string, string | string[] | undefined>;

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, URLs, or tokens. */
function logOutcome(outcome: string) {
  console.info(`nutrition.today outcome=${outcome}`);
}

type Resolved = { model: TodayPanelModel; chip: ProfileChip };

async function resolvePanel(searchParams: SearchParams): Promise<Resolved> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') return { model: { kind: 'SESSION' }, chip: UNKNOWN_CHIP };
  if (subject.status === 'UNAVAILABLE') return { model: { kind: 'UNAVAILABLE' }, chip: UNKNOWN_CHIP };
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    return { model: { kind: 'LOADING' }, chip: UNKNOWN_CHIP };
  }
  const envelope = await readDiaryToday(subject.context);
  const model = toTodayPanelModel(envelope);
  // The chip comes from this same payload: no second mint or read.
  return { model, chip: model.kind === 'TODAY' && envelope.data ? chipFromDay(envelope.data) : UNKNOWN_CHIP };
}

export async function LiveTodayPanel({ searchParams, compact }: { searchParams: SearchParams; compact?: boolean }) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let resolved: Resolved;
  try {
    resolved = await resolvePanel(searchParams);
  } catch (error) {
    unstable_rethrow(error); // let Next's own redirect and dynamic-rendering signals through
    resolved = { model: { kind: 'UNAVAILABLE' }, chip: UNKNOWN_CHIP };
  }
  logOutcome(todayOutcome(resolved.model));
  const panel = <TodayPanel model={resolved.model} signInHref={signInHref} compact={compact} />;
  if (compact) return panel;
  return (
    <>
      <NutritionHeader view="diary" chip={resolved.chip} updatedAt={berlinClock(new Date())} />
      {panel}
    </>
  );
}
