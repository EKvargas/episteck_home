import { Suspense } from 'react';
import { ProfilePanel } from '@/components/features/nutrition/ProfilePanel';
import { UNKNOWN_CHIP } from '@/integration/nutrition/profile-chip';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionHeader } from '../NutritionHeader';
import styles from '../page.module.css';
import { LiveProfilePanel } from './LiveProfilePanel';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function ProfilePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (SERVER_CONFIGURATION.mode === 'MOCK') {
    return (
      <div className={styles.nutritionCanvas}>
        <ProfilePanel model={{ kind: 'NOT_CONFIGURED' }} signInHref="" />
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
            <NutritionHeader view="profile" chip={UNKNOWN_CHIP} updatedAt={null} />
            <div className={styles.grid}>
              <ProfilePanel model={{ kind: 'LOADING', subjectName: null }} signInHref="" />
            </div>
          </>
        }
      >
        <LiveProfilePanel searchParams={params} />
      </Suspense>
    </div>
  );
}
