import { redirect } from 'next/navigation';
import { getBootstrapForRequest } from '@/integration/home/bootstrap.server';
import { hoyRedirectPath } from '@/integration/nutrition/nutrition-href';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionDemoCluster } from './NutritionDemoCluster';

export const dynamic = 'force-dynamic';

type SearchParams = Record<string, string | string[] | undefined>;

export default async function NutritionPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  if (SERVER_CONFIGURATION.mode === 'MOCK') return <NutritionDemoCluster />;

  // The bootstrap is cached per request and shared with the layout. A dead session already got
  // the layout's one redirect to /login, so only a READY session is sent on to Hoy.
  const [params, bootstrap] = await Promise.all([searchParams, getBootstrapForRequest()]);
  if (bootstrap.delivery !== 'READY') return null;
  redirect(hoyRedirectPath(params));
}
