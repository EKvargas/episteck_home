import { getHomeHubServerConfiguration } from './integration/home/server-config';

export async function register() {
  if (process.env.NODE_ENV === 'production') {
    getHomeHubServerConfiguration();
  }
}
