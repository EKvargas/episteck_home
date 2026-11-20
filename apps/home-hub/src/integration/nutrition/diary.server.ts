import 'server-only';
import { cookies } from 'next/headers';
import { assertIssuedContext, type F3ActiveContext } from '../home/active-context';
import { SERVER_CONFIGURATION } from '../state/Environment.server';
import { loadDiaryToday } from './diary-loader';

/** Server-only: read the active Person's food diary for today for this request. */
export async function readDiaryToday(context: F3ActiveContext) {
  assertIssuedContext(context);
  const cookieValue = SERVER_CONFIGURATION.mode === 'LIVE'
    ? (await cookies()).get('episteck_home_session')?.value
    : undefined;
  return loadDiaryToday({
    mode: SERVER_CONFIGURATION.mode,
    personId: context.personId,
    cookieValue,
    bffBaseUrl: SERVER_CONFIGURATION.bffBaseUrl,
    nutritionBaseUrl: SERVER_CONFIGURATION.nutritionBaseUrl,
    fetcher: fetch,
  });
}
