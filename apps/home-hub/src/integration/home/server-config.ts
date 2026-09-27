import { validateEnvironmentMode, type EnvironmentMode } from '../state/Environment.ts';

export interface HomeHubServerConfiguration {
  mode: EnvironmentMode;
  bffBaseUrl?: string;
  publicOrigin: string;
}

function configuredOrigin(
  value: string | undefined,
  name: string,
  production: boolean,
  allowHttpLoopback: boolean,
  requireLoopback: boolean,
): string {
  if (!value) throw new Error(`FATAL: ${name} is required.`);

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`FATAL: ${name} must be a trusted HTTP origin.`);
  }

  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  if (!['http:', 'https:'].includes(url.protocol)
    || url.username
    || url.password
    || url.pathname !== '/'
    || url.search
    || url.hash
    || (production && requireLoopback && !loopback)
    || (production && url.protocol !== 'https:' && !(allowHttpLoopback && loopback))) {
    throw new Error(`FATAL: ${name} must be a trusted HTTP origin.`);
  }
  return url.origin;
}

export function getHomeHubServerConfiguration(
  env: NodeJS.ProcessEnv = process.env,
): HomeHubServerConfiguration {
  const production = env.NODE_ENV === 'production';
  const mode = validateEnvironmentMode(env.HOME_HUB_DATA_MODE, production);
  const bffBaseUrl = mode === 'LIVE'
    ? configuredOrigin(env.HOME_HUB_BFF_BASE_URL, 'HOME_HUB_BFF_BASE_URL', production, true, true)
    : undefined;
  const publicOrigin = env.HOME_HUB_PUBLIC_ORIGIN
    ? configuredOrigin(env.HOME_HUB_PUBLIC_ORIGIN, 'HOME_HUB_PUBLIC_ORIGIN', production, true, false)
    : production
      ? configuredOrigin(undefined, 'HOME_HUB_PUBLIC_ORIGIN', production, true, false)
      : 'http://127.0.0.1:3000';

  if (production && mode !== 'LIVE') {
    throw new Error('FATAL: HOME_HUB_DATA_MODE must be LIVE in production environment.');
  }

  return { mode, bffBaseUrl, publicOrigin };
}
