import 'server-only';
import { cache } from 'react';
import { cookies } from 'next/headers';
import { loadBootstrap } from './bootstrap-loader';
import { SERVER_CONFIGURATION } from '../state/Environment.server';

/**
 * One bootstrap read per server render: the root layout and the Nutrition panel share it.
 * React cache() is request-scoped; nothing is kept across requests or sessions.
 */
export const getBootstrapForRequest = cache(async () => {
  if (SERVER_CONFIGURATION.mode === 'MOCK') {
    return loadBootstrap({
      mode: 'MOCK',
      cookieValue: undefined,
      bffBaseUrl: undefined,
      fetcher: fetch,
    });
  }

  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('episteck_home_session')?.value;
  return loadBootstrap({
    mode: 'LIVE',
    cookieValue: sessionCookie,
    bffBaseUrl: SERVER_CONFIGURATION.bffBaseUrl,
    fetcher: fetch,
  });
});
