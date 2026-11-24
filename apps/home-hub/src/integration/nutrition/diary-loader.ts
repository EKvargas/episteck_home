import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import { discardBody, FETCH_TIMEOUT_MS } from '../state/fetch-timeout.ts';
import { parseDayWire, type DiaryDay } from './diary-contract.ts';
import {
  DELEGATION_HEADER,
  failedEnvelope,
  mintNutritionDelegation,
  PERSON_ID,
  readJson,
  readyEnvelope,
} from './nutrition-delegation.ts';

export interface LoadDiaryTodayOptions {
  mode: 'MOCK' | 'LIVE';
  personId: string;
  cookieValue: string | undefined;
  bffBaseUrl: string | undefined;
  nutritionBaseUrl: string | undefined;
  fetcher: typeof fetch;
  /** Per-fetch timeout in milliseconds. Defaults to FETCH_TIMEOUT_MS. */
  timeoutMs?: number;
}

type Envelope = DataEnvelope<DiaryDay>;

const failed = (code: SafeUIErrorCode): Envelope => failedEnvelope<DiaryDay>(code);

function reject(response: Response, code: SafeUIErrorCode): Envelope {
  discardBody(response);
  return failed(code);
}

function emptyDay(): DiaryDay {
  const none = { known: null, itemsTotal: 0, itemsUncounted: 0, status: 'NONE', target: null, percent: null } as const;
  return {
    profileVersion: null,
    nutrients: { energy_kcal: none, protein_g: none, fiber_g: none },
    date: '', mode: 'GENERAL', trimester: null, dayStatus: 'NO_ENTRIES', sugarStatus: 'NONE',
    freeSugarsKnownG: null, itemsTotal: 0, itemsUncounted: 0, limit: null, entries: [], attribution: [],
  };
}

/**
 * Read one Person's food diary for today. Same trust model as the profile read: Home mints one
 * delegation, Nutrition fixes the domain and action, the subject is the validated active context.
 */
export async function loadDiaryToday(o: LoadDiaryTodayOptions): Promise<Envelope> {
  if (o.mode === 'MOCK') return readyEnvelope(emptyDay(), 'MOCK');
  if (!o.bffBaseUrl || !o.nutritionBaseUrl) return failed('NOT_CONFIGURED');
  if (!o.cookieValue) return failed('SESSION_REQUIRED');
  if (!PERSON_ID.test(o.personId)) return failed('INVALID_RESPONSE');

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
      new URL(`/diary/${encodeURIComponent(o.personId)}/days/today`, o.nutritionBaseUrl).toString(),
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
    return readyEnvelope(parseDayWire(parsed.body), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE');
  }
}
