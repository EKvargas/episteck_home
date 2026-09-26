import 'server-only';
import { cookies } from 'next/headers';
import { loadBootstrap } from './bootstrap-loader';
import { SERVER_ENVIRONMENT_MODE } from '../state/Environment.server';

export async function getBootstrapForRequest() {
  if (SERVER_ENVIRONMENT_MODE === 'MOCK') {
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
    bffBaseUrl: process.env.HOME_HUB_BFF_BASE_URL,
    fetcher: fetch,
  });
}
