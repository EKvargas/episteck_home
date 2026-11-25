import { Suspense } from 'react';
import { TodayPanel } from '@/components/features/nutrition/TodayPanel';
import { WeeklyPanel } from '@/components/features/nutrition/WeeklyPanel';
import { WEEKLY_TITLE } from '@/components/features/nutrition/weekly-model';
import { UNKNOWN_CHIP } from '@/integration/nutrition/profile-chip';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionHeader } from '../NutritionHeader';
import styles from '../page.module.css';
import { LiveTodayPanel } from './LiveTodayPanel';
import { LiveWeeklyPanel } from './LiveWeeklyPanel';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function TodayPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (SERVER_CONFIGURATION.mode === 'MOCK') {
    return (
      <div className={styles.nutritionCanvas}>
        <TodayPanel model={{ kind: 'NOT_CONFIGURED' }} signInHref="" />
      </div>
    );
  }

  const params = await searchParams;
  return (
    <div className={styles.nutritionCanvas}>
      {/* Keyed on the raw selector so one subject's panel can never paint under another's. */}
      <Suspense
        key={JSON.stringify(params.person ?? null)}
        fallback={
          <>
            <NutritionHeader view="diary" chip={UNKNOWN_CHIP} updatedAt={null} />
            <TodayPanel model={{ kind: 'LOADING' }} signInHref="" />
          </>
        }
      >
        <LiveTodayPanel
          searchParams={params}
          weekly={(
            <Suspense fallback={<WeeklyPanel model={{ kind: 'LOADING' }} title={WEEKLY_TITLE} />}>
              <LiveWeeklyPanel searchParams={params} />
            </Suspense>
          )}
        />
      </Suspense>
    </div>
  );
}
