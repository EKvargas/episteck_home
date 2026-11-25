import { unstable_rethrow } from 'next/navigation';
import { NutrientPanel } from '@/components/features/nutrition/NutrientPanel';
import {
  nutrientDetailOutcome, toNutrientDetailModel, type DetailCode, type NutrientDetailModel,
} from '@/components/features/nutrition/nutrient-detail-model';
import { RangeLinks } from '@/components/features/nutrition/PeriodPanel';
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
  console.info(`nutrition.nutrient outcome=${outcome}`);
}

type Resolved = { model: NutrientDetailModel; chip: ProfileChip };

async function resolvePanel(searchParams: SearchParams, code: DetailCode, range: RangeDays): Promise<Resolved> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') return { model: { kind: 'SESSION' }, chip: UNKNOWN_CHIP };
  if (subject.status === 'UNAVAILABLE') return { model: { kind: 'UNAVAILABLE' }, chip: UNKNOWN_CHIP };
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    return { model: { kind: 'LOADING' }, chip: UNKNOWN_CHIP };
  }
  // One mint and one period read for the chosen range; the header chip comes from the same payload.
  const envelope = await readDiaryPeriod(subject.context, range);
  const model = toNutrientDetailModel(envelope, code, subject.self, subject.linkPerson);
  return { model, chip: model.kind === 'DETAIL' && envelope.data ? chipFromPeriod(envelope.data) : UNKNOWN_CHIP };
}

export async function LiveNutrientPanel({ searchParams, code, range }: {
  searchParams: SearchParams; code: DetailCode; range: RangeDays;
}) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let resolved: Resolved;
  try {
    resolved = await resolvePanel(searchParams, code, range);
  } catch (error) {
    unstable_rethrow(error);
    resolved = { model: { kind: 'UNAVAILABLE' }, chip: UNKNOWN_CHIP };
  }
  logOutcome(nutrientDetailOutcome(resolved.model));
  const person = typeof searchParams.person === 'string' ? searchParams.person : null;
  // "Actualizado" and the refresh only over data that read: a state message carries its own action.
  const updatedAt = resolved.model.kind === 'DETAIL' ? berlinClock(new Date()) : null;
  return (
    <>
      <NutritionHeader view="detail" chip={resolved.chip} updatedAt={updatedAt} />
      <RangeLinks range={range} path={`/nutrition/nutriente/${code}`} param="rango" person={person} />
      <NutrientPanel model={resolved.model} signInHref={signInHref} />
    </>
  );
}
