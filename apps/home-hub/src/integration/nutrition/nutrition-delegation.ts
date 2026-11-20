import type { DataEnvelope } from '../state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import { discardBody, FETCH_TIMEOUT_MS, isAbortError } from '../state/fetch-timeout.ts';

export const NUTRITION_AUDIENCE = 'svc-nutrition';
export const DELEGATION_HEADER = 'X-Episteck-Delegation';
export const PERSON_ID = /^[A-Za-z0-9-]{1,64}$/;

export type JsonRead = { ok: true; body: unknown } | { ok: false; timedOut: boolean };

export function readyEnvelope<T>(data: T, environment: 'MOCK' | 'LIVE'): DataEnvelope<T> {
  return { delivery: 'READY', authorization: 'GRANTED', freshness: 'FRESH', environment, data };
}

export function failedEnvelope<T>(errorCode: SafeUIErrorCode): DataEnvelope<T> {
  return {
    delivery: 'ERROR',
    authorization: errorCode === 'ACCESS_DENIED' ? 'DENIED' : 'INDETERMINATE',
    freshness: 'UNKNOWN',
    environment: 'LIVE',
    errorCode,
  };
}

export async function readJson(response: Response): Promise<JsonRead> {
  try {
    return { ok: true, body: await response.json() };
  } catch (error) {
    return { ok: false, timedOut: isAbortError(error) };
  }
}

/** One delegation for one Nutrition call. Never retried, logged, or returned. */
export async function mintNutritionDelegation(o: {
  fetcher: typeof fetch;
  bffBaseUrl: string;
  cookieValue: string;
  timeoutMs?: number;
}): Promise<{ token: string } | { error: SafeUIErrorCode }> {
  let response: Response;
  try {
    response = await o.fetcher(
      new URL(`/delegation?audience=${NUTRITION_AUDIENCE}`, o.bffBaseUrl).toString(),
      {
        method: 'POST',
        cache: 'no-store',
        redirect: 'manual',
        signal: AbortSignal.timeout(o.timeoutMs ?? FETCH_TIMEOUT_MS),
        headers: { Accept: 'application/json', Cookie: `episteck_home_session=${o.cookieValue}` },
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
