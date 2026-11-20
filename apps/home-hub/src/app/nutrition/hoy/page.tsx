import { Suspense } from 'react';
import { TodayPanel } from '@/components/features/nutrition/TodayPanel';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import styles from '../page.module.css';
import { LiveTodayPanel } from './LiveTodayPanel';

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
        fallback={<TodayPanel model={{ kind: 'LOADING' }} signInHref="" />}
      >
        <LiveTodayPanel searchParams={params} />
      </Suspense>
    </div>
  );
}
