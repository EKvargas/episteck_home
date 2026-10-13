import { Suspense } from 'react';
import { ProfilePanel } from '@/components/features/nutrition/ProfilePanel';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { LiveProfilePanel } from './LiveProfilePanel';
import { NutritionDemoCluster } from './NutritionDemoCluster';
import { NutritionHeader } from './NutritionHeader';
import styles from './page.module.css';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function NutritionPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (SERVER_CONFIGURATION.mode === 'MOCK') return <NutritionDemoCluster />;

  const params = await searchParams;
  return (
    <div className={styles.nutritionCanvas}>
      <NutritionHeader />
      {/* A div, not <main>: AppShell already renders the page's one main landmark. */}
      <div className={styles.grid}>
        {/* Keyed on the raw selector so one subject's panel can never paint under another's. */}
        <Suspense
          key={JSON.stringify(params.person ?? null)}
          fallback={<ProfilePanel model={{ kind: 'LOADING', subjectName: null }} signInHref="" />}
        >
          <LiveProfilePanel searchParams={params} />
        </Suspense>
      </div>
    </div>
  );
}
