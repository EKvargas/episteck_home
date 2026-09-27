import 'server-only';
import { cookies } from 'next/headers';
import { loadBootstrap } from './bootstrap-loader';
import { SERVER_CONFIGURATION } from '../state/Environment.server';

export async function getBootstrapForRequest() {
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
}
