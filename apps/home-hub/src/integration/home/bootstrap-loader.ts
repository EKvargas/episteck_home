import type { BootstrapContext } from './Viewer';
import type { DataEnvelope } from '../state/DataEnvelope';
import type { SafeUIErrorCode } from '../state/SafeUIErrorCode';
import { parseBootstrapWire } from './bootstrap-contract.ts';

export type BootstrapLoadResult = DataEnvelope<BootstrapContext>;

export const mockBootstrapWire = {
  version: 1,
  viewer: { personId: 'PSN-00001', displayName: 'Erick' },
  personContexts: [
    { type: 'PERSON', personId: 'PSN-00001', displayName: 'Erick' },
    { type: 'PERSON', personId: 'PSN-00007', displayName: 'Ana' },
  ],
  circleContexts: [{ type: 'CIRCLE', circleId: 'CIR-00001', displayName: 'Family' }],
  careRelationships: [
    { subjectPersonId: 'PSN-00007', relationshipType: 'CAREGIVER' },
  ],
} as const;

interface LoadBootstrapOptions {
  mode: 'MOCK' | 'LIVE';
  cookieValue: string | undefined;
  bffBaseUrl: string | undefined;
  fetcher: typeof fetch;
}

function trustedBootstrapUrl(baseUrl: string | undefined): string {
  if (!baseUrl) throw new Error('HOME_HUB_BFF_BASE_URL is required in LIVE mode.');
  let parsed: URL;
  try {
    parsed = new URL(baseUrl);
  } catch {
    throw new Error('HOME_HUB_BFF_BASE_URL must be a trusted HTTP origin.');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)
    || parsed.username
    || parsed.password
    || parsed.pathname !== '/'
    || parsed.search
    || parsed.hash) throw new Error('HOME_HUB_BFF_BASE_URL must be a trusted HTTP origin.');
  return new URL('/bootstrap', parsed).toString();
}

function ready(data: BootstrapContext, environment: 'MOCK' | 'LIVE'): BootstrapLoadResult {
  return {
    delivery: 'READY',
    authorization: 'GRANTED',
    freshness: 'FRESH',
    environment,
    data,
  };
}

function failed(errorCode: SafeUIErrorCode, environment: 'MOCK' | 'LIVE'): BootstrapLoadResult {
  return {
    delivery: 'ERROR',
    authorization: 'INDETERMINATE',
    freshness: 'UNKNOWN',
    environment,
    errorCode,
  };
}

export async function loadBootstrap(options: LoadBootstrapOptions): Promise<BootstrapLoadResult> {
  if (options.mode === 'MOCK') {
    return ready(parseBootstrapWire(mockBootstrapWire), 'MOCK');
  }

  const bootstrapUrl = trustedBootstrapUrl(options.bffBaseUrl);
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.cookieValue) headers.Cookie = `episteck_home_session=${options.cookieValue}`;

  let response: Response;
  try {
    response = await options.fetcher(bootstrapUrl, {
      method: 'GET',
      cache: 'no-store',
      headers,
      redirect: 'manual',
    });
  } catch {
    return failed('SERVICE_UNAVAILABLE', 'LIVE');
  }

  if (response.status === 401) return failed('SESSION_INVALID', 'LIVE');
  if (response.status === 502) return failed('INVALID_RESPONSE', 'LIVE');
  if (response.status === 503) return failed('SERVICE_UNAVAILABLE', 'LIVE');
  if (response.status !== 200) return failed('SERVICE_UNAVAILABLE', 'LIVE');

  try {
    return ready(parseBootstrapWire(await response.json()), 'LIVE');
  } catch {
    return failed('INVALID_RESPONSE', 'LIVE');
  }
}
