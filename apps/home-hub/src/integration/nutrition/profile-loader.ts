import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
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
}

type Envelope = DataEnvelope<ProfileSummary>;

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

async function readJson(response: Response): Promise<{ ok: true; body: unknown } | { ok: false }> {
  try {
    return { ok: true, body: await response.json() };
  } catch {
    return { ok: false };
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
        headers: { Accept: 'application/json', Cookie: `episteck_home_session=${options.cookieValue}` },
      },
    );
  } catch {
    return { error: 'SERVICE_UNAVAILABLE' };
  }
  if (response.status === 401) return { error: 'SESSION_INVALID' };
  if (response.status !== 200) return { error: 'SERVICE_UNAVAILABLE' };
  const parsed = await readJson(response);
  if (!parsed.ok || typeof parsed.body !== 'object' || parsed.body === null) return { error: 'INVALID_RESPONSE' };
  const { delegation, audience } = parsed.body as Record<string, unknown>;
  if (typeof delegation !== 'string' || delegation.length === 0 || audience !== NUTRITION_AUDIENCE) {
    return { error: 'INVALID_RESPONSE' };
  }
  return { token: delegation };
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
        headers: { Accept: 'application/json', [DELEGATION_HEADER]: minted.token },
      },
    );
  } catch {
    return failed('SERVICE_UNAVAILABLE');
  }

  if (response.status === 403) return failed('ACCESS_DENIED');
  if (response.status === 401) return failed('SESSION_INVALID');
  if (response.status >= 500) return failed('SERVICE_UNAVAILABLE');
  if (response.status !== 200 && response.status !== 404) return failed('INVALID_RESPONSE');

  const parsed = await readJson(response);
  if (!parsed.ok) return failed('INVALID_RESPONSE');
  if (response.status === 404) {
    return isAbsentProfileBody(parsed.body) ? ready({ presence: 'ABSENT' }, 'LIVE') : failed('INVALID_RESPONSE');
  }
  try {
    return ready(parseProfileWire(parsed.body), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE');
  }
}
