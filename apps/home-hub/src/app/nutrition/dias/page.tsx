import { Suspense } from 'react';
import { PeriodPanel, RangeLinks } from '@/components/features/nutrition/PeriodPanel';
import { parseRange } from '@/integration/nutrition/period-range';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionHeader } from '../NutritionHeader';
import styles from '../page.module.css';
import { LivePeriodPanel } from './LivePeriodPanel';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function DaysPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (SERVER_CONFIGURATION.mode === 'MOCK') {
    return (
      <div className={styles.nutritionCanvas}>
        <PeriodPanel model={{ kind: 'NOT_CONFIGURED' }} signInHref="" />
      </div>
    );
  }

  const params = await searchParams;
  const range = parseRange(params.dias);
  const person = typeof params.person === 'string' ? params.person : null;
  return (
    <div className={styles.nutritionCanvas}>
      <NutritionHeader view="days" />
      <RangeLinks range={range} person={person} />
      {/* Keyed on the raw selector and the range so one subject's or window's panel never paints under another's. */}
      <Suspense
        key={JSON.stringify([params.person ?? null, range])}
        fallback={<PeriodPanel model={{ kind: 'LOADING' }} signInHref="" />}
      >
        <LivePeriodPanel searchParams={params} range={range} />
      </Suspense>
    </div>
  );
}
