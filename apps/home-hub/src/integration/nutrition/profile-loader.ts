import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import { discardBody, FETCH_TIMEOUT_MS } from '../state/fetch-timeout.ts';
import {
  DELEGATION_HEADER,
  failedEnvelope,
  mintNutritionDelegation,
  PERSON_ID,
  readJson,
  readyEnvelope,
} from './nutrition-delegation.ts';
import { isAbsentProfileBody, parseProfileWire, type ProfileRead } from './profile-contract.ts';

export interface LoadNutritionProfileOptions {
  mode: 'MOCK' | 'LIVE';
  personId: string;
  cookieValue: string | undefined;
  bffBaseUrl: string | undefined;
  nutritionBaseUrl: string | undefined;
  fetcher: typeof fetch;
  /** Per-fetch timeout in milliseconds. Defaults to FETCH_TIMEOUT_MS. */
  timeoutMs?: number;
}

type Envelope = DataEnvelope<ProfileRead>;

const ready = (data: ProfileRead, environment: 'MOCK' | 'LIVE'): Envelope => readyEnvelope(data, environment);
const failed = (errorCode: SafeUIErrorCode): Envelope => failedEnvelope<ProfileRead>(errorCode);

/** Cancel the unread body, then fail. */
function reject(response: Response, errorCode: SafeUIErrorCode): Envelope {
  discardBody(response);
  return failed(errorCode);
}

/**
 * Read one Person's Nutrition profile for the current session.
 * No actor, domain, or action input exists: Home derives the actor, Nutrition fixes
 * NUTRITION/VIEW, and the subject is the already-validated active context.
 */
export async function loadNutritionProfile(options: LoadNutritionProfileOptions): Promise<Envelope> {
  if (options.mode === 'MOCK') return ready({ presence: 'ABSENT' }, 'MOCK');
  if (!options.bffBaseUrl || !options.nutritionBaseUrl) return failed('NOT_CONFIGURED');
  if (!options.cookieValue) return failed('SESSION_REQUIRED');
  if (!PERSON_ID.test(options.personId)) return failed('INVALID_RESPONSE');

  const minted = await mintNutritionDelegation({
    fetcher: options.fetcher,
    timeoutMs: options.timeoutMs,
    bffBaseUrl: options.bffBaseUrl,
    cookieValue: options.cookieValue,
  });
  if ('error' in minted) return failed(minted.error);

  let response: Response;
  try {
    response = await options.fetcher(
      new URL(`/profile/${encodeURIComponent(options.personId)}`, options.nutritionBaseUrl).toString(),
      {
        method: 'GET',
        cache: 'no-store',
        redirect: 'manual',
        signal: AbortSignal.timeout(options.timeoutMs ?? FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json', [DELEGATION_HEADER]: minted.token },
      },
    );
  } catch {
    return failed('SERVICE_UNAVAILABLE');
  }

  if (response.status === 403) return reject(response, 'ACCESS_DENIED');
  if (response.status === 401) return reject(response, 'SESSION_INVALID');
  if (response.status >= 500) return reject(response, 'SERVICE_UNAVAILABLE');
  if (response.status !== 200 && response.status !== 404) return reject(response, 'INVALID_RESPONSE');

  const parsed = await readJson(response);
  if (!parsed.ok) return failed(parsed.timedOut ? 'SERVICE_UNAVAILABLE' : 'INVALID_RESPONSE');
  if (response.status === 404) {
    return isAbsentProfileBody(parsed.body) ? ready({ presence: 'ABSENT' }, 'LIVE') : failed('INVALID_RESPONSE');
  }
  try {
    return ready(parseProfileWire(parsed.body), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE');
  }
}
