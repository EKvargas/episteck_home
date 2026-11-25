import { notFound } from 'next/navigation';
import { Suspense } from 'react';
import { detailCode } from '@/components/features/nutrition/nutrient-detail-model';
import { NutrientPanel } from '@/components/features/nutrition/NutrientPanel';
import { RangeLinks } from '@/components/features/nutrition/PeriodPanel';
import { parseRange } from '@/integration/nutrition/period-range';
import { UNKNOWN_CHIP } from '@/integration/nutrition/profile-chip';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionHeader } from '../../NutritionHeader';
import styles from '../../page.module.css';
import { LiveNutrientPanel } from '../LiveNutrientPanel';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function NutrientPage({ params, searchParams }: {
  params: Promise<{ code: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const code = detailCode((await params).code);
  if (code === null) notFound();

  if (SERVER_CONFIGURATION.mode === 'MOCK') {
    return (
      <div className={`${styles.nutritionCanvas} ${styles.column}`}>
        <NutrientPanel model={{ kind: 'NOT_CONFIGURED' }} signInHref="" />
      </div>
    );
  }

  const query = await searchParams;
  const range = parseRange(query.rango);
  const person = typeof query.person === 'string' ? query.person : null;
  return (
    <div className={`${styles.nutritionCanvas} ${styles.column}`}>
      {/* Keyed on the raw selector, the nutrient and the range so one panel never paints under another's. */}
      <Suspense
        key={JSON.stringify([query.person ?? null, code, range])}
        fallback={
          <>
            <NutritionHeader view="detail" chip={UNKNOWN_CHIP} updatedAt={null} />
            <RangeLinks range={range} path={`/nutrition/nutriente/${code}`} param="rango" person={person} />
            <NutrientPanel model={{ kind: 'LOADING' }} signInHref="" />
          </>
        }
      >
        <LiveNutrientPanel searchParams={query} code={code} range={range} />
      </Suspense>
    </div>
  );
}
