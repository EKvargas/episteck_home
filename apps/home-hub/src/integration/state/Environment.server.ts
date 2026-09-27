import 'server-only';
import { getHomeHubServerConfiguration } from '../home/server-config';

export const SERVER_CONFIGURATION = getHomeHubServerConfiguration();
export const SERVER_ENVIRONMENT_MODE = SERVER_CONFIGURATION.mode;

export type { EnvironmentMode } from './Environment';
