import 'server-only';
import { cookies } from 'next/headers';
import type { DataEnvelope } from '../state/DataEnvelope';
import { assertIssuedContext, type F3ActiveContext } from '../home/active-context';
import { SERVER_CONFIGURATION } from '../state/Environment.server';
import type { PeriodSummary } from './period-contract';
import { loadDiaryPeriod } from './period-loader';
import { periodStart, type RangeDays } from './period-range';

/** Server-only: read the active Person's last `days` days (ending today in Berlin) for this request. */
export async function readDiaryPeriod(context: F3ActiveContext, days: RangeDays): Promise<DataEnvelope<PeriodSummary>> {
  assertIssuedContext(context);
  const cookieValue = SERVER_CONFIGURATION.mode === 'LIVE'
    ? (await cookies()).get('episteck_home_session')?.value
    : undefined;
  return loadDiaryPeriod({
    mode: SERVER_CONFIGURATION.mode,
    personId: context.personId,
    cookieValue,
    bffBaseUrl: SERVER_CONFIGURATION.bffBaseUrl,
    nutritionBaseUrl: SERVER_CONFIGURATION.nutritionBaseUrl,
    fetcher: fetch,
    start: periodStart(days, new Date()),
  });
}
