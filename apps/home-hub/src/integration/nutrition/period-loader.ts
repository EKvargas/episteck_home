import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import { discardBody, FETCH_TIMEOUT_MS } from '../state/fetch-timeout.ts';
import { DAY_NUTRIENTS } from './diary-contract.ts';
import { parsePeriodWire, type AveragedNutrient, type PeriodAverage, type PeriodSummary } from './period-contract.ts';
import {
  DELEGATION_HEADER,
  failedEnvelope,
  mintNutritionDelegation,
  PERSON_ID,
  readJson,
  readyEnvelope,
} from './nutrition-delegation.ts';

export interface LoadDiaryPeriodOptions {
  mode: 'MOCK' | 'LIVE';
  personId: string;
  cookieValue: string | undefined;
  bffBaseUrl: string | undefined;
  nutritionBaseUrl: string | undefined;
  fetcher: typeof fetch;
  /** First day of the window, YYYY-MM-DD. */
  start: string;
  /** Per-fetch timeout in milliseconds. Defaults to FETCH_TIMEOUT_MS. */
  timeoutMs?: number;
}

type Envelope = DataEnvelope<PeriodSummary>;

const START = /^\d{4}-\d{2}-\d{2}$/;
const failed = (code: SafeUIErrorCode): Envelope => failedEnvelope<PeriodSummary>(code);

function reject(response: Response, code: SafeUIErrorCode): Envelope {
  discardBody(response);
  return failed(code);
}

function emptyPeriod(start: string): PeriodSummary {
  const none: PeriodAverage = {
    averageKnown: null, averagePercent: null, daysUsed: 0, leftOut: { open: 0, noEntries: 0, partial: 0 },
  };
  const averages = Object.fromEntries([...DAY_NUTRIENTS, 'free_sugars_g'].map((c) => [c, none])) as Record<AveragedNutrient, PeriodAverage>;
  return { start, end: start, hasProfile: false, days: [], averages };
}

/**
 * Read one Person's day-by-day history from `start`. Same trust model as the Hoy read: one delegation,
 * one GET, never retried; the subject is the validated active context.
 */
export async function loadDiaryPeriod(o: LoadDiaryPeriodOptions): Promise<Envelope> {
  if (o.mode === 'MOCK') return readyEnvelope(emptyPeriod(o.start), 'MOCK');
  if (!o.bffBaseUrl || !o.nutritionBaseUrl) return failed('NOT_CONFIGURED');
  if (!o.cookieValue) return failed('SESSION_REQUIRED');
  if (!PERSON_ID.test(o.personId) || !START.test(o.start)) return failed('INVALID_RESPONSE');

  const minted = await mintNutritionDelegation({
    fetcher: o.fetcher,
    timeoutMs: o.timeoutMs,
    bffBaseUrl: o.bffBaseUrl,
    cookieValue: o.cookieValue,
  });
  if ('error' in minted) return failed(minted.error);

  let response: Response;
  try {
    response = await o.fetcher(
      new URL(`/diary/${encodeURIComponent(o.personId)}/period?start=${o.start}`, o.nutritionBaseUrl).toString(),
      {
        method: 'GET',
        cache: 'no-store',
        redirect: 'manual',
        signal: AbortSignal.timeout(o.timeoutMs ?? FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json', [DELEGATION_HEADER]: minted.token },
      },
    );
  } catch {
    return failed('SERVICE_UNAVAILABLE');
  }

  if (response.status === 401) return reject(response, 'SESSION_INVALID');
  if (response.status === 403) return reject(response, 'ACCESS_DENIED');
  if (response.status >= 500) return reject(response, 'SERVICE_UNAVAILABLE');
  if (response.status !== 200) return reject(response, 'INVALID_RESPONSE');

  const parsed = await readJson(response);
  if (!parsed.ok) return failed(parsed.timedOut ? 'SERVICE_UNAVAILABLE' : 'INVALID_RESPONSE');
  try {
    return readyEnvelope(parsePeriodWire(parsed.body), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE');
  }
}
