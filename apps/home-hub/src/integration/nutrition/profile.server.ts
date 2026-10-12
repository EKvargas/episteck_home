import 'server-only';
import { cookies } from 'next/headers';
import type { F3ActiveContext } from '../home/active-context';
import { SERVER_CONFIGURATION } from '../state/Environment.server';
import { loadNutritionProfile } from './profile-loader';

/** Server-only: read the active Person's Nutrition profile summary for this request. */
export async function readNutritionProfile(context: F3ActiveContext) {
  const cookieValue = SERVER_CONFIGURATION.mode === 'LIVE'
    ? (await cookies()).get('episteck_home_session')?.value
    : undefined;
  return loadNutritionProfile({
    mode: SERVER_CONFIGURATION.mode,
    personId: context.personId,
    cookieValue,
    bffBaseUrl: SERVER_CONFIGURATION.bffBaseUrl,
    nutritionBaseUrl: SERVER_CONFIGURATION.nutritionBaseUrl,
    fetcher: fetch,
  });
}
