import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import { discardBody, FETCH_TIMEOUT_MS, isAbortError } from '../state/fetch-timeout.ts';
import { isAbsentProfileBody, parseProfileWire, type ProfileSummary } from './profile-contract.ts';

const NUTRITION_AUDIENCE = 'svc-nutrition';
const DELEGATION_HEADER = 'X-Episteck-Delegation';
const PERSON_ID = /^[A-Za-z0-9-]{1,64}$/;

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

type Envelope = DataEnvelope<ProfileSummary>;
type JsonRead = { ok: true; body: unknown } | { ok: false; timedOut: boolean };

function ready(data: ProfileSummary, environment: 'MOCK' | 'LIVE'): Envelope {
  return { delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data };
}

function failed(errorCode: SafeUIErrorCode): Envelope {
  return {
    delivery: 'ERROR',
    authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE',
    freshness: 'UNKNOWN',
    environment: 'LIVE',
    errorCode,
  };
}

async function readJson(response: Response): Promise<JsonRead> {
  try {
    return { ok: true, body: await response.json() };
  } catch (error) {
    return { ok: false, timedOut: isAbortError(error) };
  }
}

/** One delegation for one Nutrition call. Never retried, logged, or returned. */
async function mintDelegation(
  options: LoadNutritionProfileOptions & { bffBaseUrl: string; cookieValue: string },
): Promise<{ token: string } | { error: SafeUIErrorCode }> {
  let response: Response;
  try {
    response = await options.fetcher(
      new URL(`/delegation?audience=${NUTRITION_AUDIENCE}`, options.bffBaseUrl).toString(),
      {
        method: 'POST',
        cache: 'no-store',
        redirect: 'manual',
        signal: AbortSignal.timeout(options.timeoutMs ?? FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json', Cookie: `episteck_home_session=${options.cookieValue}` },
      },
    );
  } catch {
    return { error: 'SERVICE_UNAVAILABLE' };
  }
  if (response.status === 401) {
    discardBody(response);
    return { error: 'SESSION_INVALID' };
  }
  if (response.status !== 200) {
    discardBody(response);
    return { error: 'SERVICE_UNAVAILABLE' };
  }
  const parsed = await readJson(response);
  if (!parsed.ok) return { error: parsed.timedOut ? 'SERVICE_UNAVAILABLE' : 'INVALID_RESPONSE' };
  if (typeof parsed.body !== 'object' || parsed.body === null) return { error: 'INVALID_RESPONSE' };
  const { delegation, audience } = parsed.body as Record<string, unknown>;
  if (typeof delegation !== 'string' || delegation.length === 0 || audience !== NUTRITION_AUDIENCE) {
    return { error: 'INVALID_RESPONSE' };
  }
  return { token: delegation };
}

/** Cancel the unread body, then fail. */
function reject(response: Response, errorCode: SafeUIErrorCode): Envelope {
  discardBody(response);
  return failed(errorCode);
}

/**
 * Read one Person's Nutrition profile summary for the current session.
 * No actor, domain, or action input exists: Home derives the actor, Nutrition fixes
 * NUTRITION/VIEW, and the subject is the already-validated active context.
 */
export async function loadNutritionProfile(options: LoadNutritionProfileOptions): Promise<Envelope> {
  if (options.mode === 'MOCK') return ready({ presence: 'ABSENT' }, 'MOCK');
  if (!options.bffBaseUrl || !options.nutritionBaseUrl) return failed('NOT_CONFIGURED');
  if (!options.cookieValue) return failed('SESSION_REQUIRED');
  if (!PERSON_ID.test(options.personId)) return failed('INVALID_RESPONSE');

  const minted = await mintDelegation({
    ...options,
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
