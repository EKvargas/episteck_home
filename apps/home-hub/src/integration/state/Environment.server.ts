import 'server-only';
import { validateEnvironmentMode, EnvironmentMode } from './Environment';

export function getEnvironmentMode(): EnvironmentMode {
  return validateEnvironmentMode(
    process.env.HOME_HUB_DATA_MODE,
    process.env.NODE_ENV === 'production'
  );
}

// Evaluated on server startup and during production builds that render the app.
export const SERVER_ENVIRONMENT_MODE = getEnvironmentMode();

export type { EnvironmentMode };
