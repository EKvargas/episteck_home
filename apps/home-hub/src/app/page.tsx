import { Suspense } from 'react';
import { NutritionActions } from '@/components/features/nutrition/NutritionActions';
import { TodayPanel } from '@/components/features/nutrition/TodayPanel';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import HomeDemo from './HomeDemo';
import { HomeNutritionLinks } from './HomeNutritionLinks';
import { LiveTodayPanel } from './nutrition/hoy/LiveTodayPanel';
import { NutritionHeader } from './nutrition/NutritionHeader';
import styles from './nutrition/page.module.css';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function HomePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (SERVER_CONFIGURATION.mode === 'MOCK') return <HomeDemo />;

  const params = await searchParams;
  return (
    <div className={styles.nutritionCanvas}>
      <NutritionHeader view="home" />
      <Suspense
        key={JSON.stringify(params.person ?? null)}
        fallback={<TodayPanel model={{ kind: 'LOADING' }} signInHref="" compact />}
      >
        <LiveTodayPanel searchParams={params} compact />
      </Suspense>
      <HomeNutritionLinks />
      <NutritionActions />
    </div>
  );
}
